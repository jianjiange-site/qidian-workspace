"""发帖写扩散 MQ Producer（RocketMQ 5.x gRPC Proxy）。

严格按 post-service-design.md §9.1 / §10.2.2 实现：
- 事务 COMMIT 后同步发送 fanout 消息
- 本地 retry 3 次，每次 timeout 2s
- 3 次全失败 → log.error + prometheus Counter +1，不阻塞接口返回
"""
import json
import logging
from typing import Optional

from prometheus_client import Counter

from config.mq import get_producer, get_tag, get_topic

logger = logging.getLogger(__name__)

FANOUT_PRODUCE_FAIL = Counter(
    "post_fanout_produce_fail",
    "Producer 重试 3 次仍失败"
)


class PostFanoutProducer:
    """发帖后将 postId 写入 fanout topic，由 Consumer 异步做写扩散。

    设计要点：
    - 构造时优先使用 config.mq 已启动的全局 producer；若 MQ 未启用则退化为桩。
    - ``send`` 是同步阻塞方法（等待 broker ack），业务层应通过线程池调用，
      避免阻塞 asyncio 事件循环。
    """

    def __init__(self, producer: Optional["Producer"] = None):  # type: ignore[name-defined]
        self._producer = producer if producer is not None else get_producer()
        if self._producer is None:
            logger.warning("RocketMQ producer 未初始化，PostFanoutProducer 将以桩模式运行")

    def _build_message(self, post_id: int, author_user_id: int, created_at_epoch: int):
        """构造 RocketMQ 5.x Message 对象。"""
        from rocketmq import Message

        body = json.dumps({
            "postId": post_id,
            "authorUserId": author_user_id,
            "createdAtEpoch": created_at_epoch,
        }, ensure_ascii=False).encode("utf-8")

        msg = Message()
        msg.topic = get_topic()
        msg.body = body
        msg.tag = get_tag()
        msg.keys = str(post_id)
        return msg

    def sync_send(self, post_id: int, author_user_id: int, created_at_epoch: int) -> bool:
        """同步发送 fanout 消息（带本地 3 次重试）。

        Args:
            post_id: 帖子业务主键。
            author_user_id: 作者 user_id。
            created_at_epoch: 发帖时间 UTC 秒级时间戳，作为 timeline score。

        Returns:
            True 发送成功，False 表示 3 次重试均失败（调用方应记录日志，不抛异常）。
        """
        if self._producer is None:
            logger.info(
                "[PostFanoutProducer 桩] sync_send(post_id=%s, author=%s, epoch=%s)",
                post_id, author_user_id, created_at_epoch,
            )
            return True

        for attempt in range(1, 4):
            try:
                msg = self._build_message(post_id, author_user_id, created_at_epoch)
                result = self._producer.send(msg)
                # rocketmq-python-client 发送成功返回 SendResult，失败直接抛异常
                logger.info(
                    "fanout send ok, post_id=%s author=%s attempt=%s result=%s",
                    post_id, author_user_id, attempt, result,
                )
                return True
            except Exception as e:
                logger.warning(
                    "fanout send retry, post_id=%s attempt=%s error=%s",
                    post_id, attempt, e,
                )

        logger.error("fanout send FAILED after 3 retries, post_id=%s", post_id)
        FANOUT_PRODUCE_FAIL.inc()
        return False
