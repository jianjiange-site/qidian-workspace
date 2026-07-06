"""CommentService：评论增删查。

职责范围（来自 post-service-design.md §4 / §5.5）:
- 评论创建：参数校验、帖子存在性校验、写入 DB 后回填 comment_id（与自增 id 等值）、写入 Redis 窗口。
- 评论列表：优先读 Redis ZSet 窗口，未命中/数据不全时读 DB 并回填缓存。
- 评论删除：仅允许评论作者删除，软删除并同步更新缓存与计数。
"""
import logging

from config.database import get_session
from config.redis import get_redis
from constants.error_code import ErrorCode
from exceptions.exceptions import BizException
from managers.post_comment_manager import PostCommentManager
from managers.post_manager import PostManager

logger = logging.getLogger(__name__)


class CommentService:
    """评论服务，负责评论的增删查。"""

    def __init__(self):
        self._redis = get_redis()

    async def create_comment(
        self,
        user_id: int,
        post_id: int,
        content: str,
        root_id: int = 0,
        parent_id: int = 0,
    ) -> int:
        """创建评论。

        Args:
            user_id: 评论作者 ID。
            post_id: 所属帖子 ID。
            content: 评论内容，最长 512 字符。
            root_id: 根评论 ID，一级评论为 0（预留楼中楼）。
            parent_id: 直接父评论 ID，一级评论为 0（预留楼中楼）。

        Returns:
            新创建评论的业务主键 comment_id。

        Raises:
            BizException: 内容为空/过长，或帖子不存在。
        """
        content = content.strip()
        if not content:
            raise BizException(ErrorCode.COMMENT_CONTENT_EMPTY)
        if len(content) > 512:
            raise BizException(ErrorCode.COMMENT_CONTENT_TOO_LONG)

        async with get_session() as session:
            post_manager = PostManager(session, self._redis)
            post = await post_manager.get_by_post_id(post_id)
            if post is None:
                raise BizException(ErrorCode.POST_NOT_FOUND)

            comment_manager = PostCommentManager(session, self._redis)
            comment = await comment_manager.create(
                post_id=post_id,
                user_id=user_id,
                content=content,
                root_id=root_id,
                parent_id=parent_id,
            )
            comment_id = comment.comment_id

        logger.info("Comment created: commentId=%s postId=%s userId=%s", comment_id, post_id, user_id)
        return comment_id

    async def list_comments(
        self,
        post_id: int,
        cursor: int,
        page_size: int,
    ) -> tuple[list[dict], str, bool]:
        """获取帖子的一级评论列表（游标分页）。

        读取策略：
        1. 先读 Redis ZSet 窗口，拿到最新 200 条内的 comment_id。
        2. 若窗口中有数据，逐条读 Hash 缓存；缓存缺失则读 DB 并回填。
        3. 若窗口为空，直接读 DB 并回填缓存。

        Args:
            post_id: 帖子业务主键。
            cursor: 游标 comment_id，首次传 0。
            page_size: 分页大小，最大限制为 50。

        Returns:
            (comments, next_cursor, has_more)
        """
        page_size = max(1, min(page_size, 50))
        async with get_session() as session:
            comment_manager = PostCommentManager(session, self._redis)
            cached_ids = await comment_manager.list_cached_comments(post_id, cursor, page_size)

            if cached_ids:
                comments = []
                for cid in cached_ids:
                    cached = await comment_manager.get_cached_comment(cid)
                    if cached:
                        comments.append(self._format_cached(cached))
                    else:
                        # 缓存被逐出或过期，回源 DB 并回填
                        comment = await comment_manager.get_by_comment_id(cid)
                        if comment:
                            await comment_manager.cache_comment(comment)
                            comments.append(self._format_db(comment))
            else:
                # 窗口未命中，兜底走数据库分页
                db_comments = await comment_manager.list_db_comments(post_id, cursor, page_size)
                comments = []
                for comment in db_comments:
                    await comment_manager.cache_comment(comment)
                    comments.append(self._format_db(comment))

        next_cursor = ""
        has_more = len(comments) == page_size
        if has_more and comments:
            next_cursor = str(comments[-1]["comment_id"])
        return comments, next_cursor, has_more

    async def delete_comment(self, user_id: int, comment_id: int) -> None:
        """删除评论。

        Args:
            user_id: 当前操作用户 ID。
            comment_id: 要删除的评论 ID。

        Raises:
            BizException: 评论不存在，或当前用户不是评论作者。
        """
        async with get_session() as session:
            comment_manager = PostCommentManager(session, self._redis)
            comment = await comment_manager.get_by_comment_id(comment_id)
            if comment is None:
                raise BizException(ErrorCode.COMMENT_NOT_FOUND)
            if comment.user_id != user_id:
                raise BizException(ErrorCode.PERMISSION_DENIED)

            await comment_manager.mark_deleted(comment)

        logger.info("Comment deleted: commentId=%s userId=%s", comment_id, user_id)

    def _format_db(self, comment) -> dict:
        """将 DB 读出的 PostComment ORM 对象格式化为 dict。"""
        return {
            "comment_id": comment.comment_id,
            "post_id": comment.post_id,
            "user_id": comment.user_id,
            "root_id": comment.root_id,
            "parent_id": comment.parent_id,
            "reply_to_user_id": comment.reply_to_user_id,
            "content": comment.content,
            "created_at": comment.created_at.isoformat(),
        }

    def _format_cached(self, cached: dict) -> dict:
        """将 Redis Hash 读出的评论缓存格式化为 dict（字段做 int 转换）。"""
        return {
            "comment_id": int(cached["comment_id"]),
            "post_id": int(cached["post_id"]),
            "user_id": int(cached["user_id"]),
            "root_id": int(cached["root_id"]),
            "parent_id": int(cached["parent_id"]),
            "reply_to_user_id": int(cached["reply_to_user_id"]),
            "content": cached["content"],
            "created_at": cached["created_at"],
        }
