"""post-service gRPC 测试客户端。

连接已启动的 server（python server.py 在另一个终端），
测试 CreatePost / DeletePost 全链路。

用法: python test/test_client.py
"""
import asyncio
import grpc
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proto_stubs.post.post_pb2 import CreatePostRequest, DeletePostRequest
from proto_stubs.post.post_pb2_grpc import PostServiceStub
from config.logging_config import setup_logging, set_trace_id

setup_logging()
set_trace_id("test-client-001")
logger = logging.getLogger("test_client")

SERVER = "localhost:50051"


async def main():
    channel = grpc.aio.insecure_channel(SERVER)
    stub = PostServiceStub(channel)
    md = [("x-user-id", "1001")]

    # ---- 1. 参数校验 ----
    r = await stub.CreatePost(CreatePostRequest(content=""), metadata=md)
    logger.info("[PASS] empty content: code=%s msg=%s", r.base.code, r.base.message)
    assert r.base.code == 4001

    r = await stub.CreatePost(CreatePostRequest(content="x" * 2000), metadata=md)
    logger.info("[PASS] too long: code=%s", r.base.code)
    assert r.base.code == 4002

    # ---- 2. 正常发帖 ----
    r = await stub.CreatePost(
        CreatePostRequest(content="测试帖子", image_keys=["k1.jpg", "k2.jpg"]),
        metadata=md,
    )
    logger.info("[PASS] create: code=%s post_id=%s", r.base.code, r.post_id)
    assert r.base.code == 0
    assert r.post_id > 0
    post_id = r.post_id

    # ---- 3. 删帖 ----
    r = await stub.DeletePost(DeletePostRequest(post_id=99999999), metadata=md)
    logger.info("[PASS] delete-not-found: code=%s", r.base.code)
    assert r.base.code == 4005

    r = await stub.DeletePost(DeletePostRequest(post_id=post_id), metadata=md)
    logger.info("[PASS] delete: code=%s", r.base.code)
    assert r.base.code == 0

    r = await stub.DeletePost(DeletePostRequest(post_id=post_id), metadata=md)
    logger.info("[PASS] delete-again: code=%s", r.base.code)
    assert r.base.code == 4005

    await channel.close()
    logger.info("===== 6/6 passed =====")


if __name__ == "__main__":
    asyncio.run(main())