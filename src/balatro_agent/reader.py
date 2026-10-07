import asyncio
from datetime import datetime, timezone
import json
import time
import uuid

from pydantic import ValidationError

from .contract import ADAPTER_VERSION, SCHEMA_VERSION, POLICY_VERSION, UPSTREAM_COMMIT, GAME_VERSION, Envelope, Observation
from .policy import canonical, observation_id, project
from .settings import Settings
from .transport import GameClient, ReaderError

ERRORS = {
    "disconnected": "游戏读取接口未连接。",
    "request_timeout": "读取请求超时；没有执行游戏动作。",
    "invalid_response": "接口响应不符合协议；原始响应未导出。",
    "adapter_error": "游戏只读适配器报告错误；原始错误未导出。",
    "version_mismatch": "读取契约或固定版本不匹配。",
    "unknown_profile": "无法确认游戏当前实际档位。",
    "unsupported": "当前阶段、规则或 Mod 组合尚不支持。",
    "invalid_timeout": "timeout_s 必须是 0–30 秒内的有限数值。",
    "internal_error": "只读服务内部检查失败；未导出原始异常。",
    "log_unavailable": "安全读取记录未能写入；本次观察未交付。",
}


def error_result(code: str) -> dict:
    if code not in ERRORS:
        code = "internal_error"
    return {"status": code, "reason": ERRORS[code], "read_only": True}


