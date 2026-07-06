"""PostServiceServicer：9 个 RPC 的 gRPC 实现，只负责编排 service。

职责范围（来自 post-service-design.md §4）:
- 从 gRPC Metadata 中提取 user_id（由 mobile-gateway 注入）。
- 设置每次请求的 trace_id / user_id 到日志上下文。
- 调用 services 层完成业务，统一捕获 BizException 与未预期异常，转换为 BaseResponse。
- 不直接访问 DB / Redis / MQ，只负责协议转换与异常兜底。
"""
import logging
import uuid

import grpc
from dating_proto_qidian_post import base_response_pb2, post_pb2, post_pb2_grpc

from config.logging_config import set_trace_id, set_user_id
from constants.error_code import ErrorCode
from exceptions.exceptions import BizException
from services.comment_service import CommentService
from services.feed_service import FeedService
from services.like_service import LikeService
from services.post_read_service import PostReadService
from services.post_write_service import PostWriteService

logger = logging.getLogger(__name__)

# gateway 注入的用户 ID metadata key
_USER_ID_METADATA_KEY = "x-user-id"


def _extract_user_id(context: grpc.ServicerContext) -> int | None:
    """从 gRPC invocation metadata 中提取 x-user-id 并转为 int。"""
    metadata = dict(context.invocation_metadata() or [])
    user_id_str = metadata.get(_USER_ID_METADATA_KEY)
    if not user_id_str:
        return None
    try:
        return int(user_id_str)
    except ValueError:
        return None


def _set_context(user_id: int | None) -> None:
    """设置本次请求的 trace_id 和 user_id 到日志上下文。"""
    trace_id = str(uuid.uuid4())
    set_trace_id(trace_id)
    set_user_id(str(user_id) if user_id else "-")


def _ok_base() -> base_response_pb2.BaseResponse:
    """构造成功 BaseResponse。"""
    return base_response_pb2.BaseResponse(code=ErrorCode.OK, message="")


def _err_base(code: int, message: str) -> base_response_pb2.BaseResponse:
    """构造失败 BaseResponse。"""
    return base_response_pb2.BaseResponse(code=code, message=message)


def _fill_post_info(proto: post_pb2.PostInfo, data: dict) -> None:
    """将 service 层返回的帖子 dict 填充到 proto PostInfo。"""
    proto.post_id = data["post_id"]
    proto.user_id = data["user_id"]
    proto.content = data["content"]
    proto.like_count = data["like_count"]
    proto.comment_count = data["comment_count"]
    proto.liked = data["liked"]
    proto.created_at = data["created_at"]
    proto.images.extend([
        post_pb2.PostImage(sort_order=i, image_key=key)
        for i, key in enumerate(data.get("image_keys", []))
    ])


def _fill_pagination(
    proto: base_response_pb2.Pagination,
    next_cursor: str,
    has_more: bool,
) -> None:
    """将分页信息填充到 proto Pagination。"""
    proto.next_cursor = next_cursor
    proto.has_more = has_more


