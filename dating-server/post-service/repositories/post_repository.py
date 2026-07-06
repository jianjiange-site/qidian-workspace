"""posts 表 repository — 单表 CRUD。

职责范围（来自 post-service-design.md §5.1）:
- 帖子主表的插入、查询、软删除。
- 所有查询默认过滤 deleted=0，不对外暴露内部自增 id。
- 分页以 post_id 为游标（游标分页，避免深页码问题）。
"""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from model.post_model import Post


class PostRepository:
    """posts 表数据访问层。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, post: Post) -> Post:
        """插入一条帖子记录。

        Args:
            post: Post ORM 实例，已填充 post_id / user_id / content 等字段。

        Returns:
            刷新后的 Post 实例（含自增 id）。
        """
        self._session.add(post)
        await self._session.flush()
        return post

    async def get_by_post_id(self, post_id: int) -> Post | None:
        """根据业务主键 post_id 查询未删除的帖子。

        Args:
            post_id: 帖子业务主键。

        Returns:
            Post 实例；不存在或已删除则返回 None。
        """
        result = await self._session.execute(
            select(Post).where(Post.post_id == post_id, Post.deleted == 0)
        )
        return result.scalar_one_or_none()

    async def list_by_user_id(
        self,
        user_id: int,
        cursor: int,
        page_size: int,
    ) -> list[Post]:
        """查询指定用户的帖子列表（游标分页）。

        Args:
            user_id: 目标用户 ID。
            cursor: 游标，上一次返回的最小 post_id；首次传 0。
            page_size: 本次查询条数。

        Returns:
            按 post_id 降序排列的 Post 列表。
        """
        stmt = (
            select(Post)
            .where(Post.user_id == user_id, Post.deleted == 0, Post.status == 1)
            .order_by(Post.post_id.desc())
            .limit(page_size)
        )
        if cursor > 0:
            # 游标分页：只取比上次最小 post_id 更小的记录
            stmt = stmt.where(Post.post_id < cursor)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_deleted(self, post_id: int) -> bool:
        """软删除帖子（更新 deleted=1, status=0）。

        Args:
            post_id: 帖子业务主键。

        Returns:
            是否真的有记录被更新。
        """
        result = await self._session.execute(
            update(Post)
            .where(Post.post_id == post_id, Post.deleted == 0)
            .values(deleted=1, status=0, updated_at=datetime.now(timezone.utc))
        )
        return result.rowcount > 0

    async def list_recent_ids(self, since: datetime) -> list[int]:
        """查询某时间点之后创建的未删除帖子 ID 列表。

        Args:
            since: 时间下限，用于 Feed 池重建等场景。

        Returns:
            post_id 列表。
        """
        result = await self._session.execute(
            select(Post.post_id)
            .where(Post.deleted == 0, Post.status == 1, Post.created_at >= since)
        )
        return list(result.scalars().all())

    async def list_recent(self, since: datetime) -> list[Post]:
        """查询某时间点之后创建的未删除帖子完整记录。

        Args:
            since: 时间下限，用于 Feed 池重建等场景。

        Returns:
            Post 实例列表。
        """
        result = await self._session.execute(
            select(Post)
            .where(Post.deleted == 0, Post.status == 1, Post.created_at >= since)
        )
        return list(result.scalars().all())
