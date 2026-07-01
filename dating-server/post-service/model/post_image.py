"""帖子图片 — ``post_images``"""
from datetime import datetime
from sqlalchemy import BigInteger, SmallInteger, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PostImage(Base):
    __tablename__ = "post_images"

    # 业务主键引用（与 sort_order 组成联合 PK）
    post_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, comment="帖子业务主键，关联 posts.post_id"
    )
    # 图片排序序号，0~8
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, comment="图片排序，取值 0~8"
    )
    # 对象存储 key，不存 URL
    image_key: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="对象存储 key，不存完整 URL"
    )
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
