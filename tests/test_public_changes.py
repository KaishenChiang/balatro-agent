"""Synthetic delivery history; no native game reads or strategy examples."""
from copy import deepcopy

import pytest

from balatro_agent.compact import expand, present
from balatro_agent.contract import POLICY_VERSION, SCHEMA_VERSION
from balatro_agent.policy import canonical
from balatro_agent.public_changes import PROTOCOL, PublicChanges


SESSION = '0123456789abcdef'


def observation(epoch=1, phase='hand'):
    return {'schema_version': SCHEMA_VERSION, 'visibility_policy_version': POLICY_VERSION,
            'profile': 3, 'observation_id': f'obs-{SESSION}-{epoch}', 'phase': phase,
            'ready': True, 'ready_reason': 'ui_operable',
            'resources': {'availability': 'observed', 'dollars': 0, 'chips': 0,
                          'hands_left': 4, 'discards_left': 3, 'ante': 1, 'round': 1},
            'setup': {'availability': 'observed', 'deck_name': 'Public Deck',
                      'stake_name': 'Public Stake'},
            'regions': [{'name': 'hand', 'capacity': 8, 'selection_limit': 5,
                         'cards': [{'position': 0, 'visibility': 'face_up', 'selected': False,
                                    'rank': 'Ace', 'suit': 'Spades', 'name': 'Ace',
                                    'debuffed': False, 'forced_selection': False,
                                    'description': ['Displayed card description']}]},
                        {'name': 'jokers', 'capacity': 5, 'selection_limit': 1, 'cards': []},
                        {'name': 'consumables', 'capacity': 2, 'selection_limit': 1, 'cards': []}],
            'blinds': [{'slot': 'current', 'name': 'Displayed Blind',
                        'description': ['Displayed constraint'], 'required_chips': 300}]}


def delivered(tracker, public, **fields):
    prepared = tracker.prepare({'status': 'ok', 'observation': public, **fields})
    assert tracker.commit(prepared)
    return prepared.result['public_changes']


def test_first_delivery_has_no_baseline_and_preserves_full_observation():
    tracker, public = PublicChanges(), observation()
    original = deepcopy(public)
    prepared = tracker.prepare({'status': 'ok', 'observation': public})
    assert prepared.result['observation'] == original and public == original
    assert prepared.result['public_changes'] == {
        'protocol': PROTOCOL, 'status': 'unavailable', 'reason': 'no_baseline',
        'to_observation_id': public['observation_id']}
    assert tracker.commit(prepared)
    unchanged = delivered(tracker, observation(2))
    assert unchanged['status'] == 'compared'
    assert set(unchanged['unchanged']) == {'phase', 'hand', 'jokers', 'consumables', 'resources', 'blinds'}
    assert not unchanged['changed'] and not unchanged['unknown']


def test_preparing_an_undelivered_snapshot_cannot_advance_history():
    tracker = PublicChanges()
    delivered(tracker, observation())
    intermediate = observation(2)
    intermediate['resources']['dollars'] = 50
    tracker.prepare({'status': 'ok', 'observation': intermediate})
    current = observation(3)
    current['resources']['dollars'] = 2
    hint = delivered(tracker, current)
    assert hint['from_observation_id'] == observation()['observation_id']
    assert hint['resource_changes'] == {'dollars': {'before': 0, 'after': 2}}


def test_committed_baseline_is_detached_from_the_callers_object():
    tracker, public = PublicChanges(), observation()
    delivered(tracker, public)
    public['resources']['dollars'] = 999
    public['regions'][0]['cards'][0]['description'].append('Later mutation')
    hint = delivered(tracker, observation(2))
    assert not hint['changed']


def test_resource_and_hand_changes_are_facts_without_choosing_strategy():
    tracker = PublicChanges()
    delivered(tracker, observation())
    current = observation(2)
    current['resources'].update(dollars=4, hands_left=3)
    current['regions'][0]['cards'][0]['rank'] = 'King'
    hint = delivered(tracker, current)
    assert hint['changed'] == ['hand', 'resources']
    assert hint['resource_changes'] == {'dollars': {'before': 0, 'after': 4},
                                       'hands_left': {'before': 4, 'after': 3}}
    assert 'blinds' in hint['unchanged']
    assert not any(key in hint for key in ('recommended_action', 'strategy', 'targets'))


