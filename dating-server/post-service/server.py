"""post-service gRPC 服务端入口。

启动 gRPC server + APScheduler 定时任务。
用法: python server.py
"""
import asyncio
import logging
from concurrent import futures

import grpc
from dating_proto_qidian_post.post_pb2_grpc import add_PostServiceServicer_to_server

from config.database import init_db
from config.logging_config import setup_logging
from config.minio import init_minio
from config.mq import init_mq, shutdown_mq
from config.redis import init_redis
from config import settings
from grpc_server import PostServicer

logger = logging.getLogger(__name__)


def _init_scheduler():
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.warning("APScheduler 未安装，定时任务不启用")
        return None

    from jobs.like_flush_job import LikeFlushJob
    from jobs.comment_flush_job import CommentFlushJob
    from jobs.feed_score_job import FeedScoreJob

    scheduler = AsyncIOScheduler()
    scheduler.add_job(LikeFlushJob().run, "interval", seconds=60, max_instances=1)
    scheduler.add_job(CommentFlushJob().run, "interval", seconds=60, max_instances=1)
    scheduler.add_job(FeedScoreJob().run, "interval", seconds=300, max_instances=1)
    return scheduler


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

    # 6. RocketMQ producer / consumer（失败不阻止 gRPC 启动）
    await init_mq()

    # 7. APScheduler 定时任务
    scheduler = _init_scheduler()
    if scheduler:
        scheduler.start()
        logger.info("APScheduler 定时任务已启动")

    # 7. gRPC Server
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    add_PostServiceServicer_to_server(PostServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    await server.start()

    logger.info("post-service gRPC 服务已启动，监听端口: %s", port)
    logger.info("已注册 RPC: CreatePost, GetPostDetail, ListUserPosts, DeletePost, ActionLike, CreateComment, ListComments, DeleteComment, GetRecommendFeed")

    try:
        await server.wait_for_termination()
    finally:
        shutdown_mq()


if __name__ == "__main__":
    asyncio.run(serve())
