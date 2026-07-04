from common import base_response_pb2 as _base_response_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class LikeAction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    LIKE_ACTION_UNSPECIFIED: _ClassVar[LikeAction]
    LIKE: _ClassVar[LikeAction]
    UNLIKE: _ClassVar[LikeAction]
LIKE_ACTION_UNSPECIFIED: LikeAction
LIKE: LikeAction
UNLIKE: LikeAction

class PostImage(_message.Message):
    __slots__ = ("sort_order", "image_key")
    SORT_ORDER_FIELD_NUMBER: _ClassVar[int]
    IMAGE_KEY_FIELD_NUMBER: _ClassVar[int]
    sort_order: int
    image_key: str
    def __init__(self, sort_order: _Optional[int] = ..., image_key: _Optional[str] = ...) -> None: ...

class PostInfo(_message.Message):
    __slots__ = ("post_id", "user_id", "content", "images", "like_count", "comment_count", "liked", "created_at")
    POST_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IMAGES_FIELD_NUMBER: _ClassVar[int]
    LIKE_COUNT_FIELD_NUMBER: _ClassVar[int]
    COMMENT_COUNT_FIELD_NUMBER: _ClassVar[int]
    LIKED_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    post_id: int
    user_id: int
    content: str
    images: _containers.RepeatedCompositeFieldContainer[PostImage]
    like_count: int
    comment_count: int
    liked: bool
    created_at: str
    def __init__(self, post_id: _Optional[int] = ..., user_id: _Optional[int] = ..., content: _Optional[str] = ..., images: _Optional[_Iterable[_Union[PostImage, _Mapping]]] = ..., like_count: _Optional[int] = ..., comment_count: _Optional[int] = ..., liked: bool = ..., created_at: _Optional[str] = ...) -> None: ...

class CommentInfo(_message.Message):
    __slots__ = ("comment_id", "post_id", "user_id", "root_id", "parent_id", "reply_to_user_id", "content", "created_at")
    COMMENT_ID_FIELD_NUMBER: _ClassVar[int]
    POST_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    REPLY_TO_USER_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    comment_id: int
    post_id: int
    user_id: int
    root_id: int
    parent_id: int
    reply_to_user_id: int
    content: str
    created_at: str
    def __init__(self, comment_id: _Optional[int] = ..., post_id: _Optional[int] = ..., user_id: _Optional[int] = ..., root_id: _Optional[int] = ..., parent_id: _Optional[int] = ..., reply_to_user_id: _Optional[int] = ..., content: _Optional[str] = ..., created_at: _Optional[str] = ...) -> None: ...

class CreatePostRequest(_message.Message):
    __slots__ = ("content", "image_keys")
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IMAGE_KEYS_FIELD_NUMBER: _ClassVar[int]
    content: str
    image_keys: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, content: _Optional[str] = ..., image_keys: _Optional[_Iterable[str]] = ...) -> None: ...

class CreatePostResponse(_message.Message):
    __slots__ = ("base", "post_id")
    BASE_FIELD_NUMBER: _ClassVar[int]
    POST_ID_FIELD_NUMBER: _ClassVar[int]
    base: _base_response_pb2.BaseResponse
    post_id: int
    def __init__(self, base: _Optional[_Union[_base_response_pb2.BaseResponse, _Mapping]] = ..., post_id: _Optional[int] = ...) -> None: ...

class GetPostDetailRequest(_message.Message):
    __slots__ = ("post_id",)
    POST_ID_FIELD_NUMBER: _ClassVar[int]
    post_id: int
    def __init__(self, post_id: _Optional[int] = ...) -> None: ...

class GetPostDetailResponse(_message.Message):
    __slots__ = ("base", "post")
    BASE_FIELD_NUMBER: _ClassVar[int]
    POST_FIELD_NUMBER: _ClassVar[int]
    base: _base_response_pb2.BaseResponse
    post: PostInfo
    def __init__(self, base: _Optional[_Union[_base_response_pb2.BaseResponse, _Mapping]] = ..., post: _Optional[_Union[PostInfo, _Mapping]] = ...) -> None: ...

class ListUserPostsRequest(_message.Message):
    __slots__ = ("user_id", "page_size", "cursor")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    user_id: int
    page_size: int
    cursor: int
    def __init__(self, user_id: _Optional[int] = ..., page_size: _Optional[int] = ..., cursor: _Optional[int] = ...) -> None: ...

class ListUserPostsResponse(_message.Message):
    __slots__ = ("base", "items", "pagination")
    BASE_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    PAGINATION_FIELD_NUMBER: _ClassVar[int]
    base: _base_response_pb2.BaseResponse
    items: _containers.RepeatedCompositeFieldContainer[PostInfo]
    pagination: _base_response_pb2.Pagination
    def __init__(self, base: _Optional[_Union[_base_response_pb2.BaseResponse, _Mapping]] = ..., items: _Optional[_Iterable[_Union[PostInfo, _Mapping]]] = ..., pagination: _Optional[_Union[_base_response_pb2.Pagination, _Mapping]] = ...) -> None: ...

