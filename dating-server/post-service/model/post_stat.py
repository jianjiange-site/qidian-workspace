"""计数底座 — ``post_stats``

只存已刷盘部分，实时值 = 底座 + Redis 增量。
"""
from datetime import datetime
from sqlalchemy import BigInteger, Integer, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PostStat(Base):
    __tablename__ = "post_stats"

    # 帖子业务主键
    post_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, comment="帖子业务主键，关联 posts.post_id"
    )
    # 累计点赞（已刷盘部分）
    like_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="累计点赞数（已刷盘部分）"
    )
    # 累计评论
    comment_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="累计评论数（已刷盘部分）"
    )
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        # 给未来「最热」榜单留口子
        Index("idx_post_stats_likes", like_count.desc()),
        Index("idx_post_stats_comments", comment_count.desc()),
    )
