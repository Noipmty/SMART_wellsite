"""PostgreSQL 持久化仓储：与内存仓储同接口，容器按 REPO_BACKEND 切换。

设计要点：
- 聚合整体以 JSONB 落库（data 列），过滤/排序字段冗余为独立列建索引；
  模型演进无需迁移表结构，与 Pydantic 模型 1:1。
- update(key, patch) 语义与内存实现对齐：行锁（SELECT ... FOR UPDATE）内
  反序列化 → 就地 patch → 整体写回，单进程语义下无丢失更新。
- 表名统一 app_ 前缀，与 docker/init 早期业务表（devices/alerts 等旧 schema）隔离。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

import asyncpg
import structlog
from pydantic import BaseModel

from libs.schemas.alerts import Alert, AlertStatus, WorkOrder, WorkOrderStatus
from libs.schemas.graph import (
    EntityType,
    GraphBuildMeta,
    GraphCommunity,
    GraphEdge,
    GraphNode,
)
from libs.schemas.kb import (
    CandidateStatus,
    IndexStatus,
    KBCandidate,
    KBChunk,
    KBDocument,
)
from libs.schemas.trace import TraceRecord

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# ==================== DDL ====================

DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS app_alerts (
        alert_id   TEXT PRIMARY KEY,
        status     TEXT NOT NULL,
        level      TEXT NOT NULL,
        scope      TEXT,
        last_seen  TIMESTAMPTZ NOT NULL,
        data       JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_app_alerts_filter ON app_alerts(status, level, scope)",
    "CREATE INDEX IF NOT EXISTS idx_app_alerts_last_seen ON app_alerts(last_seen DESC)",
    """
    CREATE TABLE IF NOT EXISTS app_work_orders (
        order_id   TEXT PRIMARY KEY,
        status     TEXT NOT NULL,
        assignee   TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        data       JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_app_orders_filter ON app_work_orders(status, assignee)",
    "CREATE INDEX IF NOT EXISTS idx_app_orders_created ON app_work_orders(created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS app_kb_documents (
        doc_id     TEXT PRIMARY KEY,
        status     TEXT NOT NULL,
        doc_type   TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        data       JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_app_kb_docs_filter ON app_kb_documents(status, doc_type)",
    """
    CREATE TABLE IF NOT EXISTS app_kb_chunks (
        chunk_id TEXT PRIMARY KEY,
        doc_id   TEXT NOT NULL,
        seq      INT  NOT NULL,
        data     JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_app_kb_chunks_doc ON app_kb_chunks(doc_id, seq)",
    """
    CREATE TABLE IF NOT EXISTS app_kb_candidates (
        candidate_id TEXT PRIMARY KEY,
        status       TEXT NOT NULL,
        source_type  TEXT,
        source_id    TEXT,
        created_at   TIMESTAMPTZ NOT NULL,
        data         JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_app_kb_cand_status ON app_kb_candidates(status)",
    "CREATE INDEX IF NOT EXISTS idx_app_kb_cand_source ON app_kb_candidates(source_type, source_id)",
    """
    CREATE TABLE IF NOT EXISTS app_graph_nodes (
        name        TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        degree      INT  NOT NULL DEFAULT 0,
        data        JSONB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_graph_edges (
        id       BIGSERIAL PRIMARY KEY,
        source   TEXT NOT NULL,
        target   TEXT NOT NULL,
        relation TEXT NOT NULL,
        weight   REAL NOT NULL DEFAULT 1.0,
        doc_id   TEXT,
        UNIQUE (source, target, relation)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_app_graph_edges_nodes ON app_graph_edges(source, target)",
    """
    CREATE TABLE IF NOT EXISTS app_graph_communities (
        community_id TEXT PRIMARY KEY,
        size         INT  NOT NULL DEFAULT 0,
        data         JSONB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_graph_meta (
        id   INT PRIMARY KEY CHECK (id = 1),
        data JSONB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_traces (
        trace_id   TEXT PRIMARY KEY,
        session_id TEXT,
        intent     TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        data       JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_app_traces_created ON app_traces(created_at DESC)",
)


async def run_ddl(pool: asyncpg.Pool) -> None:
    """执行全部建表/索引语句（幂等）。"""
    async with pool.acquire() as conn:
        for stmt in DDL_STATEMENTS:
            await conn.execute(stmt)
    logger.info("pg_repo.ddl_applied", statements=len(DDL_STATEMENTS))


# ==================== 序列化 ====================


def _dump(model: BaseModel) -> str:
    return model.model_dump_json()


def _load(cls: type[T], raw: Any) -> T:
    return cls.model_validate(json.loads(raw) if isinstance(raw, str) else raw)


class _JsonbTable:
    """JSONB 聚合表通用读写（单聚合一表一模型）。"""

    TABLE: str = ""
    ID_COL: str = ""
    MODEL: type[BaseModel] = BaseModel

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def count(self) -> int:
        row = await self._pool.fetchrow(f"SELECT COUNT(*) AS n FROM {self.TABLE}")
        return int(row["n"])

    async def _all(self) -> list[Any]:
        rows = await self._pool.fetch(f"SELECT data FROM {self.TABLE}")
        return [_load(self.MODEL, r["data"]) for r in rows]

    async def _one(self, key: str) -> Any | None:
        row = await self._pool.fetchrow(
            f"SELECT data FROM {self.TABLE} WHERE {self.ID_COL} = $1", key
        )
        return _load(self.MODEL, row["data"]) if row else None

    async def _insert(self, key: str, obj: BaseModel, extra: dict[str, Any]) -> None:
        cols = [self.ID_COL, *extra.keys(), "data"]
        vals = [key, *extra.values(), _dump(obj)]
        placeholders = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
        sql = (
            f"INSERT INTO {self.TABLE} ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT ({self.ID_COL}) DO UPDATE SET data = EXCLUDED.data"
        )
        # data 列需显式 jsonb 转换
        sql = sql.replace(f"${len(cols)}", f"${len(cols)}::jsonb")
        await self._pool.execute(sql, *vals)

    async def _delete(self, key: str) -> bool:
        result = await self._pool.execute(
            f"DELETE FROM {self.TABLE} WHERE {self.ID_COL} = $1", key
        )
        return result.endswith(" 1")

    async def _update(
        self, key: str, patch: Callable[[Any], None], extra: Callable[[Any], dict[str, Any]]
    ) -> Any | None:
        """行锁内反序列化 → patch → 写回（含冗余过滤列同步）。"""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"SELECT data FROM {self.TABLE} WHERE {self.ID_COL} = $1 FOR UPDATE",
                    key,
                )
                if row is None:
                    return None
                obj = _load(self.MODEL, row["data"])
                patch(obj)
                cols = extra(obj)
                set_clause = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(cols))
                await conn.execute(
                    f"UPDATE {self.TABLE} SET {set_clause}, data = ${len(cols) + 2}::jsonb"
                    f" WHERE {self.ID_COL} = $1",
                    key,
                    *cols.values(),
                    _dump(obj),
                )
                return obj


# ==================== 告警 / 工单 ====================


class PgAlertRepository(_JsonbTable):
    """app_alerts：alert_id → Alert（JSONB）。"""

    TABLE = "app_alerts"
    ID_COL = "alert_id"
    MODEL = Alert

    @staticmethod
    def _cols(a: Alert) -> dict[str, Any]:
        return {"status": a.status.value, "level": a.level,
                "scope": a.scope, "last_seen": a.last_seen}

    async def save(self, alert: Alert) -> Alert:
        await self._insert(alert.alert_id, alert, self._cols(alert))
        return alert

    async def get_by_id(self, alert_id: str) -> Alert | None:
        return await self._one(alert_id)

    async def update(self, key: str, patch: Callable[[Alert], None]) -> Alert | None:
        return await self._update(key, patch, self._cols)

    async def list(self, predicate: Callable[[Alert], bool] | None = None) -> list[Alert]:
        items = await self._all()
        return items if predicate is None else [a for a in items if predicate(a)]

    async def query(
        self,
        status: AlertStatus | None = None,
        level: str | None = None,
        well_id: str | None = None,
    ) -> list[Alert]:
        clauses, vals = ["TRUE"], []
        if status is not None:
            vals.append(status.value)
            clauses.append(f"status = ${len(vals)}")
        if level is not None:
            vals.append(level)
            clauses.append(f"level = ${len(vals)}")
        if well_id is not None:
            vals.append(well_id)
            clauses.append(f"scope = ${len(vals)}")
        rows = await self._pool.fetch(
            f"SELECT data FROM app_alerts WHERE {' AND '.join(clauses)}"
            " ORDER BY last_seen DESC",
            *vals,
        )
        return [_load(Alert, r["data"]) for r in rows]


class PgWorkOrderRepository(_JsonbTable):
    """app_work_orders：order_id → WorkOrder（JSONB）。"""

    TABLE = "app_work_orders"
    ID_COL = "order_id"
    MODEL = WorkOrder

    @staticmethod
    def _cols(o: WorkOrder) -> dict[str, Any]:
        return {"status": o.status.value, "assignee": o.assignee,
                "created_at": o.created_at}

    async def save(self, order: WorkOrder) -> WorkOrder:
        await self._insert(order.order_id, order, self._cols(order))
        return order

    async def get_by_id(self, order_id: str) -> WorkOrder | None:
        return await self._one(order_id)

    async def update(self, key: str, patch: Callable[[WorkOrder], None]) -> WorkOrder | None:
        return await self._update(key, patch, self._cols)

    async def query(
        self,
        status: WorkOrderStatus | None = None,
        assignee: str | None = None,
    ) -> list[WorkOrder]:
        clauses, vals = ["TRUE"], []
        if status is not None:
            vals.append(status.value)
            clauses.append(f"status = ${len(vals)}")
        if assignee is not None:
            vals.append(assignee)
            clauses.append(f"assignee = ${len(vals)}")
        rows = await self._pool.fetch(
            f"SELECT data FROM app_work_orders WHERE {' AND '.join(clauses)}"
            " ORDER BY created_at DESC",
            *vals,
        )
        return [_load(WorkOrder, r["data"]) for r in rows]


# ==================== 知识库 ====================


class PgKBDocumentRepository(_JsonbTable):
    """app_kb_documents：doc_id → KBDocument（JSONB）。"""

    TABLE = "app_kb_documents"
    ID_COL = "doc_id"
    MODEL = KBDocument

    @staticmethod
    def _cols(d: KBDocument) -> dict[str, Any]:
        return {"status": d.status.value, "doc_type": d.doc_type,
                "created_at": d.created_at}

    async def save(self, doc: KBDocument) -> KBDocument:
        await self._insert(doc.doc_id, doc, self._cols(doc))
        return doc

    async def get_by_id(self, doc_id: str) -> KBDocument | None:
        return await self._one(doc_id)

    async def update(self, key: str, patch: Callable[[KBDocument], None]) -> KBDocument | None:
        return await self._update(key, patch, self._cols)

    async def delete(self, key: str) -> bool:
        return await self._delete(key)

    async def query(
        self,
        status: IndexStatus | None = None,
        doc_type: str | None = None,
    ) -> list[KBDocument]:
        clauses, vals = ["TRUE"], []
        if status is not None:
            vals.append(status.value)
            clauses.append(f"status = ${len(vals)}")
        if doc_type is not None:
            vals.append(doc_type)
            clauses.append(f"doc_type = ${len(vals)}")
        rows = await self._pool.fetch(
            f"SELECT data FROM app_kb_documents WHERE {' AND '.join(clauses)}"
            " ORDER BY created_at DESC",
            *vals,
        )
        return [_load(KBDocument, r["data"]) for r in rows]


class PgKBChunkRepository:
    """app_kb_chunks：chunk_id → KBChunk（JSONB）。"""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def count(self) -> int:
        row = await self._pool.fetchrow("SELECT COUNT(*) AS n FROM app_kb_chunks")
        return int(row["n"])

    async def save_all(self, chunks: list[KBChunk]) -> None:
        await self._pool.executemany(
            "INSERT INTO app_kb_chunks (chunk_id, doc_id, seq, data)"
            " VALUES ($1, $2, $3, $4::jsonb)"
            " ON CONFLICT (chunk_id) DO UPDATE SET data = EXCLUDED.data",
            [(c.chunk_id, c.doc_id, c.seq, _dump(c)) for c in chunks],
        )

    async def list_by_doc(self, doc_id: str) -> list[KBChunk]:
        rows = await self._pool.fetch(
            "SELECT data FROM app_kb_chunks WHERE doc_id = $1 ORDER BY seq", doc_id
        )
        return [_load(KBChunk, r["data"]) for r in rows]

    async def delete_by_doc(self, doc_id: str) -> int:
        result = await self._pool.execute(
            "DELETE FROM app_kb_chunks WHERE doc_id = $1", doc_id
        )
        return int(result.rsplit(" ", 1)[-1])

    async def list_ready(self, ready_doc_ids: set[str]) -> list[KBChunk]:
        if not ready_doc_ids:
            return []
        rows = await self._pool.fetch(
            "SELECT data FROM app_kb_chunks WHERE doc_id = ANY($1::text[])",
            list(ready_doc_ids),
        )
        return [_load(KBChunk, r["data"]) for r in rows]


class PgKBCandidateRepository(_JsonbTable):
    """app_kb_candidates：candidate_id → KBCandidate（JSONB）。"""

    TABLE = "app_kb_candidates"
    ID_COL = "candidate_id"
    MODEL = KBCandidate

    @staticmethod
    def _cols(c: KBCandidate) -> dict[str, Any]:
        return {"status": c.status.value, "source_type": c.source_type,
                "source_id": c.source_id, "created_at": c.created_at}

    async def save(self, candidate: KBCandidate) -> KBCandidate:
        await self._insert(candidate.candidate_id, candidate, self._cols(candidate))
        return candidate

    async def get_by_id(self, candidate_id: str) -> KBCandidate | None:
        return await self._one(candidate_id)

    async def update(self, key: str, patch: Callable[[KBCandidate], None]) -> KBCandidate | None:
        return await self._update(key, patch, self._cols)

    async def find_by_source(self, source_type: str, source_id: str) -> KBCandidate | None:
        row = await self._pool.fetchrow(
            "SELECT data FROM app_kb_candidates WHERE source_type = $1 AND source_id = $2"
            " ORDER BY created_at DESC LIMIT 1",
            source_type,
            source_id,
        )
        return _load(KBCandidate, row["data"]) if row else None

    async def query(self, status: CandidateStatus | None = None) -> list[KBCandidate]:
        if status is None:
            rows = await self._pool.fetch(
                "SELECT data FROM app_kb_candidates ORDER BY created_at DESC"
            )
        else:
            rows = await self._pool.fetch(
                "SELECT data FROM app_kb_candidates WHERE status = $1"
                " ORDER BY created_at DESC",
                status.value,
            )
        return [_load(KBCandidate, r["data"]) for r in rows]


# ==================== 知识图谱 ====================


class PgGraphRepository:
    """app_graph_nodes / app_graph_edges / app_graph_communities / app_graph_meta。"""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def count(self) -> int:
        row = await self._pool.fetchrow("SELECT COUNT(*) AS n FROM app_graph_nodes")
        return int(row["n"])

    # ---------------- 节点 ----------------

    async def get_node(self, name: str) -> GraphNode | None:
        row = await self._pool.fetchrow(
            "SELECT data FROM app_graph_nodes WHERE name = $1", name
        )
        return _load(GraphNode, row["data"]) if row else None

    async def query_nodes(
        self,
        entity_type: EntityType | None = None,
        keyword: str | None = None,
    ) -> list[GraphNode]:
        clauses, vals = ["TRUE"], []
        if entity_type is not None:
            vals.append(entity_type.value)
            clauses.append(f"entity_type = ${len(vals)}")
        if keyword:
            vals.append(f"%{keyword}%")
            clauses.append(f"name LIKE ${len(vals)}")
        rows = await self._pool.fetch(
            f"SELECT data FROM app_graph_nodes WHERE {' AND '.join(clauses)}"
            " ORDER BY degree DESC, name",
            *vals,
        )
        return [_load(GraphNode, r["data"]) for r in rows]

    # ---------------- 边 / 邻居 ----------------

    @staticmethod
    def _edge_from_row(row: asyncpg.Record) -> GraphEdge:
        return GraphEdge(
            source=row["source"], target=row["target"], relation=row["relation"],
            weight=row["weight"], doc_id=row["doc_id"] or "",
        )

    async def edges_of(self, name: str) -> list[GraphEdge]:
        rows = await self._pool.fetch(
            "SELECT * FROM app_graph_edges WHERE source = $1 OR target = $1"
            " ORDER BY weight DESC",
            name,
        )
        return [self._edge_from_row(r) for r in rows]

    async def list_edges(self) -> list[GraphEdge]:
        rows = await self._pool.fetch("SELECT * FROM app_graph_edges ORDER BY weight DESC")
        return [self._edge_from_row(r) for r in rows]

    # ---------------- 社区 ----------------

    async def list_communities(self) -> list[GraphCommunity]:
        rows = await self._pool.fetch(
            "SELECT data FROM app_graph_communities ORDER BY size DESC"
        )
        return [_load(GraphCommunity, r["data"]) for r in rows]

    async def get_community(self, community_id: str) -> GraphCommunity | None:
        row = await self._pool.fetchrow(
            "SELECT data FROM app_graph_communities WHERE community_id = $1",
            community_id,
        )
        return _load(GraphCommunity, row["data"]) if row else None

    # ---------------- 构建 ----------------

    async def replace_graph(
        self,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        communities: dict[str, GraphCommunity],
    ) -> None:
        """原子替换整图（单事务：清空 + 全量写入）。"""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM app_graph_edges")
                await conn.execute("DELETE FROM app_graph_nodes")
                await conn.execute("DELETE FROM app_graph_communities")
                await conn.executemany(
                    "INSERT INTO app_graph_nodes (name, entity_type, degree, data)"
                    " VALUES ($1, $2, $3, $4::jsonb)",
                    [(n.name, n.entity_type.value, n.degree, _dump(n))
                     for n in nodes.values()],
                )
                await conn.executemany(
                    "INSERT INTO app_graph_edges (source, target, relation, weight, doc_id)"
                    " VALUES ($1, $2, $3, $4, $5)"
                    " ON CONFLICT (source, target, relation) DO UPDATE"
                    " SET weight = EXCLUDED.weight, doc_id = EXCLUDED.doc_id",
                    [(e.source, e.target, e.relation, e.weight, e.doc_id or None)
                     for e in edges],
                )
                await conn.executemany(
                    "INSERT INTO app_graph_communities (community_id, size, data)"
                    " VALUES ($1, $2, $3::jsonb)",
                    [(c.community_id, c.size, _dump(c)) for c in communities.values()],
                )

    async def get_meta(self) -> GraphBuildMeta:
        row = await self._pool.fetchrow("SELECT data FROM app_graph_meta WHERE id = 1")
        return _load(GraphBuildMeta, row["data"]) if row else GraphBuildMeta()

    async def set_meta(self, patch: Callable[[GraphBuildMeta], None]) -> GraphBuildMeta:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT data FROM app_graph_meta WHERE id = 1 FOR UPDATE"
                )
                meta = _load(GraphBuildMeta, row["data"]) if row else GraphBuildMeta()
                patch(meta)
                await conn.execute(
                    "INSERT INTO app_graph_meta (id, data) VALUES (1, $1::jsonb)"
                    " ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
                    _dump(meta),
                )
                return meta.model_copy()


# ==================== 链路追踪 ====================


class PgTraceRepository(_JsonbTable):
    """app_traces：trace_id → TraceRecord（JSONB）。"""

    TABLE = "app_traces"
    ID_COL = "trace_id"
    MODEL = TraceRecord

    @staticmethod
    def _cols(r: TraceRecord) -> dict[str, Any]:
        return {"session_id": r.session_id, "intent": r.intent,
                "created_at": r.created_at}

    async def save(self, record: TraceRecord) -> TraceRecord:
        await self._insert(record.trace_id, record, self._cols(record))
        return record

    async def get(self, key: str) -> TraceRecord | None:
        return await self._one(key)

    async def query(
        self,
        session_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        intent: str | None = None,
    ) -> list[TraceRecord]:
        clauses, vals = ["TRUE"], []
        if session_id is not None:
            vals.append(session_id)
            clauses.append(f"session_id = ${len(vals)}")
        if intent is not None:
            vals.append(intent)
            clauses.append(f"intent = ${len(vals)}")
        if start is not None:
            vals.append(start)
            clauses.append(f"created_at >= ${len(vals)}")
        if end is not None:
            vals.append(end)
            clauses.append(f"created_at <= ${len(vals)}")
        rows = await self._pool.fetch(
            f"SELECT data FROM app_traces WHERE {' AND '.join(clauses)}"
            " ORDER BY created_at DESC",
            *vals,
        )
        return [_load(TraceRecord, r["data"]) for r in rows]


# ==================== 工厂 ====================


class PgRepositories:
    """PG 仓储集合（容器装配用）。"""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.alert_repo = PgAlertRepository(pool)
        self.order_repo = PgWorkOrderRepository(pool)
        self.trace_repo = PgTraceRepository(pool)
        self.kb_doc_repo = PgKBDocumentRepository(pool)
        self.kb_chunk_repo = PgKBChunkRepository(pool)
        self.kb_candidate_repo = PgKBCandidateRepository(pool)
        self.graph_repo = PgGraphRepository(pool)
