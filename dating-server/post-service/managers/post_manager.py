"""Post 聚合 manager：帖子 + 图片读写、详情缓存。

职责范围（来自 post-service-design.md §4）:
- 聚合 posts 与 post_images 两张表的操作。
- 帖子详情缓存（Redis Hash），TTL 7 天。
- 被 services 层调用，不直接对外暴露。

调用方向：grpc_server → services → managers → repositories。
"""
from datetime import datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from config.redis import cache_key
from model.post_model import Post
from model.post_image_model import PostImage
from repositories.post_repository import PostRepository
from repositories.post_image_repository import PostImageRepository


class PostManager:
    """帖子聚合管理器，负责帖子主表 + 图片表 + 详情缓存。"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self._session = session
        self._redis = redis
        self._post_repo = PostRepository(session)
        self._image_repo = PostImageRepository(session)

    async def create(
        self,
        post_id: int,
        user_id: int,
        content: str,
        image_keys: list[str],
    ) -> Post:
        """创建帖子主记录并批量插入图片。

        Args:
            post_id: 雪花算法生成的业务主键。
            user_id: 发帖人 ID。
            content: 帖子文本内容。
            image_keys: 图片对象存储 key 列表，最多 9 张。

        Returns:
            创建后的 Post ORM 实例。
        """
        post = Post(
            post_id=post_id,
            user_id=user_id,
            content=content,
            status=1,
            deleted=0,
        )
        await self._post_repo.create(post)

        # 按传入顺序生成 PostImage 记录，sort_order 从 0 开始
        images = [
            PostImage(post_id=post_id, sort_order=i, image_key=key)
            for i, key in enumerate(image_keys)
        ]
        if images:
            await self._image_repo.batch_create(images)

        return post

    async def get_by_post_id(self, post_id: int) -> Post | None:
        """根据业务主键查询帖子（未删除）。"""
        return await self._post_repo.get_by_post_id(post_id)

    async def get_images(self, post_id: int) -> list[PostImage]:
        """查询指定帖子的所有图片，按 sort_order 排序。"""
        return await self._image_repo.list_by_post_id(post_id)

    async def cache_detail(
        self,
        post_id: int,
        user_id: int,
        content: str,
        image_keys: list[str],
        created_at: str,
    ) -> None:
        """将帖子详情写入 Redis Hash 缓存。

        缓存 key: <prefix>:post:detail:{post_id}
        缓存内容: post_id / user_id / content / image_keys / created_at。
        """
        key = cache_key(f"post:detail:{post_id}")
        await self._redis.hset(
            key,
            mapping={
                "post_id": post_id,
                "user_id": user_id,
                "content": content,
                "image_keys": ",".join(image_keys),
                "created_at": created_at,
            },
        )
        await self._redis.expire(key, timedelta(days=7))

    async def get_cached_detail(self, post_id: int) -> dict | None:
        """从 Redis Hash 读取帖子详情缓存。"""
        key = cache_key(f"post:detail:{post_id}")
        data = await self._redis.hgetall(key)
        if not data:
            return None
        return data

    async def invalidate_detail(self, post_id: int) -> None:
        """删除帖子详情缓存（删帖时调用）。"""
        key = cache_key(f"post:detail:{post_id}")
        await self._redis.delete(key)

    async def list_by_user_id(
        self,
        user_id: int,
        cursor: int,
        page_size: int,
    ) -> list[Post]:
        """查询指定用户的帖子列表（游标分页）。"""
        return await self._post_repo.list_by_user_id(user_id, cursor, page_size)

    async def mark_deleted(self, post_id: int) -> bool:
        """软删除帖子。"""
        return await self._post_repo.mark_deleted(post_id)
