"""user-service gRPC 桩 — 待 user-service 实现后替换。

当前返回 mock 数据，不影响 post-service 主流程开发。
"""
import logging

logger = logging.getLogger(__name__)


class UserClient:
    """调用 user-service gRPC 的客户端桩。

    TODO: user-service 实现后，替换为 gRPC stub 调用。
    """

    async def get_gender(self, user_id: int) -> bool:
        """获取用户性别。Returns: True=男, False=女"""
        gender = user_id % 2 == 0
        logger.info("[UserClient 桩] get_gender(user_id=%s) → %s", user_id, "男" if gender else "女")
        return gender

    async def get_friend_user_ids(self, user_id: int) -> list[int]:
        """获取好友 user_id 列表。"""
        logger.info("[UserClient 桩] get_friend_user_ids(user_id=%s) → []", user_id)
        return []

    async def is_male(self, user_id: int) -> bool:
        """判断用户是否为男性。"""
        return await self.get_gender(user_id)