@pytest.mark.parametrize('visibility', ['face_down', 'stone', 'undiscovered'])
def test_hidden_card_fields_cannot_change_the_hint_or_baseline(visibility):
    tracker = PublicChanges()
    first = observation()
    card = first['regions'][0]['cards'][0]
    card.update(visibility=visibility, rank='SECRET_RANK', suit='SECRET_SUIT',
                seed='SECRET_SEED', native_id='SECRET_ID')
    if visibility == 'face_down':
        card.update(name='SECRET_NAME', description=['SECRET_DESCRIPTION'])
    delivered(tracker, first)
    current = deepcopy(first)
    current['observation_id'] = f'obs-{SESSION}-2'
    current['regions'][0]['cards'][0].update(rank='OTHER_SECRET', suit='OTHER_SECRET',
                                           native_id='OTHER_SECRET', seed='OTHER_SECRET')
    hint = delivered(tracker, current)
    assert 'hand' in hint['unknown'] and 'hand' not in hint['unchanged']
    assert 'hand' not in hint['changed']
    assert 'SECRET' not in canonical(hint) and 'SECRET' not in canonical(tracker._baseline)


def test_public_visibility_change_remains_visible_and_uncertain():
    tracker = PublicChanges()
    delivered(tracker, observation())
    current = observation(2)
    current['regions'][0]['cards'][0]['visibility'] = 'face_down'
    hint = delivered(tracker, current)
    assert 'hand' in hint['changed'] and 'hand' in hint['unknown']
    assert 'hand' not in hint['unchanged']


@pytest.mark.parametrize('field', ['ante', 'round', 'dollars'])
def test_null_resources_are_unknown_not_zero_or_numeric_deltas(field):
    tracker = PublicChanges()
    first = observation()
    first['resources'][field] = None
    delivered(tracker, first)
    hint = delivered(tracker, observation(2))
    assert field in hint['unknown_resources']
    assert field not in hint.get('resource_changes', {})
    assert 'resources' in hint['unknown'] and 'resources' not in hint['unchanged']


def test_unknown_resource_availability_does_not_export_a_numeric_delta():
    tracker = PublicChanges()
    delivered(tracker, observation())
    current = observation(2)
    current['resources'].update(availability='unknown', dollars=9)
    hint = delivered(tracker, current)
    assert 'resources' in hint['unknown'] and 'resource_changes' not in hint


@pytest.mark.parametrize('issue', ['tooltip_unavailable', 'dynamic_tooltip_omitted',
                                 'unconfirmed_field', 'unsupported_rule'])
def test_omitted_text_never_proves_an_unchanged_region_or_blind(issue):
    tracker = PublicChanges()
    delivered(tracker, observation())
    current = observation(2)
    current['unknowns'] = [issue]
    hint = delivered(tracker, current)
    assert {'hand', 'blinds'} <= set(hint['unknown'])
    assert not {'hand', 'blinds'}.intersection(hint['unchanged'])


def test_known_empty_region_is_distinct_from_a_region_not_displayed():
    tracker = PublicChanges()
    first = observation()
    delivered(tracker, first)
    current = deepcopy(first)
    current['observation_id'] = f'obs-{SESSION}-2'
    assert 'jokers' in delivered(tracker, current)['unchanged']
    current['observation_id'] = f'obs-{SESSION}-3'
    current['regions'].pop(1)
    hint = delivered(tracker, current)
    assert 'jokers' in hint['changed'] and 'jokers' in hint['unknown']


def test_dynamic_visible_joker_text_and_order_changes_are_reported():
    tracker = PublicChanges()
    first = observation()
    cards = [{**deepcopy(first['regions'][0]['cards'][0]), 'position': i,
              'name': f'Displayed Joker {i}', 'rank': None, 'suit': None} for i in range(2)]
    first['regions'][1]['cards'] = cards
    delivered(tracker, first)
    current = deepcopy(first)
    current['observation_id'] = f'obs-{SESSION}-2'
    current['regions'][1]['cards'][0]['description'] = ['New displayed value']
    assert 'jokers' in delivered(tracker, current)['changed']
    current['observation_id'] = f'obs-{SESSION}-3'
    a, b = current['regions'][1]['cards']
    current['regions'][1]['cards'] = [{**b, 'position': 0}, {**a, 'position': 1}]
    assert 'jokers' in delivered(tracker, current)['changed']


