"""帖子写操作 gRPC Servicer — 继承生成的 PostServiceServicer。

实现 CreatePost / DeletePost 两个 RPC，user_id 从 gRPC Metadata 取。
"""
import json
import logging
import time
from datetime import datetime

from proto_stubs.post.post_pb2 import (
    CreatePostRequest,
    CreatePostResponse,
    DeletePostRequest,
    DeletePostResponse,
)
from proto_stubs.common.base_response_pb2 import BaseResponse
from proto_stubs.post.post_pb2_grpc import PostServiceServicer

from config.database import get_db
from config.redis import get_redis, cache_key
from config.snowflake import next_id
from client.user_client import UserClient
from constant.error_code import ErrorCode
from exception import BizException
from mq.producer.post_fanout_producer import PostFanoutProducer
from model import Post, PostImage, PostStat

logger = logging.getLogger(__name__)

# ---------- 依赖（待接入真实组件后替换） ----------

_user_client = UserClient()
_fanout_producer = PostFanoutProducer()

# ---------- 常量 ----------

MAX_CONTENT_LEN = 1024
MAX_IMAGES = 9
DETAIL_TTL_SECONDS = 7 * 24 * 3600


class PostWriteService(PostServiceServicer):
    """发帖 / 删帖 gRPC 接口实现。

    其余 7 个 RPC 未实现，调用方会收到 UNIMPLEMENTED 状态码。
    """

    # ====================================================================
    # CreatePost
    # ====================================================================

    async def CreatePost(self, request: CreatePostRequest, context) -> CreatePostResponse:
        """发布帖子。

        流程：
        1. 入口校验
        2. 生成雪花 post_id
        3. 事务写入 posts + post_images + post_stats
        4. Redis 缓存帖子详情
        5. 入冷启动池
        6. 写扩散 MQ
        7. 返回 post_id
        """
        user_id = _get_user_id(context)

        try:
            post_id = await self._do_create(user_id, request.content, list(request.image_keys))
            return CreatePostResponse(base=BaseResponse(code=0), post_id=post_id)
        except BizException as e:
            logger.warning("CreatePost biz err: [%s] %s", e.code, e.message)
            return CreatePostResponse(base=BaseResponse(code=e.code, message=e.message))
        except Exception:
            logger.exception("CreatePost 内部错误")
            return CreatePostResponse(
                base=BaseResponse(code=ErrorCode.INTERNAL_ERROR.value, message="服务内部错误")
            )

    async def _do_create(self, user_id: int, content: str, image_keys: list[str]) -> int:
        # ---- 1. 入口校验 ----
        if not content or not content.strip():
            raise BizException(ErrorCode.CONTENT_EMPTY)
        if len(content) > MAX_CONTENT_LEN:
            raise BizException(ErrorCode.CONTENT_TOO_LONG, f"当前 {len(content)} 字，上限 {MAX_CONTENT_LEN}")
        if len(image_keys) > MAX_IMAGES:
            raise BizException(ErrorCode.IMAGE_COUNT_EXCEEDED, f"当前 {len(image_keys)} 张，上限 {MAX_IMAGES}")
        for key in image_keys:
            if not key or not key.strip():
                raise BizException(ErrorCode.IMAGE_KEY_EMPTY)

        # ---- 2. 生成 ID ----
        post_id = next_id()
        now_epoch = int(time.time())

        # ---- 3. 事务写入 ----
        async for session in get_db():
            session.add(Post(post_id=post_id, user_id=user_id, content=content, status=1))
            for i, key in enumerate(image_keys):
                session.add(PostImage(post_id=post_id, sort_order=i, image_key=key))
            session.add(PostStat(post_id=post_id, like_count=0, comment_count=0))
            await session.commit()
        logger.info("发帖成功: post_id=%s, user_id=%s, images=%s", post_id, user_id, len(image_keys))

        # ---- 4. Redis 缓存 ----
        try:
            r = get_redis()
            detail = {
                "post_id": str(post_id),
                "user_id": str(user_id),
                "content": content,
                "image_keys": json.dumps(image_keys, ensure_ascii=False),
                "like_count": "0",
                "comment_count": "0",
                "created_at": datetime.utcnow().isoformat(),
            }
            await r.hset(cache_key(f"post:detail:{post_id}"), mapping=detail)
            await r.expire(cache_key(f"post:detail:{post_id}"), DETAIL_TTL_SECONDS)
        except Exception:
            logger.warning("Redis 缓存失败, post_id=%s", post_id, exc_info=True)

        # ---- 5. 冷启动池 ----
        try:
            r = get_redis()
            is_male = await _user_client.is_male(user_id)
            pool = cache_key(f"feed:cold_start:pool:{'male' if is_male else 'female'}")
            await r.zadd(pool, {str(post_id): now_epoch})
            await r.expire(pool, DETAIL_TTL_SECONDS)
        except Exception:
            logger.warning("冷启动池写入失败, post_id=%s", post_id, exc_info=True)

        # ---- 6. 写扩散 ----
        try:
            ok = _fanout_producer.sync_send(post_id, user_id, now_epoch)
            if not ok:
                logger.error("写扩散失败, post_id=%s", post_id)
        except Exception:
            logger.exception("写扩散异常, post_id=%s")

        return post_id

    # ====================================================================
    # DeletePost
    # ====================================================================

    async def DeletePost(self, request: DeletePostRequest, context) -> DeletePostResponse:
        """删除帖子（逻辑删除）。

        流程：
        1. SELECT 校验：存在 + 未删 + 作者本人
        2. UPDATE deleted = 1
        3. 清除缓存 + 冷启动池 + 待刷盘集合
        4. 不删 post_likes / post_comments（留审计）
        5. 不删 timeline（读侧容错）
        """
        user_id = _get_user_id(context)
        post_id = request.post_id

        try:
            await self._do_delete(post_id, user_id)
            return DeletePostResponse(base=BaseResponse(code=0))
        except BizException as e:
            logger.warning("DeletePost biz err: [%s] %s", e.code, e.message)
            return DeletePostResponse(base=BaseResponse(code=e.code, message=e.message))
        except Exception:
            logger.exception("DeletePost 内部错误")
            return DeletePostResponse(
                base=BaseResponse(code=ErrorCode.INTERNAL_ERROR.value, message="服务内部错误")
            )

    async def _do_delete(self, post_id: int, user_id: int) -> None:
        from sqlalchemy import select

        # ---- 1. 校验 ----
        async for session in get_db():
            result = await session.execute(
                select(Post).where(Post.post_id == post_id, Post.deleted == 0)
            )
            post = result.scalar_one_or_none()
            if post is None:
                raise BizException(ErrorCode.POST_NOT_FOUND)
            if post.user_id != user_id:
                raise BizException(ErrorCode.PERMISSION_DENIED)

            # ---- 2. 逻辑删除 ----
            post.deleted = 1
            await session.commit()
        logger.info("删帖成功: post_id=%s, user_id=%s", post_id, user_id)

        # ---- 3. 清除缓存 & 池 ----
        try:
            r = get_redis()
            await r.delete(cache_key(f"post:detail:{post_id}"))
            for gender in ("male", "female"):
                await r.zrem(cache_key(f"feed:cold_start:pool:{gender}"), str(post_id))
            await r.srem(cache_key("post:updated_set"), str(post_id))
        except Exception:
            logger.warning("缓存清除失败, post_id=%s", post_id, exc_info=True)


# ---------- 辅助 ----------

def _get_user_id(context) -> int:
    """从 gRPC Metadata 提取 x-user-id。"""
    metadata = dict(context.invocation_metadata())
    return int(metadata.get("x-user-id", "0"))