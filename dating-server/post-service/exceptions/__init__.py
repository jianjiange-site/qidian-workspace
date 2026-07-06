"""post-service 异常模块。

gRPC 层统一 catch BizException → 转 proto BaseResponse，status code 一律 OK。
"""
from .exceptions import BizException

__all__ = ["BizException"]