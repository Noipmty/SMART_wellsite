"""智慧井场多智能体系统 - 全局配置模型。"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """系统全局配置，通过 .env 加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 运行环境 ----
    env: Literal["dev", "prod"] = "dev"
    log_level: str = "DEBUG"

    # ---- PostgreSQL ----
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "wellsite"
    postgres_user: str = "wellsite"
    postgres_password: str = "wellsite_dev_2026"

    # ---- TDengine ----
    tdengine_host: str = "localhost"
    tdengine_port: int = 6030
    tdengine_user: str = "root"
    tdengine_password: str = "taosdata"
    tdengine_database: str = "wellsite"

    # ---- Redis ----
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    # ---- MySQL（模拟事件总线） ----
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_db: str = "wellsite_bus"
    mysql_user: str = "wellsite"
    mysql_password: str = "wellsite_dev_2026"

    # ---- MinIO ----
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "wellsite"

    # ---- Neo4j（阶段二启用） ----
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_dev_2026"

    # ---- Milvus（阶段二启用） ----
    milvus_host: str = "localhost"
    milvus_port: int = 19530

    # ---- LLM ----
    llm_provider: Literal["mock", "doubao", "deepseek"] = "mock"
    llm_timeout: int = 30
    llm_max_retries: int = 3
    llm_token_budget: int = 4096

    # ---- LangSmith ----
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str = ""
    langsmith_project: str = "smart-wellsite"

    # ---- Prometheus ----
    prometheus_port: int = 9090

    # ---- FastAPI 网关 ----
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000
    # 逗号分隔的允许来源，"*" 表示不携带凭证的全放行
    cors_origins: str = "*"

    # ---- 事件总线 ----
    eventbus_backend: Literal["memory", "mysql", "redis_stream"] = "mysql"

    # ---- 仓储后端（memory=内存/mock 语义；pg=PostgreSQL 持久化） ----
    repo_backend: Literal["memory", "pg"] = "memory"

    # ---- 安全 ----
    secret_key: str = "change-me-in-production"
    audit_log_enabled: bool = True

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def mysql_dsn(self) -> str:
        return (
            f"mysql+mysqlconnector://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def cors_origin_list(self) -> list[str]:
        """解析 CORS_ORIGINS（逗号分隔），去空白、去空项。"""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局配置单例。"""
    return Settings()
