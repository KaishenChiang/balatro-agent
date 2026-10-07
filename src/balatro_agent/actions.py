"""Strict model input and filtered game lifecycle contract. No strategy."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .contract import Envelope

NO_PARAMS = {'sort_rank', 'sort_suit', 'reroll', 'cash_out', 'next_round', 'skip_pack',
             'open_run_setup', 'next_setup_page', 'previous_setup_page', 'start_run', 'continue_run',
             'run_info', 'deck_info', 'close_menu', 'main_menu', 'continue_endless',
             'next_setup_choices', 'previous_setup_choices', 'open_options', 'open_settings',
             'next_game_speed', 'previous_game_speed'}
TARGET_ACTIONS = {'buy', 'buy_and_use', 'sell', 'use', 'select_pack_card'}
ACTIONS = NO_PARAMS | TARGET_ACTIONS | {'play', 'discard', 'select', 'reorder', 'select_blind', 'skip_blind', 'select_setup_option'}
ActionKind = Literal['sort_rank', 'sort_suit', 'play', 'discard', 'reroll', 'cash_out', 'next_round',
                     'skip_pack', 'open_run_setup', 'next_setup_page', 'previous_setup_page', 'start_run',
                     'continue_run', 'run_info', 'deck_info', 'close_menu', 'main_menu', 'continue_endless',
                     'buy', 'buy_and_use', 'sell', 'use', 'select_pack_card', 'select', 'reorder',
                     'select_blind', 'skip_blind', 'select_setup_option', 'next_setup_choices', 'previous_setup_choices',
                     'open_options', 'open_settings', 'next_game_speed', 'previous_game_speed']
REASONS = Literal['accepted', 'completed', 'invalid_request', 'unknown_action', 'invalid_parameters', 'unknown_profile',
                  'test_profile_required', 'profile_mismatch', 'stale_observation', 'not_ready', 'unsupported_rule', 'wrong_phase',
                  'invalid_target', 'selection_restricted', 'button_unavailable', 'insufficient_capacity',
                  'action_busy', 'id_conflict', 'journal_unavailable', 'native_error', 'completion_timeout',
                  'record_not_found', 'session_changed', 'transport_uncertain', 'log_unavailable',
                  'service_error', 'checkpoint_unavailable', 'invalid_response', 'events_cancelled',
                  'native_unlock_input', 'input_context_changed']


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: ActionKind
    parameters: dict
    observation_id: str = Field(pattern=r'^obs-[0-9a-f]{16}-[0-9]+$')
    action_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$')
    reason: str = Field(min_length=1, max_length=1024)
    experience_refs: list[str] = Field(max_length=30)

    @model_validator(mode='after')
    def check_parameters(self):
        if self.action not in ACTIONS:
            raise ValueError('unknown_action')
        p = self.parameters
        expected = set()
        if self.action in ('play', 'discard') and p:
            expected = {'positions'}
            values = p.get('positions')
            if (not isinstance(values, list) or not 1 <= len(values) <= 5
                    or any(type(i) is not int or not 0 <= i <= 200 for i in values)
                    or len(set(values)) != len(values)):
                raise ValueError('invalid_parameters')
            p['positions'] = sorted(values)
        elif self.action == 'select_setup_option':
            expected = {'kind', 'position'}
            if p.get('kind') not in ('deck', 'stake') or type(p.get('position')) is not int or not 0 <= p['position'] <= 200:
                raise ValueError('invalid_parameters')
        elif self.action in TARGET_ACTIONS:
            expected = {'region', 'position'}
            if p.get('region') not in ('jokers', 'consumables', 'shop_jokers', 'shop_vouchers', 'shop_boosters', 'pack'):
                raise ValueError('invalid_parameters')
            if type(p.get('position')) is not int or not 0 <= p['position'] <= 200:
                raise ValueError('invalid_parameters')
        elif self.action in ('select', 'reorder'):
            key = 'positions' if self.action == 'select' else 'order'
            expected = {'region', key}
            regions = ('hand', 'jokers', 'consumables', 'shop_jokers', 'shop_vouchers', 'shop_boosters', 'pack') if key == 'positions' else ('hand', 'jokers', 'consumables')
            values = p.get(key)
            if p.get('region') not in regions or not isinstance(values, list) or len(values) > 200:
                raise ValueError('invalid_parameters')
            if any(type(i) is not int or not 0 <= i <= 200 for i in values) or len(set(values)) != len(values):
                raise ValueError('invalid_parameters')
            if key == 'positions':
                p[key] = sorted(values)
        elif self.action in ('select_blind', 'skip_blind'):
            expected = {'blind_slot'}
            if p.get('blind_slot') not in ('Small', 'Big', 'Boss'):
                raise ValueError('invalid_parameters')
        if set(p) != expected:
            raise ValueError('invalid_parameters')
        if any(not isinstance(s, str) or not 1 <= len(s) <= 100 for s in self.experience_refs):
            raise ValueError('invalid_parameters')
        self.experience_refs = sorted(set(self.experience_refs))
        return self


class ActionTiming(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)
    native_elapsed_ms: float | int | None = Field(default=None, ge=0, le=43_200_000)
    callback_to_completed_ms: float | int | None = Field(default=None, ge=0, le=43_200_000)
    transport_wait_ms: float | int | None = Field(default=None, ge=0, le=43_200_000)
    poll_count: int | None = Field(default=None, ge=0, le=100_000)


class ActionWire(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)
    state: Literal['REJECTED', 'RUNNING', 'AWAITING_INPUT', 'COMPLETED', 'UNKNOWN']
    reason: REASONS
    action_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$')
    observation_id: str | None = Field(default=None, pattern=r'^obs-[0-9a-f]{16}-[0-9]+$')
    game_session: str = Field(pattern=r'^[0-9a-f]{16}$')
    submitted: bool | None = None
    execution_profile: int | None = Field(default=None, ge=1, le=3)
    duplicate: bool = False
    callback_confirmed: bool = False
    related_events_complete: bool = False
    completion_signal: Literal['callback_events', 'terminal_confirmation'] | None = None
    required_action: Literal['close_menu'] | None = None
    input_for_action_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$')
    snapshot: Envelope | None = None
    timing: ActionTiming | None = None
