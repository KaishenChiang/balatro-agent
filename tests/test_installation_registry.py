"""Cross-checkout intents, ownership and interrupted persistence boundaries."""
from dataclasses import replace
from pathlib import Path

import pytest

from balatro_agent.installation_registry import (
    InstallationRegistry, RegistrationGuard, SCHEMA, TRACKING, atomic_json)
from balatro_agent.settings import Settings


@pytest.fixture
def registered(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    store = InstallationRegistry(tmp_path / 'client/balatro-agent/installation.local.json')
    settings = Settings(lifecycle_file=root / 'config/game-lifecycle.local.json',
        log_dir=root / 'runs/live', registration_file=store.path)
    value = {'schema': SCHEMA, 'checkpoint_tracking': TRACKING, 'root': str(root),
        'installed_files': []}
    with store.lock():
        store.publish(value)
    return root, store, settings, value


def test_intent_survives_source_directory_becoming_unavailable(registered):
    root, store, settings, _ = registered
    guard = RegistrationGuard(settings)
    checkpoint = {'pending': {'action_id': 'original-uncertain'}, 'input_pending': None}
    local = settings.log_dir / 'executor/checkpoint.json'
    guard.persist('executor', checkpoint, lambda: atomic_json(local, checkpoint))
    retained = root.parent / 'retained-source'
    assert root.resolve().is_relative_to(root.parent.resolve())
    assert retained.resolve().is_relative_to(root.parent.resolve())
    root.rename(retained)
    with pytest.raises(ValueError, match='Unresolved'):
        store.ensure_idle(root)
    with pytest.raises(OSError, match='registration_unavailable'):
        guard.check()
    assert store.checkpoint('executor', root) == checkpoint


def test_failed_local_intent_cannot_be_replaced_by_a_new_request(registered):
    root, store, settings, _ = registered
    guard = RegistrationGuard(settings)
    checkpoint = {'pending': {'action_id': 'original-before-dispatch'}, 'input_pending': None}
    def broken_local():
        raise OSError('local disk unavailable')
    with pytest.raises(OSError):
        guard.persist('executor', checkpoint, broken_local)
    called = []
    with pytest.raises(OSError):
        guard.persist('executor', {'pending': {'action_id': 'different'}, 'input_pending': None}, lambda: called.append(True))
    assert called == []
    assert store.checkpoint('executor', root) == checkpoint


def test_clearing_pending_requires_successful_local_persistence(registered):
    root, store, settings, _ = registered
    guard = RegistrationGuard(settings)
    checkpoint = {'pending': 'original-operation'}
    local = settings.log_dir / 'lifecycle/checkpoint.json'
    guard.persist('lifecycle', checkpoint, lambda: atomic_json(local, checkpoint))
    def broken_local():
        raise OSError('local disk unavailable')
    with pytest.raises(OSError):
        guard.persist('lifecycle', {'pending': None}, broken_local)
    assert store.checkpoint('lifecycle', root) == checkpoint
    assert store.read_json(local) == checkpoint


def test_migration_prevents_old_service_from_submitting_a_new_intent(registered):
    root, store, settings, value = registered
    fresh = root.parent / 'fresh-source'
    fresh.mkdir()
    with store.lock():
        store.publish({**value, 'root': str(fresh)})
    called = []
    with pytest.raises(OSError):
        RegistrationGuard(settings).persist('executor', {'pending': {'action_id': 'old-service'}, 'input_pending': None}, lambda: called.append(True))
    assert called == []
    newer = replace(settings, lifecycle_file=fresh / 'config/game-lifecycle.local.json', log_dir=fresh / 'runs/live')
    RegistrationGuard(newer).check()
    assert list((store.path.parent / 'history').glob('*.json'))


def test_preparation_lock_blocks_new_game_intents(registered):
    root, store, settings, _ = registered
    called = []
    with store.lock():
        with pytest.raises(OSError):
            RegistrationGuard(settings).persist('executor', {'pending': {'action_id': 'while-moving'}, 'input_pending': None}, lambda: called.append(True))
    assert called == []
    store.ensure_idle(root)


def test_stale_connection_cannot_replace_another_connections_intent(registered):
    root, store, settings, _ = registered
    idle = {'pending': None, 'input_pending': None}
    original = {'pending': {'action_id': 'first-connection'}, 'input_pending': None}
    local = settings.log_dir / 'executor/checkpoint.json'
    RegistrationGuard(settings).persist('executor', original, lambda: atomic_json(local, original), expected=idle)
    called = []
    with pytest.raises(OSError):
        RegistrationGuard(settings).persist('executor', {'pending': {'action_id': 'stale-connection'}, 'input_pending': None},
            lambda: called.append(True), expected=idle)
    assert called == []
    assert store.checkpoint('executor', root) == original
    assert store.read_json(local) == original


def test_lifecycle_cannot_dispatch_while_a_game_action_is_unresolved(registered):
    root, store, settings, _ = registered
    original = {'pending': {'action_id': 'unresolved-game-action'}, 'input_pending': None}
    local = settings.log_dir / 'executor/checkpoint.json'
    RegistrationGuard(settings).persist('executor', original, lambda: atomic_json(local, original))
    called = []
    with pytest.raises(OSError):
        RegistrationGuard(settings).persist('lifecycle', {'pending': 'new-launch'}, lambda: called.append(True),
            expected={'pending': None})
    assert called == []
    assert store.checkpoint('executor', root) == original
    assert store.checkpoint('lifecycle', root) == {'pending': None}
