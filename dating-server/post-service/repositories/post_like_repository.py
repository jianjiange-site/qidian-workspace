"""post_likes 表 repository — 幂等 upsert。

职责范围（来自 post-service-design.md §5.4 / §6.2）:
- 点赞记录的幂等写入：使用 PostgreSQL 方言的 upsert（INSERT ... ON CONFLICT DO UPDATE）。
- 当状态未变化时返回 False，避免重复触发 Redis 增量。
- 联合主键 (user_id, post_id) 天然防重复点赞。
"""
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from model.post_like_model import PostLike


class PostLikeRepository:
    """post_likes 表数据访问层。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def upsert(self, user_id: int, post_id: int, status: int) -> bool:
        """幂等 upsert 点赞记录。

        行为：
        - 首次点赞：插入 (user_id, post_id, status=1)。
        - 取消点赞后再次点赞：更新 status=1，复用原行。
        - 已经是目标状态：ON CONFLICT WHERE 条件不命中，rowcount=0，返回 False。

        Args:
            user_id: 点赞用户 ID。
            post_id: 被点赞帖子 ID。
            status: 目标状态，1=已赞 / 0=已取消。

        Returns:
            True 表示数据库状态真的发生了改变；False 表示已经是目标状态（幂等）。
        """
        stmt = (
            insert(PostLike)
            .values(
                user_id=user_id,
                post_id=post_id,
                status=status,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                index_elements=["user_id", "post_id"],
                set_={
                    "status": status,
                    "updated_at": datetime.now(timezone.utc),
                },
                # 仅当状态发生变化时才更新，实现幂等
                where=(PostLike.status != status),
            )
        )
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def get(self, user_id: int, post_id: int) -> PostLike | None:
        """查询 (user_id, post_id) 的点赞记录。

        Args:
            user_id: 点赞用户 ID。
            post_id: 被点赞帖子 ID。

        Returns:
            PostLike 实例；不存在返回 None。
        """
        from sqlalchemy import select

        result = await self._session.execute(
            select(PostLike).where(
                PostLike.user_id == user_id,
                PostLike.post_id == post_id,
            )
        )
        return result.scalar_one_or_none()
