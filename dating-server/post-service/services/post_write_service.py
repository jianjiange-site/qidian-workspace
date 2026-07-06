"""PostWriteService：发帖 / 删帖业务编排。

职责范围（来自 post-service-design.md §4）:
- 参数校验、业务主键生成、事务内 DB 写入。
- 事务外 best-effort 操作：详情缓存、冷启动池、MQ 写扩散。
- 调用 managers 完成实际数据与缓存操作。

注意：
- 缓存 / MQ 等操作放在事务外，失败仅记录日志，不影响发帖成功。
- 冷启动池按发帖人性别分桶（男性发的帖进入 male 池，女性用户会从该池读取）。
"""
import asyncio
import logging
from datetime import datetime, timedelta

from clients.user_client import UserClient
from config.database import get_session
from config.redis import cache_key, get_redis
from config.snowflake import next_id
from constants.error_code import ErrorCode
from exceptions.exceptions import BizException
from managers.post_manager import PostManager
from managers.post_stat_manager import PostStatManager
from mq.fanout_producer import PostFanoutProducer

logger = logging.getLogger(__name__)


class PostWriteService:
    """帖子写服务，负责发帖与删帖。"""

    def __init__(self):
        self._redis = get_redis()
        self._user_client = UserClient()
        self._fanout_producer = PostFanoutProducer()

    async def create_post(self, user_id: int, content: str, image_keys: list[str]) -> int:
        """发帖。

        流程：
        1. 参数校验（空内容、长度、图片数量、空图片 key）。
        2. 生成雪花 post_id，事务内写入 posts、post_images、post_stats。
        3. 事务外写入 Redis 详情缓存、冷启动池、发送 MQ fanout。

        Args:
            user_id: 发帖人 ID（由 gateway 注入，已鉴权）。
            content: 帖子文本内容。
            image_keys: 图片对象存储 key 列表。

        Returns:
            新创建帖子的业务主键 post_id。
        """
        content = content.strip()
        if not content:
            raise BizException(ErrorCode.CONTENT_EMPTY)
        if len(content) > 1024:
            raise BizException(ErrorCode.CONTENT_TOO_LONG)
        if len(image_keys) > 9:
            raise BizException(ErrorCode.IMAGE_COUNT_EXCEEDED)
        if any(not key for key in image_keys):
            raise BizException(ErrorCode.IMAGE_KEY_EMPTY)

        post_id = next_id()

        # 事务内：写入帖子主表、图片表、计数底座
        async with get_session() as session:
            post_manager = PostManager(session, self._redis)
            stat_manager = PostStatManager(session, self._redis)

            await post_manager.create(
                post_id=post_id,
                user_id=user_id,
                content=content,
                image_keys=image_keys,
            )
            await stat_manager.create(post_id)

        # 事务外 best-effort：缓存、冷启动池、MQ
        try:
            await post_manager.cache_detail(
                post_id=post_id,
                user_id=user_id,
                content=content,
                image_keys=image_keys,
                created_at=datetime.utcnow().isoformat(),
            )
        except Exception:
            logger.warning("cache detail failed, post_id=%s", post_id, exc_info=True)

        try:
            # 按作者性别进入对应冷启动池，异性用户会读到
            is_male = await self._user_client.is_male(user_id)
            gender_key = "male" if is_male else "female"
            cold_pool_key = cache_key(f"feed:cold_start:pool:{gender_key}")
            epoch = int(datetime.utcnow().timestamp())
            await self._redis.zadd(cold_pool_key, {str(post_id): epoch})
            await self._redis.expire(cold_pool_key, timedelta(days=7))
        except Exception:
            logger.warning("cold pool failed, post_id=%s", post_id, exc_info=True)

        try:
            # 同步发送 fanout MQ，由同进程 consumer 做写扩散到关注者 timeline
            # 通过线程池调用，避免阻塞 asyncio 事件循环
            await asyncio.to_thread(
                self._fanout_producer.sync_send,
                post_id=post_id,
                author_user_id=user_id,
                created_at_epoch=int(datetime.utcnow().timestamp()),
            )
        except Exception:
            logger.error("fanout send failed, post_id=%s", post_id, exc_info=True)

        logger.info("Post created: postId=%s userId=%s images=%s", post_id, user_id, len(image_keys))
        return post_id

    async def delete_post(self, user_id: int, post_id: int) -> None:
        """删帖。

        流程：
        1. 校验帖子存在且属于当前用户。
        2. 事务内软删除帖子。
        3. 事务外清理详情缓存、冷启动池、待刷盘集合。

        Args:
            user_id: 当前操作用户 ID。
            post_id: 要删除的帖子 ID。
        """
        async with get_session() as session:
            post_manager = PostManager(session, self._redis)
            post = await post_manager.get_by_post_id(post_id)
            if post is None:
                raise BizException(ErrorCode.POST_NOT_FOUND)
            if post.user_id != user_id:
                raise BizException(ErrorCode.PERMISSION_DENIED)

            await post_manager.mark_deleted(post_id)

        # 事务外 best-effort 清理
        try:
            await post_manager.invalidate_detail(post_id)
        except Exception:
            logger.warning("invalidate detail failed, post_id=%s", post_id, exc_info=True)

        try:
            is_male = await self._user_client.is_male(user_id)
            gender_key = "male" if is_male else "female"
            cold_pool_key = cache_key(f"feed:cold_start:pool:{gender_key}")
            await self._redis.zrem(cold_pool_key, str(post_id))
        except Exception:
            logger.warning("remove from cold pool failed, post_id=%s", post_id, exc_info=True)

        try:
            await self._redis.srem(cache_key("post:updated_set"), post_id)
        except Exception:
            logger.warning("remove from updated set failed, post_id=%s", post_id, exc_info=True)
