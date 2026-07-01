"""点赞幂等记录 — ``post_likes``

联合主键 (user_id, post_id)，不 DELETE 而是 UPDATE status=0，
再次点赞时复用同一行，ON CONFLICT DO UPDATE。
"""
from datetime import datetime
from sqlalchemy import BigInteger, SmallInteger, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PostLike(Base):
    __tablename__ = "post_likes"

    # 点赞用户
    user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, comment="点赞用户 user_id"
    )
    # 被赞帖子
    post_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, comment="被赞帖子业务主键"
    )
    # 1=已赞 / 0=已取消
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="点赞状态：1=已赞，0=已取消"
    )
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        # 反查「谁赞了这帖」— Partial Index 省空间
        Index(
            "idx_post_likes_post_status",
            "post_id",
            postgresql_where=(status == 1),
        ),
    )
