"""Small factual hints between successfully delivered public observations.

No game, disk, model or strategy access. Prepare before delivery logging and
commit only after that log succeeds. The full observation remains authoritative.
"""
from dataclasses import dataclass

from .contract import Observation
from .policy import canonical, project


PROTOCOL = 'public-changes-v1'
_RUN_PHASES = frozenset(('hand', 'shop', 'pack', 'blind_select', 'round_eval', 'terminal'))
_RESOURCE_FIELDS = ('dollars', 'chips', 'hands_left', 'discards_left', 'ante', 'round',
                    'reroll_cost', 'pack_choices')
_REGIONS = {'hand': ('hand',), 'jokers': ('jokers',), 'consumables': ('consumables',),
            'shop': ('shop_jokers', 'shop_vouchers', 'shop_boosters'), 'pack': ('pack',)}
_UNCERTAIN_TEXT = frozenset(('tooltip_unavailable', 'dynamic_tooltip_omitted',
                            'unconfirmed_field', 'unsupported_rule'))


@dataclass(frozen=True)
class PreparedChanges:
    """Only result is public; the other fields are an in-process delivery token."""
    result: dict
    _owner: object
    _generation: int
    _next: dict | None
    _advance: bool = True


def _identity(observation):
    _, session, epoch = observation['observation_id'].split('-')
    return session, int(epoch)


def _safe_observation(value):
    # Reuse the sole whitelist and hidden-card masks, including error paths.
    public = project(Observation.model_validate(value))
    canonical(public)  # Nonfinite numbers cannot become comparison evidence.
    return public


def _unavailable(reason, observation=None):
    hint = {'protocol': PROTOCOL, 'status': 'unavailable', 'reason': reason}
    if observation is not None:
        hint['to_observation_id'] = observation['observation_id']
    return hint


def _region(observation, names):
    found = [r for r in observation['regions'] if r['name'] in names]
    if not found:
        return None, True
    uncertain = bool(_UNCERTAIN_TEXT.intersection(observation['unknowns']))
    for region in found:
        uncertain |= region['capacity'] is None or region['selection_limit'] is None
        for card in region['cards']:
            uncertain |= (card['visibility'] != 'face_up' or card.get('name') is None
                          or not card.get('description') or card.get('debuffed') is None
                          or card.get('forced_selection') is None)
            if region['name'] == 'hand' and card['visibility'] == 'face_up':
                uncertain |= card['rank'] is None or card['suit'] is None
            if region['name'] in ('shop_jokers', 'shop_vouchers', 'shop_boosters'):
                uncertain |= card.get('price') is None
            if region['name'] in ('jokers', 'consumables'):
                uncertain |= card.get('sell_price') is None
    return found, uncertain


def _section(hint, name, before, after, uncertain=False):
    if before is None and after is None:
        if uncertain:
            hint['unknown'].append(name)
        return
    if before != after:
        hint['changed'].append(name)
    elif not uncertain:
        hint['unchanged'].append(name)
    if uncertain:
        hint['unknown'].append(name)


def _compare(before, after):
    hint = {'protocol': PROTOCOL, 'status': 'compared',
            'from_observation_id': before['observation_id'],
            'to_observation_id': after['observation_id'],
            'changed': [], 'unchanged': [], 'unknown': []}
    _section(hint, 'phase', before['phase'], after['phase'])
    for name, regions in _REGIONS.items():
        old, old_unknown = _region(before, regions)
        new, new_unknown = _region(after, regions)
        if old is None and new is None:
            phases = {before['phase'], after['phase']}
            if (name == 'hand' and not phases.intersection(('hand', 'pack'))
                    or name in ('shop', 'pack') and name not in phases):
                continue
        _section(hint, name, old, new, old_unknown or new_unknown)

    old_resources, new_resources = before['resources'], after['resources']
    resource_changes, uncertain_resources = {}, []
    resources_observed = (old_resources['availability'] == 'observed'
                          and new_resources['availability'] == 'observed')
    for name in _RESOURCE_FIELDS:
        old, new = old_resources[name], new_resources[name]
        # These two values only apply in their respective visible phases.
        if name in ('reroll_cost', 'pack_choices') and old is None and new is None:
            continue
        if not resources_observed or old is None or new is None:
            uncertain_resources.append(name)
        elif old != new:
            resource_changes[name] = {'before': old, 'after': new}
    uncertain = (old_resources['availability'] != 'observed'
                 or new_resources['availability'] != 'observed' or bool(uncertain_resources))
    _section(hint, 'resources', old_resources, new_resources, uncertain)
    if resource_changes:
        hint['resource_changes'] = resource_changes
    if uncertain_resources:
        hint['unknown_resources'] = uncertain_resources

    old_blinds, new_blinds = before['blinds'], after['blinds']
    if old_blinds or new_blinds:
        # Compare displayed constraints, not native blind identifiers or effects.
        fields = ('slot', 'name', 'description', 'required_chips')
        old = [{k: blind[k] for k in fields} for blind in old_blinds]
        new = [{k: blind[k] for k in fields} for blind in new_blinds]
        uncertain = (not old or not new or bool(_UNCERTAIN_TEXT.intersection(
            before['unknowns'] + after['unknowns']))
            or any(b['name'] is None or b['required_chips'] is None for b in old + new))
        _section(hint, 'blinds', old, new, uncertain)
    else:
        hint['unknown'].append('blinds')

    for name in ('poker_hands', 'deck_composition'):
        old, new = before['menus'][name], after['menus'][name]
        if old or new:
            uncertain = not old or not new
            if name == 'poker_hands':
                uncertain |= any(hand[k] is None for hand in old + new
                                 for k in ('level', 'chips', 'mult', 'played'))
            else:
                uncertain |= any(entry['card']['visibility'] != 'face_up'
                                 for entry in old + new)
            _section(hint, name, old, new, uncertain)
    return hint


