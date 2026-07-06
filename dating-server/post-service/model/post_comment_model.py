"""post_comments 表模型 — 评论（预留楼中楼）。"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PostComment(Base):
    """评论表，预留楼中楼扩展字段。

    字段说明（来自 post-service-design.md §5.5）:
    - id: 内部物理主键，自增 bigserial。
    - comment_id: 业务主键，对外暴露，简单库可与 id 等值。
    - post_id: 所属帖子 ID。
    - user_id: 评论作者 ID。
    - root_id: 根评论 ID；自身是根评论时为 0。
    - parent_id: 直接父评论 ID；一级评论为 0。
    - reply_to_user_id: 被回复人用户 ID；一级评论为 0。
    - content: 评论文本内容，最长 512 字符。
    - status: 评论状态，0=已删除 / 1=正常。
    - deleted: 逻辑删除标记，0=未删除 / 1=已删除。
    - created_at: 创建时间。

    设计要点：
    - 初期所有评论 root_id = parent_id = reply_to_user_id = 0。
    - 升级楼中楼时数据库零改动，只在 service 层填字段、读侧多查一次。
    """

    __tablename__ = "post_comments"

    # 内部物理主键，自增
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 业务主键，对外暴露；与 id 等值，插入时先为空，flush 获得 id 后再回填
    comment_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    # 所属帖子 ID
    post_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 评论作者 ID
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 根评论 ID，自身是根则为 0
    root_id: Mapped[int] = mapped_column(BigInteger, default=0)
    # 直接父评论 ID，一级评论为 0
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    # 被回复人用户 ID，一级评论为 0
    reply_to_user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    # 评论文本内容，VARCHAR(512)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 评论状态：0=已删除 / 1=正常
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    # 逻辑删除标记：0=未删除 / 1=已删除
    deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        # (post_id, root_id, created_at DESC) —— 一级评论分页（root_id=0）
        Index("idx_post_comments_post_root_created", "post_id", "root_id", "created_at"),
        # (root_id, created_at ASC) —— 楼中楼按时间正序展开
        Index("idx_post_comments_root_created", "root_id", "created_at"),
    )