def test_displayed_blind_constraints_change_but_defeat_label_alone_does_not():
    tracker = PublicChanges()
    first = observation()
    first['blinds'][0]['state'] = 'Current'
    delivered(tracker, first)
    current = deepcopy(first)
    current['observation_id'] = f'obs-{SESSION}-2'
    current['blinds'][0]['state'] = 'Defeated'
    assert 'blinds' in delivered(tracker, current)['unchanged']
    current['observation_id'] = f'obs-{SESSION}-3'
    current['blinds'][0]['required_chips'] = 600
    assert 'blinds' in delivered(tracker, current)['changed']


@pytest.mark.parametrize('change,reason', [
    ('profile', 'profile_changed'), ('session', 'session_changed'),
    ('round', 'round_rollback'), ('deck', 'run_setup_changed'), ('stake', 'run_setup_changed')])
def test_live_scope_changes_rebase_without_cross_scope_comparison(change, reason):
    tracker = PublicChanges()
    delivered(tracker, observation(2))
    current = observation(3)
    if change == 'profile':
        current['profile'] = 2
    elif change == 'session':
        current['observation_id'] = 'obs-fedcba9876543210-1'
    elif change == 'round':
        current['resources']['round'] = 0
    else:
        current['setup'][f'{change}_name'] = 'Different displayed choice'
    hint = delivered(tracker, current)
    assert hint['status'] == 'unavailable' and hint['reason'] == reason
    next_public = deepcopy(current)
    session = current['observation_id'].split('-')[1]
    next_public['observation_id'] = f'obs-{session}-4'
    assert delivered(tracker, next_public)['from_observation_id'] == current['observation_id']


def test_native_ante_reduction_is_a_resource_change_in_the_same_run():
    tracker = PublicChanges()
    first = observation()
    first['resources'].update(ante=5, round=9)
    delivered(tracker, first)
    current = deepcopy(first)
    current['observation_id'] = f'obs-{SESSION}-2'
    current['resources']['ante'] = 4
    hint = delivered(tracker, current)
    assert hint['status'] == 'compared'
    assert hint['resource_changes'] == {'ante': {'before': 5, 'after': 4}}


@pytest.mark.parametrize('kind,reason', [('profile','profile_changed'), ('session','session_changed')])
def test_current_scope_change_is_not_inferred_to_be_an_archived_receipt(kind,reason):
    tracker=PublicChanges(); delivered(tracker,observation())
    current=observation(2)
    if kind=='profile': current['profile']=2
    else: current['observation_id']='obs-fedcba9876543210-2'
    hint=delivered(tracker,current,state='COMPLETED',submitted=True)
    assert hint['reason']==reason
    assert tracker._baseline['observation_id']==current['observation_id']


@pytest.mark.parametrize('action', ['start_run', 'continue_run'])
def test_confirmed_run_boundaries_do_not_reuse_the_old_build(action):
    tracker = PublicChanges()
    delivered(tracker, observation())
    current = observation(2)
    result = {'state': 'COMPLETED', 'submitted': True, 'action_id': 'new-run', 'observation': current}
    prepared = tracker.prepare(result, {'action': action, 'action_id': 'new-run'})
    assert prepared.result['public_changes']['reason'] == 'run_boundary'
    assert prepared.result['state'] == 'COMPLETED'
    tracker.commit(prepared)
    assert tracker.prepare(result, {'action': action, 'action_id': 'new-run'}).result[
        'public_changes']['status'] == 'compared'


@pytest.mark.parametrize('kind', ['older', 'other_session', 'other_profile'])
def test_historical_action_receipts_never_replace_the_current_baseline(kind):
    tracker = PublicChanges()
    delivered(tracker, observation(5))
    receipt = observation(4 if kind == 'older' else 6)
    if kind == 'other_session':
        receipt['observation_id'] = 'obs-fedcba9876543210-100'
    elif kind == 'other_profile':
        receipt['profile'] = 2
    prepared=tracker.prepare({'state':'COMPLETED','submitted':True,'observation':receipt},historical=True)
    assert tracker.commit(prepared)
    hint=prepared.result['public_changes']
    assert hint['status'] == 'unavailable' and hint['reason'].startswith('historical_')
    assert delivered(tracker, observation(7))['from_observation_id'] == observation(5)['observation_id']


