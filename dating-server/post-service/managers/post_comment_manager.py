"""PostComment manager：评论增删 + ZSet 缓存窗口。

职责范围（来自 post-service-design.md §5.5 / §6）:
- 评论的创建、删除、按帖子查询。
- 使用 Redis ZSet 维护每个帖子最新 200 条评论 ID 窗口，加速列表读取。
- 评论数通过 Redis 增量累加，由 CommentFlushJob 定期刷盘。
"""
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from config.redis import cache_key
from model.post_comment_model import PostComment
from repositories.post_comment_repository import PostCommentRepository


class PostCommentManager:
    """评论管理器，负责评论持久化、Redis ZSet 窗口与计数增量。"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self._session = session
        self._redis = redis
        self._repo = PostCommentRepository(session)

    async def create(
        self,
        post_id: int,
        user_id: int,
        content: str,
        root_id: int = 0,
        parent_id: int = 0,
        reply_to_user_id: int = 0,
    ) -> PostComment:
        """创建一条评论并更新相关缓存。

        Args:
            post_id: 所属帖子 ID。
            user_id: 评论作者 ID。
            content: 评论内容。
            root_id: 根评论 ID，一级评论为 0。
            parent_id: 直接父评论 ID，一级评论为 0。
            reply_to_user_id: 被回复人 ID，一级评论为 0。

        Returns:
            创建后的 PostComment ORM 实例（comment_id 已回填为自增 id）。
        """
        comment = PostComment(
            post_id=post_id,
            user_id=user_id,
            content=content,
            root_id=root_id,
            parent_id=parent_id,
            reply_to_user_id=reply_to_user_id,
            status=1,
            deleted=0,
        )
        await self._repo.create(comment)

        # comment_id 与数据库自增主键 id 等值，用于游标分页
        comment.comment_id = comment.id

        # 将评论 ID 加入该帖子的 ZSet 窗口，score 为 comment_id（按时间自然有序）
        key = cache_key(f"post:comments:{post_id}")
        await self._redis.zadd(key, {str(comment.comment_id): comment.comment_id})
        # 只保留最新 200 条，超出部分从低分段移除
        await self._redis.zremrangebyrank(key, 0, -201)
        await self._redis.expire(key, timedelta(days=7))

        # 评论数 +1，并标记待刷盘
        await self._redis.incr(cache_key(f"post:stat:incr:{post_id}:comments"), 1)
        await self._redis.sadd(cache_key("post:updated_set"), post_id)
        await self._redis.expire(cache_key("post:updated_set"), timedelta(days=7))

        return comment

    async def get_by_comment_id(self, comment_id: int) -> PostComment | None:
        """根据业务主键查询评论（未删除）。"""
        return await self._repo.get_by_comment_id(comment_id)

    async def list_cached_comments(self, post_id: int, cursor: int, page_size: int) -> list[int]:
        """从 Redis ZSet 中读取比 cursor 更小的评论 ID（游标分页）。

        Args:
            post_id: 帖子业务主键。
            cursor: 游标 comment_id，首次传 0；下一页传上次返回的最小 comment_id。
            page_size: 本次读取条数。

        Returns:
            comment_id 列表，按 comment_id 降序（新评论 id 大，排在前面）。
        """
        key = cache_key(f"post:comments:{post_id}")
        # 游标为 0 表示第一页，从最大 score 开始取；否则取比 cursor 小的记录
        max_score = "+inf" if cursor <= 0 else cursor - 1
        members = await self._redis.zrevrangebyscore(
            key, max_score, "-inf", start=0, num=page_size
        )
        return [int(m) for m in members]

    async def list_db_comments(
        self,
        post_id: int,
        cursor: int,
        page_size: int,
    ) -> list[PostComment]:
        """从数据库查询一级评论（缓存未命中或数据不全时兜底）。"""
        return await self._repo.list_by_post_id(post_id, cursor, page_size)

    async def cache_comment(self, comment: PostComment) -> None:
        """将单条评论详情写入 Redis Hash 缓存。"""
        key = cache_key(f"post:comment:{comment.comment_id}")
        await self._redis.hset(
            key,
            mapping={
                "comment_id": comment.comment_id,
                "post_id": comment.post_id,
                "user_id": comment.user_id,
                "root_id": comment.root_id,
                "parent_id": comment.parent_id,
                "reply_to_user_id": comment.reply_to_user_id,
                "content": comment.content,
                "created_at": comment.created_at.isoformat(),
            },
        )
        await self._redis.expire(key, timedelta(days=7))

    async def get_cached_comment(self, comment_id: int) -> dict | None:
        """从 Redis Hash 读取单条评论详情缓存。"""
        key = cache_key(f"post:comment:{comment_id}")
        data = await self._redis.hgetall(key)
        return data if data else None

    async def mark_deleted(self, comment: PostComment) -> None:
        """软删除评论并同步清理相关缓存与计数。

        操作：
        - DB 中标记 deleted=1。
        - 从该帖子的评论 ZSet 中移除。
        - 评论计数 -1（Redis 增量，待 CommentFlushJob 刷盘）。
        """
        from sqlalchemy import update

        await self._session.execute(
            update(PostComment)
            .where(PostComment.comment_id == comment.comment_id)
            .values(deleted=1)
        )

        key = cache_key(f"post:comments:{comment.post_id}")
        await self._redis.zrem(key, str(comment.comment_id))
        await self._redis.incr(
            cache_key(f"post:stat:incr:{comment.post_id}:comments"), -1
        )
        await self._redis.sadd(cache_key("post:updated_set"), comment.post_id)
        await self._redis.expire(cache_key("post:updated_set"), timedelta(days=7))
