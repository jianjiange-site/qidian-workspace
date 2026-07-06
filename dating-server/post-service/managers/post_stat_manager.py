"""PostStat manager：计数底座 + Redis 增量读写。

职责范围（来自 post-service-design.md §5.3 / §6.2）:
- 维护「DB 计数底座 + Redis 未刷盘增量」的实时计数模型。
- 提供增量写入、实时读取、原子刷盘、待刷盘集合管理。
- session 为 None 时，仅操作 Redis（供 Job 使用）。
"""
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from config.redis import cache_key
from model.post_stat_model import PostStat
from repositories.post_stat_repository import PostStatRepository


class PostStatManager:
    """帖子计数管理器，负责底座 + Redis 增量的读写与刷盘协调。"""

    def __init__(self, session: AsyncSession | None, redis: Redis):
        self._session = session
        self._redis = redis
        # session 为 None 时，repo 不会被使用（Job 纯 Redis 阶段）
        self._repo = PostStatRepository(session) if session else None

    async def create(self, post_id: int) -> PostStat:
        """发帖时初始化计数底座（like_count=0, comment_count=0）。"""
        stat = PostStat(post_id=post_id, like_count=0, comment_count=0)
        return await self._repo.create(stat)

    async def get_base(self, post_id: int) -> PostStat | None:
        """查询已刷盘的计数底座。"""
        return await self._repo.get_by_post_id(post_id)

    async def get_realtime_counts(self, post_id: int) -> tuple[int, int]:
        """获取实时点赞数与评论数。

        实时值 = post_stats 底座 + Redis 未刷盘增量。
        即使 Job 正在刷盘，由于 Lua 原子取走增量，用户看到的结果始终一致。
        """
        base = await self.get_base(post_id)
        base_likes = base.like_count if base else 0
        base_comments = base.comment_count if base else 0

        like_incr = await self._redis.get(cache_key(f"post:stat:incr:{post_id}:likes"))
        comment_incr = await self._redis.get(
            cache_key(f"post:stat:incr:{post_id}:comments")
        )
        return (
            base_likes + int(like_incr or 0),
            base_comments + int(comment_incr or 0),
        )

    async def incr_like(self, post_id: int, delta: int) -> None:
        """点赞/取消点赞时累加 Redis 点赞增量，并标记待刷盘。"""
        await self._redis.incr(cache_key(f"post:stat:incr:{post_id}:likes"), delta)
        await self._mark_updated(post_id)

    async def incr_comment(self, post_id: int, delta: int) -> None:
        """评论/删评论时累加 Redis 评论增量，并标记待刷盘。"""
        await self._redis.incr(cache_key(f"post:stat:incr:{post_id}:comments"), delta)
        await self._mark_updated(post_id)

    async def _mark_updated(self, post_id: int) -> None:
        """将 post_id 加入待刷盘集合，供 LikeFlushJob / CommentFlushJob 消费。"""
        key = cache_key("post:updated_set")
        await self._redis.sadd(key, post_id)
        await self._redis.expire(key, timedelta(days=7))

    async def remove_from_updated_set(self, *post_ids: int) -> None:
        """从待刷盘集合中移除已完全刷盘的 post_id。"""
        if not post_ids:
            return
        await self._redis.srem(cache_key("post:updated_set"), *post_ids)

    async def pop_updated_post_ids(self, count: int) -> list[int]:
        """随机取出 count 个待刷盘 post_id（不会真正移除集合元素）。"""
        members = await self._redis.srandmember(cache_key("post:updated_set"), count)
        return [int(m) for m in members]

    async def get_remaining_delta(self, post_id: int) -> tuple[int, int]:
        """获取 post_id 剩余的点赞/评论未刷盘增量。"""
        like_incr = await self._redis.get(cache_key(f"post:stat:incr:{post_id}:likes"))
        comment_incr = await self._redis.get(
            cache_key(f"post:stat:incr:{post_id}:comments")
        )
        return int(like_incr or 0), int(comment_incr or 0)

    async def flush_like_delta(self, post_id: int) -> int:
        """原子性地取走并归零 Redis 点赞增量。

        使用 Lua 脚本保证 GET 和 SET 0 的原子性，避免并发下丢数。
        """
        key = cache_key(f"post:stat:incr:{post_id}:likes")
        lua = """
            local v = redis.call('GET', KEYS[1])
            redis.call('SET', KEYS[1], 0)
            return v or 0
        """
        value = await self._redis.eval(lua, 1, key)
        return int(value or 0)

    async def flush_comment_delta(self, post_id: int) -> int:
        """原子性地取走并归零 Redis 评论增量。"""
        key = cache_key(f"post:stat:incr:{post_id}:comments")
        lua = """
            local v = redis.call('GET', KEYS[1])
            redis.call('SET', KEYS[1], 0)
            return v or 0
        """
        value = await self._redis.eval(lua, 1, key)
        return int(value or 0)

    async def persist_like_delta(self, post_id: int, delta: int) -> bool:
        """将点赞增量持久化到 post_stats（由 Job 在事务中调用）。"""
        if delta == 0:
            return True
        return await self._repo.increment_like(post_id, delta)

    async def persist_comment_delta(self, post_id: int, delta: int) -> bool:
        """将评论增量持久化到 post_stats（由 Job 在事务中调用）。"""
        if delta == 0:
            return True
        return await self._repo.increment_comment(post_id, delta)
