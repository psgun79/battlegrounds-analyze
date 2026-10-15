"""Small, replaceable semantic layer; unknown tags always survive in entity revisions."""
import re

KEYWORDS = ("TAUNT", "DIVINE_SHIELD", "REBORN", "VENOMOUS", "POISONOUS",
            "WINDFURY", "STEALTH", "DEATHRATTLE", "LIFESTEAL", "CANT_BE_TARGETED_BY_SPELLS")
BUTTONS = {
    "TB_BaconShop_8p_Reroll_Button": "ROLL",
    "TB_BaconShopLockAll_Button": "FREEZE_TOGGLE",
    "BG36_Button_DarkGift": "DARK_GIFT",
}


def action_kind(card, tags):
    if card in BUTTONS:
        return BUTTONS[card]
    if card.startswith("TB_BaconShop_DragBuy"):
        return "BUY"
    if card.startswith("TB_BaconShop_DragSell"):
        return "SELL"
    if re.fullmatch(r"TB_BaconShopTechUp\d+_Button", card):
        return "TAVERN_UPGRADE"
    if tags.get("CARDTYPE") == "HERO_POWER":
        return "HERO_POWER"
    if tags.get("CARDTYPE") in ("SPELL", "BATTLEGROUND_SPELL"):
        return "SPELL_USE"
    if tags.get("CARDTYPE") == "BATTLEGROUND_TRINKET":
        return "TRINKET_USE"
    if tags.get("CARDTYPE") == "MINION" and tags.get("ZONE") == "HAND":
        return "PLAY"
    if tags.get("CARDTYPE") == "MINION" and tags.get("HAS_ACTIVATE_POWER") == 1:
        return "ACTIVATE"
    return "UNKNOWN_ACTION"


def mechanics(tags):
    return {k: v for k, v in tags.items() if any(s in k for s in (
        "DARK_GIFT", "NIGHTMARE", "TRINKET", "QUEST", "ANOMALY", "BACON_",
        "TAG_SCRIPT_DATA", "ACTIVATE", "LOCKBOX", "FISHBAIT"))}
