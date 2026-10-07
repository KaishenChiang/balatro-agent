import asyncio
import ipaddress
from urllib.parse import urlsplit

import httpx


class ReaderError(Exception):
    """Only a fixed code may escape the trust boundary."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class GameClient:
    def __init__(self, url: str, timeout_s: float, transport: httpx.AsyncBaseTransport | None = None):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("invalid_loopback_endpoint")
        if not ipaddress.ip_address(parsed.hostname or "").is_loopback:
            raise ValueError("non_loopback_endpoint")
        self._client = httpx.AsyncClient(base_url=url, timeout=timeout_s, trust_env=False, follow_redirects=False, transport=transport)
        self._lock = asyncio.Lock()
        self._counter = 0

    async def read(self, method: str, timeout_s: float | None = None) -> dict:
        if method not in ("health", "reader_snapshot"):
            raise ReaderError("method_not_allowed")
        return await self._request(method, {}, timeout_s)

    async def action(self, method: str, params: dict, timeout_s: float | None = None) -> dict:
        if method not in ("act_submit", "action_status"):
            raise ReaderError("method_not_allowed")
        return await self._request(method, params, timeout_s)

    async def _request(self, method: str, params: dict, timeout_s: float | None = None) -> dict:
        async with self._lock:
            self._counter += 1
            identifier = self._counter
            try:
                async with self._client.stream("POST", "/", json={"jsonrpc": "2.0", "method": method, "params": params, "id": identifier}, timeout=timeout_s) as response:
                    if response.status_code != 200:
                        raise ReaderError("invalid_response")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2_000_000:
                            raise ReaderError("invalid_response")
                import json
                envelope = json.loads(body)
                if not isinstance(envelope, dict) or envelope.get("jsonrpc") != "2.0" or envelope.get("id") != identifier:
                    raise ReaderError("invalid_response")
                if "error" in envelope or not isinstance(envelope.get("result"), dict):
                    raise ReaderError("adapter_error")
                return envelope["result"]
            except ReaderError:
                raise
            except httpx.TimeoutException:
                raise ReaderError("request_timeout") from None
            except httpx.RequestError:
                raise ReaderError("disconnected") from None
            except (ValueError, UnicodeError):
                raise ReaderError("invalid_response") from None

    async def close(self) -> None:
        await self._client.aclose()
