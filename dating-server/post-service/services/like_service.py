"""LikeService：点赞 / 取消点赞业务编排。

职责范围（来自 post-service-design.md §4）:
- 校验帖子存在性。
- 在事务内调用 PostLikeManager 完成幂等 upsert 与 Redis 增量。
- 事务提交后记录日志。
"""
import logging

from config.database import get_session
from config.redis import get_redis
from constants.error_code import ErrorCode
from exceptions.exceptions import BizException
from managers.post_like_manager import PostLikeManager
from managers.post_manager import PostManager

logger = logging.getLogger(__name__)


class LikeService:
    """点赞服务，负责点赞 / 取消点赞的业务编排。"""

    def __init__(self):
        self._redis = get_redis()

    async def action_like(self, user_id: int, post_id: int, liked: bool) -> None:
        """处理点赞或取消点赞。

        Args:
            user_id: 操作用户 ID。
            post_id: 被点赞帖子 ID。
            liked: True 为点赞，False 为取消点赞。

        Raises:
            BizException: 帖子不存在时抛出 POST_NOT_FOUND。
        """
        async with get_session() as session:
            post_manager = PostManager(session, self._redis)
            post = await post_manager.get_by_post_id(post_id)
            if post is None:
                raise BizException(ErrorCode.POST_NOT_FOUND)

            like_manager = PostLikeManager(session, self._redis)
            await like_manager.action(user_id, post_id, liked)

        logger.info("Like action: userId=%s postId=%s liked=%s", user_id, post_id, liked)
