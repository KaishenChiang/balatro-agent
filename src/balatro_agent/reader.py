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
from .compact import present, VIEWS
from .polling import poll_delay
from .public_changes import PublicChanges, PROTOCOL as CHANGES_PROTOCOL

ERRORS = {
    "disconnected": "The game reader is disconnected.",
    "request_timeout": "The read request timed out; no game action was performed.",
    "invalid_response": "The response does not match the protocol; the raw response was not exported.",
    "adapter_error": "The read-only game adapter reported an error; the raw error was not exported.",
    "version_mismatch": "The reader contract or pinned version does not match.",
    "unknown_profile": "The actual current game profile cannot be confirmed.",
    "unsupported": "The current phase, rules or Mod combination is unsupported.",
    "invalid_timeout": "timeout_s must be a finite number between 0 and 30 seconds.",
    "internal_error": "The read-only service failed internal checks; the raw exception was not exported.",
    "log_unavailable": "The safe delivery record could not be written; this observation was not delivered.",
    "invalid_view": "view must be compact or full; no game read or action was performed.",
}


def error_result(code: str) -> dict:
    if code not in ERRORS:
        code = "internal_error"
    return {"status": code, "reason": ERRORS[code], "read_only": True}


class Reader:
    def __init__(self, settings: Settings | None = None, client: GameClient | None = None):
        self.settings = settings or Settings.runtime()
        from .activity import ActivityJournal
        self.activity = ActivityJournal(self.settings)
        self.public_changes = PublicChanges()
        self.client = client or GameClient(self.settings.url, self.settings.request_timeout_s)
        self._log_file = self.settings.log_dir / ("reader-" + uuid.uuid4().hex + ".jsonl")
        self._tool_lock = asyncio.Lock()
        self._observation_profiles = {}
        self.last_delivered_observation = None
        self.plans = None

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

    def remember_observation(self, observation):
        previous = self.last_delivered_observation
        if previous is not None:
            current_id = observation['observation_id'].split('-')
            previous_id = previous['observation_id'].split('-')
            if current_id[1] == previous_id[1] and int(current_id[2]) < int(previous_id[2]):
                return  # A cached action receipt is history, not a new decision point.
        self.last_delivered_observation = observation

    def _deliver(self, tool: str, result: dict, view='full') -> dict:
        if "observation" in result:
            # Service wall clock is outside the public game state and its ID.
            # It enables per-run reporting without another game data source.
            sampled = datetime.now(timezone.utc)
            result = {**result, "server_time": {"utc": sampled.isoformat(), "unix_s": sampled.timestamp()}}
        observation = result.get('observation')
        prepared = self.public_changes.prepare(result)
        result = prepared.result
        historical = result.get('public_changes', {}).get('reason', '').startswith('historical_')
        if self.plans is not None and not historical:
            result = self.plans.attach(result)
        elif self.plans is not None:
            result = {**result, 'run_plan_status': 'stale_observation'}
        result = present(result, view)
        try:
            self._record_delivered(tool, result)
        except OSError:
            self.public_changes.reset()
            # Filesystem error messages may include arbitrary path contents.
            # Fail closed rather than hand back an unrecorded observation.
            failure = error_result("log_unavailable")
            self.activity.delivered(tool, failure)
            return failure
        self.public_changes.commit(prepared)
        if observation is not None and not historical:
            self.remember_observation(observation)
        self.activity.delivered(tool, result)
        return result

    async def health(self) -> dict:
        async with self._tool_lock:
            try:
                data = await self._envelope("health")
                result = {"status": "ok", "connected": True, "read_only": True,
                          "schema_version": SCHEMA_VERSION, "adapter_version": ADAPTER_VERSION,
                          "public_changes_protocol": CHANGES_PROTOCOL,
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
            result['notes_read_views'] = ['content', 'index', 'full']
            result['observation_views'] = ['compact', 'full']
            result['observation_encoding'] = 'columns-v1'
            return self._deliver("health", result)

    async def observe(self, view='full') -> dict:
        async with self._tool_lock:
            if view not in VIEWS:
                return self._deliver('observe', error_result('invalid_view'))
            try:
                result = await self._observe()
            except ReaderError as exc:
                result = error_result(exc.code)
            except Exception:
                result = error_result("internal_error")
            return self._deliver("observe", result, view)

    async def wait_until_ready(self, timeout_s: float = 10.0, view='full') -> dict:
        async with self._tool_lock:
            if view not in VIEWS:
                return self._deliver('wait_until_ready', error_result('invalid_view'))
            import math
            if isinstance(timeout_s, bool) or not isinstance(timeout_s, (float, int)) or not math.isfinite(timeout_s) or not 0 <= timeout_s <= 30:
                result = error_result("invalid_timeout")
            else:
                deadline = time.monotonic() + timeout_s
                latest = None
                poll_count = 0
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
                        await asyncio.sleep(min(poll_delay(poll_count, self.settings.poll_interval_s), max(0, deadline - time.monotonic())))
                        poll_count += 1
                except ReaderError as exc:
                    result = error_result(exc.code)
                    if latest is not None and latest.get("observation") is not None:
                        result["last_observation"] = latest["observation"]
                except Exception:
                    result = error_result("internal_error")
            return self._deliver("wait_until_ready", result, view)