@pytest.mark.parametrize('has_baseline', [False, True])
def test_explicit_archival_receipt_cannot_seed_or_advance_delivery_history(has_baseline):
    tracker = PublicChanges()
    if has_baseline:
        delivered(tracker, observation())
    receipt = {'state': 'COMPLETED', 'submitted': True, 'observation': observation(5)}
    prepared = tracker.prepare(receipt, historical=True)
    assert prepared.result['public_changes']['reason'] == 'historical_receipt'
    assert tracker.commit(prepared)
    hint = delivered(tracker, observation(6))
    if has_baseline:
        assert hint['from_observation_id'] == observation()['observation_id']
    else:
        assert hint['reason'] == 'no_baseline'


@pytest.mark.parametrize('fields,reason', [({'state': 'UNKNOWN'}, 'action_uncertain'),
                                         ({'state': 'RUNNING'}, 'action_pending'),
                                         ({'state': 'AWAITING_INPUT'}, 'action_pending')])
def test_pending_or_uncertain_actions_clear_hints_without_relabeling_results(fields, reason):
    tracker = PublicChanges()
    delivered(tracker, observation())
    prepared = tracker.prepare({'observation': observation(2), **fields})
    assert prepared.result['state'] == fields['state']
    assert prepared.result['public_changes']['reason'] == reason
    tracker.commit(prepared)
    assert delivered(tracker, observation(3))['reason'] == 'no_baseline'


@pytest.mark.parametrize('phase', ['main_menu', 'menu', 'transition'])
def test_leaving_actionable_run_drops_comparison_baseline(phase):
    tracker = PublicChanges()
    delivered(tracker, observation())
    hint = delivered(tracker, observation(2, phase))
    assert hint['reason'] == 'outside_actionable_run'
    assert delivered(tracker, observation(3))['reason'] == 'no_baseline'


def test_terminal_can_be_compared_but_cannot_become_next_runs_baseline():
    tracker = PublicChanges()
    delivered(tracker, observation())
    terminal = observation(2, 'terminal')
    terminal['outcome'] = 'win'
    assert delivered(tracker, terminal)['status'] == 'compared'
    assert delivered(tracker, observation(3))['reason'] == 'no_baseline'


@pytest.mark.parametrize('metadata', [{'status': 'disconnected'}, {'status': 'log_unavailable'},
                                    {'state': 'UNKNOWN'}, {'status': 'ok', 'connected': False},
                                    {'status': 'ok', 'actual_profile': 2},
                                    {'status': 'ok', 'game_session': 'fedcba9876543210'}])
def test_delivery_gaps_and_health_scope_changes_need_a_fresh_baseline(metadata):
    tracker = PublicChanges()
    delivered(tracker, observation())
    prepared = tracker.prepare(metadata)
    assert prepared.result['public_changes']['reason'] == 'delivery_gap'
    tracker.commit(prepared)
    assert delivered(tracker, observation(2))['reason'] == 'no_baseline'


@pytest.mark.parametrize('metadata', [{'status': 'ok', 'connected': True, 'actual_profile': 3,
                                     'game_session': SESSION},
                                    {'state': 'REJECTED', 'submitted': False}])
def test_healthy_metadata_and_unsubmitted_rejections_preserve_baseline(metadata):
    tracker = PublicChanges()
    delivered(tracker, observation())
    prepared = tracker.prepare(metadata)
    assert 'public_changes' not in prepared.result
    tracker.commit(prepared)
    assert delivered(tracker, observation(2))['status'] == 'compared'


def test_restart_invalid_data_and_same_id_conflicts_report_unavailable_without_raw_errors():
    assert delivered(PublicChanges(), observation())['reason'] == 'no_baseline'
    tracker = PublicChanges()
    delivered(tracker, observation())
    conflict = observation()
    conflict['resources']['dollars'] = 100
    assert delivered(tracker, conflict)['reason'] == 'observation_conflict'
    bad = observation(2)
    bad['profile'] = 'SECRET_INVALID'
    hint = delivered(tracker, bad)
    assert hint['reason'] == 'invalid_observation' and 'SECRET' not in canonical(hint)
    assert delivered(tracker, observation(3))['reason'] == 'no_baseline'


