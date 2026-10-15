"""Detailed audit Markdown. Keep the historical exporter available unchanged."""
import re


def clean(value):
    return re.sub(r"[\r\n]+", " ", str(value)).replace("|", "\\|") if value is not None else "?"


def markdown(data):
    entities, states = data["entityStates"], data["snapshots"]
    def card(ref):
        c = entities.get(ref, {})
        label = c.get("name") or c.get("cardId") or f"entity {c.get('entityId', '?')}"
        stats = f" {c['attack']}/{c.get('health', '?')}" if c.get("attack") is not None else ""
        tier = f" T{c['tavernTier']}" if c.get("tavernTier") is not None else ""
        cost = f" cost={c['cost']}" if c.get("cost") is not None else ""
        golden = " GOLDEN" if c.get("golden") else ""
        tribes = f" ({','.join(map(str, c['tribes']))})" if c.get("tribes") else ""
        keywords = " " + ",".join(c.get("keywords", [])) if c.get("keywords") else ""
        effects = "; ".join(clean(x.get("name") or x.get("cardId") or x.get("entityId")) for x in c.get("enchantments", []))
        gift = c.get("darkGift")
        if gift: effects += "; Dark Gift=" + clean(gift.get("name") or gift.get("cardId"))
        return f"{clean(label)} [{c.get('cardId') or '?'} #{c.get('entityId', '?')}]{stats}{tier}{golden}{tribes}{keywords}{cost}" + (f" {{{effects}}}" if effects else "")
    def line_cards(refs):
        return " / ".join(f"{i}. {card(ref)}" for i, ref in enumerate(refs, 1)) or "(empty / not observed; see coverage)"
    def status(s):
        return f"HP {clean(s['hp'])} + Armor {clean(s['armor'])} | Tier {clean(s['tavernTier'])} | Gold {clean(s['remainingGold'])} | Upgrade {clean(s['upgradeCost'])} | Frozen {clean(s['frozen'])}"
    m = data["match"]
    lines = [f"# Battlegrounds review — {m['id']}", "",
             f"{m['startedAt']} | {data['result']['status']} | Placement {clean(data['result']['placement'])}",
             f"Hero: {card(m['hero']) if m['hero'] else '?'}", "",
             "> Evaluate each choice using its BEFORE state only. Unknown ≠ zero. Transient shop states may not have been clickable.",
             "> Opponent boards are observed encounters, not a simultaneous lobby average. Zero damage does not prove a tie.", ""]
    for warning in data["quality"]["warnings"]: lines.append(f"- Capture warning: {warning}")
    # Card rules are static metadata, displayed once; never rewrite historical entity stats.
    rules = {}
    for c in entities.values():
        if c.get("text"): rules[c["cardId"]] = c
    for turn in data["turns"]:
        if not turn["events"] and not turn["shopSnapshots"] and not turn["combat"]: continue
        lines.extend(["", f"# Turn {turn['turn']}" + (" — hero selection" if turn["turn"] == 0 else ""), ""])
        if sid := turn["startState"]:
            s = states[sid]
            lines.extend([status(s), f"Board: {line_cards(s['board'])}", f"Hand: {line_cards(s['hand'])}"])
        entries = [(x["sequence"], 0, "shop", x) for x in turn["shopSnapshots"]]
        entries += [(x["sequence"], 1, "action", x) for x in turn["events"]]
        last_shop_signature = None
        shown_choices = set()
        last_board = None
        last_hand = None
        last_powers = None
        for _, _, kind, obj in sorted(entries, key=lambda x: (x[0], x[1])):
            if kind == "shop":
                s = states[obj["state"]]
                signature = (tuple(card(ref) for ref in s["shop"]), s["frozen"], s["tavernTier"])
                if signature != last_shop_signature:
                    last_shop_signature = signature
                    transient = " [resolving effect; may be transient]" if obj["transient"] else ""
                    lines.extend(["", f"## Shop {obj['state']} — {obj['reason']}{transient}", status(s)])
                    lines.extend(f"- {card(ref)}" for ref in s["shop"])
                    if not s["shop"]: lines.append("- (empty / not observed)")
                if choice := s.get("choices"):
                    signature = (choice["id"], tuple(choice["offered"]))
                    if signature not in shown_choices:
                        shown_choices.add(signature)
                        lines.append(f"Discover #{choice['id']}: {line_cards(choice['offered'])}")
            else:
                a = obj
                b = states.get(a["stateBefore"], {})
                after = states.get(a["stateAfter"], {})
                actor = card(a.get("actor")) if a.get("actor") else ""
                target = f" → {card(a['target'])}" if a.get("target") else ""
                lines.extend(["", f"### {a['action']} {actor}{target}",
                              f"{a['timestamp']} | {a['stateBefore']} → {a['stateAfter'] or 'pending'} | Gold {clean(b.get('remainingGold'))} → {clean(after.get('remainingGold'))} | {a['evidence']} | {a.get('status','')}"])
                board, hand = line_cards(b.get('board', [])), line_cards(b.get('hand', []))
                if board != last_board: lines.append("Before board: " + board)
                if hand != last_hand: lines.append("Before hand: " + hand)
                last_board, last_hand = board, hand
                if a["phase"] != "RECRUIT" and b.get("choices"):
                    lines.append("Choices: " + line_cards(b["choices"]["offered"]))
                if after:
                    board, hand = line_cards(after.get('board', [])), line_cards(after.get('hand', []))
                    if board != last_board: lines.append("After board: " + board)
                    if hand != last_hand: lines.append("After hand: " + hand)
                    last_board, last_hand = board, hand
                powers = line_cards(b.get("heroPowers", []))
                if b.get("heroPowers") and powers != last_powers: lines.append("Hero powers: " + powers)
                last_powers = powers
        if c := turn["combat"]:
            start = states[c["startState"]]
            lines.extend(["", "## Combat", f"Capture: {c['captureMethod']} | {c['startState']} → {c['endState'] or '?'}",
                          f"Player board: {line_cards(start['board'])}",
                          f"Opponent: {card(start['opponentHero'])}",
                          f"Opponent board: {line_cards(start['opponentBoard'])}",
                          f"Result: {c['result']} | Taken {clean(c['damageTaken'])} | Dealt {clean(c['damageDealt'])} | Lethal {clean(c['lethal'])}",
                          f"Combat events: {len(c['events'])}; full attack/death sequence in JSON."])
        # Last observed public lobby info, including raw tier/health on heroes. No fabricated averages.
        candidate = states.get(turn["startState"] or "", {})
        if candidate.get("lobbyHeroes"):
            lines.extend(["", "Lobby hero observations (boards unavailable):"])
            for ref in candidate["lobbyHeroes"]:
                e = entities[ref]
                lines.append(f"- {card(ref)} | Tier {clean(e['rawTags'].get('PLAYER_TECH_LEVEL'))} | Place {clean(e['rawTags'].get('PLAYER_LEADERBOARD_PLACE'))}")
    if rules:
        lines.extend(["", "# Card text reference (provided card database)"])
        for cid, c in sorted(rules.items()): lines.append(f"- {cid}: {clean(c['text'])}")
    lines.extend(["", "# Capture limits", *[f"- {x}" for x in data["quality"]["limitations"]], ""])
    return "\n".join(lines)


audit_markdown = markdown
