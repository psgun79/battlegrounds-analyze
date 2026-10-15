"""Review document projection. Full lexical telemetry lives in the adjacent events journal.

The review file remains self-contained for decisions: cards, stats, effects, choices,
economy, actions, combat and public lobby observations are all embedded.
"""
from copy import deepcopy

from .season import KEYWORDS, mechanics

GAMEPLAY_TAGS = set(KEYWORDS) | {
    "ZONE", "ZONE_POSITION", "CONTROLLER", "CARDTYPE", "CARDRACE", "COST", "ATK", "HEALTH", "DAMAGE", "ARMOR",
    "TECH_LEVEL", "PLAYER_TECH_LEVEL", "PLAYER_ID", "PLAYER_LEADERBOARD_PLACE", "PLAYER_TRIPLES",
    "PREMIUM", "FROZEN", "EXHAUSTED", "NUM_TIMES_HERO_POWER_USED_THIS_GAME", "HEROPOWER_ACTIVATIONS_THIS_TURN",
    "COOLDOWN", "CANT_PLAY", "ATTACHED", "CREATOR", "CREATOR_DBID", "DARK_GIFT_ENTITY", "IS_NIGHTMARE_BONUS",
    "RESOURCES", "RESOURCES_USED", "TEMP_RESOURCES", "BaconMaxGold", "NEXT_OPPONENT_PLAYER_ID",
}


def review_document(data):
    result = {k: deepcopy(v) for k, v in data.items() if k not in ("snapshots", "entityStates", "optionSets")}
    result["telemetry"] = {"journal": f"{data['match']['id']}.events.jsonl",
                           "tagCoverage": "Gameplay and named season tags in this file; all original numeric/internal tags in journal."}
    pools = {key: data[key] for key in ("snapshots", "entityStates", "optionSets")}
    for key in pools: result[key] = {}
    lookup = {ref: key for key, pool in pools.items() for ref in pool}
    pending = []
    def refs(value):
        if isinstance(value, str) and value in lookup: pending.append(value)
        elif isinstance(value, dict):
            for v in value.values(): refs(v)
        elif isinstance(value, list):
            for v in value: refs(v)
    refs(result)
    def trim_entity(card):
        if not isinstance(card, dict): return
        tags = card.get("rawTags", {})
        card["rawTags"] = {k: v for k, v in tags.items() if k in GAMEPLAY_TAGS or k in mechanics(tags)
                           or k.startswith("NEW_")}
        for enchantment in card.get("enchantments", []): trim_entity(enchantment)
        if card.get("darkGift"): trim_entity(card["darkGift"])
    while pending:
        ref = pending.pop(); pool = lookup[ref]
        if ref in result[pool]: continue
        value = deepcopy(pools[pool][ref])
        if pool == "entityStates": trim_entity(value)
        result[pool][ref] = value
        refs(value)
    return result
