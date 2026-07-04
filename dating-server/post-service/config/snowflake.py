"""简单雪花 ID 生成器 — 单机版，无需 Nacos 注册 worker_id。

格式：42位毫秒时间戳 + 5位 datacenter(0) + 5位 worker(0) + 12位序列号
"""
import threading
import time

# 自定义起始时间 2026-01-01 00:00:00 UTC（毫秒）
_EPOCH_MS = 1767225600000
_WORKER_BITS = 5
_DATACENTER_BITS = 5
_SEQUENCE_BITS = 12
_MAX_SEQUENCE = (1 << _SEQUENCE_BITS) - 1

_lock = threading.Lock()
_last_timestamp_ms = -1
_sequence = 0


def next_id() -> int:
    """生成一个全局唯一的雪花 ID（int64）。"""
    global _last_timestamp_ms, _sequence

    with _lock:
        now_ms = int(time.time() * 1000)
        if now_ms < _last_timestamp_ms:
            # 时钟回拨，等一会儿（简单处理）
            now_ms = _last_timestamp_ms

        if now_ms == _last_timestamp_ms:
            _sequence = (_sequence + 1) & _MAX_SEQUENCE
            if _sequence == 0:
                # 本毫秒序列号用完，等到下一毫秒
                while now_ms <= _last_timestamp_ms:
                    now_ms = int(time.time() * 1000)
        else:
            _sequence = 0

        _last_timestamp_ms = now_ms

    return ((now_ms - _EPOCH_MS) << (_WORKER_BITS + _DATACENTER_BITS + _SEQUENCE_BITS)) | _sequence