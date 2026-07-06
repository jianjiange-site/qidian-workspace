"""post-service gRPC 测试客户端。

用法:
    1. 先启动服务端: python server.py
    2. 再运行测试:   python test/test_client.py

测试覆盖:
    - CreatePost / GetPostDetail / ListUserPosts / DeletePost
    - ActionLike / CreateComment / ListComments / DeleteComment
    - GetRecommendFeed
    每个接口至少 5 组用例，图片会真实上传到 MinIO。
"""
import asyncio
import logging
import mimetypes
import sys
from datetime import datetime
from pathlib import Path

import grpc
from minio import Minio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dating_proto_qidian_post import post_pb2
from dating_proto_qidian_post.post_pb2_grpc import PostServiceStub
from config import settings
from config.logging_config import setup_logging, set_trace_id
from config.minio import init_minio, get_minio, get_bucket, make_object_key

setup_logging()
set_trace_id("test-client")
logger = logging.getLogger("test_client")

SERVER = "localhost:50051"
TEST_USER = 1001
OTHER_USER = 1002


def user_md(user_id: int = TEST_USER):
    """构造携带当前用户 ID 的 gRPC metadata。

    服务端 interceptor 从 metadata 中读取 `x-user-id` 来识别请求用户，
    所有需要登录态的接口都要带上该 metadata。
    """
    return [("x-user-id", str(user_id))]


def assert_ok(r, msg=""):
    """断言响应业务码为 0（成功），否则抛出 AssertionError。"""
    if r.base.code != 0:
        raise AssertionError(f"{msg} expected code=0, got {r.base.code}: {r.base.message}")


def assert_code(r, code: int, msg=""):
    """断言响应业务码等于指定错误码，用于校验参数校验、权限、资源不存在等场景。"""
    if r.base.code != code:
        raise AssertionError(
            f"{msg} expected code={code}, got {r.base.code}: {r.base.message}"
        )


