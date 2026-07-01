"""评论表 — ``post_comments``（预留楼中楼字段）

初期所有评论 root_id = parent_id = reply_to_user_id = 0，
升级楼中楼时数据库零改动，只在 service 层填好字段即可。
"""
from datetime import datetime
from sqlalchemy import BigInteger, Integer, SmallInteger, String, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PostComment(Base):
    __tablename__ = "post_comments"

    # 内部自增主键
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="内部自增主键"
    )
    # 业务主键，对外暴露
    comment_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, comment="业务主键，对外暴露"
    )
    # 所属帖子
    post_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="所属帖子业务主键"
    )
    # 评论人
    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="评论人 user_id"
    )
    # 根评论 ID（自身是根则为 0）
    root_id: Mapped[int] = mapped_column(
        BigInteger, default=0, comment="根评论 ID，自身是根则为 0"
    )
    # 直接父评论 ID
    parent_id: Mapped[int] = mapped_column(
        BigInteger, default=0, comment="直接父评论 ID，一级评论为 0"
    )
    # 被回复人
    reply_to_user_id: Mapped[int] = mapped_column(
        BigInteger, default=0, comment="被回复人 user_id，一级评论为 0"
    )
    # 评论内容，≤512
    content: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="评论内容，上限 512 字符"
    )
    # 状态
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="状态：0=已删，1=正常"
    )
    # 逻辑删除
    deleted: Mapped[int] = mapped_column(
        SmallInteger, default=0, comment="逻辑删除：0=正常，1=已删除"
    )
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        # 一级评论分页（root_id=0）
        Index("idx_comments_post_root", "post_id", "root_id", created_at.desc()),
        # 楼中楼按时间正序展开（为升级铺路）
        Index("idx_comments_root_created", "root_id", created_at.asc()),
    )
