"""RocketMQ 配置与全局 producer/consumer 生命周期管理（RocketMQ 5.x gRPC Proxy）。

所有连接信息优先从环境变量 / Nacos 读取，与 §5.1 技术栈选型对齐。
producer / consumer 使用官方纯 Python 客户端 ``rocketmq-python-client``，
通过 Proxy 端口（默认 8080/8081）接入，Windows / Linux 均可运行。
"""
import asyncio
import logging
import os
from typing import Optional

# rocketmq-python-client 导入时会强制创建 ~/logs/rocketmq_python/，
# Windows 下 expanduser("~") 读 USERPROFILE，直接写用户主目录可能无权限，
# 因此重定向到项目本地目录
_ROCKETMQ_LOG_HOME = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), ".rocketmq_logs")
)
os.makedirs(_ROCKETMQ_LOG_HOME, exist_ok=True)
# 同时覆盖 HOME/USERPROFILE，兼容不同平台
os.environ["HOME"] = _ROCKETMQ_LOG_HOME
os.environ["USERPROFILE"] = _ROCKETMQ_LOG_HOME

from . import settings

logger = logging.getLogger(__name__)

# 全局 MQ 实例，由 init_mq() 启动，shutdown_mq() 关闭
_producer: Optional["Producer"] = None  # type: ignore[name-defined]
_consumer: Optional["SimpleConsumer"] = None  # type: ignore[name-defined]
_consumer_task: Optional[asyncio.Task] = None
_running = False


def get_endpoints() -> str:
    """RocketMQ 5.x Proxy endpoints（gRPC 接入点），支持逗号分隔多地址。

    优先读 ``rocketmq.endpoints``；未配置时，尝试从 ``rocketmq.nameserver_addr``
    的主机名推断 Proxy 端口 8080。
    """
    endpoints = settings.get_str("rocketmq.endpoints", default="")
    if endpoints:
        return endpoints
    ns = settings.get_str("rocketmq.nameserver_addr", default="localhost:9876")
    host = ns.rsplit(":", 1)[0]
    # 8080 Proxy 路由同步可能延迟，优先尝试 8081
    return f"{host}:8081"


def get_access_key() -> str:
    """RocketMQ ACL access key。"""
    return settings.get_str("rocketmq.access_key", default="")


def get_secret_key() -> str:
    """RocketMQ ACL secret key。"""
    return settings.get_str("rocketmq.secret_key", default="")


def get_topic() -> str:
    """fanout topic。用户指定：dev-qidian-post-sevices。"""
    return settings.get_str("rocketmq.topic", default="dev-qidian-post-sevices")


def get_tag() -> str:
    """fanout tag，统一 POST_FANOUT。"""
    return settings.get_str("rocketmq.tag", default="POST_FANOUT")


def get_producer_group() -> str:
    """producer group。"""
    return settings.get_str(
        "rocketmq.producer_group", default="dev-qidian-post-service-producer"
    )


def get_consumer_group() -> str:
    """consumer group，用户指定：dev-qidian-consumer。"""
    return settings.get_str("rocketmq.consumer_group", default="dev-qidian-consumer")


def is_mq_enabled() -> bool:
    """RocketMQ 开关：显式关闭时跳过启动，不影响本地调试。"""
    return settings.get_bool("rocketmq.enabled", default=True)


def _make_config():
    """构造 RocketMQ 5.x ClientConfiguration（含 ACL 凭证）。"""
    from rocketmq import ClientConfiguration, Credentials

    ak = get_access_key()
    sk = get_secret_key()
    credentials = Credentials(ak, sk) if ak and sk else None
    return ClientConfiguration(get_endpoints(), credentials)