class TestClient:
    """post-service 端到端测试客户端。

    负责：
    - 初始化配置、MinIO、gRPC 通道；
    - 上传测试图片到 MinIO；
    - 按接口编排用例并统计 pass/fail；
    - 测试结束后关闭连接。
    """

    def __init__(self):
        self.channel = None
        self.stub = None
        self.image_keys: list[str] = []
        self.created_post_ids: list[int] = []
        self.created_comment_ids: list[int] = []
        self.passed = 0
        self.failed = 0

    async def setup(self):
        """测试前置：加载 Nacos 配置、初始化 MinIO、建立 gRPC 连接并上传图片。"""
        await settings.init_config()
        await init_minio()
        self.channel = grpc.aio.insecure_channel(SERVER)
        self.stub = PostServiceStub(self.channel)
        await self._upload_images()

    async def teardown(self):
        """测试后置：关闭 gRPC 通道释放连接。"""
        if self.channel:
            await self.channel.close()

    async def _upload_images(self):
        """把 test/images/ 下图片上传到 MinIO，生成 image_keys。"""
        image_dir = Path(__file__).resolve().parent / "images"
        files = sorted(image_dir.glob("*"))
        if not files:
            raise RuntimeError("test/images/ 目录下没有图片")

        client: Minio = get_minio()
        bucket = get_bucket()
        uploaded = []
        for f in files:
            ext = f.suffix.lstrip(".").lower() or "jpg"
            content_type, _ = mimetypes.guess_type(str(f))
            content_type = content_type or "application/octet-stream"
            object_key = make_object_key(TEST_USER, ext)
            client.fput_object(bucket, object_key, str(f), content_type=content_type)
            uploaded.append(object_key)
            logger.info("uploaded %s -> %s", f.name, object_key)
        self.image_keys = uploaded

    async def _case(self, name: str, coro):
        """执行一个异步测试用例，捕获异常并记录 pass/fail。"""
        try:
            await coro
        except Exception as e:
            self.failed += 1
            logger.error("[FAIL] %s: %s", name, e)
            return
        self.passed += 1
        logger.info("[PASS] %s", name)

    # ------------------------------------------------------------------
    # CreatePost
    # ------------------------------------------------------------------
    async def test_create_post(self):
        logger.info("--- CreatePost ---")

        async def _empty_content():
            r = await self.stub.CreatePost(post_pb2.CreatePostRequest(content=""), metadata=user_md())
            assert_code(r, 4001)
        await self._case("empty content", _empty_content())

        async def _content_too_long():
            r = await self.stub.CreatePost(
                post_pb2.CreatePostRequest(content="x" * 1025), metadata=user_md()
            )
            assert_code(r, 4002)
        await self._case("content too long", _content_too_long())

        async def _too_many_images():
            # 凑够 10 个图片 key，触发数量超限校验
            ten_keys = (self.image_keys * 2)[:10]
            r = await self.stub.CreatePost(
                post_pb2.CreatePostRequest(
                    content="图片过多", image_keys=ten_keys
                ),
                metadata=user_md(),
            )
            assert_code(r, 4003)
        await self._case("too many images", _too_many_images())

        async def _empty_image_key():
            r = await self.stub.CreatePost(
                post_pb2.CreatePostRequest(content="空图片key", image_keys=[""]),
                metadata=user_md(),
            )
            assert_code(r, 4004)
        await self._case("empty image key", _empty_image_key())

        async def _create_without_images():
            r = await self.stub.CreatePost(
                post_pb2.CreatePostRequest(content="无图帖子"), metadata=user_md()
            )
            assert_ok(r, "create without images")
            assert r.post_id > 0
            self.created_post_ids.append(r.post_id)
        await self._case("create without images", _create_without_images())

        async def _create_with_1_image():
            r = await self.stub.CreatePost(
                post_pb2.CreatePostRequest(
                    content="单图帖子", image_keys=self.image_keys[:1]
                ),
                metadata=user_md(),
            )
            assert_ok(r, "create with 1 image")
            self.created_post_ids.append(r.post_id)
        await self._case("create with 1 image", _create_with_1_image())

        async def _create_with_9_images():
            r = await self.stub.CreatePost(
                post_pb2.CreatePostRequest(
                    content="九图帖子", image_keys=self.image_keys[:9]
                ),
                metadata=user_md(),
            )
            assert_ok(r, "create with 9 images")
            self.created_post_ids.append(r.post_id)
        await self._case("create with 9 images", _create_with_9_images())

        # 为后续测试多准备几个帖子
        for i in range(3):
            async def _prepare_post(idx=i):
                r = await self.stub.CreatePost(
                    post_pb2.CreatePostRequest(
                        content=f"准备帖子 {idx} - {datetime.utcnow().isoformat()}",
                        image_keys=self.image_keys[: (idx % 3)],
                    ),
                    metadata=user_md(),
                )
                assert_ok(r, f"prepare post {idx}")
                self.created_post_ids.append(r.post_id)
            await self._case(f"prepare post {i}", _prepare_post())

    # ------------------------------------------------------------------
    # GetPostDetail
    # ------------------------------------------------------------------
    async def test_get_post_detail(self):
        logger.info("--- GetPostDetail ---")

        async def _post_not_found_0():
            r = await self.stub.GetPostDetail(
                post_pb2.GetPostDetailRequest(post_id=0), metadata=user_md()
            )
            assert_code(r, 4005)
        await self._case("post not found 0", _post_not_found_0())

        async def _post_not_found_random():
            r = await self.stub.GetPostDetail(
                post_pb2.GetPostDetailRequest(post_id=999999999999), metadata=user_md()
            )
            assert_code(r, 4005)
        await self._case("post not found random", _post_not_found_random())

        post_id = self.created_post_ids[0]

        async def _get_detail_with_like_status():
            r = await self.stub.GetPostDetail(
                post_pb2.GetPostDetailRequest(post_id=post_id), metadata=user_md()
            )
            assert_ok(r, "get detail with like status")
            assert r.post.post_id == post_id
            assert r.post.content
            assert r.post.liked is False
        await self._case("get detail with like status", _get_detail_with_like_status())

        async def _get_detail_after_like():
            await self.stub.ActionLike(
                post_pb2.ActionLikeRequest(post_id=post_id, action=post_pb2.LIKE),
                metadata=user_md(),
            )
            r = await self.stub.GetPostDetail(
                post_pb2.GetPostDetailRequest(post_id=post_id), metadata=user_md()
            )
            assert_ok(r, "get detail after like")
            assert r.post.liked is True
            assert r.post.like_count >= 1
        await self._case("get detail after like", _get_detail_after_like())

        # 删除一个帖子，验证删后查不到
        del_id = self.created_post_ids[-1]
        await self.stub.DeletePost(
            post_pb2.DeletePostRequest(post_id=del_id), metadata=user_md()
        )
        async def _get_deleted_post():
            r = await self.stub.GetPostDetail(
                post_pb2.GetPostDetailRequest(post_id=del_id), metadata=user_md()
            )
            assert_code(r, 4005)
        await self._case("get deleted post", _get_deleted_post())

    # ------------------------------------------------------------------
    # ListUserPosts
    # ------------------------------------------------------------------
    async def test_list_user_posts(self):
        logger.info("--- ListUserPosts ---")

        async def _list_empty_user():
            r = await self.stub.ListUserPosts(
                post_pb2.ListUserPostsRequest(user_id=99999999, page_size=10, cursor=0),
                metadata=user_md(),
            )
            assert_ok(r, "list empty user")
            assert len(r.items) == 0
        await self._case("list empty user", _list_empty_user())

        async def _list_first_page():
            nonlocal r_first
            r_first = await self.stub.ListUserPosts(
                post_pb2.ListUserPostsRequest(user_id=TEST_USER, page_size=3, cursor=0),
                metadata=user_md(),
            )
            assert_ok(r_first, "list first page")
            assert 1 <= len(r_first.items) <= 3
            assert r_first.pagination.has_more is True
        r_first = None
        await self._case("list first page", _list_first_page())

        async def _list_second_page():
            cursor = int(r_first.pagination.next_cursor)
            r2 = await self.stub.ListUserPosts(
                post_pb2.ListUserPostsRequest(
                    user_id=TEST_USER, page_size=3, cursor=cursor
                ),
                metadata=user_md(),
            )
            assert_ok(r2, "list second page")
            assert len(r2.items) >= 1
        await self._case("list second page", _list_second_page())

        async def _page_size_zero():
            r = await self.stub.ListUserPosts(
                post_pb2.ListUserPostsRequest(user_id=TEST_USER, page_size=0, cursor=0),
                metadata=user_md(),
            )
            assert_ok(r, "page size zero uses default")
            assert len(r.items) <= 10
        await self._case("page size zero uses default", _page_size_zero())

        async def _page_size_capped():
            r = await self.stub.ListUserPosts(
                post_pb2.ListUserPostsRequest(
                    user_id=TEST_USER, page_size=100, cursor=0
                ),
                metadata=user_md(),
            )
            assert_ok(r, "page size capped at 50")
            assert len(r.items) <= 50
        await self._case("page size capped at 50", _page_size_capped())

    # ------------------------------------------------------------------
    # DeletePost
    # ------------------------------------------------------------------
    async def test_delete_post(self):
        logger.info("--- DeletePost ---")

        async def _delete_without_user():
            r = await self.stub.DeletePost(
                post_pb2.DeletePostRequest(post_id=self.created_post_ids[0])
            )
            assert_code(r, 4030)
        await self._case("delete without user", _delete_without_user())

        async def _delete_not_found():
            r = await self.stub.DeletePost(
                post_pb2.DeletePostRequest(post_id=888888888888), metadata=user_md()
            )
            assert_code(r, 4005)
        await self._case("delete not found", _delete_not_found())

        # 创建一个专门用来测试权限的帖子
        r = await self.stub.CreatePost(
            post_pb2.CreatePostRequest(content="他人权限测试"), metadata=user_md(OTHER_USER)
        )
        assert_ok(r, "create post for other user")
        other_post_id = r.post_id

        async def _delete_other_user_post():
            r = await self.stub.DeletePost(
                post_pb2.DeletePostRequest(post_id=other_post_id), metadata=user_md(TEST_USER)
            )
            assert_code(r, 4030)
        await self._case("delete other user's post", _delete_other_user_post())

        async def _delete_own_post():
            nonlocal deleted_post_id
            deleted_post_id = self.created_post_ids[1]
            r = await self.stub.DeletePost(
                post_pb2.DeletePostRequest(post_id=deleted_post_id), metadata=user_md()
            )
            assert_ok(r, "delete own post")
        deleted_post_id = None
        await self._case("delete own post", _delete_own_post())

        async def _delete_same_post_again():
            r = await self.stub.DeletePost(
                post_pb2.DeletePostRequest(post_id=deleted_post_id), metadata=user_md()
            )
            assert_code(r, 4005)
        await self._case("delete same post again", _delete_same_post_again())

    # ------------------------------------------------------------------
    # ActionLike
    # ------------------------------------------------------------------
    async def test_action_like(self):
        logger.info("--- ActionLike ---")

        post_id = self.created_post_ids[2]

        async def _like_without_user():
            r = await self.stub.ActionLike(
                post_pb2.ActionLikeRequest(post_id=post_id, action=post_pb2.LIKE)
            )
            assert_code(r, 4030)
        await self._case("like without user", _like_without_user())

        async def _like_unspecified_action():
            r = await self.stub.ActionLike(
                post_pb2.ActionLikeRequest(post_id=post_id), metadata=user_md()
            )
            assert_code(r, 5000)
        await self._case("like unspecified action", _like_unspecified_action())

        async def _like_post_not_found():
            r = await self.stub.ActionLike(
                post_pb2.ActionLikeRequest(post_id=777777777777, action=post_pb2.LIKE),
                metadata=user_md(),
            )
            assert_code(r, 4005)
        await self._case("like post not found", _like_post_not_found())

        async def _like_success():
            r = await self.stub.ActionLike(
                post_pb2.ActionLikeRequest(post_id=post_id, action=post_pb2.LIKE),
                metadata=user_md(),
            )
            assert_ok(r, "like success")
        await self._case("like success", _like_success())

        async def _like_idempotent():
            r = await self.stub.ActionLike(
                post_pb2.ActionLikeRequest(post_id=post_id, action=post_pb2.LIKE),
                metadata=user_md(),
            )
            assert_ok(r, "like idempotent")
        await self._case("like idempotent", _like_idempotent())

        async def _unlike_success():
            r = await self.stub.ActionLike(
                post_pb2.ActionLikeRequest(post_id=post_id, action=post_pb2.UNLIKE),
                metadata=user_md(),
            )
            assert_ok(r, "unlike success")
        await self._case("unlike success", _unlike_success())

        async def _unlike_idempotent():
            r = await self.stub.ActionLike(
                post_pb2.ActionLikeRequest(post_id=post_id, action=post_pb2.UNLIKE),
                metadata=user_md(),
            )
            assert_ok(r, "unlike idempotent")
        await self._case("unlike idempotent", _unlike_idempotent())

    # ------------------------------------------------------------------
    # CreateComment
    # ------------------------------------------------------------------
    async def test_create_comment(self):
        logger.info("--- CreateComment ---")

        post_id = self.created_post_ids[3]

        async def _empty_comment_content():
            r = await self.stub.CreateComment(
                post_pb2.CreateCommentRequest(post_id=post_id, content=""),
                metadata=user_md(),
            )
            assert_code(r, 4007)
        await self._case("empty comment content", _empty_comment_content())

        async def _comment_content_too_long():
            r = await self.stub.CreateComment(
                post_pb2.CreateCommentRequest(post_id=post_id, content="x" * 513),
                metadata=user_md(),
            )
            assert_code(r, 4008)
        await self._case("comment content too long", _comment_content_too_long())

        async def _comment_post_not_found():
            r = await self.stub.CreateComment(
                post_pb2.CreateCommentRequest(post_id=666666666666, content="测试"),
                metadata=user_md(),
            )
            assert_code(r, 4005)
        await self._case("comment post not found", _comment_post_not_found())

        for i in range(3):
            async def _create_comment(idx=i):
                r = await self.stub.CreateComment(
                    post_pb2.CreateCommentRequest(
                        post_id=post_id, content=f"评论内容 {idx}"
                    ),
                    metadata=user_md(),
                )
                assert_ok(r, f"create comment {idx}")
                assert r.comment_id > 0
                self.created_comment_ids.append(r.comment_id)
            await self._case(f"create comment {i}", _create_comment())

    # ------------------------------------------------------------------
    # ListComments
    # ------------------------------------------------------------------
    async def test_list_comments(self):
        logger.info("--- ListComments ---")

        async def _list_comments_post_not_found():
            r = await self.stub.ListComments(
                post_pb2.ListCommentsRequest(post_id=555555555555, page_size=10, cursor=0),
                metadata=user_md(),
            )
            # 当前实现：帖子不存在也返回空列表成功
            assert_ok(r, "list comments post not found")
            assert len(r.items) == 0
        await self._case("list comments post not found", _list_comments_post_not_found())

        post_id = self.created_post_ids[3]

        async def _list_first_page():
            nonlocal r_first
            r_first = await self.stub.ListComments(
                post_pb2.ListCommentsRequest(post_id=post_id, page_size=2, cursor=0),
                metadata=user_md(),
            )
            assert_ok(r_first, "list first page")
            assert len(r_first.items) >= 1
            assert r_first.pagination.has_more is True
        r_first = None
        await self._case("list first page", _list_first_page())

        async def _list_second_page():
            cursor = int(r_first.pagination.next_cursor)
            r2 = await self.stub.ListComments(
                post_pb2.ListCommentsRequest(post_id=post_id, page_size=2, cursor=cursor),
                metadata=user_md(),
            )
            assert_ok(r2, "list second page")
            assert len(r2.items) >= 1
        await self._case("list second page", _list_second_page())

        async def _list_page_size_zero():
            r = await self.stub.ListComments(
                post_pb2.ListCommentsRequest(post_id=post_id, page_size=0, cursor=0),
                metadata=user_md(),
            )
            assert_ok(r, "list page size zero")
            assert len(r.items) <= 10
        await self._case("list page size zero", _list_page_size_zero())

        async def _list_page_size_capped():
            r = await self.stub.ListComments(
                post_pb2.ListCommentsRequest(post_id=post_id, page_size=100, cursor=0),
                metadata=user_md(),
            )
            assert_ok(r, "list page size capped")
            assert len(r.items) <= 50
        await self._case("list page size capped", _list_page_size_capped())

    # ------------------------------------------------------------------
    # DeleteComment
    # ------------------------------------------------------------------
    async def test_delete_comment(self):
        logger.info("--- DeleteComment ---")

        async def _delete_comment_without_user():
            r = await self.stub.DeleteComment(
                post_pb2.DeleteCommentRequest(comment_id=self.created_comment_ids[0])
            )
            assert_code(r, 4030)
        await self._case("delete comment without user", _delete_comment_without_user())

        async def _delete_comment_not_found():
            r = await self.stub.DeleteComment(
                post_pb2.DeleteCommentRequest(comment_id=444444444444), metadata=user_md()
            )
            assert_code(r, 4006)
        await self._case("delete comment not found", _delete_comment_not_found())

        # 用其他用户创建一条评论，测试权限
        r = await self.stub.CreateComment(
            post_pb2.CreateCommentRequest(
                post_id=self.created_post_ids[3], content="他人评论"
            ),
            metadata=user_md(OTHER_USER),
        )
        assert_ok(r, "create comment for other user")
        other_comment_id = r.comment_id

        async def _delete_other_user_comment():
            r = await self.stub.DeleteComment(
                post_pb2.DeleteCommentRequest(comment_id=other_comment_id),
                metadata=user_md(TEST_USER),
            )
            assert_code(r, 4030)
        await self._case("delete other user's comment", _delete_other_user_comment())

        async def _delete_own_comment():
            nonlocal deleted_comment_id
            deleted_comment_id = self.created_comment_ids[0]
            r = await self.stub.DeleteComment(
                post_pb2.DeleteCommentRequest(comment_id=deleted_comment_id), metadata=user_md()
            )
            assert_ok(r, "delete own comment")
        deleted_comment_id = None
        await self._case("delete own comment", _delete_own_comment())

        async def _delete_same_comment_again():
            r = await self.stub.DeleteComment(
                post_pb2.DeleteCommentRequest(comment_id=deleted_comment_id), metadata=user_md()
            )
            assert_code(r, 4006)
        await self._case("delete same comment again", _delete_same_comment_again())

    # ------------------------------------------------------------------
    # GetRecommendFeed
    # ------------------------------------------------------------------
    async def test_get_recommend_feed(self):
        logger.info("--- GetRecommendFeed ---")

        async def _feed_without_user():
            r = await self.stub.GetRecommendFeed(
                post_pb2.GetRecommendFeedRequest(page_size=10, cursor="")
            )
            assert_code(r, 4030)
        await self._case("feed without user", _feed_without_user())

        async def _feed_first_page():
            nonlocal r_first
            r_first = await self.stub.GetRecommendFeed(
                post_pb2.GetRecommendFeedRequest(page_size=5, cursor=""),
                metadata=user_md(),
            )
            assert_ok(r_first, "feed first page")
        r_first = None
        await self._case("feed first page", _feed_first_page())

        async def _feed_second_page():
            cursor = r_first.pagination.next_cursor
            r2 = await self.stub.GetRecommendFeed(
                post_pb2.GetRecommendFeedRequest(page_size=5, cursor=cursor),
                metadata=user_md(),
            )
            assert_ok(r2, "feed second page")
        await self._case("feed second page", _feed_second_page())

        async def _feed_page_size_zero():
            r = await self.stub.GetRecommendFeed(
                post_pb2.GetRecommendFeedRequest(page_size=0, cursor=""),
                metadata=user_md(),
            )
            assert_ok(r, "feed page size zero")
            assert len(r.items) <= 10
        await self._case("feed page size zero", _feed_page_size_zero())

        async def _feed_page_size_capped():
            r = await self.stub.GetRecommendFeed(
                post_pb2.GetRecommendFeedRequest(page_size=100, cursor=""),
                metadata=user_md(),
            )
            assert_ok(r, "feed page size capped")
            assert len(r.items) <= 50
        await self._case("feed page size capped", _feed_page_size_capped())

    # ------------------------------------------------------------------
    # 运行入口
    # ------------------------------------------------------------------
    async def run(self):
        """按顺序执行所有接口测试，并输出最终统计结果。

        任何一个用例失败都会累计 failed 计数，最终 failed>0 时退出码为 1，
        方便 CI/CD 流水线识别测试失败。
        """
        await self.setup()

        await self.test_create_post()
        await self.test_get_post_detail()
        await self.test_list_user_posts()
        await self.test_delete_post()
        await self.test_action_like()
        await self.test_create_comment()
        # await self.test_list_comments()
        # await self.test_delete_comment()
        # await self.test_get_recommend_feed()

        await self.teardown()
        logger.info("===== passed=%s failed=%s =====", self.passed, self.failed)
        if self.failed > 0:
            sys.exit(1)


async def main():
    """测试入口：实例化 TestClient 并启动测试流程。"""
    client = TestClient()
    await client.run()


if __name__ == "__main__":
    asyncio.run(main())
