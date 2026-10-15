"""Event reducer and immutable, self-contained decision snapshots."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from . import __version__
from .season import KEYWORDS, action_kind, mechanics


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Match:
    def __init__(self, record, source, date=None, local_player=None, cards=None):
        self.source = source
        self.date = date
        self.entities = {}
        self.names = {}
        self.game_id = None
        self.local = local_player
        self.local_override = local_player
        self.bob = None
        self.cards = cards or {}
        self.turn = 0
        self.phase = "HERO_SELECT"
        self.stack = []
        self.seq = 0
        self.last_record = record
        self.last_snapshot = None
        self.last_state_hash = None
        self.last_shop_hash = None
        self.entity_cache = {}
        self.attachments = {}
        self.pending_choice = None
        self.pending_reorder = None
        self.chosen_id = None
        self.options = []
        self.option_id = None
        self.options_dirty = False
        self.dirty = True
        self.is_bg = False
        self.ended = False
        start = f"{date or 'unknown-date'}T{record['time']}"
        match_id = hashlib.sha256(f"{source}:{start}:{record['line']}".encode()).hexdigest()[:16]
        self.data = {
            "schemaVersion": 1, "loggerVersion": __version__,
            "match": {"id": match_id, "serverMatchId": None, "startedAt": start,
                      "timeBasis": "client-local; date from source folder or --date; no assumed UTC",
                      "source": source, "gameType": None, "build": None, "region": None,
                      "mmrBefore": None, "mmrAfter": None, "localPlayerId": local_player,
                      "hero": None, "availableTribes": None, "bannedTribes": None},
            "turns": [], "snapshots": {}, "entityStates": {}, "optionSets": {}, "rawEventCounts": {},
            "result": {"status": "in_progress", "placement": None, "endedAt": None},
            "quality": {"warnings": [], "limitations": [
                "Unobserved information is null, never a simulated fact.",
                "Lobby boards are only visible while fighting; lobby average board growth is not measurable.",
                "No win probabilities, MMR, region or tribe bans without an additional source.",
                "Only state before an action may be used for decision evaluation.",
                "Shop updates inside a resolving block may be transient, not actionable.",
                "Duos teammates and special memory-only shop UI are not supported.",
            ]},
        }
        self.current_turn()

    def warning(self, message):
        if message not in self.data["quality"]["warnings"]:
            self.data["quality"]["warnings"].append(message)

    def current_turn(self):
        if not self.data["turns"] or self.data["turns"][-1]["turn"] != self.turn:
            self.data["turns"].append({"turn": self.turn, "startState": None, "events": [],
                                       "shopSnapshots": [], "decisionSnapshots": [], "combat": None})
            self.last_shop_hash = None
        return self.data["turns"][-1]

    def resolve(self, ref):
        if not ref:
            return None
        eid = ref.get("id")
        name = ref.get("name")
        if not eid and name:
            eid = self.names.get(name)
            if not eid and name == "GameEntity":
                eid = self.game_id
        if not eid:
            return None
        entity = self.entities.setdefault(eid, {"entityId": eid, "cardId": "", "name": None,
                                                 "tags": {}, "observedAtLine": self.last_record["line"]})
        if ref.get("cardId"):
            entity["cardId"] = ref["cardId"]
        if name and name not in ("UNKNOWN ENTITY", "UNKNOWN HUMAN PLAYER"):
            entity["name"] = name
            self.names[name] = eid
        # Bracket fields supply identity/visibility when a log starts mid-match. Tags remain authoritative.
        for key, tag in (("zone", "ZONE"), ("position", "ZONE_POSITION"), ("controller", "CONTROLLER")):
            if ref.get(key) is not None and tag not in entity["tags"]:
                entity["tags"][tag] = ref[key]
        return entity

    def player_entity(self, player=None):
        player = self.local if player is None else player
        return next((e for e in self.entities.values() if e.get("role") == "player"
                     and e["tags"].get("PLAYER_ID") == player), None)

    def hero_entity(self, player=None):
        player = self.local if player is None else player
        p = self.player_entity(player)
        if p and p["tags"].get("HERO_ENTITY") in self.entities:
            return self.entities[p["tags"]["HERO_ENTITY"]]
        candidates = [e for e in self.entities.values() if e["tags"].get("CARDTYPE") == "HERO"
                      and e["tags"].get("ZONE") == "PLAY" and e["tags"].get("CONTROLLER") == player]
        return candidates[0] if len(candidates) == 1 else None

    def determine_players(self):
        players = [e for e in self.entities.values() if e.get("role") == "player"]
        bob = next((p for p in players if p["tags"].get("BACON_DUMMY_PLAYER") == 1), None)
        if bob:
            self.bob = bob["tags"]["PLAYER_ID"]
            self.is_bg = True
            humans = [p for p in players if p is not bob]
            if len(humans) == 1 and self.local_override is None:
                self.local = humans[0]["tags"]["PLAYER_ID"]
        self.data["match"]["localPlayerId"] = self.local

    def card_view(self, e, attached=True):
        t = e["tags"]
        db = self.cards.get(e["cardId"], {})
        max_hp = t.get("HEALTH")
        tribes = db.get("races") or ([db["race"]] if db.get("race") else [])
        if not tribes and t.get("CARDRACE"):
            tribes = [t["CARDRACE"]]
        result = {"entityId": e["entityId"], "cardId": e["cardId"] or None,
                  "name": db.get("name") or e["name"], "type": t.get("CARDTYPE", db.get("type")),
                  "position": t.get("ZONE_POSITION"), "tavernTier": t.get("TECH_LEVEL", db.get("techLevel")),
                  "tribes": tribes or None, "attack": t.get("ATK"),
                  "health": max_hp - t.get("DAMAGE", 0) if isinstance(max_hp, int) else None,
                  "maxHealth": max_hp, "baseAttack": db.get("attack"), "baseHealth": db.get("health"),
                  "cost": t.get("COST"), "golden": t.get("PREMIUM") == 1 if "PREMIUM" in t else None,
                  "keywords": [k for k in KEYWORDS if t.get(k) == 1],
                  "text": db.get("text"), "statDuration": "unknown", "rawTags": dict(t),
                  "mechanics": mechanics(t), "enchantments": []}
        if attached:
            result["enchantments"] = [self.card_view(self.entities[aid], False)
                                      for aid in sorted(self.attachments.get(e["entityId"], set()))
                                      if self.entities[aid]["tags"].get("ZONE") not in ("GRAVEYARD", "REMOVEDFROMGAME")]
            gift = self.entities.get(t.get("DARK_GIFT_ENTITY"))
            if gift:
                result["darkGift"] = self.card_view(gift, False)
        return result

    def revision(self, e):
        if e is None:
            return None
        view = self.card_view(e)
        key = fingerprint(view)
        cached = self.entity_cache.get(e["entityId"])
        if cached and cached[0] == key:
            return cached[1]
        revision = f"e{e['entityId']}v{cached[2] + 1 if cached else 1}"
        self.entity_cache[e["entityId"]] = (key, revision, cached[2] + 1 if cached else 1)
        self.data["entityStates"][revision] = view
        return revision

    def state(self):
        self.determine_players()
        player = self.player_entity()
        hero = self.hero_entity()
        pt = player["tags"] if player else {}
        ht = hero["tags"] if hero else {}
        gold = pt.get("RESOURCES")
        remaining = gold + pt.get("TEMP_RESOURCES", 0) - pt.get("RESOURCES_USED", 0) if isinstance(gold, int) else None
        play = [e for e in self.entities.values() if e["tags"].get("ZONE") == "PLAY"]
        mine = [e for e in play if self.local is not None and e["tags"].get("CONTROLLER") == self.local]
        enemy = [e for e in play if self.bob is not None and e["tags"].get("CONTROLLER") == self.bob]
        def ordered(items):
            return [self.revision(e) for e in sorted(items, key=lambda e: (e["tags"].get("ZONE_POSITION", 0), e["entityId"]))]
        def minions(items):
            return [e for e in items if e["tags"].get("CARDTYPE") == "MINION" and e["tags"].get("ZONE_POSITION", 0) > 0]
        shop = [e for e in enemy if e["tags"].get("CARDTYPE") in ("MINION", "BATTLEGROUND_SPELL")
                and e["tags"].get("ZONE_POSITION", 0) > 0]
        buttons = [e for e in mine if "Button" in e["cardId"]]
        upgrade = next((e for e in buttons if action_kind(e["cardId"], e["tags"]) == "TAVERN_UPGRADE"), None)
        frozen_values = [e["tags"].get("FROZEN") for e in shop]
        frozen = any(v == 1 for v in frozen_values) if frozen_values else None
        powers = [e for e in mine if e["tags"].get("CARDTYPE") == "HERO_POWER" and e not in buttons
                  and not e["cardId"].startswith("TB_BaconShop_Drag")]
        lobby = [e for e in self.entities.values() if e["tags"].get("CARDTYPE") == "HERO"
                 and "PLAYER_LEADERBOARD_PLACE" in e["tags"]]
        game = self.entities.get(self.game_id, {}).get("tags", {})
        return {"turn": self.turn, "phase": self.phase, "hp": ht.get("HEALTH", 0) - ht.get("DAMAGE", 0) if "HEALTH" in ht else None,
                "armor": ht.get("ARMOR"), "maxHp": ht.get("HEALTH"), "tavernTier": ht.get("PLAYER_TECH_LEVEL", pt.get("PLAYER_TECH_LEVEL")),
                "gold": gold, "remainingGold": remaining, "upgradeCost": upgrade["tags"].get("COST") if upgrade else None,
                "hero": self.revision(hero), "heroPowers": ordered(powers), "buttons": ordered(buttons),
                "board": ordered(minions(mine)),
                "hand": ordered(e for e in self.entities.values() if e["tags"].get("ZONE") == "HAND"
                                and self.local is not None and e["tags"].get("CONTROLLER") == self.local),
                "shop": ordered(shop) if self.phase == "RECRUIT" else [],
                "shopKnown": self.phase == "RECRUIT" and self.bob is not None,
                "frozen": frozen if self.phase == "RECRUIT" else None,
                "opponentHero": self.revision(self.hero_entity(self.bob)) if self.bob else None,
                "opponentBoard": ordered(minions(enemy)) if self.phase == "COMBAT" else [],
                "nextOpponentPlayerId": pt.get("NEXT_OPPONENT_PLAYER_ID"), "lobbyHeroes": ordered(lobby),
                "lobbyBoardCoverage": "current opponent only; no lobby board average",
                "season": {"gameTags": mechanics(game), "playerTags": mechanics(pt),
                           "entities": ordered(e for e in mine if e["tags"].get("CARDTYPE") in ("BATTLEGROUND_TRINKET", "BATTLEGROUND_QUEST_REWARD"))},
                "choices": deepcopy(self.pending_choice), "options": self.option_id}

    def snapshot(self, reason, boundary=False, force_shop=False):
        s = self.state()
        state_hash = fingerprint(s)
        if state_hash == self.last_state_hash:
            sid = self.last_snapshot
        else:
            sid = f"s{len(self.data['snapshots']) + 1}"
            self.data["snapshots"][sid] = {"id": sid, "sequence": self.seq,
                "timestamp": self.last_record.get("timestamp", self.last_record["time"]), "sourceLine": self.last_record["line"], **s}
            self.last_snapshot, self.last_state_hash = sid, state_hash
        turn = self.current_turn()
        # Keep complete option observations even when the shop itself did not change.
        # The review exporter needs these to distinguish actionable states from hydration.
        if boundary and reason in ("available_options", "before_action", "after_action", "before_reorder", "before_choice"):
            row = {"state": sid, "sequence": self.seq, "reason": reason,
                   "decisionBoundary": True, "transient": False}
            if not turn["decisionSnapshots"] or turn["decisionSnapshots"][-1] != row:
                turn["decisionSnapshots"].append(row)
        if boundary and self.phase == "RECRUIT" and not turn["events"]:
            turn["startState"] = sid
        shop_hash = fingerprint([s["shop"], s["frozen"], s["tavernTier"], s["choices"]])
        if self.phase == "RECRUIT" and (shop_hash != self.last_shop_hash or force_shop):
            turn["shopSnapshots"].append({"state": sid, "sequence": self.seq, "reason": reason,
                                         "decisionBoundary": boundary, "transient": bool(self.stack) and not boundary})
            self.last_shop_hash = shop_hash
        self.dirty = False
        return sid

    def event(self, kind, before, after=None, **fields):
        e = {"id": f"a{sum(len(t['events']) for t in self.data['turns']) + 1}", "sequence": self.seq,
             "timestamp": self.last_record.get("timestamp", self.last_record["time"]), "sourceLine": self.last_record["line"],
             "turn": self.turn, "phase": self.phase, "action": kind,
             "stateBefore": before, "stateAfter": after, "evidence": "observed", **fields}
        self.current_turn()["events"].append(e)
        return e

    def flush_boundary(self):
        if self.options_dirty:
            self.commit_options()
            self.options_dirty = False
            self.snapshot("available_options", boundary=True)
        if self.dirty and self.is_bg and self.phase != "COMBAT":
            self.snapshot("state_update")

    def commit_options(self):
        key = "o" + fingerprint(self.options)[:16]
        self.data["optionSets"][key] = deepcopy(self.options)
        self.option_id = key
        if self.pending_reorder:
            event, eid, position = self.pending_reorder
            if self.entities[eid]["tags"].get("ZONE_POSITION") == position:
                event["stateAfter"] = self.snapshot("reorder_confirmed")
                event["status"] = "confirmed_at_next_options"
            self.pending_reorder = None

    def close_block(self, inferred=False):
        block = self.stack.pop()
        if block.get("heroHit"):
            hit = block["heroHit"]
            target = self.entities[hit["targetId"]]
            t = target["tags"]
            after = t.get("HEALTH", 0) - t.get("DAMAGE", 0) + t.get("ARMOR", 0)
            c = self.current_turn()["combat"]
            c["damageTaken"] = max(0, hit["before"] - after) if hit["side"] == "local" else 0
            c["damageDealt"] = max(0, hit["before"] - after) if hit["side"] == "opponent" else 0
            c["result"] = "loss" if hit["side"] == "local" else "win"
            c["resultEvidence"] = "hero_attack_block" if not inferred else "hero_attack_block_boundary_inferred"
        if self.phase == "COMBAT" and not block["event"]: return
        after = self.snapshot("after_action" if block["event"] else "effect_resolved",
                              boundary=bool(block["event"]), force_shop=bool(block["event"]))
        if event := block["event"]:
            event["stateAfter"] = after
            event["status"] = "boundary_inferred" if inferred else "resolved"
            event["endSourceLine"] = self.last_record["line"]
            a = self.data["snapshots"][after]["remainingGold"]
            b = self.data["snapshots"][event["stateBefore"]]["remainingGold"]
            event["goldDelta"] = a - b if a is not None and b is not None else None

    def hero_hit(self, block, target):
        actor = self.entities.get(block.get("actorId"))
        if not actor or not target or actor["tags"].get("CARDTYPE") != "HERO" or target["tags"].get("CARDTYPE") != "HERO": return
        t = target["tags"]
        if t.get("HEALTH") is None: return
        side = "local" if t.get("CONTROLLER") == self.local else "opponent" if t.get("CONTROLLER") == self.bob else None
        if side:
            block["heroHit"] = {"targetId": target["entityId"], "side": side,
                                "before": t["HEALTH"] - t.get("DAMAGE", 0) + t.get("ARMOR", 0)}

    def consume(self, r):
        # Finish option lists before the action consumes them; no future information leaks backwards.
        if r["kind"] not in ("option", "options_start") and self.options_dirty:
            self.commit_options()
            self.snapshot("available_options", boundary=True)
            self.options_dirty = False
        self.seq += 1
        self.last_record = r
        counts = self.data["rawEventCounts"]
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        kind = r["kind"]
        if kind == "entity":
            e = self.resolve(r["entity"])
            if e:
                if r.get("change") == "CHANGE_ENTITY":
                    # A transform has new base tags; subsequent tags update the known live entity.
                    e["cardId"] = r["entity"].get("cardId", "")
                e["role"] = r["role"]
                if r["role"] == "game": self.game_id = e["entityId"]; self.names["GameEntity"] = self.game_id
                if "playerId" in r: e["tags"]["PLAYER_ID"] = r["playerId"]
        elif kind == "player_name":
            p = self.player_entity(r["playerId"])
            if p: p["name"] = r["name"]; self.names[r["name"]] = p["entityId"]
        elif kind == "metadata":
            values = r["values"]
            if "BuildNumber" in values: self.data["match"]["build"] = values["BuildNumber"]
            gt = values.get("GameType")
            if gt:
                self.data["match"]["gameType"] = gt
                self.is_bg = "BATTLEGROUNDS" in gt
                if "DUO" in gt: self.warning("Duos is not supported: treat boards/opponents as partial.")
        elif kind == "tag":
            self.on_tag(r)
        elif kind == "block_start":
            # Some client builds omit outer BLOCK_END records. Indentation of the next block
            # gives a safe boundary, but label it inferred rather than claiming exact completion.
            while self.stack and self.stack[-1]["depth"] >= r.get("depth", 0):
                self.warning("Missing BLOCK_END recovered using next block indentation; affected actions are boundary_inferred.")
                self.close_block(inferred=True)
            self.flush_boundary()
            actor = self.resolve(r["entity"])
            target = self.resolve(r["target"])
            before = self.snapshot("before_action" if r["blockType"] == "PLAY" else "before_effect",
                                   boundary=r["blockType"] == "PLAY", force_shop=r["blockType"] == "PLAY") if self.phase != "COMBAT" else None
            block = {"type": r["blockType"], "event": None, "depth": r.get("depth", 0)}
            if actor and r["blockType"] == "PLAY" and self.phase == "RECRUIT" and actor["tags"].get("CONTROLLER") == self.local and not any(b["event"] for b in self.stack):
                action = action_kind(actor["cardId"], actor["tags"])
                if action == "FREEZE_TOGGLE":
                    frozen = self.data["snapshots"][before]["frozen"]
                    action = "UNFREEZE" if frozen else "FREEZE" if frozen is not None else "FREEZE_TOGGLE"
                block["event"] = self.event(action, before, actor=self.revision(actor), target=self.revision(target),
                    cost=actor["tags"].get("COST"), goldDelta=None, status="pending")
            elif r["blockType"] == "ATTACK" and self.phase == "COMBAT":
                self.capture_combat("first_attack_fallback", before)
                combat = self.current_turn()["combat"]
                attack = {"sequence": self.seq, "timestamp": r.get("timestamp", r["time"]), "sourceLine": r["line"],
                          "attacker": self.revision(actor), "target": self.revision(target)}
                combat["events"].append({"type": "ATTACK", **attack})
                block["attack"] = combat["events"][-1]
                block["actorId"] = actor["entityId"] if actor else None
                self.hero_hit(block, target)
                if combat["firstAttacker"] is None:
                    combat["firstAttacker"] = attack["attacker"]
            self.stack.append(block)
        elif kind == "block_end":
            if not self.stack:
                self.warning("Unmatched BLOCK_END: source may be truncated or format changed.")
            else:
                self.close_block()
        elif kind == "options_start":
            self.options = []
            self.options_dirty = True
        elif kind == "option":
            e = self.resolve(r["entity"])
            self.options.append({"entity": self.revision(e), "error": r["error"], "optionIndex": r.get("optionIndex")})
            self.options_dirty = True
        elif kind == "send_option":
            values = r.get("values", {})
            option = next((o for o in self.options if o.get("optionIndex") == values.get("selectedOption")), None)
            card = self.data["entityStates"].get(option["entity"], {}) if option else {}
            pos = values.get("selectedPosition", 0)
            if card.get("type") == "MINION" and card.get("rawTags", {}).get("ZONE") == "PLAY" and pos > 0 and self.phase == "RECRUIT":
                before = self.snapshot("before_reorder", boundary=True)
                event = self.event("REORDER", before, actor=option["entity"], toPosition=pos,
                                   evidence="observed_send_option", status="requested")
                self.pending_reorder = (event, card["entityId"], pos)
        elif kind.startswith("choice_"):
            self.on_choice(r)
        self.dirty = True

    def on_tag(self, r):
        tag, value = r["tag"], r["value"]
        e = self.resolve(r["entity"])
        # In BG the dummy player's display name changes with its hero. HERO_ENTITY is a
        # player tag; map it by the referenced hero's controller, not by a mutable name.
        if tag == "HERO_ENTITY" and "name" in r["entity"]:
            hero = self.entities.get(value)
            owner = self.player_entity(hero["tags"].get("CONTROLLER")) if hero else None
            if owner:
                e = owner
                self.names[r["entity"]["name"]] = owner["entityId"]
        if not e:
            self.warning("Unresolved named entity in tag changes; inspect events.jsonl / player mapping.")
            return
        prev = e["tags"].get(tag)
        if prev == value: return
        if tag == "HERO_ENTITY" and self.phase == "COMBAT" and e is self.player_entity(self.bob):
            new_hero = self.entities.get(value, {})
            if new_hero.get("cardId", "").startswith("TB_BaconShopBob") and self.current_turn()["combat"]:
                self.finish_combat()  # before the opponent is restored to Bob
        if tag == "TURN" and e["entityId"] == self.game_id and not r.get("initial"):
            if self.phase == "COMBAT": self.finish_combat()
            self.flush_boundary()
            self.turn = (int(value) + 1) // 2
            self.phase = "RECRUIT" if int(value) % 2 else "COMBAT"
            self.options = []
            self.current_turn()
        before = None
        if tag == "ZONE_POSITION" and prev is not None and self.phase == "RECRUIT" and not self.stack and not self.pending_reorder and e["tags"].get("ZONE") == "PLAY" and e["tags"].get("CONTROLLER") == self.local and e["tags"].get("CARDTYPE") == "MINION":
            before = self.snapshot("before_position_change")
        e["tags"][tag] = value
        if tag == "ATTACHED":
            self.attachments.get(prev, set()).discard(e["entityId"])
            self.attachments.setdefault(value, set()).add(e["entityId"])
        self.determine_players()
        if self.phase == "COMBAT" and tag == "DEFENDING" and value == 1:
            attack_block = next((b for b in reversed(self.stack) if "attack" in b), None)
            if attack_block:
                attack_block["attack"]["target"] = self.revision(e)
                self.hero_hit(attack_block, e)
        if before:
            self.event("REORDER", before, self.snapshot("after_position_change"), actor=self.revision(e),
                       evidence="inferred_from_position_change", fromPosition=prev, toPosition=value)
        if tag in ("2022", "3533") and prev == 1 and value == 0 and self.phase == "COMBAT":
            # 3533 ends board setup; 2022 ends start-of-combat effects. Prefer earliest setup boundary.
            self.capture_combat(f"setup_tag_{tag}")
        if self.phase == "COMBAT" and self.current_turn()["combat"]:
            c = self.current_turn()["combat"]
            event_type = None
            if tag == "DIVINE_SHIELD" and prev == 1 and value == 0: event_type = "DIVINE_SHIELD_LOST"
            if tag == "ZONE" and value == "GRAVEYARD": event_type = "DEATH"
            if tag == "ZONE" and value == "PLAY" and not r.get("initial"): event_type = "ENTER_PLAY"
            if event_type: c["events"].append({"type": event_type, "sequence": self.seq, "entity": self.revision(e), "sourceLine": r["line"]})
        if tag == "PLAYSTATE" and value in ("WON", "LOST", "TIED", "CONCEDED", 4, 5, 6, 8) and e is self.player_entity():
            self.finish("completed")
        if tag == "STATE" and value in ("COMPLETE", 3) and e["entityId"] == self.game_id:
            self.finish("completed")
        if self.ended and tag == "PLAYER_LEADERBOARD_PLACE":
            self.update_result()

    def on_choice(self, r):
        if r["kind"] == "choice_header":
            if r["chosen"]:
                self.chosen_id = r["choiceId"]
            else:
                self.pending_choice = {"id": r["choiceId"], "source": None, "offered": [], "offeredIndices": [], "header": r["raw"]}
        elif r["kind"] == "choice_source" and self.pending_choice:
            self.pending_choice["source"] = self.revision(self.resolve(r["entity"]))
        elif r["kind"] == "choice_item":
            e = self.resolve(r["entity"])
            if not r["chosen"] and self.pending_choice:
                indexed = dict(zip(self.pending_choice['offeredIndices'],self.pending_choice['offered']))
                indexed[r['index']] = self.revision(e)
                self.pending_choice['offeredIndices'] = sorted(indexed)
                self.pending_choice['offered'] = [indexed[i] for i in self.pending_choice['offeredIndices']]
                self.snapshot("choice_offered", boundary=True)
            elif r["chosen"]:
                # SendChoices and DebugPrintEntitiesChosen can report the same decision twice.
                key = (self.chosen_id, e["entityId"] if e else None)
                if key == getattr(self, "last_choice_key", None): return
                self.last_choice_key = key
                before = self.snapshot("before_choice", boundary=True)
                self.pending_choice = None
                self.event("CHOOSE", before, self.snapshot("choice_submitted"),
                           target=self.revision(e), choiceId=self.chosen_id,
                           status="submitted; effects may occur in subsequent blocks")

    def capture_combat(self, method, sid=None):
        turn = self.current_turn()
        if turn["combat"]: return
        sid = sid or self.snapshot("combat_start")
        s = self.data["snapshots"][sid]
        turn["combat"] = {"startState": sid, "captureMethod": method,
                          "startIsExact": method == "setup_tag_3533",
                          "endState": None, "firstAttacker": None, "events": [],
                          "result": "unknown", "damageTaken": None, "damageDealt": None,
                          "lethal": None, "winProbability": None,
                          "opponentHero": s["opponentHero"]}
        if method == "first_attack_fallback":
            self.warning("Some combat boards were captured at first attack, after possible start-of-combat effects.")

    def finish_combat(self):
        if not self.current_turn()["combat"]:
            self.capture_combat("end_only_incomplete")
            self.warning("Combat start boundary missing; at least one combat has only an end-state fallback.")
        c = self.current_turn()["combat"]
        if c["endState"]: return
        c["endState"] = self.snapshot("combat_end")
        start = self.data["snapshots"][c["startState"]]
        end = self.data["snapshots"][c["endState"]]
        def effective(s, enemy=False):
            if enemy:
                hero = self.data["entityStates"].get(s["opponentHero"], {})
                hp, armor = hero.get("health"), hero.get("rawTags", {}).get("ARMOR")
            else: hp, armor = s["hp"], s["armor"]
            return hp + (armor or 0) if hp is not None else None
        if not c.get("resultEvidence"):
            # Only the local persistent hero provides a safe delta fallback. Opponent armor/health
            # may be reset to Bob's defaults before HERO_ENTITY changes, so never subtract that.
            a, b = effective(start), effective(end)
            c["damageTaken"] = max(0, a-b) if a is not None and b is not None else None
            c["damageDealt"] = None
            c["result"] = "loss" if c["damageTaken"] else "unknown"
            c["resultEvidence"] = "local_hero_delta_fallback; opponent damage unknown"
        c["lethal"] = end["hp"] <= 0 if end["hp"] is not None else None

    def update_result(self):
        hero = self.hero_entity()
        if hero:
            self.data["match"]["hero"] = self.revision(hero)
            placement = hero["tags"].get("PLAYER_LEADERBOARD_PLACE")
            if self.ended and isinstance(placement, int) and 1 <= placement <= 8:
                self.data["result"]["placement"] = placement

    def finish(self, status="incomplete"):
        self.flush_boundary()
        if self.phase == "COMBAT": self.finish_combat()
        self.ended = status == "completed"
        self.data["result"]["status"] = status
        self.data["result"]["endedAt"] = self.last_record.get("timestamp", self.last_record["time"]) if self.ended else None
        if self.stack: self.warning("Open blocks remain; pending actions have no confirmed stateAfter.")
        if self.local is None: self.warning("Local player unresolved. Use --local-player with the actual PlayerID.")
        if not self.ended: self.warning("Capture is incomplete (EOF, restart, rotation, or interrupted game).")
        self.update_result()

    def checkpoint(self):
        self.flush_boundary()
        self.update_result()
        self.data["capturedAt"] = datetime.now(timezone.utc).isoformat()
        return self.data
