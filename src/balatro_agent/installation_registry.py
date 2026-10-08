"""Independent installation ownership and pending-action mirrors.

The registry survives replacing a source checkout. Its lock serializes
preparation with durable intents; it never reads game state or selects actions.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import uuid

from .local_audit import canonical, make_dir, no_links

SCHEMA = 'balatro-installation-registry-1'
TRACKING = 'checkpoint-mirror-v1'
CHECKPOINT_KEYS = {'executor': {'pending', 'input_pending'}, 'lifecycle': {'pending'}}
ENVIRONMENT_KEY = 'BALATRO_AGENT_REGISTRATION_FILE'


def registry_path(config):
    return config.absolute().parent / 'balatro-agent/installation.local.json'


def atomic_json(path, value):
    no_links(path)
    make_dir(path.parent)
    temporary = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
        no_links(path)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class InstallationRegistry:
    def __init__(self, path):
        self.path = Path(path).absolute()

    @contextmanager
    def lock(self):
        """Nonblocking OS lock shared by preparation and intent persistence."""
        make_dir(self.path.parent)
        lock_path = self.path.with_name('installation.lock')
        no_links(lock_path)
        stream = lock_path.open('a+b')
        locked = False
        try:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'\0'); stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
            yield self
        finally:
            if locked:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)
            stream.close()

    def read_json(self, path, limit=1024 * 1024):
        no_links(path)
        if path.stat().st_size > limit:
            raise ValueError('Installation registry exceeds its size limit')
        return json.loads(path.read_text(encoding='utf-8'))

    def read(self):
        if not self.path.exists():
            return None
        value = self.read_json(self.path)
        if (not isinstance(value, dict) or value.get('schema') != SCHEMA
                or value.get('checkpoint_tracking') != TRACKING
                or not isinstance(value.get('root'), str) or not Path(value['root']).is_absolute()
                or not isinstance(value.get('installed_files'), list)):
            raise ValueError('Independent installation receipt is invalid; preserve it')
        return value

    def checkpoint_path(self, area):
        if area not in CHECKPOINT_KEYS:
            raise ValueError('Invalid checkpoint area')
        return self.path.with_name('checkpoint-' + area + '.local.json')

    def checkpoint(self, area, root):
        value = self.read_json(self.checkpoint_path(area), 65536)
        checkpoint = value.get('checkpoint') if isinstance(value, dict) else None
        if (not isinstance(value, dict) or value.get('schema') != TRACKING
                or not isinstance(value.get('root'), str) or Path(value['root']) != root
                or not isinstance(checkpoint, dict) or set(checkpoint) != CHECKPOINT_KEYS[area]):
            raise ValueError('Independent checkpoint is invalid; preserve it')
        return checkpoint

    def ensure_idle(self, root):
        for area in CHECKPOINT_KEYS:
            if any(value is not None for value in self.checkpoint(area, root).values()):
                raise ValueError('Unresolved independent checkpoint; query the original action first')

    def write_checkpoint(self, area, root, checkpoint):
        if not isinstance(checkpoint, dict) or set(checkpoint) != CHECKPOINT_KEYS[area]:
            raise ValueError('Invalid checkpoint')
        atomic_json(self.checkpoint_path(area), {'schema': TRACKING, 'root': str(root), 'checkpoint': checkpoint})

    def publish(self, value):
        if self.path.exists():
            previous = self.read()
            self.ensure_idle(Path(previous['root']))
            import hashlib
            history = self.path.parent / 'history' / (hashlib.sha256(canonical(previous).encode()).hexdigest() + '.json')
            if history.exists():
                if self.read_json(history) != previous:
                    raise ValueError('Independent installation history changed')
            else:
                atomic_json(history, previous)
        root = Path(value['root'])
        if not self.path.exists():
            for area in CHECKPOINT_KEYS:
                if self.checkpoint_path(area).exists() and any(
                        v is not None for v in self.checkpoint(area, root).values()):
                    raise ValueError('Unresolved independent checkpoint; preserve it')
        for area, keys in CHECKPOINT_KEYS.items():
            self.write_checkpoint(area, root, {key: None for key in keys})
        atomic_json(self.path, value)


class RegistrationGuard:
    def __init__(self, settings):
        self.log_dir = settings.log_dir
        registration = getattr(settings, 'registration_file', None)
        self.store = InstallationRegistry(registration) if registration else None
        self.root = settings.lifecycle_file.absolute().parent.parent if self.store else None

    def _check(self):
        value = self.store.read()
        if value is None or Path(value['root']) != self.root:
            raise ValueError('registration_owner_changed')
        for area in CHECKPOINT_KEYS:
            mirrored = self.store.checkpoint(area, self.root)
            local_path = self.log_dir / area / 'checkpoint.json'
            local = self.store.read_json(local_path, 65536) if local_path.exists() else {key: None for key in CHECKPOINT_KEYS[area]}
            if mirrored != local:
                raise ValueError('independent_checkpoint_differs')

    def check(self):
        if self.store is None:
            return
        try:
            self._check()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise OSError('registration_unavailable') from exc

    def persist(self, area, checkpoint, write_local, *, expected=None):
        if self.store is None:
            return write_local()
        try:
            with self.store.lock():
                self._check()
                if expected is not None and self.store.checkpoint(area, self.root) != expected:
                    raise ValueError('checkpoint_changed_since_read')
                if any(value is not None for value in checkpoint.values()):
                    for other in CHECKPOINT_KEYS:
                        if other != area and any(value is not None for value in self.store.checkpoint(other, self.root).values()):
                            raise ValueError('another_operation_is_pending')
                # Persist an unresolved intent independently before local
                # persistence and dispatch. Clear it only after local success.
                if any(value is not None for value in checkpoint.values()):
                    self.store.write_checkpoint(area, self.root, checkpoint)
                write_local()
                self.store.write_checkpoint(area, self.root, checkpoint)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise OSError('registration_unavailable') from exc
