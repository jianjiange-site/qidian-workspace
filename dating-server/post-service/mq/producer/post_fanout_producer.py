"""发帖写扩散 MQ 生产者桩 — 待接入 RocketMQ 后实现。

当前仅打日志，不阻塞主流程。
"""
import logging

logger = logging.getLogger(__name__)


class PostFanoutProducer:
    """发帖后将 postId 写入 fanout topic，由 Consumer 异步做写扩散。

    TODO: 接入 RocketMQ 后替换为 syncSend 调用。
    """

    def sync_send(self, post_id: int, author_user_id: int, created_at_epoch: int) -> bool:
        """同步发送 fanout 消息（带本地 3 次重试）。

        Returns:
            True 发送成功，False 失败（不阻塞返回）。
        """
        logger.info(
            "[PostFanoutProducer 桩] sync_send(post_id=%s, author=%s, epoch=%s) → ok",
            post_id, author_user_id, created_at_epoch,
        )
        return True