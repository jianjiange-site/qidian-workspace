"""post-service 业务错误码定义。

gRPC status code 一律 OK，业务错误用 code 区分。
4xxx = 业务错误，5xxx = 系统错误。
"""
from enum import IntEnum


class ErrorCode(IntEnum):
    """业务错误码，值与 Nacos 配置 / proto 契约对齐。"""

    # ---------- 成功 ----------
    OK = 0

    # ---------- 帖子 (40xx) ----------
    CONTENT_EMPTY = 4001          # content 为空
    CONTENT_TOO_LONG = 4002       # content 超长（>1024）
    IMAGE_COUNT_EXCEEDED = 4003   # 图片数量超限（>9）
    IMAGE_KEY_EMPTY = 4004        # 图片 key 为空
    POST_NOT_FOUND = 4005         # 帖子不存在

    # ---------- 评论 (400x) ----------
    COMMENT_NOT_FOUND = 4006       # 评论不存在
    COMMENT_CONTENT_EMPTY = 4007   # 评论内容为空
    COMMENT_CONTENT_TOO_LONG = 4008  # 评论内容超长（>512）

    # ---------- 权限 (403x) ----------
    PERMISSION_DENIED = 4030      # 权限不足（非作者操作）

    # ---------- 系统 (5xxx) ----------
    INTERNAL_ERROR = 5000         # 内部错误


# 错误码 → 默认中文消息
_ERROR_MESSAGES: dict[int, str] = {
    ErrorCode.CONTENT_EMPTY: "帖子内容不能为空",
    ErrorCode.CONTENT_TOO_LONG: "帖子内容超过 1024 字",
    ErrorCode.IMAGE_COUNT_EXCEEDED: "图片数量不能超过 9 张",
    ErrorCode.IMAGE_KEY_EMPTY: "图片标识不能为空",
    ErrorCode.POST_NOT_FOUND: "帖子不存在",
    ErrorCode.COMMENT_NOT_FOUND: "评论不存在",
    ErrorCode.COMMENT_CONTENT_EMPTY: "评论内容不能为空",
    ErrorCode.COMMENT_CONTENT_TOO_LONG: "评论内容超过 512 字",
    ErrorCode.PERMISSION_DENIED: "权限不足",
    ErrorCode.INTERNAL_ERROR: "服务内部错误",
}


def get_message(code: int, fallback: str = "") -> str:
    """根据错误码获取默认中文消息。"""
    return _ERROR_MESSAGES.get(code, fallback)