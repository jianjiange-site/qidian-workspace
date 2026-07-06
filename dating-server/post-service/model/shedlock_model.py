"""shedlock 表模型 — 多实例定时任务互斥锁。

设计背景（来自 post-service-design.md §6.1 / §5.1）:
- 本地单实例开发可以不接；部署多实例前必须接，否则 LikeFlushJob / CommentFlushJob /
  FeedScoreJob 会在多个 pod 上重复跑，浪费 PG 资源并可能产生脏数据。
- 表结构参考 Java Shedlock 设计，用 PG 行级锁/唯一主键做互斥，过期时间兜底防止
  进程崩溃后死锁。
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class Shedlock(Base):
    """分布式任务锁表。

    字段说明:
    - name: 任务名称，主键。例如 "LikeFlushJob"。
    - lock_until: 锁的过期时间。超过该时间后其他实例可以抢占。
    - locked_at: 本次加锁时间，用于审计。
    - locked_by: 加锁实例标识（hostname + pid），方便排查。
    """

    __tablename__ = "shedlock"

    # 任务名称，全局唯一
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 锁过期时间，超过后其他实例可抢占
    lock_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 本次加锁时间
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # 加锁实例标识
    locked_by: Mapped[str] = mapped_column(String(255), nullable=False)
