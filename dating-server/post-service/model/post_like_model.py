"""post_likes 表模型 — 点赞幂等记录。"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, PrimaryKeyConstraint, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PostLike(Base):
    """点赞幂等记录表。

    字段说明（来自 post-service-design.md §5.4）:
    - user_id: 点赞用户 ID。
    - post_id: 被点赞的帖子 ID。
    - status: 点赞状态，1=已赞 / 0=已取消。
    - created_at: 首次点赞时间。
    - updated_at: 状态变更时间。

    设计要点：
    - 联合主键 (user_id, post_id) 防重复点赞。
    - 不 DELETE，而是 UPDATE status=0，复用同一行避免 INSERT 冲突。
    - 索引 (post_id, status) 用于反查「谁赞了这帖」，Partial Index 可进一步限定 status=1。
    """

    __tablename__ = "post_likes"

    # 点赞用户 ID
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 被点赞的帖子 ID
    post_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 点赞状态：1=已赞 / 0=已取消
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    # 首次点赞时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # 状态变更时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        # (user_id, post_id) 联合主键，防重复点赞
        PrimaryKeyConstraint("user_id", "post_id"),
        # (post_id, status) —— 反查「谁赞了这帖」
        Index("idx_post_likes_post_id_status", "post_id", "status"),
    )