def test_absent_core_regions_and_blinds_are_unknown_not_known_empty():
    tracker = PublicChanges()
    first = observation()
    first['regions'] = first['regions'][:1]
    first['blinds'] = []
    delivered(tracker, first)
    current = deepcopy(first)
    current['observation_id'] = f'obs-{SESSION}-2'
    hint = delivered(tracker, current)
    assert {'jokers', 'consumables', 'blinds'} <= set(hint['unknown'])
    assert not {'jokers', 'consumables', 'blinds'}.intersection(hint['unchanged'])
    assert 'shop' not in hint['unknown'] and 'pack' not in hint['unknown']


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
def test_nonfinite_resources_cannot_enter_the_hint_or_baseline(value):
    tracker = PublicChanges()
    public = observation()
    public['resources']['dollars'] = value
    assert delivered(tracker, public)['reason'] == 'invalid_observation'
    assert tracker._baseline is None


@pytest.mark.parametrize('field', ['debuffed', 'forced_selection', 'rank', 'suit'])
def test_missing_applicable_hand_fields_are_unknown_even_when_identical(field):
    tracker = PublicChanges()
    first = observation()
    first['regions'][0]['cards'][0][field] = None
    delivered(tracker, first)
    current = deepcopy(first)
    current['observation_id'] = f'obs-{SESSION}-2'
    hint = delivered(tracker, current)
    assert 'hand' in hint['unknown'] and 'hand' not in hint['unchanged']


@pytest.mark.parametrize('region,price', [('shop_jokers','price'), ('shop_vouchers','price'),
    ('shop_boosters','price'), ('jokers','sell_price'), ('consumables','sell_price')])
def test_region_specific_prices_are_unknown_but_inapplicable_fields_are_not(region,price):
    tracker = PublicChanges()
    first = observation(phase='shop' if region.startswith('shop_') else 'hand')
    card = {'position': 0, 'selected': False, 'visibility': 'face_up', 'name': 'Visible item',
            'description': ['Public text'], 'debuffed': False, 'forced_selection': False,
            price: 0}  # No rank/suit, or price from another region, applies here.
    first['regions'] = [r for r in first['regions'] if r['name'] != region]
    first['regions'].append({'name': region, 'capacity': 5, 'selection_limit': 1, 'cards': [card]})
    delivered(tracker, first)
    current = deepcopy(first); current['observation_id'] = f'obs-{SESSION}-2'
    section = 'shop' if region.startswith('shop_') else region
    assert section in delivered(tracker, current)['unchanged']
    current['observation_id'] = f'obs-{SESSION}-3'
    current['regions'][-1]['cards'][0][price] = None
    hint = delivered(tracker, current)
    assert section in hint['changed'] and section in hint['unknown'] and section not in hint['unchanged']


def test_out_of_order_or_foreign_prepared_commits_fail_conservatively():
    tracker = PublicChanges()
    a = tracker.prepare({'status': 'ok', 'observation': observation()})
    b = tracker.prepare({'status': 'ok', 'observation': observation(2)})
    assert tracker.commit(a) and not tracker.commit(b)
    assert delivered(tracker, observation(3))['reason'] == 'no_baseline'
    assert not PublicChanges().commit(tracker.prepare({'status': 'ok', 'observation': observation(4)}))


def test_hint_is_bounded_and_identical_across_full_and_compact_presentation():
    tracker = PublicChanges()
    first = observation()
    first['regions'][0]['cards'] = [{**deepcopy(first['regions'][0]['cards'][0]), 'position': i}
                                  for i in range(200)]
    delivered(tracker, first)
    current = deepcopy(first)
    current['observation_id'] = f'obs-{SESSION}-2'
    current['resources'].update(dollars=20, chips=80, hands_left=3, discards_left=1, ante=2, round=2)
    prepared = tracker.prepare({'status': 'ok', 'observation': current})
    compact = present(prepared.result, 'compact')
    assert expand(compact['observation']) == current
    assert compact['public_changes'] == prepared.result['public_changes']
    assert len(canonical(compact['public_changes']).encode('utf-8')) < 1500