class Reader:
    def __init__(self, settings: Settings | None = None, client: GameClient | None = None):
        self.settings = settings or Settings.runtime()
        self.client = client or GameClient(self.settings.url, self.settings.request_timeout_s)
        self._log_file = self.settings.log_dir / ("reader-" + uuid.uuid4().hex + ".jsonl")
        self._tool_lock = asyncio.Lock()
        self._observation_profiles = {}

    async def _envelope(self, method: str, timeout_s: float | None = None) -> Envelope:
        raw = await self.client.read(method, timeout_s or self.settings.request_timeout_s)
        try:
            result = Envelope.model_validate(raw)
        except (ValidationError, TypeError):
            raise ReaderError("invalid_response") from None
        if (result.schema_version, result.visibility_policy_version, result.adapter_version, result.upstream_commit, result.upstream_mod_version) != (SCHEMA_VERSION, POLICY_VERSION, ADAPTER_VERSION, UPSTREAM_COMMIT, "1.5.1"):
            raise ReaderError("version_mismatch")
        if result.game_version != GAME_VERSION or result.compatibility != "supported":
            raise ReaderError("unsupported")
        return result

    def _profile_status(self, actual: int | None) -> str:
        # The live native profile is recognized automatically, never selected.
        if actual is None:
            return "unknown_profile"
        return "recognized"

    def observed_profile(self, observation_id):
        return self._observation_profiles.get(observation_id)

    async def _observe(self, timeout_s: float | None = None) -> dict:
        # Every native profile is readable; an unknown profile still cannot
        # produce a snapshot with a guessed or stale profile identifier.
        envelope = await self._envelope("reader_snapshot", timeout_s)
        if envelope.profile is None:
            return error_result("unknown_profile")
        if envelope.public is None:
            return error_result("adapter_error")
        if not envelope.observation_id or not envelope.game_session or not envelope.observation_id.startswith('obs-'+envelope.game_session+'-'):
            return error_result("invalid_response")
        if (envelope.public.phase, envelope.public.ready, envelope.public.ready_reason) != (envelope.phase, envelope.ready, envelope.ready_reason):
            return error_result("invalid_response")
        return self.project_envelope(envelope)

    def project_envelope(self, envelope: Envelope) -> dict:
        public = project(envelope.public)
        public.update(schema_version=SCHEMA_VERSION, visibility_policy_version=POLICY_VERSION, profile=envelope.profile)
        public["observation_id"] = envelope.observation_id
        Observation.model_validate(public)
        self._observation_profiles[envelope.observation_id] = envelope.profile
        if len(self._observation_profiles) > 64:
            del self._observation_profiles[next(iter(self._observation_profiles))]
        return {"status": "unsupported" if public["phase"] == "unsupported" else "ok", "observation": public, "read_only": True}

    def _record_delivered(self, tool: str, result: dict) -> None:
        # Called only for the result handed back to the MCP handler, never for
        # intermediate polling snapshots that the model did not receive.
        self.settings.log_dir.mkdir(parents=True, exist_ok=True)
        row = {"kind": "construction_read", "client_context": self.settings.client_context, "tool": tool, "delivered_utc": datetime.now(timezone.utc).isoformat(), "result": result}
        with self._log_file.open("a", encoding="utf-8") as handle:
            handle.write(canonical(row) + "\n")

    def _deliver(self, tool: str, result: dict) -> dict:
        try:
            self._record_delivered(tool, result)
        except OSError:
            # Filesystem error messages may include arbitrary path contents.
            # Fail closed rather than hand back an unrecorded observation.
            return error_result("log_unavailable")
        return result

    async def health(self) -> dict:
        async with self._tool_lock:
            try:
                data = await self._envelope("health")
                result = {"status": "ok", "connected": True, "read_only": True,
                          "schema_version": SCHEMA_VERSION, "adapter_version": ADAPTER_VERSION,
                          "upstream_commit": UPSTREAM_COMMIT, "upstream_release": "1.5.2",
                          "upstream_mod_version": "1.5.1", "game_version": data.game_version,
                          "actual_profile": data.profile, "profile_policy": "current-native-v1",
                          "profile_status": self._profile_status(data.profile),
                          "phase": data.phase, "ready": data.ready, "ready_reason": data.ready_reason,
                          "tools": getattr(self, "supported_tools", ["health", "observe", "wait_until_ready"]),
                          "game_session": data.game_session}
                for field in ('setup_selection_protocol', 'direct_hand_protocol', 'direct_target_protocol', 'preferences_protocol'):
                    value = getattr(data, field)
                    if value is not None:
                        result[field] = value
            except ReaderError as exc:
                result = error_result(exc.code)
                result["connected"] = exc.code not in ("disconnected", "request_timeout")
            except Exception:
                result = error_result("internal_error")
            result['notes_read_views'] = ['full', 'content']
            return self._deliver("health", result)

    async def observe(self) -> dict:
        async with self._tool_lock:
            try:
                result = await self._observe()
            except ReaderError as exc:
                result = error_result(exc.code)
            except Exception:
                result = error_result("internal_error")
            return self._deliver("observe", result)

    async def wait_until_ready(self, timeout_s: float = 10.0) -> dict:
        async with self._tool_lock:
            import math
            if isinstance(timeout_s, bool) or not isinstance(timeout_s, (float, int)) or not math.isfinite(timeout_s) or not 0 <= timeout_s <= 30:
                result = error_result("invalid_timeout")
            else:
                deadline = time.monotonic() + timeout_s
                latest = None
                try:
                    while True:
                        remaining = deadline - time.monotonic()
                        if latest is not None and remaining <= 0:
                            result = {"status": "timeout", "read_only": True, "observation": latest["observation"]}
                            break
                        latest = await self._observe(min(self.settings.request_timeout_s, max(0.001, remaining)))
                        if latest["status"] != "ok":
                            result = latest
                            break
                        if latest["observation"]["ready"]:
                            result = {**latest, "status": "ready"}
                            break
                        await asyncio.sleep(min(self.settings.poll_interval_s, max(0, deadline - time.monotonic())))
                except ReaderError as exc:
                    result = error_result(exc.code)
                    if latest is not None and latest.get("observation") is not None:
                        result["last_observation"] = latest["observation"]
                except Exception:
                    result = error_result("internal_error")
            return self._deliver("wait_until_ready", result)