async def _start_producer() -> Optional["Producer"]:
    """启动 fanout producer。"""
    try:
        from rocketmq import Producer
    except (ImportError, NotImplementedError) as e:
        logger.warning("rocketmq-python-client 不可用，producer 不启用: %s", e)
        return None

    config = _make_config()
    producer = Producer(config, (get_topic(),))
    await asyncio.to_thread(producer.startup)
    logger.info(
        "RocketMQ producer 已启动: endpoints=%s, group=%s, topic=%s, tag=%s",
        get_endpoints(),
        get_producer_group(),
        get_topic(),
        get_tag(),
    )
    return producer


async def _consume_loop(consume_callback) -> None:
    """SimpleConsumer 长轮询循环：把同步 receive 放在线程里执行，避免阻塞事件循环。"""
    global _running
    _running = True
    while _running:
        try:
            # 每次最多拉 10 条，消息不可见时间 15s
            messages = await asyncio.to_thread(_consumer.receive, 10, 15)
            if not messages:
                continue
            for msg in messages:
                try:
                    success = await consume_callback(msg.body)
                    if success:
                        await asyncio.to_thread(_consumer.ack, msg)
                except Exception:
                    logger.exception("fanout consume failed, msg_id=%s", getattr(msg, "message_id", "?"))
                    # 未 ack，消息会在 invisible_duration 后重新投递
        except Exception:
            logger.exception("RocketMQ consumer receive error")
            await asyncio.sleep(1)


async def _start_consumer() -> Optional["SimpleConsumer"]:
    """启动 fanout SimpleConsumer，并拉起后台长轮询任务。"""
    try:
        from rocketmq import SimpleConsumer, FilterExpression
    except (ImportError, NotImplementedError) as e:
        logger.warning("rocketmq-python-client 不可用，consumer 不启用: %s", e)
        return None

    config = _make_config()
    consumer = SimpleConsumer(config, get_consumer_group())
    await asyncio.to_thread(consumer.startup)
    # 按 tag 订阅；若 tag 为空则订阅全部
    tag = get_tag()
    if tag:
        consumer.subscribe(get_topic(), FilterExpression(tag))
    else:
        consumer.subscribe(get_topic())
    logger.info(
        "RocketMQ consumer 已启动: endpoints=%s, group=%s, topic=%s, tag=%s",
        get_endpoints(),
        get_consumer_group(),
        get_topic(),
        get_tag(),
    )
    return consumer


async def init_mq() -> None:
    """服务启动时调用：初始化 RocketMQ producer 与 consumer。"""
    global _producer, _consumer, _consumer_task
    if not is_mq_enabled():
        logger.info("RocketMQ 已禁用，跳过初始化")
        return

    try:
        _producer = await _start_producer()
        _consumer = await _start_consumer()
        if _consumer:
            from mq.fanout_consumer import PostFanoutConsumer
            from clients.user_client import UserClient
            from config.redis import get_redis

            loop_consumer = PostFanoutConsumer(UserClient(), get_redis())
            _consumer_task = asyncio.create_task(_consume_loop(loop_consumer.consume))
    except Exception:
        logger.exception("RocketMQ 初始化失败")
        # MQ 失败不阻塞 gRPC 服务启动


def shutdown_mq() -> None:
    """服务关闭时调用：优雅停止 producer 与 consumer。"""
    global _producer, _consumer, _consumer_task, _running
    _running = False

    if _consumer_task:
        _consumer_task.cancel()
        _consumer_task = None

    try:
        if _consumer:
            consumer = _consumer
            _consumer = None
            asyncio.get_event_loop().run_until_complete(asyncio.to_thread(consumer.shutdown))
            logger.info("RocketMQ consumer 已关闭")
    except Exception:
        logger.exception("RocketMQ consumer 关闭异常")

    try:
        if _producer:
            producer = _producer
            _producer = None
            asyncio.get_event_loop().run_until_complete(asyncio.to_thread(producer.shutdown))
            logger.info("RocketMQ producer 已关闭")
    except Exception:
        logger.exception("RocketMQ producer 关闭异常")


def get_producer() -> Optional["Producer"]:
    """获取已启动的 producer 实例。"""
    return _producer
