"""Nacos configuration client via HTTP API.

Environment variables:
- NACOS_SERVER_ADDR  (default: 38.76.188.242:8848)
- NACOS_USERNAME     (default: nacos)
- NACOS_PASSWORD     (from env, no default)
- NACOS_NAMESPACE    (default: public)
- NACOS_GROUP        (default: DEFAULT_GROUP)
- NACOS_DATA_ID      (default: post-service-dev.yaml)
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SERVER = "38.76.188.242:8848"
DEFAULT_USERNAME = "nacos"
DEFAULT_GROUP = "DEFAULT_GROUP"
DEFAULT_DATA_ID = "post-service-dev.yaml"


@dataclass
class NacosConfig:
    """Parsed YAML content from Nacos, accessed via dotted keys."""

    _data: dict = field(default_factory=dict)

    def get(self, key: str, default=None):
        """Dotted-path access, e.g.  get("postgres.url")."""
        node = self._data
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def __repr__(self):
        return f"NacosConfig({len(self._data)} keys)"


class NacosClient:
    """Thin async wrapper around Nacos OpenAPI."""

    def __init__(
        self,
        server_addr: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.server_addr = (server_addr or os.getenv(
            "NACOS_SERVER_ADDR", DEFAULT_SERVER
        )).rstrip("/")
        self.username = username or os.getenv("NACOS_USERNAME", DEFAULT_USERNAME)
        self.password = password or os.getenv("NACOS_PASSWORD", "")
        self._token: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def _base_url(self) -> str:
        return f"http://{self.server_addr}/nacos/v1"

    async def __aenter__(self) -> "NacosClient":
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        await self._login()
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _login(self) -> None:
        if not self.password:
            logger.warning("NACOS_PASSWORD not set, Nacos config disabled")
            return
        try:
            resp = await self._client.post(
                f"{self._base_url}/auth/login",
                data={"username": self.username, "password": self.password},
            )
            resp.raise_for_status()
            body = resp.json()
            self._token = body.get("accessToken")
            if self._token:
                logger.info("Nacos login ok, ttl=%s", body.get("tokenTtl"))
            else:
                logger.warning("Nacos login returned no token: %s", body)
        except Exception as exc:
            logger.warning("Nacos login failed: %s", exc)

    async def get_config(
        self,
        data_id: Optional[str] = None,
        group: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> NacosConfig:
        """Fetch and parse a configuration from Nacos."""
        if not self._token:
            return NacosConfig()

        data_id = data_id or os.getenv("NACOS_DATA_ID", DEFAULT_DATA_ID)
        group = group or os.getenv("NACOS_GROUP", DEFAULT_GROUP)
        namespace = namespace or os.getenv("NACOS_NAMESPACE", "")

        params = {
            "dataId": data_id,
            "group": group,
            "tenant": namespace,
            "accessToken": self._token,
        }
        try:
            resp = await self._client.get(
                f"{self._base_url}/cs/configs", params=params
            )
            resp.raise_for_status()
            raw = resp.text.strip()
            if not raw:
                logger.info("Nacos config %s is empty", data_id)
                return NacosConfig()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.info("Nacos config %s not found (404)", data_id)
            else:
                logger.warning("Nacos get_config failed: %s", exc)
            return NacosConfig()
        except Exception as exc:
            logger.warning("Nacos get_config failed: %s", exc)
            return NacosConfig()

        parsed = _parse_yaml(raw)
        logger.info("Nacos config %s loaded, %d top-level keys", data_id, len(parsed))
        return NacosConfig(parsed)


def _parse_yaml(raw: str) -> dict:
    """Minimal YAML parser for flat Nacos configs.

    Uses PyYAML if available, otherwise falls back to manual parsing.
    """
    try:
        import yaml as _yaml
        data = _yaml.safe_load(raw)
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass

    result: dict = {}
    current_section: Optional[str] = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not value and not line.startswith(" "):
                current_section = key
                result[current_section] = {}
            elif current_section:
                result[current_section][key] = value
            else:
                result[key] = value
    return result
