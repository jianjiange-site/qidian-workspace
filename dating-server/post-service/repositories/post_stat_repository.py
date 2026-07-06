"""post_stats 表 repository — 计数底座。

职责范围（来自 post-service-design.md §5.3 / §6.2）:
- 帖子计数底座的创建、查询、批量查询。
- 点赞 / 评论增量的持久化刷盘（Write Coalescing）。
- 实时计数 = 底座 + Redis 增量，由 manager 层合并。
"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from model.post_stat_model import PostStat


class PostStatRepository:
    """post_stats 表数据访问层。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, stat: PostStat) -> PostStat:
        """插入一条计数底座记录（发帖时初始化 like_count=0, comment_count=0）。

        Args:
            stat: PostStat ORM 实例。

        Returns:
            刷新后的 PostStat 实例。
        """
        self._session.add(stat)
        await self._session.flush()
        return stat

    async def get_by_post_id(self, post_id: int) -> PostStat | None:
        """根据 post_id 查询计数底座。

        Args:
            post_id: 帖子业务主键。

        Returns:
            PostStat 实例；不存在返回 None。
        """
        result = await self._session.execute(
            select(PostStat).where(PostStat.post_id == post_id)
        )
        return result.scalar_one_or_none()

    async def batch_get_by_post_ids(self, post_ids: list[int]) -> list[PostStat]:
        """批量查询多个帖子的计数底座。

        Args:
            post_ids: 帖子业务主键列表。

        Returns:
            PostStat 实例列表，用于 Feed 池重建等批量场景。
        """
        result = await self._session.execute(
            select(PostStat).where(PostStat.post_id.in_(post_ids))
        )
        return list(result.scalars().all())

    async def increment_like(self, post_id: int, delta: int) -> bool:
        """将 Redis 中累加的点赞增量刷盘到 post_stats。

        Args:
            post_id: 帖子业务主键。
            delta: 点赞增量（可正可负，由 LikeFlushJob 聚合后写入）。

        Returns:
            是否真的有记录被更新。
        """
        result = await self._session.execute(
            update(PostStat)
            .where(PostStat.post_id == post_id)
            .values(like_count=PostStat.like_count + delta)
        )
        return result.rowcount > 0

    async def increment_comment(self, post_id: int, delta: int) -> bool:
        """将 Redis 中累加的评论增量刷盘到 post_stats。

        Args:
            post_id: 帖子业务主键。
            delta: 评论增量（可正可负，由 CommentFlushJob 聚合后写入）。

        Returns:
            是否真的有记录被更新。
        """
        result = await self._session.execute(
            update(PostStat)
            .where(PostStat.post_id == post_id)
            .values(comment_count=PostStat.comment_count + delta)
        )
        return result.rowcount > 0
