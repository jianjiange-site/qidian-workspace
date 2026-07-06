"""FeedService：推荐 Feed 三路混合。

职责范围（来自 post-service-design.md §4 / §8）:
- GetRecommendFeed：从推荐池、冷启动池、好友 timeline 三路取帖，按位置规则混排，并用布隆过滤去重。
- rebuild_recommend_pool：由 FeedScoreJob 调用，按 Hacker News 变体公式重建性别分桶推荐池。
- 用户读到的 Feed 是异性优先：男性用户读 female 池，女性用户读 male 池。
"""
import logging
import math
from datetime import datetime, timedelta, timezone

from clients.user_client import UserClient
from config.database import get_session
from config.redis import cache_key, get_redis
from managers.post_manager import PostManager
from managers.post_stat_manager import PostStatManager
from services.post_read_service import PostReadService

logger = logging.getLogger(__name__)

# Hacker News 变体参数
# score = (W_BASE + ALPHA * likes + BETA * comments) / (hours + 2) ^ GAMMA
_W_BASE = 10.0
_ALPHA = 1.0
_BETA = 3.0
_GAMMA = 1.5


class FeedService:
    """Feed 服务，负责推荐流读取与推荐池重建。"""

    def __init__(self):
        self._redis = get_redis()
        self._user_client = UserClient()
        self._post_read_service = PostReadService()

    async def get_recommend_feed(
        self,
        user_id: int,
        page_size: int,
        cursor: str,
    ) -> tuple[list[dict], str, bool]:
        """获取当前用户的推荐 Feed。

        流程：
        1. 解析游标（recommend_offset:cold_start_offset）。
        2. 根据当前用户性别取「异性」的推荐池与冷启动池。
        3. 从好友 timeline 取最近 7 天的新帖。
        4. 三路混排 + 布隆去重，得到候选 post_id 列表。
        5. 逐个查详情，已读帖子写入布隆过滤器。

        Args:
            user_id: 当前用户 ID。
            page_size: 分页大小，最大限制为 50。
            cursor: 游标字符串，格式 "rec_offset:cs_offset"；首次可传 "0:0" 或空。

        Returns:
            (items, next_cursor, has_more)
        """
        page_size = max(1, min(page_size, 50))
        rec_offset, cs_offset = self._parse_cursor(cursor)

        gender = await self._user_client.is_male(user_id)
        opposite = "female" if gender else "male"

        # 用户读到的是异性发的帖
        recommend_key = cache_key(f"feed:pool:recommend:{opposite}")
        cold_key = cache_key(f"feed:cold_start:pool:{opposite}")
        timeline_key = cache_key(f"user:timeline:{user_id}")
        bloom_key = cache_key(f"user:read:bloom:{user_id}")

        # 推荐池：按综合分排序，多取 3 倍用于去重兜底
        recommend_ids = [
            int(pid)
            for pid in await self._redis.zrevrange(
                recommend_key, rec_offset, rec_offset + page_size * 3 - 1
            )
        ]
        # 冷启动池：按时间排序，取新帖
        cold_ids = [
            int(pid)
            for pid in await self._redis.zrevrange(
                cold_key, cs_offset, cs_offset + page_size - 1
            )
        ]
        # 好友 timeline：最近 7 天，最多 5 条，用于强插
        friend_ids = [
            int(pid)
            for pid in await self._redis.zrevrangebyscore(
                timeline_key,
                int(datetime.utcnow().timestamp()),
                int((datetime.utcnow() - timedelta(days=7)).timestamp()),
                start=0,
                num=5,
            )
        ]

        candidate_ids = await self._merge_three_way(
            recommend_ids, cold_ids, friend_ids, page_size, bloom_key
        )

        # 查详情并标记已读；若帖子已被删除则跳过
        items = []
        for pid in candidate_ids:
            try:
                detail = await self._post_read_service.get_post_detail(pid, user_id)
                items.append(detail)
                await self._mark_read(bloom_key, str(pid))
            except Exception:
                logger.warning("skip deleted post in feed, post_id=%s", pid)

        # 下一页游标：推荐位直接翻 page_size，冷启动位每次 +1
        next_rec_offset = rec_offset + page_size
        next_cs_offset = cs_offset + 1
        next_cursor = f"{next_rec_offset}:{next_cs_offset}"
        has_more = len(items) == page_size

        logger.info(
            "Feed returned: userId=%s size=%s recommend=%s cold=%s friend=%s",
            user_id,
            len(items),
            len(recommend_ids),
            len(cold_ids),
            len(friend_ids),
        )
        return items, next_cursor, has_more

    def _parse_cursor(self, cursor: str) -> tuple[int, int]:
        """解析游标字符串为 (recommend_offset, cold_start_offset)。

        非法或空游标默认返回 (0, 0)。
        """
        if not cursor or cursor == "0:0":
            return 0, 0
        parts = cursor.split(":")
        if len(parts) != 2:
            return 0, 0
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return 0, 0

    async def _merge_three_way(
        self,
        recommend: list[int],
        cold: list[int],
        friend: list[int],
        page_size: int,
        bloom_key: str,
    ) -> list[int]:
        """按位置规则三路混排，并用布隆过滤 + 同页 used 集合去重。

        位置规则（可随产品策略调整）：
        - 第 3 位优先好友帖；没有则取推荐池未读帖。
        - 第 6 位优先冷启动帖；没有则取推荐池未读帖。
        - 其他位置优先推荐池未读帖；推荐池空则补冷启动；再空则补好友。

        去重规则：
        - 每个 post_id 在同一页内只出现一次（used_friend 集合）。
        - 已被用户读过的帖子（布隆过滤器）不会被再次推荐。
        """
        result = []
        used_friend = set()
        rec_idx = cold_idx = friend_idx = 0

        for pos in range(1, page_size + 1):
            chosen = None
            if pos == 3:
                # 第 3 位强插好友帖
                chosen = await self._pick_from(friend, friend_idx, bloom_key, used_friend)
                if chosen:
                    friend_idx += 1
                else:
                    chosen = await self._pick_from(recommend, rec_idx, bloom_key, used_friend)
                    if chosen:
                        rec_idx += 1
            elif pos == 6:
                # 第 6 位强插冷启动帖
                chosen = await self._pick_from(cold, cold_idx, bloom_key, used_friend)
                if chosen:
                    cold_idx += 1
                else:
                    chosen = await self._pick_from(recommend, rec_idx, bloom_key, used_friend)
                    if chosen:
                        rec_idx += 1
            else:
                # 默认优先推荐池
                chosen = await self._pick_from(recommend, rec_idx, bloom_key, used_friend)
                if chosen:
                    rec_idx += 1
                else:
                    chosen = await self._pick_from(cold, cold_idx, bloom_key, used_friend)
                    if chosen:
                        cold_idx += 1
                    else:
                        chosen = await self._pick_from(friend, friend_idx, bloom_key, used_friend)
                        if chosen:
                            friend_idx += 1

            if chosen:
                used_friend.add(chosen)
                result.append(chosen)

            if len(result) >= page_size:
                break

        return result

    async def _is_read(self, bloom_key: str, pid: str) -> bool:
        """判断帖子是否已读。优先 RedisBloom，模块不存在则退化到 Set。"""
        try:
            return await self._redis.bf.exists(bloom_key, pid)
        except Exception:
            return await self._redis.sismember(bloom_key, pid)

    async def _mark_read(self, bloom_key: str, pid: str) -> None:
        """将帖子标记为已读。优先 RedisBloom，模块不存在则退化到 Set。"""
        try:
            await self._redis.bf.add(bloom_key, pid)
        except Exception:
            await self._redis.sadd(bloom_key, pid)
            await self._redis.expire(bloom_key, timedelta(days=7))

    async def _pick_from(
        self,
        source: list[int],
        idx: int,
        bloom_key: str,
        used: set[int] | None = None,
    ) -> int | None:
        """从 source 中跳过已读帖和同页已用帖，返回下一个可用 post_id。"""
        while idx < len(source):
            pid = source[idx]
            if used and pid in used:
                idx += 1
                continue
            if not await self._is_read(bloom_key, str(pid)):
                return pid
            idx += 1
        return None

    async def rebuild_recommend_pool(self) -> None:
        """FeedScoreJob 调用：全量重建推荐池。

        流程：
        1. 取近 3 天未删除帖子。
        2. 批量查 post_stats 底座与 Redis 增量，得到实时计数。
        3. 批量查作者性别，将帖子分到 male/female 两个桶。
        4. 按 Hacker News 变体公式打分，保留前 3000，写入对应性别池。
        """
        since = datetime.now(timezone.utc) - timedelta(days=3)
        async with get_session() as session:
            post_manager = PostManager(session, self._redis)
            stat_manager = PostStatManager(session, self._redis)

            posts = await post_manager._post_repo.list_recent(since)
            post_ids = [p.post_id for p in posts]
            stats = {s.post_id: s for s in await stat_manager._repo.batch_get_by_post_ids(post_ids)}

        distinct_user_ids = list({p.user_id for p in posts})
        gender_map = await self._user_client.get_genders(distinct_user_ids)

        now = datetime.now(timezone.utc)
        male_batch = []
        female_batch = []
        for post in posts:
            stat = stats.get(post.post_id)
            like_count, comment_count = await stat_manager.get_realtime_counts(post.post_id)
            hours_diff = (now - post.created_at).total_seconds() / 3600.0
            score = (_W_BASE + _ALPHA * like_count + _BETA * comment_count) / (
                hours_diff + 2
            ) ** _GAMMA
            is_male = gender_map.get(post.user_id, False)
            if is_male:
                male_batch.append((score, post.post_id))
            else:
                female_batch.append((score, post.post_id))

        await self._write_pool("male", male_batch)
        await self._write_pool("female", female_batch)

        logger.info(
            "Feed pool rebuilt, candidates=%s male=%s female=%s",
            len(posts),
            len(male_batch),
            len(female_batch),
        )

    async def _write_pool(self, gender: str, batch: list[tuple[float, int]]) -> None:
        """将打分结果写入推荐池，使用 tmp key + rename 保证原子性切换。

        Args:
            gender: "male" 或 "female"。
            batch: (score, post_id) 列表。
        """
        tmp_key = cache_key(f"feed:pool:recommend:{gender}:tmp")
        target_key = cache_key(f"feed:pool:recommend:{gender}")

        await self._redis.delete(tmp_key)
        if batch:
            await self._redis.zadd(tmp_key, {str(pid): score for score, pid in batch})

        # 只保留综合分最高的 3000 条
        size = await self._redis.zcard(tmp_key)
        if size > 3000:
            await self._redis.zremrangebyrank(tmp_key, 0, size - 3001)
        await self._redis.expire(tmp_key, timedelta(days=7))

        # 原子性替换旧池
        await self._redis.rename(tmp_key, target_key)
