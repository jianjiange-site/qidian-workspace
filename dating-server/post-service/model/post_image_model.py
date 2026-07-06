"""post_images 表模型 — 帖子图片。"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, PrimaryKeyConstraint, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PostImage(Base):
    """帖子图片表。

    字段说明（来自 post-service-design.md §5.2）:
    - post_id: 业务主键引用，指向 posts.post_id。
    - sort_order: 图片在帖子中的排序，0..8，最多 9 张。
    - image_key: 对象存储 key（如 MinIO），服务端不存完整 URL。
    - created_at: 创建时间。

    主键为 (post_id, sort_order) 联合主键，便于未来按 post_id 范围分表/分区。
    """

    __tablename__ = "post_images"

    # 业务主键引用，指向 posts.post_id
    post_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 图片排序，0..8
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # 对象存储 key，不存 URL
    image_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        # (post_id, sort_order) 联合主键
        PrimaryKeyConstraint("post_id", "sort_order"),
    )
