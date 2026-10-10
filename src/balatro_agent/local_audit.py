"""Fixed-path, bounded local-tool records. Never log rejected raw inputs."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import uuid


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def no_links(path: Path) -> None:
    path = path.absolute()
    for component in [*reversed(path.parents), path]:
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('unsafe_path')


def safe_path(root: Path, *parts: str) -> Path:
    root = root.absolute()
    path = root.joinpath(*parts)
    if not path.is_relative_to(root) or '..' in path.relative_to(root).parts:
        raise ValueError('unsafe_path')
    no_links(path)
    return path


def make_dir(path: Path) -> None:
    no_links(path)
    path.mkdir(parents=True, exist_ok=True)
    no_links(path)


class LocalAudit:
    def __init__(self, settings, *, activity=None):
        self.root = settings.log_dir / 'local'
        self.context = settings.client_context
        self.name = 'local-' + uuid.uuid4().hex + '.jsonl'
        self.activity = activity

    def record(self, tool, kind, value):
        make_dir(self.root)
        path = safe_path(self.root, self.name)
        row = {'tool': tool, 'kind': kind, 'client_context': self.context,
               'utc': datetime.now(timezone.utc).isoformat(), 'value': value}
        with path.open('a', encoding='utf-8') as stream:
            stream.write(canonical(row) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        if self.activity is not None and (kind == 'delivered' or kind == 'intent' and tool in ('launch_game', 'close_game')):
            try:
                self.activity.delivered(tool, value)
            except Exception:
                pass

    def deliver(self, tool, result, *, write=False):
        try:
            self.record(tool, 'delivered', result)
        except (OSError, ValueError):
            response = {'status': 'log_unavailable', 'reason': '安全交付记录未能写入。', 'read_only': not write}
            if write:
                response['write_state'] = 'UNKNOWN' if result.get('write_state') == 'COMMITTED' else 'NOT_COMMITTED'
            if self.activity is not None:
                try:
                    self.activity.delivered(tool, response)
                except Exception:
                    pass
            return response
        return result
