"""post-service gRPC 服务端入口。

启动 gRPC server，注册 PostWriteService（含 CreatePost / DeletePost）。
其余 RPC 未实现，调用方会收到 UNIMPLEMENTED。

用法: python server.py
"""
import asyncio
import logging

import grpc
from concurrent import futures

from proto_stubs.post.post_pb2_grpc import add_PostServiceServicer_to_server
from service.PostWriteService import PostWriteService

from config.logging_config import setup_logging
from config import settings
from config.database import init_db
from config.redis import init_redis
from config.minio import init_minio

logger = logging.getLogger(__name__)


async def serve(port: int = 50051) -> None:
    """启动 post-service gRPC 服务器。"""

    # 1. 配置中心（Nacos）
    await settings.init_config()

    # 2. 日志
    setup_logging()

    # 3. 数据库（含自动建表）
    await init_db()

    # 4. Redis
    await init_redis()

    # 5. MinIO（非强依赖，失败不阻止启动）
    await init_minio()

    # 6. gRPC Server
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    add_PostServiceServicer_to_server(PostWriteService(), server)
    server.add_insecure_port(f"[::]:{port}")
    await server.start()

    logger.info("post-service gRPC 服务已启动，监听端口: %s", port)
    logger.info("已注册 RPC: CreatePost, DeletePost")

    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())