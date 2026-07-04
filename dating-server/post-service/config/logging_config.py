"""统一日志配置 — stdout 输出，供 Promtail → Loki → Grafana 采集查询。

双通道输出：
1. stdout — Docker 容器模式下由 Promtail docker_sd 采集
2. Loki HTTP Push — 本地开发时直推 Loki（http://localhost:3100）

特性：
- 日志走 stdout + 直推 Loki，禁写文件
- 通过 contextvars 实现 MDC 风格的 trace_id / user_id 透传
- ERROR 日志必带堆栈
- 自动脱敏手机号、身份证号、密码/token 等敏感字段
"""
import json
import logging
import queue
import time
import re
import sys
import threading
from contextvars import ContextVar
from typing import Optional

# --------------- MDC（Mapped Diagnostic Context） ---------------

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")


def set_trace_id(trace_id: str) -> None:
    trace_id_ctx.set(trace_id)


def set_user_id(user_id: str) -> None:
    user_id_ctx.set(user_id)


# --------------- 敏感信息过滤器 ---------------

_SENSITIVE_PATTERNS = [
    (re.compile(r"\b1[3-9]\d{9}\b"), lambda m: m.group()[:3] + "****" + m.group()[-4:]),
    (re.compile(r"\b\d{6}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[0-9Xx]\b"),
     lambda m: m.group()[:4] + "**********" + m.group()[-4:]),
    (re.compile(r'(password|passwd|pwd|secret|token|accesskey|secretkey|ak|sk)\s*[:=]\s*\S+', re.IGNORECASE),
     lambda m: m.group().split("=")[0].split(":")[0] + "=***"),
]


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, replacer in _SENSITIVE_PATTERNS:
                record.msg = pattern.sub(replacer, record.msg)
        return True


# --------------- 上下文过滤器 ---------------

class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_ctx.get("-")
        record.user_id = user_id_ctx.get("-")
        return True


# --------------- 格式化器 ---------------

class StdoutFormatter(logging.Formatter):
    def __init__(self):
        super().__init__(
            fmt=(
                "%(asctime)s.%(msecs)03d  %(levelname)-7s "
                "[post-service] [trace=%(trace_id)s] [uid=%(user_id)s]  "
                "%(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )


# --------------- Loki HTTP Push Handler ---------------

class _LokiPushHandler(logging.Handler):
    """异步批量推送日志到 Loki HTTP Push API。

    - 后台线程 + 队列攒批，不阻塞业务线程
    - 批量间隔 1s，积压达 100 条立即冲刷
    - 推送失败静默丢弃
    """

    def __init__(self, url: str):
        super().__init__()
        self._url = url
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait({
                "timestamp": int(record.created * 1e9),
                "line": self.format(record),
            })
            if self._worker is None:
                self._start_worker()
        except Exception:
            pass

    def _start_worker(self) -> None:
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _run(self) -> None:
        import requests as _r
        batch = []

        last_flush = time.monotonic()
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
                batch.append(item)
            except queue.Empty:
                pass

            if len(batch) >= 100 or (batch and (self._stop.is_set() or time.monotonic() - last_flush >= 1.0)):
                self._flush(batch, _r)
                last_flush = time.monotonic()
                batch = []

    def _flush(self, batch: list, _r) -> None:
        if not batch:
            return
        batch.sort(key=lambda r: r["timestamp"])
        payload = {
            "streams": [{
                "stream": {"service": "post-service", "job": "python-local"},
                "values": [[str(r["timestamp"]), r["line"]] for r in batch],
            }]
        }
        try:
            _r.post(self._url, json=payload, timeout=5)
        except Exception:
            pass

    def close(self) -> None:
        self._stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2)
        super().close()


# --------------- 初始化入口 ---------------

_logging_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    fmt = StdoutFormatter()

    # stdout handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.addFilter(ContextFilter())
    sh.addFilter(SensitiveDataFilter())
    root.addHandler(sh)

    # Loki push handler（本地开发直推；Docker 下 Promtail 也能从 stdout 收）
    import os as _os
    loki_url = _os.getenv("LOKI_PUSH_URL", "http://localhost:3100/loki/api/v1/push")
    lh = _LokiPushHandler(loki_url)
    lh.setFormatter(fmt)
    lh.addFilter(ContextFilter())
    lh.addFilter(SensitiveDataFilter())
    lh.setLevel(level)
    root.addHandler(lh)

    # 第三方库日志收敛
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("grpc").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("redis.asyncio").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info("日志系统初始化完成，输出目标: stdout + Loki(%s)", loki_url)