class PublicChanges:
    """One ephemeral baseline shared by Reader and Executor delivery paths."""
    def __init__(self):
        self._baseline = None
        self._generation = 0

    def reset(self):
        self._baseline = None
        self._generation += 1

    def prepare(self, result, request=None, *, historical=False):
        """Decorate a copy without consuming an undelivered observation."""
        before = self._baseline
        value = result.get('observation')
        if value is None:
            # A healthy metadata-only response is not an observation or a gap.
            healthy = result.get('status') == 'ok'
            if healthy and before is not None:
                session, _ = _identity(before)
                healthy = (result.get('connected') is not False
                           and result.get('actual_profile', before['profile']) == before['profile']
                           and result.get('game_session', session) == session)
            rejected = result.get('state') == 'REJECTED' and result.get('submitted') is False
            keep = healthy or rejected
            hint = None if keep else _unavailable('delivery_gap')
            return PreparedChanges(dict(result) if hint is None else {**result, 'public_changes': hint},
                                   self, self._generation, before if keep else None)

        try:
            after = _safe_observation(value)
        except (ValueError, TypeError, KeyError):
            return PreparedChanges({**result, 'public_changes': _unavailable('invalid_observation')},
                                   self, self._generation, None)

        reason, advance = ('historical_receipt', False) if historical else (None, True)
        if before is not None and reason is None:
            previous_session, previous_epoch = _identity(before)
            session, epoch = _identity(after)
            # Read-only historical receipts must neither rewind nor clear a
            # newer baseline, even if the receipt is from an old run boundary.
            if session == previous_session and epoch < previous_epoch:
                reason, advance = 'historical_observation', False
            elif after['observation_id'] == before['observation_id'] and before != after:
                reason = 'observation_conflict'

        if reason is None:
            if result.get('state') == 'UNKNOWN':
                reason = 'action_uncertain'
            elif result.get('state') in ('RUNNING', 'AWAITING_INPUT'):
                reason = 'action_pending'
            elif not after['ready'] or after['phase'] not in _RUN_PHASES:
                reason = 'outside_actionable_run'
            elif after['setup']['page'] in ('deck_choice', 'stake_choice'):
                reason = 'run_setup'
            elif before is None:
                reason = 'no_baseline'
            elif _identity(before)[0] != _identity(after)[0]:
                reason = 'session_changed'
            elif before['profile'] != after['profile']:
                reason = 'profile_changed'
            elif (request and result.get('state') == 'COMPLETED' and not result.get('duplicate')
                  and request.get('action_id') == result.get('action_id')
                  and request.get('action') in ('start_run', 'continue_run')
                  and after['observation_id'] != before['observation_id']):
                reason = 'run_boundary'
            elif any(before['setup'][key] != after['setup'][key]
                     for key in ('deck_name', 'stake_name')):
                reason = 'run_setup_changed'
            else:
                old_round, new_round = before['resources']['round'], after['resources']['round']
                if old_round is not None and new_round is not None and new_round < old_round:
                    reason = 'round_rollback'

        hint = _unavailable(reason, after) if reason else _compare(before, after)
        clear = reason in ('observation_conflict', 'action_uncertain', 'action_pending',
                           'outside_actionable_run', 'run_setup') or after['phase'] == 'terminal'
        next_baseline = None if clear else after
        return PreparedChanges({**result, 'public_changes': hint}, self, self._generation,
                               next_baseline, advance)

    def commit(self, prepared):
        """Call only after the actual presented result's delivery log succeeds."""
        if prepared._owner is not self or prepared._generation != self._generation:
            self.reset()
            return False
        if prepared._advance:
            self._baseline = prepared._next
        self._generation += 1
        return True
