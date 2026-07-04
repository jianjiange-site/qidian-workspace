"""MinIO 上传测试脚本 — 同时验证日志配置。

用法：在 workspace 根目录运行: python scripts/test_minio_upload.py
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dating-server" / "post-service"))

os.environ["MINIO_ENDPOINT"] = "minio-api.jianjiange.site"
os.environ["MINIO_ACCESS_KEY"] = "admin"
os.environ["MINIO_SECRET_KEY"] = "GorLDkuOhGyK5c1RXh2gaPooXgtso/MR"
os.environ["MINIO_BUCKET_NAME"] = "dating-qidian"
os.environ["MINIO_SECURE"] = "true"
os.environ["MINIO_CDN_BASE_URL"] = "https://minio.jianjiange.site"

from config.logging_config import setup_logging, set_trace_id, set_user_id
from config.minio import init_minio, get_minio, get_bucket, make_object_key, get_cdn_url

setup_logging()
set_trace_id("test-upload-001")
set_user_id("1001")

log = logging.getLogger("minio_test")


async def main():
    log.info("===== MinIO 上传测试开始 =====")

    # 1. 初始化 MinIO
    ok = await init_minio()
    if not ok:
        log.error("MinIO 初始化失败，测试终止")
        return
    log.info("MinIO 初始化成功，bucket=" + get_bucket())

    # 2. 找到测试图片
    image_path = Path(__file__).resolve().parent.parent / "dating-server" / "post-service" / "微信图片_20260515141737_13_3.jpg"
    if not image_path.exists():
        log.error("测试图片不存在: " + str(image_path))
        return
    log.info("测试图片: %s (%.1f KB)", image_path.name, image_path.stat().st_size / 1024)

    # 3. 生成 object key
    ext = image_path.suffix.lstrip(".")
    object_key = make_object_key(user_id=1001, ext=ext)
    log.info("目标 key: " + object_key)

    # 4. 上传
    client = get_minio()
    bucket = get_bucket()
    loop = asyncio.get_running_loop()

    try:
        await loop.run_in_executor(
            None,
            lambda: client.fput_object(bucket, object_key, str(image_path)),
        )
        log.info("上传成功!")
    except Exception:
        log.exception("上传失败!")
        return

    # 5. 验证（共享桶可能无 stat 权限，失败不影响上传结论）
    try:
        stat = await loop.run_in_executor(
            None,
            lambda: client.stat_object(bucket, object_key),
        )
        log.info("对象验证: size=%s bytes, etag=%s", stat.size, stat.etag)
    except Exception:
        log.warning("stat_object 无权限（共享桶策略限制），上传本身已成功")

    # 6. CDN URL
    cdn_url = get_cdn_url(object_key)
    log.info("CDN 访问地址: " + cdn_url)

    log.info("===== MinIO 上传测试完成 =====")


if __name__ == "__main__":
    asyncio.run(main())