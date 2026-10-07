"""The one projection used for returned observations and persisted live logs."""
import hashlib
import json

from .contract import Card, CardDetails, PublicState


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def project_card(card: CardDetails) -> dict:
    result = card.model_dump()
    if card.visibility == "face_down":
        # Even costs, debuff status, enhancements or forced selection can identify
        # a hidden card. Only these observed position/state fields survive.
        if isinstance(card, Card):
            return {"position": card.position, "visibility": "face_down", "selected": card.selected}
        return {"visibility": "face_down"}
    if card.visibility == "stone":
        result["rank"] = None
        result["suit"] = None
    if card.visibility == "undiscovered":
        result["rank"] = None
        result["suit"] = None
    return result


def project(state: PublicState) -> dict:
    result = state.model_dump()
    for region, source in zip(result["regions"], state.regions, strict=True):
        positions = [card.position for card in source.cards]
        if positions != sorted(set(positions)):
            raise ValueError("invalid_public_order")
        region["cards"] = [project_card(card) for card in source.cards]
    for entry, source in zip(result["menus"]["deck_composition"], state.menus.deck_composition, strict=True):
        entry["card"] = project_card(source.card)
        # A menu composition is a multiset; it has no positional target token.
        entry["card"].pop("position", None)
        entry["card"].pop("selected", None)
    result["menus"]["deck_composition"].sort(key=canonical)
    if not state.ready:
        for action in result["ui_actions"]:
            action["enabled"] = False
        for option in result['setup']['options']:
            option['enabled'] = False
    positions = [o.position for o in state.setup.options]
    if positions != list(range(len(positions))) or (positions and state.setup.page is None):
        raise ValueError('invalid_setup_order')
    expected_kind = 'deck' if state.setup.page == 'deck_choice' else 'stake'
    if any(o.kind != expected_kind for o in state.setup.options):
        raise ValueError('invalid_setup_order')
    region_cards = {r.name: {c.position: c for c in r.cards} for r in state.regions}
    safe_actions = []
    for action in result["ui_actions"]:
        if action["position"] is not None:
            card = region_cards.get(action["region"], {}).get(action["position"])
            if card is None:
                continue
            if card.visibility == "face_down":
                # No identity-dependent buy/use/sell or labels for back cards.
                continue
        safe_actions.append(action)
    result["ui_actions"] = safe_actions
    return result


def observation_id(public: dict) -> str:
    # Only the projected public result participates, including any UI decision
    # point. No transport timestamps or hidden native state are hashed.
    return "obs-" + hashlib.sha256(canonical(public).encode("utf-8")).hexdigest()[:24]
