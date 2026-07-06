"""post-service 业务异常定义。

约定：
- gRPC 层统一 catch BizException → 转成 proto BaseResponse{code, message}
- gRPC status code 一律 OK，业务错误靠 BaseResponse.code 区分
"""
from constants.error_code import ErrorCode, get_message


class BizException(Exception):
    """业务异常。

    在 service 层抛出，由 gRPC 层统一捕获并转为 proto BaseResponse。

    Usage:
        raise BizException(ErrorCode.POST_NOT_FOUND)
        raise BizException(ErrorCode.CONTENT_TOO_LONG, "自定义提示")
    """

    def __init__(self, code: int | ErrorCode, message: str = ""):
        if isinstance(code, ErrorCode):
            self.code = code.value
        else:
            self.code = code
        self.message = message or get_message(self.code)
        super().__init__(f"[{self.code}] {self.message}")

    def to_dict(self) -> dict:
        """转为字典，方便填充 proto BaseResponse。"""
        return {"code": self.code, "message": self.message}