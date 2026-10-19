"""事件总线内存实现测试：发布 → 订阅 → 收到，通配 topic 生效。"""

import pytest

from libs.eventbus.memory import InMemoryEventBus
from libs.eventbus.base import EventMessage


@pytest.mark.asyncio
async def test_publish_subscribe_basic():
    """基本发布订阅：发布一条消息，订阅者应收到。"""
    bus = InMemoryEventBus()
    received = []

    async def handler(msg: EventMessage) -> bool:
        received.append(msg)
        return True

    await bus.subscribe("wellsite/WS001/sensor/#", handler)
    await bus.start()

    msg_id = await bus.publish(
        "wellsite/WS001/sensor/DEV001/load_anomaly",
        {"value": 28.5, "threshold": 35.0},
        {"trace_id": "test-001"},
    )

    assert msg_id is not None
    assert len(received) == 1
    assert received[0].topic == "wellsite/WS001/sensor/DEV001/load_anomaly"
    assert received[0].payload["value"] == 28.5

    await bus.stop()


@pytest.mark.asyncio
async def test_wildcard_single_layer():
    """单层通配 *：只匹配一层。"""
    bus = InMemoryEventBus()
    received = []

    async def handler(msg: EventMessage) -> bool:
        received.append(msg)
        return True

    # * 匹配单层
    await bus.subscribe("wellsite/WS001/sensor/*", handler)
    await bus.start()

    # 应匹配
    await bus.publish("wellsite/WS001/sensor/DEV001", {"v": 1})
    # 不应匹配（两层）
    await bus.publish("wellsite/WS001/sensor/DEV001/load", {"v": 2})
    # 不应匹配（其他 site）
    await bus.publish("wellsite/WS002/sensor/DEV001", {"v": 3})

    assert len(received) == 1
    assert received[0].payload["v"] == 1

    await bus.stop()


@pytest.mark.asyncio
async def test_wildcard_multi_layer():
    """多层通配 #：匹配剩余所有层级。"""
    bus = InMemoryEventBus()
    received = []

    async def handler(msg: EventMessage) -> bool:
        received.append(msg)
        return True

    # # 匹配多层
    await bus.subscribe("wellsite/WS001/#", handler)
    await bus.start()

    await bus.publish("wellsite/WS001/sensor/DEV001", {"v": 1})
    await bus.publish("wellsite/WS001/diagnosis/insufficient_supply", {"v": 2})
    await bus.publish("wellsite/WS001/alert/critical", {"v": 3})
    # 不匹配（其他 site）
    await bus.publish("wellsite/WS002/sensor/DEV001", {"v": 4})

    assert len(received) == 3

    await bus.stop()


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """多个订阅者：同一条消息应被所有匹配的订阅者收到。"""
    bus = InMemoryEventBus()
    received_a = []
    received_b = []

    async def handler_a(msg: EventMessage) -> bool:
        received_a.append(msg)
        return True

    async def handler_b(msg: EventMessage) -> bool:
        received_b.append(msg)
        return True

    await bus.subscribe("wellsite/+/sensor/#", handler_a, "consumer-a")
    await bus.subscribe("wellsite/WS001/#", handler_b, "consumer-b")
    await bus.start()

    await bus.publish("wellsite/WS001/sensor/DEV001/load", {"v": 1})

    assert len(received_a) == 1
    assert len(received_b) == 1

    await bus.stop()


@pytest.mark.asyncio
async def test_handler_exception_no_crash():
    """处理器抛异常不应影响其他订阅者。"""
    bus = InMemoryEventBus()
    received = []

    async def bad_handler(msg: EventMessage) -> bool:
        raise ValueError("故意报错")

    async def good_handler(msg: EventMessage) -> bool:
        received.append(msg)
        return True

    await bus.subscribe("wellsite/WS001/#", bad_handler, "bad")
    await bus.subscribe("wellsite/WS001/#", good_handler, "good")
    await bus.start()

    await bus.publish("wellsite/WS001/sensor/DEV001", {"v": 1})

    assert len(received) == 1

    await bus.stop()


def test_topic_match_helper():
    """直接测试 topic_match 静态方法。"""
    # 单层通配 *
    assert InMemoryEventBus.topic_match("wellsite/WS001/sensor/DEV001", "wellsite/WS001/sensor/*")
    assert not InMemoryEventBus.topic_match("wellsite/WS001/sensor/DEV001/load", "wellsite/WS001/sensor/*")
    # 多层通配 #
    assert InMemoryEventBus.topic_match("wellsite/WS001/sensor/DEV001/load", "wellsite/WS001/#")
    assert InMemoryEventBus.topic_match("wellsite/WS001", "wellsite/WS001/#")
    assert not InMemoryEventBus.topic_match("wellsite/WS002/sensor", "wellsite/WS001/#")
    # + 作为 * 别名
    assert InMemoryEventBus.topic_match("wellsite/WS001/sensor/DEV001", "wellsite/+/sensor/+")
    # 混合模式：* + #
    assert InMemoryEventBus.topic_match("wellsite/WS001/sensor/DEV001/load", "wellsite/*/sensor/#")
    assert InMemoryEventBus.topic_match("wellsite/WS002/diagnosis/fault", "wellsite/*/diagnosis/#")
    assert not InMemoryEventBus.topic_match("wellsite/WS001/alert/critical", "wellsite/*/sensor/#")
