"""发帖写扩散 MQ Consumer：消费 fanout 消息后，拉 followers 后 ZADD timeline。

严格按 post-service-design.md §10.2.2 实现：
- SimpleConsumer 长轮询消费（由 config.mq 拉起后台任务）
- 拉取作者好友列表（user-service），失败抛异常让 RocketMQ 自动重投
- 对每个 follower：ZADD timeline → 裁剪至 100 条 → EXPIRE 7d
- 消息重投天然幂等：相同 post_id + epoch 覆盖写入同一 score
"""
import json
import logging
from datetime import timedelta

from redis.asyncio import Redis

from clients.user_client import UserClient
from config.redis import cache_key, get_redis

logger = logging.getLogger(__name__)


class PostFanoutConsumer:
    """消费 fanout 消息后，将帖子写入每个关注者的 timeline。"""

    def __init__(self, user_client: UserClient, redis: Redis):
        self._user_client = user_client
        self._redis = redis

    async def consume(self, body: bytes) -> bool:
        """处理一条 fanout 消息。

        Args:
            body: RocketMQ 消息体，JSON 格式：{"postId": int, "authorUserId": int, "createdAtEpoch": int}

        Returns:
            True 表示消费成功（RocketMQ 可 ack）。
            解析失败 / 缺字段也返回 True，避免非法消息无限重投。
            user-service 调用失败则抛出异常，由 RocketMQ 自动重投。
        """
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            logger.error("invalid fanout message body: %s", body)
            return True  # 无法解析的消息直接 ack，避免无限重投

        post_id = data.get("postId")
        author_id = data.get("authorUserId")
        epoch = data.get("createdAtEpoch")
        if not all([post_id, author_id, epoch]):
            logger.error("missing fields in fanout message: %s", data)
            return True

        try:
            followers = await self._user_client.get_friend_user_ids(author_id)
        except Exception:
            logger.exception("get_friend_user_ids failed, author=%s", author_id)
            raise  # 让 RocketMQ 重投，给上游 user-service 喘息时间

        if not followers:
            return True

        for follower in followers:
            key = cache_key(f"user:timeline:{follower}")
            pipe = self._redis.pipeline()
            pipe.zadd(key, {str(post_id): epoch})
            pipe.zremrangebyrank(key, 0, -101)  # 保留最近 100 条
            pipe.expire(key, timedelta(days=7))
            await pipe.execute()

        logger.info("Fanout complete: postId=%s followers=%s", post_id, len(followers))
        return True


def create_consumer() -> PostFanoutConsumer:
    """工厂函数：由 config.mq 启动 consumer 循环时调用。"""
    return PostFanoutConsumer(UserClient(), get_redis())
