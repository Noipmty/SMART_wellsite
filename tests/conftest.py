"""pytest 全局 fixtures。"""

import os
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# 测试用环境变量
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("EVENTBUS_BACKEND", "memory")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("LANGSMITH_TRACING", "false")
# 测试固定走内存仓储（.env 中 REPO_BACKEND=pg 不影响套件；
# 环境变量优先级高于 .env，PG 集成测试见 test_pg_repos.py 显式开启）
os.environ.setdefault("REPO_BACKEND", "memory")

import pytest


@pytest.fixture
def eventbus_memory():
    """内存事件总线 fixture。"""
    from libs.eventbus.memory import InMemoryEventBus
    return InMemoryEventBus()


@pytest.fixture
def mock_llm():
    """Mock LLM 客户端 fixture。"""
    from libs.llm.mock import MockLLMClient
    return MockLLMClient(delay=0)
