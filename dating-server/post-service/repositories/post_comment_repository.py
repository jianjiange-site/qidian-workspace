"""post_comments 表 repository。

职责范围（来自 post-service-design.md §5.5）:
- 评论的插入、按 comment_id 查询、按 post_id 分页查询一级评论。
- 预留 root_id / parent_id / reply_to_user_id 字段，未来升级楼中楼时数据库零改动。
- 当前只查询 root_id=0 的一级评论，软删除过滤 deleted=0。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.post_comment_model import PostComment


class PostCommentRepository:
    """post_comments 表数据访问层。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, comment: PostComment) -> PostComment:
        """插入一条评论记录。

        Args:
            comment: PostComment ORM 实例，已填充 post_id / user_id / content 等字段；
                     comment_id 留空，由 flush 后回填为自增 id。

        Returns:
            刷新后的 PostComment 实例（含自增 id）。
        """
        self._session.add(comment)
        await self._session.flush()
        return comment

    async def get_by_comment_id(self, comment_id: int) -> PostComment | None:
        """根据业务主键 comment_id 查询未删除的评论。

        Args:
            comment_id: 评论业务主键。

        Returns:
            PostComment 实例；不存在或已删除返回 None。
        """
        result = await self._session.execute(
            select(PostComment).where(
                PostComment.comment_id == comment_id,
                PostComment.deleted == 0,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_post_id(
        self,
        post_id: int,
        cursor: int,
        page_size: int,
    ) -> list[PostComment]:
        """查询指定帖子的一级评论列表（游标分页）。

        Args:
            post_id: 帖子业务主键。
            cursor: 游标，上一次返回的最小 comment_id；首次传 0。
            page_size: 本次查询条数。

        Returns:
            按 comment_id 降序排列的一级评论列表（root_id=0）。
        """
        stmt = (
            select(PostComment)
            .where(
                PostComment.post_id == post_id,
                PostComment.root_id == 0,  # 仅查询一级评论
                PostComment.deleted == 0,
            )
            .order_by(PostComment.comment_id.desc())
        )
        if cursor > 0:
            # 游标分页：只取比上次最小 comment_id 更小的记录
            stmt = stmt.where(PostComment.comment_id < cursor)
        stmt = stmt.limit(page_size)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
