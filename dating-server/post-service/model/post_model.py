"""posts 表模型 — 帖子主表。"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class Post(Base):
    """帖子主表。

    字段说明（来自 post-service-design.md §5.1）:
    - id: 内部物理主键，自增 bigserial，不对外暴露。
    - post_id: 业务主键，雪花 ID，跨库稳定，全局唯一。
    - user_id: 发帖人用户 ID。
    - content: 帖子文本内容，最长 1024 字符。
    - status: 帖子状态，0=已删除 / 1=正常 / 2=审核中。
    - deleted: 逻辑删除标记，0=未删除 / 1=已删除。
    - created_at: 创建时间，TIMESTAMPTZ，默认 CURRENT_TIMESTAMP。
    - updated_at: 更新时间，TIMESTAMPTZ，默认 CURRENT_TIMESTAMP。
    """

    __tablename__ = "posts"

    # 内部物理主键，自增，不对外暴露
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 业务主键，雪花 ID，跨库稳定
    post_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    # 发帖人用户 ID
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 帖子文本内容，VARCHAR(1024)，服务端限制长度
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 帖子状态：0=已删除 / 1=正常 / 2=审核中
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    # 逻辑删除标记：0=未删除 / 1=已删除
    deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        # (user_id, created_at DESC) —— 「我的动态」分页
        Index("idx_posts_user_id_created_at", "user_id", "created_at"),
    )
