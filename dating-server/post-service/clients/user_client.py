"""user-service gRPC 桩 — 待 user-service 实现后替换。

当前返回 mock 数据，不影响 post-service 主流程开发。
"""
import logging

from cachetools import TTLCache

logger = logging.getLogger(__name__)


class UserClient:
    """调用 user-service gRPC 的客户端桩。

    性别查询带 30s 本地 TTL 缓存，避免高频调用压垮 user-service，
    与技术文档 §5.1 / §10.2 中「cachetools 30s 性别缓存」对齐。

    TODO: user-service 实现后，替换为 gRPC stub 调用，缓存层保留。
    """

    def __init__(self):
        # 本地 TTL 缓存：最多 1024 个用户，30 秒过期
        self._gender_cache: TTLCache[int, bool] = TTLCache(maxsize=1024, ttl=30)

    async def get_gender(self, user_id: int) -> bool:
        """获取用户性别。Returns: True=男, False=女。命中缓存则直接返回。"""
        cached = self._gender_cache.get(user_id)
        if cached is not None:
            return cached

        # mock：偶数 user_id 为男，奇数为女
        gender = user_id % 2 == 0
        self._gender_cache[user_id] = gender
        logger.info("[UserClient 桩] get_gender(user_id=%s) → %s", user_id, "男" if gender else "女")
        return gender

    async def get_friend_user_ids(self, user_id: int) -> list[int]:
        """获取好友 user_id 列表。"""
        logger.info("[UserClient 桩] get_friend_user_ids(user_id=%s) → []", user_id)
        return []

    async def is_male(self, user_id: int) -> bool:
        """判断用户是否为男性。复用 get_gender 的 30s 缓存。"""
        return await self.get_gender(user_id)

    async def get_genders(self, user_ids: list[int]) -> dict[int, bool]:
        """批量取性别，用于 FeedScoreJob 重建池；优先读缓存，未命中再批量 mock。"""
        result: dict[int, bool] = {}
        missing: list[int] = []

        for uid in user_ids:
            cached = self._gender_cache.get(uid)
            if cached is not None:
                result[uid] = cached
            else:
                missing.append(uid)

        if missing:
            genders = {uid: uid % 2 == 0 for uid in missing}
            self._gender_cache.update(genders)
            result.update(genders)

        return result
