"""帖子主表 — ``posts``"""
from datetime import datetime
from sqlalchemy import BigInteger, Integer, SmallInteger, String, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class Post(Base):
    __tablename__ = "posts"

    # 内部物理主键，不对外暴露
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="内部物理主键"
    )
    # 雪花 ID，跨库稳定的业务主键
    post_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, comment="雪花 ID，跨库稳定的业务主键"
    )
    # 发帖人
    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="发帖人 user_id"
    )
    # 文本内容，≤1024
    content: Mapped[str] = mapped_column(
        String(1024), nullable=False, comment="帖子文本，上限 1024 字符"
    )
    # 0=已删 / 1=正常 / 2=审核中
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="状态：0=已删，1=正常，2=审核中"
    )
    # MyBatis-Plus @TableLogic 等价，逻辑删除标记
    deleted: Mapped[int] = mapped_column(
        SmallInteger, default=0, comment="逻辑删除：0=正常，1=已删除"
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
        # 「我的动态」分页
        Index("idx_posts_user_created", "user_id", created_at.desc()),
    )
