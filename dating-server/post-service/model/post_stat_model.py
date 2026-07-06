"""post_stats 表模型 — 计数底座。"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PostStat(Base):
    """帖子计数底座表。

    字段说明（来自 post-service-design.md §5.3）:
    - post_id: 业务主键，与 posts.post_id 1:1。
    - like_count: 已刷盘的累计点赞数（实时值 = 底座 + Redis 增量）。
    - comment_count: 已刷盘的累计评论数（实时值 = 底座 + Redis 增量）。
    - updated_at: 最后一次刷盘/更新时间。

    关键约束：本表只存「已刷盘」部分，高频写合并走 Redis 增量 + APScheduler 刷盘。
    """

    __tablename__ = "post_stats"

    # 业务主键，与 posts.post_id 1:1
    post_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # 已刷盘的累计点赞数
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    # 已刷盘的累计评论数
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    # 最后一次刷盘/更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
