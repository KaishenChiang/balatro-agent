from dataclasses import dataclass
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    # No model-facing endpoint, filesystem path or host parameters.
    url: str = "http://127.0.0.1:12346/"
    request_timeout_s: float = 2.0
    poll_interval_s: float = 0.2
    profile_file: Path = ROOT / "config/test-profile.local.json"
    log_dir: Path = ROOT / "runs/live"
    notes_dir: Path = ROOT / "runs/local-experience"
    baseline_notes_dir: Path | None = ROOT / "experience"
    lifecycle_file: Path = ROOT / "config/game-lifecycle.local.json"
    client_context: str = "unspecified"

    @classmethod
    def runtime(cls):
        # This label is bookkeeping, never proof of a Codex tool invocation.
        if os.environ.get("BALATRO_AGENT_CLIENT_CONTEXT") == "development":
            return cls(log_dir=ROOT / "runs/checks/stdio-development", notes_dir=ROOT / "runs/checks/stdio-development/experience", baseline_notes_dir=None, client_context="development")
        return cls(notes_dir=ROOT / "runs/local-experience", baseline_notes_dir=ROOT / "experience",
                   client_context="codex_config" if os.environ.get("BALATRO_AGENT_CLIENT_CONTEXT") == "codex_config" else "unspecified")

    def confirmed_profile(self) -> int | None:
        # Historical profile-2 receipts remain readable for maintenance only.
        # Current-native actions and lifecycle do not use this attestation.
        try:
            value = json.loads(self.profile_file.read_text(encoding="utf-8-sig"))
            profile = value.get("profile")
            if type(profile) is not int or profile not in (1, 2, 3):
                return None
            if value.get("native_ui_verified") is not True:
                return None
            evidence = value.get("evidence")
            if not isinstance(evidence, str) or not evidence.startswith("runs/checks/native-profile-"):
                return None
            path = (ROOT / evidence).resolve()
            if not path.is_relative_to(ROOT / "runs/checks") or not path.is_file():
                return None
            return profile
        except (OSError, ValueError, TypeError):
            return None
