"""MinIO 对象存储异步配置 — post-service 专用。

配置从 settings 读取（Nacos → env → 默认值），敏感凭据不进仓库。
本服务只往 ``post-image/`` 前缀写，不跨前缀读其他服务的数据。

特性：
- init_minio() 返回 bool 表示是否初始化成功，失败不阻断启动
- 统一 key 生成：post-image/{user_id}/{yyyymm}/{uuid}.{ext}
- 服务端不做 URL 拼装，只回 image_key 给调用方
"""
import asyncio
import logging
import uuid
from datetime import datetime
from functools import partial
from typing import Optional

from minio import Minio

from . import settings

logger = logging.getLogger(__name__)

# --------------- connection ---------------

_client: Optional[Minio] = None
_bucket: str = "dating-qidian"
_cdn_base_url: str = "https://minio.jianjiange.site"


async def init_minio() -> bool:
    """初始化 MinIO 客户端。调用时机：``init_config()`` 之后。

    Returns:
        True 表示连接成功，False 表示跳过或失败（服务照常启动）。
    """
    global _client, _bucket, _cdn_base_url

    endpoint = settings.get("minio.endpoint", default="minio-api.jianjiange.site")
    access_key = settings.get("minio.access_key", default="")
    secret_key = settings.get("minio.secret_key", default="")
    secure = settings.get_bool("minio.secure", default=True)
    _bucket = settings.get("minio.bucket_name", default="dating-qidian")
    _cdn_base_url = settings.get("minio.cdn_base_url", default="https://minio.jianjiange.site")

    if not access_key or not secret_key:
        logger.warning("MinIO 未配置 access_key/secret_key，跳过初始化")
        return False

    _client = Minio(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )

    try:
        loop = asyncio.get_running_loop()
        found = await loop.run_in_executor(None, partial(_client.bucket_exists, _bucket))
        if found:
            logger.info("MinIO 连接成功: %s, bucket=%s", endpoint, _bucket)
            return True
        else:
            logger.warning("MinIO bucket %s 不存在，请先在控制台创建", _bucket)
            return False
    except Exception:
        logger.warning("MinIO 连接失败 — 对象存储功能将不可用。", exc_info=True)
        return False


def get_minio() -> Minio:
    """获取 MinIO 客户端实例。未初始化时抛异常。"""
    if _client is None:
        raise RuntimeError("MinIO 未初始化 — 请先调用 init_minio() 并确认返回 True")
    return _client


def get_bucket() -> str:
    """获取当前使用的 bucket 名称。"""
    return _bucket


# --------------- object key 生成 ---------------

def make_object_key(user_id: int, ext: str) -> str:
    """按规范生成帖子图片的 object key。

    格式: post-image/{user_id}/{yyyymm}/{uuid}.{ext}

    例: make_object_key(1001, "jpg") → "post-image/1001/202607/a1b2c3d4.jpg"
    """
    month = datetime.utcnow().strftime("%Y%m")
    uid = uuid.uuid4().hex[:12]
    return f"post-image/{user_id}/{month}/{uid}.{ext}"


def make_tmp_object_key(user_id: int, ext: str) -> str:
    """生成临时上传用的 object key（tmp/ 前缀，24h 自动清理）。

    格式: tmp/post-image/{user_id}/{yyyymm}/{uuid}.{ext}
    """
    month = datetime.utcnow().strftime("%Y%m")
    uid = uuid.uuid4().hex[:12]
    return f"tmp/post-image/{user_id}/{month}/{uid}.{ext}"


# --------------- 公共 URL ---------------

def get_cdn_url(object_key: str) -> str:
    """根据 object key 拼装 CDN 访问 URL。"""
    return f"{_cdn_base_url}/{_bucket}/{object_key}"


# --------------- 异步包装器 ---------------

async def presigned_put_url(object_key: str, expires: int = 3600) -> str:
    """生成 presigned PUT URL，供 App 直传 MinIO。"""
    client = get_minio()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(client.presigned_put_object, _bucket, object_key, expires=expires),
    )


async def presigned_get_url(object_key: str, expires: int = 3600) -> str:
    """生成 presigned GET URL，供 App 下载图片。
    
    仅给无凭据的 App/H5 用，服务端自身不通过此方式读文件。
    """
    client = get_minio()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(client.presigned_get_object, _bucket, object_key, expires=expires),
    )