class PostServicer(post_pb2_grpc.PostServiceServicer):
    """帖子 gRPC 服务实现类，重写 proto 定义的 9 个 RPC 方法。"""

    def __init__(self):
        self._write_service = PostWriteService()
        self._read_service = PostReadService()
        self._like_service = LikeService()
        self._comment_service = CommentService()
        self._feed_service = FeedService()

    async def CreatePost(
        self,
        request: post_pb2.CreatePostRequest,
        context: grpc.ServicerContext,
    ) -> post_pb2.CreatePostResponse:
        """创建帖子 RPC。"""
        user_id = _extract_user_id(context)
        _set_context(user_id)
        response = post_pb2.CreatePostResponse()
        try:
            if user_id is None:
                raise BizException(ErrorCode.PERMISSION_DENIED)
            post_id = await self._write_service.create_post(
                user_id=user_id,
                content=request.content,
                image_keys=list(request.image_keys),
            )
            response.base.CopyFrom(_ok_base())
            response.post_id = post_id
        except BizException as e:
            response.base.CopyFrom(_err_base(e.code, e.message))
        except Exception:
            logger.exception("CreatePost failed")
            response.base.CopyFrom(_err_base(ErrorCode.INTERNAL_ERROR, "创建帖子失败"))
        return response

    async def GetPostDetail(
        self,
        request: post_pb2.GetPostDetailRequest,
        context: grpc.ServicerContext,
    ) -> post_pb2.GetPostDetailResponse:
        """获取帖子详情 RPC。"""
        user_id = _extract_user_id(context)
        _set_context(user_id)
        response = post_pb2.GetPostDetailResponse()
        try:
            data = await self._read_service.get_post_detail(request.post_id, user_id)
            response.base.CopyFrom(_ok_base())
            _fill_post_info(response.post, data)
        except BizException as e:
            response.base.CopyFrom(_err_base(e.code, e.message))
        except Exception:
            logger.exception("GetPostDetail failed")
            response.base.CopyFrom(_err_base(ErrorCode.INTERNAL_ERROR, "获取帖子详情失败"))
        return response

    async def ListUserPosts(
        self,
        request: post_pb2.ListUserPostsRequest,
        context: grpc.ServicerContext,
    ) -> post_pb2.ListUserPostsResponse:
        """获取用户帖子列表 RPC。"""
        user_id = _extract_user_id(context)
        _set_context(user_id)
        response = post_pb2.ListUserPostsResponse()
        try:
            items, next_cursor, has_more = await self._read_service.list_user_posts(
                target_user_id=request.user_id,
                current_user_id=user_id,
                cursor=request.cursor,
                page_size=request.page_size or 10,
            )
            response.base.CopyFrom(_ok_base())
            for item in items:
                _fill_post_info(response.items.add(), item)
            _fill_pagination(response.pagination, next_cursor, has_more)
        except BizException as e:
            response.base.CopyFrom(_err_base(e.code, e.message))
        except Exception:
            logger.exception("ListUserPosts failed")
            response.base.CopyFrom(_err_base(ErrorCode.INTERNAL_ERROR, "获取用户帖子失败"))
        return response

    async def DeletePost(
        self,
        request: post_pb2.DeletePostRequest,
        context: grpc.ServicerContext,
    ) -> post_pb2.DeletePostResponse:
        """删除帖子 RPC。"""
        user_id = _extract_user_id(context)
        _set_context(user_id)
        response = post_pb2.DeletePostResponse()
        try:
            if user_id is None:
                raise BizException(ErrorCode.PERMISSION_DENIED)
            await self._write_service.delete_post(user_id, request.post_id)
            response.base.CopyFrom(_ok_base())
        except BizException as e:
            response.base.CopyFrom(_err_base(e.code, e.message))
        except Exception:
            logger.exception("DeletePost failed")
            response.base.CopyFrom(_err_base(ErrorCode.INTERNAL_ERROR, "删除帖子失败"))
        return response

    async def ActionLike(
        self,
        request: post_pb2.ActionLikeRequest,
        context: grpc.ServicerContext,
    ) -> post_pb2.ActionLikeResponse:
        """点赞 / 取消点赞 RPC。"""
        user_id = _extract_user_id(context)
        _set_context(user_id)
        response = post_pb2.ActionLikeResponse()
        try:
            if user_id is None:
                raise BizException(ErrorCode.PERMISSION_DENIED)
            if request.action == post_pb2.LIKE_ACTION_UNSPECIFIED:
                raise BizException(ErrorCode.INTERNAL_ERROR, "未指定点赞操作")
            await self._like_service.action_like(
                user_id=user_id,
                post_id=request.post_id,
                liked=request.action == post_pb2.LIKE,
            )
            response.base.CopyFrom(_ok_base())
        except BizException as e:
            response.base.CopyFrom(_err_base(e.code, e.message))
        except Exception:
            logger.exception("ActionLike failed")
            response.base.CopyFrom(_err_base(ErrorCode.INTERNAL_ERROR, "点赞操作失败"))
        return response

    async def CreateComment(
        self,
        request: post_pb2.CreateCommentRequest,
        context: grpc.ServicerContext,
    ) -> post_pb2.CreateCommentResponse:
        """创建评论 RPC。"""
        user_id = _extract_user_id(context)
        _set_context(user_id)
        response = post_pb2.CreateCommentResponse()
        try:
            if user_id is None:
                raise BizException(ErrorCode.PERMISSION_DENIED)
            comment_id = await self._comment_service.create_comment(
                user_id=user_id,
                post_id=request.post_id,
                content=request.content,
                root_id=request.root_id,
                parent_id=request.parent_id,
            )
            response.base.CopyFrom(_ok_base())
            response.comment_id = comment_id
        except BizException as e:
            response.base.CopyFrom(_err_base(e.code, e.message))
        except Exception:
            logger.exception("CreateComment failed")
            response.base.CopyFrom(_err_base(ErrorCode.INTERNAL_ERROR, "创建评论失败"))
        return response

    async def ListComments(
        self,
        request: post_pb2.ListCommentsRequest,
        context: grpc.ServicerContext,
    ) -> post_pb2.ListCommentsResponse:
        """获取评论列表 RPC。"""
        user_id = _extract_user_id(context)
        _set_context(user_id)
        response = post_pb2.ListCommentsResponse()
        try:
            items, next_cursor, has_more = await self._comment_service.list_comments(
                post_id=request.post_id,
                cursor=request.cursor,
                page_size=request.page_size or 10,
            )
            response.base.CopyFrom(_ok_base())
            for item in items:
                comment = response.items.add()
                comment.comment_id = item["comment_id"]
                comment.post_id = item["post_id"]
                comment.user_id = item["user_id"]
                comment.root_id = item["root_id"]
                comment.parent_id = item["parent_id"]
                comment.reply_to_user_id = item["reply_to_user_id"]
                comment.content = item["content"]
                comment.created_at = item["created_at"]
            _fill_pagination(response.pagination, next_cursor, has_more)
        except BizException as e:
            response.base.CopyFrom(_err_base(e.code, e.message))
        except Exception:
            logger.exception("ListComments failed")
            response.base.CopyFrom(_err_base(ErrorCode.INTERNAL_ERROR, "获取评论列表失败"))
        return response

    async def DeleteComment(
        self,
        request: post_pb2.DeleteCommentRequest,
        context: grpc.ServicerContext,
    ) -> post_pb2.DeleteCommentResponse:
        """删除评论 RPC。"""
        user_id = _extract_user_id(context)
        _set_context(user_id)
        response = post_pb2.DeleteCommentResponse()
        try:
            if user_id is None:
                raise BizException(ErrorCode.PERMISSION_DENIED)
            await self._comment_service.delete_comment(user_id, request.comment_id)
            response.base.CopyFrom(_ok_base())
        except BizException as e:
            response.base.CopyFrom(_err_base(e.code, e.message))
        except Exception:
            logger.exception("DeleteComment failed")
            response.base.CopyFrom(_err_base(ErrorCode.INTERNAL_ERROR, "删除评论失败"))
        return response

    async def GetRecommendFeed(
        self,
        request: post_pb2.GetRecommendFeedRequest,
        context: grpc.ServicerContext,
    ) -> post_pb2.GetRecommendFeedResponse:
        """获取推荐 Feed RPC。"""
        user_id = _extract_user_id(context)
        _set_context(user_id)
        response = post_pb2.GetRecommendFeedResponse()
        try:
            if user_id is None:
                raise BizException(ErrorCode.PERMISSION_DENIED)
            items, next_cursor, has_more = await self._feed_service.get_recommend_feed(
                user_id=user_id,
                page_size=request.page_size or 10,
                cursor=request.cursor,
            )
            response.base.CopyFrom(_ok_base())
            for item in items:
                _fill_post_info(response.items.add(), item)
            _fill_pagination(response.pagination, next_cursor, has_more)
        except BizException as e:
            response.base.CopyFrom(_err_base(e.code, e.message))
        except Exception:
            logger.exception("GetRecommendFeed failed")
            response.base.CopyFrom(_err_base(ErrorCode.INTERNAL_ERROR, "获取推荐 Feed 失败"))
        return response
