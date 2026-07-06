"""LikeFlushJob：每分钟把 Redis 点赞增量批量刷盘到 post_stats。

设计背景（来自 post-service-design.md §6.2）:
- 爆款场景下，直接 UPDATE post_stats 单行会被行锁串行化，导致 DB 连接池打满。
- 我们的方案：点赞接口只 INCR Redis 增量；本 Job 每分钟聚合后批量刷盘。
- 1000 次点赞合并成 1 次 UPDATE，显著降低 PG 行锁持有时间。

执行流程：
1. 从 Redis Set 中随机取出 100 个「有待刷盘增量」的 post_id。
2. 对每个 post_id，原子性地取走点赞增量（Lua GET + SET 0）。
3. 在数据库事务中把增量累加到 post_stats.like_count。
4. 若某 post_id 的点赞和评论增量都已归零，从待刷盘集合中移除。
"""
import logging

from config.database import get_session
from config.redis import get_redis
from jobs.lock_utils import distributed_lock
from managers.post_stat_manager import PostStatManager

logger = logging.getLogger(__name__)


class LikeFlushJob:
    """点赞计数刷盘定时任务。"""

    def __init__(self):
        # 无 DB session 的 PostStatManager 仅用于操作 Redis
        self._redis = get_redis()

    @distributed_lock("LikeFlushJob", lock_seconds=120)
    async def run(self) -> None:
        """Job 入口，由 APScheduler 每分钟调度一次。"""
        # 1. 取出这分钟有变动的 100 个 post_id（SRANDMEMBER，不会真正移除）
        post_ids = await PostStatManager(None, self._redis).pop_updated_post_ids(100)
        if not post_ids:
            return

        # 2. 对每个 post_id，原子取走点赞增量并刷盘
        flushed = 0
        for post_id in post_ids:
            delta = await PostStatManager(None, self._redis).flush_like_delta(post_id)
            if delta == 0:
                continue
            async with get_session() as session:
                stat_manager = PostStatManager(session, self._redis)
                await stat_manager.persist_like_delta(post_id, delta)
            flushed += 1

        # 3. 清理已完全刷盘的 post_id，避免下次空跑
        to_remove = []
        for post_id in post_ids:
            remaining_likes, remaining_comments = await PostStatManager(
                None, self._redis
            ).get_remaining_delta(post_id)
            if remaining_likes == 0 and remaining_comments == 0:
                to_remove.append(post_id)
        if to_remove:
            await PostStatManager(None, self._redis).remove_from_updated_set(*to_remove)

        logger.info("Like flush completed, processed=%s flushed=%s", len(post_ids), flushed)
