"""PostReadService：帖子详情 / 用户帖子列表。

职责范围（来自 post-service-design.md §4）:
- 帖子详情读取：先读 Redis Hash 缓存，未命中再读 DB 并回填缓存。
- 用户帖子列表：游标分页，返回实时点赞/评论数及当前用户是否点赞。
- 读路径体现 Write Coalescing：实时计数 = DB 底座 + Redis 增量。
"""
import logging

from config.database import get_session
from config.redis import cache_key, get_redis
from constants.error_code import ErrorCode
from exceptions.exceptions import BizException
from managers.post_manager import PostManager
from managers.post_stat_manager import PostStatManager
from managers.post_like_manager import PostLikeManager

logger = logging.getLogger(__name__)


class PostReadService:
    """帖子读服务，负责详情与列表。"""

    def __init__(self):
        self._redis = get_redis()

    async def get_post_detail(self, post_id: int, current_user_id: int | None = None) -> dict:
        """获取帖子详情。

        流程：
        1. 优先读 Redis 详情缓存，命中则直接组装返回。
        2. 未命中则读 DB，回填 Redis 缓存后返回。

        Args:
            post_id: 帖子业务主键。
            current_user_id: 当前 viewing 用户 ID，用于判断是否已点赞；可为 None。

        Returns:
            包含帖子详情、实时计数、点赞状态的 dict。
        """
        async with get_session() as session:
            post_manager = PostManager(session, self._redis)
            stat_manager = PostStatManager(session, self._redis)
            like_manager = PostLikeManager(session, self._redis)

            cached = await post_manager.get_cached_detail(post_id)
            if cached:
                return await self._assemble_from_cache(
                    cached, stat_manager, like_manager, current_user_id
                )

            post = await post_manager.get_by_post_id(post_id)
            if post is None:
                raise BizException(ErrorCode.POST_NOT_FOUND)

            images = await post_manager.get_images(post_id)
            like_count, comment_count = await stat_manager.get_realtime_counts(post_id)
            liked = False
            if current_user_id:
                liked = await like_manager.is_liked(current_user_id, post_id)

            image_keys = [img.image_key for img in images]
            await post_manager.cache_detail(
                post_id=post_id,
                user_id=post.user_id,
                content=post.content,
                image_keys=image_keys,
                created_at=post.created_at.isoformat(),
            )

            return {
                "post_id": post.post_id,
                "user_id": post.user_id,
                "content": post.content,
                "image_keys": image_keys,
                "like_count": like_count,
                "comment_count": comment_count,
                "liked": liked,
                "created_at": post.created_at.isoformat(),
            }

    async def _assemble_from_cache(
        self,
        cached: dict,
        stat_manager: PostStatManager,
        like_manager: PostLikeManager,
        current_user_id: int | None,
    ) -> dict:
        """根据 Redis Hash 缓存组装帖子详情。

        缓存中 image_keys 以逗号拼接存储，返回前拆分为列表。
        """
        post_id = int(cached["post_id"])
        like_count, comment_count = await stat_manager.get_realtime_counts(post_id)
        liked = False
        if current_user_id:
            liked = await like_manager.is_liked(current_user_id, post_id)

        image_keys = cached.get("image_keys", "")
        return {
            "post_id": post_id,
            "user_id": int(cached["user_id"]),
            "content": cached["content"],
            "image_keys": image_keys.split(",") if image_keys else [],
            "like_count": like_count,
            "comment_count": comment_count,
            "liked": liked,
            "created_at": cached["created_at"],
        }

    async def list_user_posts(
        self,
        target_user_id: int,
        current_user_id: int | None,
        cursor: int,
        page_size: int,
    ) -> tuple[list[dict], str, bool]:
        """获取指定用户的帖子列表（游标分页）。

        Args:
            target_user_id: 要查看的用户 ID。
            current_user_id: 当前 viewing 用户 ID，用于判断点赞状态；可为 None。
            cursor: 游标 post_id，首次传 0。
            page_size: 分页大小，最大限制为 50。

        Returns:
            (items, next_cursor, has_more)
        """
        page_size = max(1, min(page_size, 50))
        async with get_session() as session:
            post_manager = PostManager(session, self._redis)
            stat_manager = PostStatManager(session, self._redis)
            like_manager = PostLikeManager(session, self._redis)

            posts = await post_manager.list_by_user_id(target_user_id, cursor, page_size)
            items = []
            for post in posts:
                like_count, comment_count = await stat_manager.get_realtime_counts(post.post_id)
                liked = False
                if current_user_id:
                    liked = await like_manager.is_liked(current_user_id, post.post_id)

                images = await post_manager.get_images(post.post_id)
                items.append({
                    "post_id": post.post_id,
                    "user_id": post.user_id,
                    "content": post.content,
                    "image_keys": [img.image_key for img in images],
                    "like_count": like_count,
                    "comment_count": comment_count,
                    "liked": liked,
                    "created_at": post.created_at.isoformat(),
                })

        next_cursor = ""
        has_more = len(items) == page_size
        if has_more and items:
            # 下一页游标为本次最后一条 post_id
            next_cursor = str(items[-1]["post_id"])
        return items, next_cursor, has_more
