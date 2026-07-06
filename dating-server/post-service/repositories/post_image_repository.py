"""post_images 表 repository。

职责范围（来自 post-service-design.md §5.2）:
- 帖子图片的批量写入与按 post_id 查询。
- 主表 post 不存图片，图片单独成表以降低写放大。
- 图片排序由 sort_order 保证，查询时按 sort_order 升序返回。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.post_image_model import PostImage


class PostImageRepository:
    """post_images 表数据访问层。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, image: PostImage) -> PostImage:
        """插入单条图片记录。

        Args:
            image: PostImage ORM 实例。

        Returns:
            刷新后的 PostImage 实例。
        """
        self._session.add(image)
        await self._session.flush()
        return image

    async def batch_create(self, images: list[PostImage]) -> list[PostImage]:
        """批量插入图片记录（发帖时最多 9 张）。

        Args:
            images: PostImage ORM 实例列表。

        Returns:
            刷新后的 PostImage 实例列表。
        """
        self._session.add_all(images)
        await self._session.flush()
        return images

    async def list_by_post_id(self, post_id: int) -> list[PostImage]:
        """查询指定帖子的所有图片，按 sort_order 升序返回。

        Args:
            post_id: 帖子业务主键。

        Returns:
            PostImage 列表，顺序与客户端上传顺序一致。
        """
        result = await self._session.execute(
            select(PostImage)
            .where(PostImage.post_id == post_id)
            .order_by(PostImage.sort_order.asc())
        )
        return list(result.scalars().all())
