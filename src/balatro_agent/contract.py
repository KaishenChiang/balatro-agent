"""Public contract. No native object identifiers, seed or draw-order fields."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "reader-2"
POLICY_VERSION = "player-visible-1"
ADAPTER_VERSION = "0.3.0"
UPSTREAM_COMMIT = "9052d76f14723293f6c6b2cecaa791a5c4ae68f3"
GAME_VERSION = "1.0.1o-FULL"

Phase = Literal["main_menu", "blind_select", "hand", "transition", "round_eval", "shop", "pack", "menu", "terminal", "unsupported"]
Reason = Literal["ui_operable", "controller_locked", "state_initializing", "processing", "ui_not_displayed", "unsupported_state", "menu_open", "unknown_readiness"]
Issue = Literal["transition_regions_suppressed", "tooltip_unavailable", "dynamic_tooltip_omitted", "unconfirmed_field", "unsupported_rule", "menu_not_open", "unsupported_menu", "readiness_unconfirmed"]
ActionName = Literal["open_run_setup", "start_run", "continue_run", "quick_start_run", "next_setup_page", "previous_setup_page", "select_setup_option", "next_setup_choices", "previous_setup_choices", "open_options", "open_settings", "next_game_speed", "previous_game_speed", "select_blind", "skip_blind", "play", "discard", "sort_rank", "sort_suit", "cash_out", "buy", "buy_and_use", "sell", "reroll", "next_round", "use", "select_pack_card", "skip_pack", "run_info", "deck_info", "close_menu", "main_menu", "continue_endless"]
RegionName = Literal["hand", "play", "jokers", "consumables", "shop_jokers", "shop_vouchers", "shop_boosters", "pack"]


class PublicModel(BaseModel):
    # Every nesting level has a field allow list. Never echo validation errors.
    model_config = ConfigDict(extra="ignore", strict=True)


class CardDetails(PublicModel):
    # Composition entries carry visible content, never a regional target token.
    visibility: Literal["face_up", "face_down", "stone", "undiscovered"]
    name: str | None = Field(default=None, max_length=512)
    rank: Literal["2", "3", "4", "5", "6", "7", "8", "9", "10", "Jack", "Queen", "King", "Ace"] | None = None
    suit: Literal["Spades", "Hearts", "Clubs", "Diamonds"] | None = None
    description: list[str] = Field(default_factory=list, max_length=100)
    tooltip_info: list[str] = Field(default_factory=list, max_length=100)
    debuffed: bool | None = None
    forced_selection: bool | None = None
    price: float | int | None = None
    sell_price: float | int | None = None

    @model_validator(mode="before")
    @classmethod
    def mask_hidden_before_validation(cls, value):
        # Invalid identity fields must not create an error side channel either.
        if isinstance(value, dict):
            if value.get("visibility") == "face_down":
                return {key: value[key] for key in ("position", "visibility", "selected") if key in value}
            if value.get("visibility") in ("stone", "undiscovered"):
                return {key: child for key, child in value.items() if key not in ("rank", "suit")}
        return value


class Card(CardDetails):
    position: int = Field(ge=0, le=200)
    selected: bool


class Region(PublicModel):
    name: RegionName
    capacity: int | None = Field(default=None, ge=0, le=200)
    selection_limit: int | None = Field(default=None, ge=0, le=200)
    cards: list[Card] = Field(default_factory=list, max_length=200)


class Resources(PublicModel):
    availability: Literal["observed", "unknown", "not_applicable"] = "unknown"
    dollars: float | int | None = None
    chips: float | int | None = None
    hands_left: int | None = None
    discards_left: int | None = None
    ante: int | None = None
    round: int | None = None
    reroll_cost: float | int | None = None
    pack_choices: int | None = None


class Blind(PublicModel):
    slot: Literal["Small", "Big", "Boss", "current"]
    name: str | None = Field(default=None, max_length=512)
    description: list[str] = Field(default_factory=list, max_length=20)
    required_chips: float | int | None = None
    reward: float | int | None = None
    state: Literal["Current", "Select", "Upcoming", "Defeated", "Skipped", "Hide"] | None = None
    skip_tag_name: str | None = Field(default=None, max_length=512)
    skip_tag_description: list[str] = Field(default_factory=list, max_length=20)


class UIAction(PublicModel):
    name: ActionName
    enabled: bool
    blind_slot: Literal["Small", "Big", "Boss"] | None = None
    region: RegionName | None = None
    position: int | None = Field(default=None, ge=0, le=200)
    label: list[str] = Field(default_factory=list, max_length=20)


class HandLevel(PublicModel):
    name: str = Field(max_length=512)
    level: int | None = None
    chips: float | int | None = None
    mult: float | int | None = None
    played: int | None = None
    description: list[str] = Field(default_factory=list, max_length=20)


class DeckEntry(PublicModel):
    card: CardDetails
    count: int = Field(ge=1, le=500)
    greyed: bool


class Menus(PublicModel):
    poker_hands: list[HandLevel] = Field(default_factory=list, max_length=20)
    deck_composition: list[DeckEntry] = Field(default_factory=list, max_length=500)
    deck_scope: Literal["displayed_menu", "not_open"] = "not_open"


class SetupOption(PublicModel):
    # Local positions refer only to cards on the current rendered setup page.
    kind: Literal["deck", "stake"]
    position: int = Field(ge=0, le=200)
    name: str | None = Field(default=None, max_length=512)
    description: list[str] = Field(default_factory=list, max_length=100)
    enabled: bool
    selected: bool


class Setup(PublicModel):
    availability: Literal["observed", "unknown", "not_applicable"] = "unknown"
    deck_name: str | None = Field(default=None, max_length=512)
    stake_name: str | None = Field(default=None, max_length=512)
    page: Literal["deck_choice", "stake_choice"] | None = None
    options: list[SetupOption] = Field(default_factory=list, max_length=200)


class Preferences(PublicModel):
    # The normal settings screen's rendered value, never an inferred setting.
    availability: Literal["observed", "not_open"] = "not_open"
    game_speed: float | int | None = None


class PublicState(PublicModel):
    phase: Phase
    ready: bool
    ready_reason: Reason
    underlying_phase: Phase | None = None
    resources: Resources
    setup: Setup = Field(default_factory=Setup)
    preferences: Preferences = Field(default_factory=Preferences)
    regions: list[Region] = Field(default_factory=list, max_length=8)
    blinds: list[Blind] = Field(default_factory=list, max_length=4)
    ui_actions: list[UIAction] = Field(default_factory=list, max_length=200)
    settlement_text: list[str] = Field(default_factory=list, max_length=300)
    menus: Menus = Field(default_factory=Menus)
    outcome: Literal["win", "loss"] | None = None
    unknowns: list[Issue] = Field(default_factory=list, max_length=100)


class Observation(PublicState):
    schema_version: Literal["reader-2"]
    visibility_policy_version: Literal["player-visible-1"]
    profile: int = Field(ge=1, le=3)
    observation_id: str = Field(pattern=r"^obs-[0-9a-f]{16}-[0-9]+$")


class Envelope(PublicModel):
    schema_version: str
    visibility_policy_version: str
    adapter_version: str
    upstream_commit: str
    upstream_mod_version: str
    game_version: str | None = None
    profile: int | None = Field(default=None, ge=1, le=3)
    phase: Phase
    ready: bool
    ready_reason: Reason
    compatibility: Literal["supported", "unsupported_mods", "unsupported_game"]
    public: PublicState | None = None
    game_session: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    observation_id: str | None = Field(default=None, pattern=r"^obs-[0-9a-f]{16}-[0-9]+$")
    setup_selection_protocol: Literal["native-choices-v1"] | None = None
    direct_hand_protocol: Literal["positions-v1"] | None = None
    direct_target_protocol: Literal["native-target-v1"] | None = None
    preferences_protocol: Literal["native-settings-v1"] | None = None
