"""分布式任务锁工具（shedlock 表实现）。

多实例部署时，APScheduler 的 `max_instances=1` 只能保证单进程内不重叠，
跨进程/跨 pod 必须通过 shedlock 表互斥。

用法:
    from jobs.lock_utils import distributed_lock

    class LikeFlushJob:
        @distributed_lock("LikeFlushJob", lock_seconds=120)
        async def run(self) -> None:
            ...
"""
import logging
import socket
from datetime import datetime, timedelta, timezone
from functools import wraps

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from config.database import get_session
from model.shedlock_model import Shedlock

logger = logging.getLogger(__name__)

LOCKED_BY = f"{socket.gethostname()}-{__import__('os').getpid()}"


async def acquire_lock(name: str, lock_seconds: int) -> bool:
    """尝试获取分布式任务锁。

    策略：
    1. 先 INSERT，成功说明锁空闲，直接获得。
    2. INSERT 冲突（ IntegrityError）说明锁记录存在，回滚后尝试 UPDATE
       `lock_until <= now` 的记录，更新成功即抢到锁。
    3. 其他情况返回 False，当前实例本次不执行。

    Args:
        name: 锁名称，通常与 Job 类名一致。
        lock_seconds: 锁持有时间，执行时间不应超过该值。

    Returns:
        True 表示成功获取锁，False 表示锁被其他实例持有或尚未过期。
    """
    now = datetime.now(timezone.utc)
    lock_until = now + timedelta(seconds=lock_seconds)

    async with get_session() as session:
        # 1. 尝试直接插入新锁记录
        try:
            session.add(
                Shedlock(
                    name=name,
                    lock_until=lock_until,
                    locked_at=now,
                    locked_by=LOCKED_BY,
                )
            )
            await session.commit()
            logger.debug("acquired new lock: %s", name)
            return True
        except IntegrityError:
            await session.rollback()

        # 2. 锁已存在，尝试抢占过期锁
        result = await session.execute(
            update(Shedlock)
            .where(Shedlock.name == name, Shedlock.lock_until <= now)
            .values(
                lock_until=lock_until,
                locked_at=now,
                locked_by=LOCKED_BY,
            )
        )
        await session.commit()
        acquired = result.rowcount > 0
        if acquired:
            logger.debug("acquired expired lock: %s", name)
        return acquired


async def release_lock(name: str) -> None:
    """释放自己持有的锁：把 lock_until 设为当前时间，允许其他实例立即抢占。

    注意：只有 locked_by 与当前实例一致时才释放，避免误放其他实例的锁。
    """
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        result = await session.execute(
            select(Shedlock).where(
                Shedlock.name == name,
                Shedlock.locked_by == LOCKED_BY,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return

        row.lock_until = now
        await session.commit()
        logger.debug("released lock: %s", name)


def distributed_lock(name: str, lock_seconds: int = 300):
    """装饰器：为 Job 的 run() 方法加分布式锁。

    Args:
        name: 锁名称，建议用 Job 类名。
        lock_seconds: 锁超时时间，默认 5 分钟。Job 实际执行时间必须小于该值，
                      否则其他实例会在超时后误抢锁。
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            acquired = await acquire_lock(name, lock_seconds)
            if not acquired:
                logger.info("distributed lock not acquired, skip: %s", name)
                return None

            try:
                return await func(*args, **kwargs)
            finally:
                await release_lock(name)

        return wrapper

    return decorator