class DeletePostRequest(_message.Message):
    __slots__ = ("post_id",)
    POST_ID_FIELD_NUMBER: _ClassVar[int]
    post_id: int
    def __init__(self, post_id: _Optional[int] = ...) -> None: ...

class DeletePostResponse(_message.Message):
    __slots__ = ("base",)
    BASE_FIELD_NUMBER: _ClassVar[int]
    base: _base_response_pb2.BaseResponse
    def __init__(self, base: _Optional[_Union[_base_response_pb2.BaseResponse, _Mapping]] = ...) -> None: ...

class ActionLikeRequest(_message.Message):
    __slots__ = ("post_id", "action")
    POST_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    post_id: int
    action: LikeAction
    def __init__(self, post_id: _Optional[int] = ..., action: _Optional[_Union[LikeAction, str]] = ...) -> None: ...

class ActionLikeResponse(_message.Message):
    __slots__ = ("base",)
    BASE_FIELD_NUMBER: _ClassVar[int]
    base: _base_response_pb2.BaseResponse
    def __init__(self, base: _Optional[_Union[_base_response_pb2.BaseResponse, _Mapping]] = ...) -> None: ...

class CreateCommentRequest(_message.Message):
    __slots__ = ("post_id", "content", "root_id", "parent_id")
    POST_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    post_id: int
    content: str
    root_id: int
    parent_id: int
    def __init__(self, post_id: _Optional[int] = ..., content: _Optional[str] = ..., root_id: _Optional[int] = ..., parent_id: _Optional[int] = ...) -> None: ...

class CreateCommentResponse(_message.Message):
    __slots__ = ("base", "comment_id")
    BASE_FIELD_NUMBER: _ClassVar[int]
    COMMENT_ID_FIELD_NUMBER: _ClassVar[int]
    base: _base_response_pb2.BaseResponse
    comment_id: int
    def __init__(self, base: _Optional[_Union[_base_response_pb2.BaseResponse, _Mapping]] = ..., comment_id: _Optional[int] = ...) -> None: ...

class ListCommentsRequest(_message.Message):
    __slots__ = ("post_id", "page_size", "cursor")
    POST_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    post_id: int
    page_size: int
    cursor: int
    def __init__(self, post_id: _Optional[int] = ..., page_size: _Optional[int] = ..., cursor: _Optional[int] = ...) -> None: ...

class ListCommentsResponse(_message.Message):
    __slots__ = ("base", "items", "pagination")
    BASE_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    PAGINATION_FIELD_NUMBER: _ClassVar[int]
    base: _base_response_pb2.BaseResponse
    items: _containers.RepeatedCompositeFieldContainer[CommentInfo]
    pagination: _base_response_pb2.Pagination
    def __init__(self, base: _Optional[_Union[_base_response_pb2.BaseResponse, _Mapping]] = ..., items: _Optional[_Iterable[_Union[CommentInfo, _Mapping]]] = ..., pagination: _Optional[_Union[_base_response_pb2.Pagination, _Mapping]] = ...) -> None: ...

class DeleteCommentRequest(_message.Message):
    __slots__ = ("comment_id",)
    COMMENT_ID_FIELD_NUMBER: _ClassVar[int]
    comment_id: int
    def __init__(self, comment_id: _Optional[int] = ...) -> None: ...

class DeleteCommentResponse(_message.Message):
    __slots__ = ("base",)
    BASE_FIELD_NUMBER: _ClassVar[int]
    base: _base_response_pb2.BaseResponse
    def __init__(self, base: _Optional[_Union[_base_response_pb2.BaseResponse, _Mapping]] = ...) -> None: ...

class GetRecommendFeedRequest(_message.Message):
    __slots__ = ("page_size", "cursor")
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    page_size: int
    cursor: str
    def __init__(self, page_size: _Optional[int] = ..., cursor: _Optional[str] = ...) -> None: ...

class GetRecommendFeedResponse(_message.Message):
    __slots__ = ("base", "items", "pagination")
    BASE_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    PAGINATION_FIELD_NUMBER: _ClassVar[int]
    base: _base_response_pb2.BaseResponse
    items: _containers.RepeatedCompositeFieldContainer[PostInfo]
    pagination: _base_response_pb2.Pagination
    def __init__(self, base: _Optional[_Union[_base_response_pb2.BaseResponse, _Mapping]] = ..., items: _Optional[_Iterable[_Union[PostInfo, _Mapping]]] = ..., pagination: _Optional[_Union[_base_response_pb2.Pagination, _Mapping]] = ...) -> None: ...

class BaseRequest(_message.Message):
    __slots__ = ("extra",)
    class ExtraEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    EXTRA_FIELD_NUMBER: _ClassVar[int]
    extra: _containers.ScalarMap[str, str]
    def __init__(self, extra: _Optional[_Mapping[str, str]] = ...) -> None: ...
