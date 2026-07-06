"""FeedScoreJob：每 5 分钟重建推荐 Feed 池。

设计背景（来自 post-service-design.md §7 / §8）:
- 推荐池按性别分桶：男性用户看到女性发的帖，女性用户看到男性发的帖。
- 池内保存近 3 天帖子，按 Hacker News 变体公式计算综合分，只保留前 3000。
- 读接口从池中取推荐帖，与好友时间线、冷启动池三路混合。

本 Job 仅做轻量编排，实际打分/写池逻辑在 FeedService.rebuild_recommend_pool() 中。
"""
import logging

from jobs.lock_utils import distributed_lock
from services.feed_service import FeedService

logger = logging.getLogger(__name__)


class FeedScoreJob:
    """推荐 Feed 池重建定时任务。"""

    @distributed_lock("FeedScoreJob", lock_seconds=600)
    async def run(self) -> None:
        """Job 入口，由 APScheduler 每 5 分钟调度一次。"""
        feed_service = FeedService()
        # 重新计算近 3 天帖子的综合分，并按性别写入推荐池
        await feed_service.rebuild_recommend_pool()
        logger.info("Feed score job completed")
