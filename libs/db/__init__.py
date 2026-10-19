"""数据库连接管理：PostgreSQL / TDengine / Redis。"""

from __future__ import annotations

import structlog
from configs import get_settings

logger = structlog.get_logger(__name__)

# PostgreSQL 连接池（懒加载）
_pg_engine = None
_pg_pool = None
_redis_client = None


async def get_pg_pool():
    """获取 PostgreSQL asyncpg 连接池（异步仓储用）。"""
    global _pg_pool
    if _pg_pool is None:
        import asyncpg

        settings = get_settings()
        _pg_pool = await asyncpg.create_pool(
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
            min_size=1,
            max_size=10,
        )
        logger.info("db.postgres.pool_ready", host=settings.postgres_host)
    return _pg_pool


def get_pg_engine():
    """获取 PostgreSQL SQLAlchemy 引擎。"""
    global _pg_engine
    if _pg_engine is None:
        from sqlalchemy import create_engine

        settings = get_settings()
        _pg_engine = create_engine(
            settings.postgres_dsn,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
        logger.info("db.postgres.connected", dsn=settings.postgres_host)
    return _pg_engine


def get_redis_client():
    """获取 Redis 客户端。"""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis

        settings = get_settings()
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        logger.info("db.redis.connected", host=settings.redis_host)
    return _redis_client


async def close_connections() -> None:
    """关闭所有数据库连接。"""
    global _pg_engine, _pg_pool, _redis_client

    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None
        logger.info("db.postgres.pool_closed")

    if _pg_engine:
        _pg_engine.dispose()
        _pg_engine = None
        logger.info("db.postgres.closed")

    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("db.redis.closed")
