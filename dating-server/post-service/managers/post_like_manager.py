"""PostLike manager：点赞 upsert + Redis 增量。

职责范围（来自 post-service-design.md §5.4 / §6.2）:
- 调用 repository 完成点赞记录的幂等 upsert。
- 状态真正变化时，累加 Redis 点赞增量并标记待刷盘。
- 查询当前用户是否已点赞（用于帖子详情返回 liked 字段）。
"""
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from config.redis import cache_key
from repositories.post_like_repository import PostLikeRepository


class PostLikeManager:
    """点赞管理器，负责点赞状态变更与 Redis 增量协调。"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self._session = session
        self._redis = redis
        self._repo = PostLikeRepository(session)

    async def action(self, user_id: int, post_id: int, liked: bool) -> bool:
        """处理点赞 / 取消点赞。

        Args:
            user_id: 操作用户 ID。
            post_id: 被点赞帖子 ID。
            liked: True 表示点赞，False 表示取消点赞。

        Returns:
            True 表示状态发生变化；False 表示已经是目标状态（幂等，不触发增量）。
        """
        status = 1 if liked else 0
        # upsert 返回 True 说明数据库行真的被修改了
        changed = await self._repo.upsert(user_id, post_id, status)
        if changed:
            # 点赞 +1，取消点赞 -1
            delta = 1 if liked else -1
            await self._redis.incr(cache_key(f"post:stat:incr:{post_id}:likes"), delta)
            await self._redis.sadd(cache_key("post:updated_set"), post_id)
            # 给增量 key 和待刷盘集合都设置 TTL，避免冷 key 长期占用内存
            await self._redis.expire(
                cache_key(f"post:stat:incr:{post_id}:likes"), timedelta(days=7)
            )
            await self._redis.expire(cache_key("post:updated_set"), timedelta(days=7))
        return changed

    async def is_liked(self, user_id: int, post_id: int) -> bool:
        """查询用户是否已点赞指定帖子。"""
        record = await self._repo.get(user_id, post_id)
        return record is not None and record.status == 1
