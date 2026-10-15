"""Decision-focused Markdown. No ranking/filtering of offered cards or player actions.

Compression is structural: effect-resolution states are excluded, identical shops
are referenced, choices are completed, and board/hand updates are written as deltas.
"""
import json

from .exporter import clean


BOUNDARIES = {"available_options", "before_action", "after_action", "before_reorder", "before_choice"}


def effect_definitions(effects):
    """JSON-native X templates and F overrides (never parse escaped Markdown)."""
    def flatten(value, prefix=''):
        flat = {}
        for k, v in value.items():
            k = 't' if k == 'tags' else k.removeprefix('TAG_SCRIPT_DATA_NUM_') if k.startswith('TAG_SCRIPT_DATA_NUM_') else k
            if k.isdigit() and prefix == 't.': k = 'S' + k
            path = prefix + k
            if isinstance(v, dict): flat.update(flatten(v, path + '.'))
            else: flat[path] = v
        return flat
    shapes, templates, instances = {}, {}, {}
    for key, alias in effects.items():
        value = flatten(json.loads(key))
        shape = value.get('cardId'), tuple(sorted(value))
        if shape not in shapes:
            xid = f'X{len(shapes)+1}'
            shapes[shape] = xid
            templates[xid] = value
        xid = shapes[shape]
        instances[alias] = {'template': xid, 'overrides': {k: v for k, v in value.items() if templates[xid][k] != v}}
    return templates, instances


def decision_points(data, turn):
    """Union of explicit decision observations and every action's before/after state.

    v0.1 logs may not retain every options boundary. Support them conservatively;
    never treat an arbitrary non-transient construction state as a player decision.
    """
    states = data["snapshots"]
    points = {}
    for row in turn.get("decisionSnapshots", []) + turn.get("shopSnapshots", []):
        if row["reason"] in BOUNDARIES and row.get("decisionBoundary", True) and not row.get("transient", False):
            points[(row["sequence"], row["state"])] = {"sequence": row["sequence"], "state": row["state"]}
    for event in turn["events"]:
        for field in ("stateBefore", "stateAfter"):
            sid = event.get(field)
            if sid in states:
                sequence = event["sequence"] if field == "stateBefore" else states[sid]["sequence"]
                points[(sequence, sid)] = {"sequence": sequence, "state": sid}
    return sorted(points.values(), key=lambda row: (row["sequence"], states[row["state"]]["sourceLine"]))


def choice_points(data, turn):
    """Do not emit the 1/3, 2/3 hydration prefixes as additional discover screens.

    A prefix is removed only within an uninterrupted run for the same choice ID.
    A selected subset or a later different set is retained as its own observation.
    """
    states = data["snapshots"]
    entries = list(decision_points(data, turn))
    # Includes hero selection and an unanswered choice on interrupted capture.
    entries.extend({"sequence": s["sequence"], "state": sid} for sid, s in states.items()
                   if s["turn"] == turn["turn"] and s.get("choices"))
    entries.sort(key=lambda row: row["sequence"])
    result = []
    for row in entries:
        choice = states[row["state"]].get("choices")
        if not choice or not choice.get("offered"): continue
        previous = result[-1] if result else None
        if previous:
            old = states[previous["state"]]["choices"]
            uninterrupted = not any(previous["sequence"] < e["sequence"] < row["sequence"] for e in turn["events"])
            if old["id"] == choice["id"] and uninterrupted and choice["offered"][:len(old["offered"])] == old["offered"]:
                result[-1] = row
                continue
            if old == choice: continue
        result.append(row)
    return result


class ReviewWriter:
    def __init__(self, data):
        self.data = data
        self.entities = data["entityStates"]
        self.states = data["snapshots"]
        self.cards = {}
        self.effects = {}
        self.card_details = {}
        self.names = {e['cardId']: e['name'] for e in self.entities.values() if e.get('cardId') and e.get('name')}
        self.metrics = {"actions": 0, "shopOccurrences": 0, "uniqueShops": 0, "choices": 0, "combats": 0}

    def effect(self, e):
        # Lifetime/controller/bookkeeping fields are not gameplay differences.
        tags = {k: v for k, v in e.get("rawTags", {}).items()
                if k not in {"ZONE", "ZONE_POSITION", "CONTROLLER", "ENTITY_ID", "ATTACHED", "CREATOR", "PLAYER_ID"}}
        value = {k: e[k] for k in ("cardId", "name", "text", "attack", "health", "keywords")
                 if e.get(k) not in (None, [], "")}
        if tags: value["tags"] = tags
        key = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if key not in self.effects: self.effects[key] = f"F{len(self.effects)+1}"
        return self.effects[key]

    def card(self, ref):
        e = self.entities.get(ref)
        if e is None: return "? (미관측)"
        identity = e.get("cardId") or f"unknown-entity-{e['entityId']}"
        if identity not in self.cards:
            self.cards[identity] = f"C{len(self.cards)+1}"
            self.card_details[identity] = {**e, 'name': self.names.get(identity, e.get('name'))}
        label = f"{self.cards[identity]}#{e['entityId']}"
        if e.get("attack") is not None or e.get("health") is not None:
            label += f" {clean(e.get('attack'))}/{clean(e.get('health'))}"
        facts = []
        defaults = self.card_details[identity]
        if e.get("tavernTier") != defaults.get("tavernTier"): facts.append(f"T{clean(e.get('tavernTier'))}")
        if e.get("golden") is not None: facts.append("황금" if e["golden"] else "일반")
        if e.get("cost") is not None: facts.append(f"COST={e['cost']}")
        facts.extend(e.get("keywords", []))
        tags = e.get("rawTags", {})
        for name in ("EXHAUSTED", "COOLDOWN", "CANT_PLAY", "HAS_ACTIVATE_POWER"):
            if tags.get(name) != defaults.get("rawTags", {}).get(name): facts.append(f"{name}={clean(tags.get(name))}")
        if e.get("tribes") != defaults.get("tribes"): facts.append("種=" + "/".join(map(str,e.get("tribes") or ['?'])))
        if e.get("maxHealth") is not None and e["maxHealth"] != e.get("health"): facts.append(f"maxHP={e['maxHealth']}")
        if facts: label += " [" + ",".join(facts) + "]"
        effects = [self.effect(x) for x in e.get("enchantments", [])]
        if e.get("darkGift"): effects.append("DarkGift:" + self.effect(e["darkGift"]))
        if e.get("mechanics"):
            mechanics = dict(e["mechanics"])
            # Pool membership is already represented by tier/tribes; retain other season data.
            mechanics = {k:v for k,v in mechanics.items() if not k.startswith("BACON_SUBSET_") and k != "IS_BACON_POOL_MINION"}
            if mechanics: effects.append(self.effect({"rawTags": mechanics}))
        if effects: label += " {" + ",".join(effects) + "}"
        return label

    def cards_line(self, refs):
        return " / ".join(self.card(ref) for ref in refs) or "∅ (빈 영역 또는 미관측; 수집 한계 참고)"

    @staticmethod
    def economy(s):
        return (f"HP {clean(s.get('hp'))}+방어도 {clean(s.get('armor'))} · "
                f"T{clean(s.get('tavernTier'))} · G{clean(s.get('remainingGold'))} · "
                f"업 {clean(s.get('upgradeCost'))} · 빙결 {clean(s.get('frozen'))}")

    def delta(self, label, previous, refs):
        current = [(self.entities[r]["entityId"], self.card(r)) for r in refs]
        if previous is None: return [f"{label}: " + self.cards_line(refs)], current
        if current == previous: return [], current
        old, new = dict(previous), dict(current)
        changes = [f"−#{eid}" for eid in old if eid not in new]
        changes += [("+" if eid not in old else "↻") + desc for eid, desc in current if old.get(eid) != desc]
        old_order, new_order = [x[0] for x in previous], [x[0] for x in current]
        # Every order change is expressed, including shifted slots caused by buys/sells/plays.
        if old_order != new_order: changes.append("순서 " + (">".join(f"#{eid}" for eid in new_order) or "∅"))
        return [f"{label} Δ: " + "; ".join(changes)], current

    def render_turn(self, turn):
        lines = ["", f"## 턴 {turn['turn']}" + (" · 영웅 선택" if turn["turn"] == 0 else ""), ""]
        shops, choices = {}, {}
        active_shop = None
        previous_board = previous_hand = previous_powers = None
        if turn.get("startState"):
            lines.append("첫 행동 전: " + self.economy(self.states[turn["startState"]]))
        timeline = [(p["sequence"], 0, "state", p) for p in decision_points(self.data, turn)]
        timeline += [(p["sequence"], 1, "choice", p) for p in choice_points(self.data, turn)]
        timeline += [(e["sequence"], 2, "action", e) for e in turn["events"]]
        for event in turn['events']:
            after = self.states.get(event.get('stateAfter'))
            if after:
                seq = after['sequence']
                timeline.append((seq, -1 if seq > event['sequence'] else 3, 'after', event))
        for _, _, kind, obj in sorted(timeline, key=lambda row: (row[0], row[1])):
            if kind == 'after':
                # An inferred outer block may finish after a nested CHOOSE. Do not expose its
                # result immediately after the outer action, before that choice was made.
                s = self.states[obj['stateAfter']]
                updates, previous_board = self.delta('보드', previous_board, s['board']); lines.extend(updates)
                updates, previous_hand = self.delta('손패', previous_hand, s['hand']); lines.extend(updates)
            elif kind == "state":
                s = self.states[obj["state"]]
                if s["phase"] != "RECRUIT": continue
                signature = (tuple(self.card(r) for r in s["shop"]), s.get("frozen"), s.get("tavernTier"), s.get("shopKnown"))
                if signature == active_shop: continue
                self.metrics["shopOccurrences"] += 1
                active_shop = signature
                if signature not in shops:
                    qid = f"Q{turn['turn']}.{len(shops)+1}"
                    shops[signature] = qid
                    self.metrics["uniqueShops"] += 1
                    lines.extend([f"**상점 {qid}** · {self.economy(s)}", self.cards_line(s["shop"])])
                else: lines.append(f"**상점 {shops[signature]} 재등장** · {self.economy(s)}")
            elif kind == "choice":
                s = self.states[obj["state"]]; choice = s["choices"]
                signature = (choice["id"], tuple(self.card(r) for r in choice["offered"]))
                if signature in choices: continue
                did = f"D{choice['id']}.{len(choices)+1}"
                choices[signature] = did
                self.metrics["choices"] += 1
                lines.extend([f"**발견/선택 {did}** · G{clean(s.get('remainingGold'))}", self.cards_line(choice["offered"])])
            else:
                e = obj; before = self.states[e["stateBefore"]]; after = self.states.get(e.get("stateAfter"))
                self.metrics["actions"] += 1
                updates, previous_board = self.delta("보드", previous_board, before["board"]); lines.extend(updates)
                updates, previous_hand = self.delta("손패", previous_hand, before["hand"]); lines.extend(updates)
                updates, previous_powers = self.delta("영능", previous_powers, before.get("heroPowers", [])); lines.extend(updates)
                actor = self.card(e["actor"]) if e.get("actor") else ""
                target = " → " + self.card(e["target"]) if e.get("target") else ""
                shop = f" · {shops[active_shop]}" if active_shop in shops else ""
                cost = f" · 비용 {e['cost']}" if e.get("cost") is not None else ""
                marker = " †" if e.get("status") == "boundary_inferred" else ""
                if after is None: marker += " [완료 미확인]"
                if e.get("evidence") != "observed": marker += f" [{e.get('evidence')}]"
                if e.get("toPosition") is not None: target += f" → 자리 {e['toPosition']}"
                lines.append(f"- **{e['id']} {e['action']}**{marker} {actor}{target} · "
                             f"G{clean(before.get('remainingGold'))}→{clean(after.get('remainingGold')) if after else '?'}{cost}{shop}")
        if c := turn.get("combat"):
            self.metrics["combats"] += 1
            s = self.states[c["startState"]]
            enemy = self.entities.get(s.get("opponentHero"), {})
            et = enemy.get("rawTags", {})
            lines.extend(["", f"**전투** · {c['captureMethod']} · {self.economy(s)}",
                          "내 시작 보드(왼쪽→오른쪽): " + self.cards_line(s["board"]),
                          "상대: " + self.card(s.get("opponentHero")) +
                          f" · HP {clean(enemy.get('health'))}+방어도 {clean(et.get('ARMOR'))} · T{clean(et.get('PLAYER_TECH_LEVEL'))}",
                          "상대 시작 보드(왼쪽→오른쪽): " + self.cards_line(s["opponentBoard"]),
                          f"결과 **{c['result']}** · 받은 피해 {clean(c['damageTaken'])} · 준 피해 {clean(c['damageDealt'])} · "
                          f"치명상 {clean(c.get('lethal'))} · 근거 {c.get('resultEvidence','?')}"])
        return lines

    def render(self):
        m = self.data["match"]
        hero = self.entities.get(m.get("hero"), {})
        body = []
        for turn in self.data["turns"]:
            if turn["events"] or turn["shopSnapshots"] or turn.get('decisionSnapshots') or turn.get("combat") or choice_points(self.data,turn):
                body.extend(self.render_turn(turn))
        lines = [f"# AI 복기 · {clean(hero.get('name') or hero.get('cardId'))} · {clean(self.data['result']['placement'])}위", "",
                 f"경기 {m['id']} · {m['startedAt']} → {self.data['result']['endedAt']} · {self.data['result']['status']}",
                 f"보존: 행동 {self.metrics['actions']}개 · 상점 관측 {self.metrics['shopOccurrences']}회"
                 f"(서로 다른 상점 {self.metrics['uniqueShops']}개) · 선택 목록 {self.metrics['choices']}개 · 전투 {self.metrics['combats']}회", "",
                 "선택 화면/행동 경계의 상점만 포함. 효과 처리 중간 상태는 audit에 보존. †=종료 경계 추론; ?=미관측.",
                 "C=아래 카드 사전, #=같은 엔티티 식별, F=효과 사전. 보드/손패 Δ: +추가, −제거, ↻변경. 생략된 상태는 직전과 같음.",
                 "각 행동은 바로 앞 상점과 보드/손패로 평가. 이후 결과·상대 보드를 당시 알고 있었다고 가정하지 말 것.",
                 "COST는 엔티티 태그이며 구매 가격과 다를 수 있음. 황금/키워드/종족/효과는 관측된 값만 수록.",
                 "전체 로비 성장 평균·승률은 미관측. 스탯 합계만으로 승패나 EV를 단정하지 말 것.", ""]
        lines.extend(f"- 수집 주의: {warning}" for warning in self.data["quality"]["warnings"])
        lines.extend(body)
        lines.extend(["", "## 카드 사전", ""])
        for cid, alias in self.cards.items():
            e = self.card_details[cid]
            extra = f" · T{clean(e.get('tavernTier'))} · 種={'/'.join(map(str,e.get('tribes') or ['?']))}"
            flags = {k:e.get('rawTags',{})[k] for k in ("EXHAUSTED", "COOLDOWN", "CANT_PLAY", "HAS_ACTIVATE_POWER") if k in e.get('rawTags',{})}
            if flags: extra += " · 기본 상태 " + json.dumps(flags, ensure_ascii=False, separators=(',',':'))
            if e.get("baseAttack") is not None or e.get("baseHealth") is not None:
                extra += f" · 기본 {clean(e.get('baseAttack'))}/{clean(e.get('baseHealth'))}"
            if e.get("text"): extra += " · " + clean(e["text"])
            lines.append(f"- {alias}: {clean(e.get('name') or '?')} [{cid}]{extra}")
        if self.effects:
            lines.extend(["", "## 효과 사전", "", "F는 X 템플릿에 표시된 속성만 덮어쓴 값. 영구/일시 여부는 미확정.",
                          "t=tags; t.S1~S99=TAG_SCRIPT_DATA_NUM_1~99. 나머지 속성명은 원본 그대로."])
            templates = {}
            template_lines = []
            instance_lines = []
            def flatten(value, prefix=""):
                flat = {}
                for k,v in value.items():
                    k = "t" if k == "tags" else k.removeprefix("TAG_SCRIPT_DATA_NUM_") if k.startswith("TAG_SCRIPT_DATA_NUM_") else k
                    if k.isdigit() and prefix == "t.": k = "S" + k
                    path = prefix + k
                    if isinstance(v, dict): flat.update(flatten(v,path+"."))
                    else: flat[path] = v
                return flat
            for key, alias in self.effects.items():
                value = flatten(json.loads(key))
                shape = (value.get("cardId"), tuple(sorted(value)))
                if shape not in templates:
                    xid = f"X{len(templates)+1}"; templates[shape] = (xid,value)
                    template_lines.append(f"- {xid}: " + clean(json.dumps(value,ensure_ascii=False,separators=(',',':'))))
                xid, base = templates[shape]
                diff = {k:v for k,v in value.items() if base[k] != v}
                instance_lines.append(f"- {alias}: {xid}" + (" + " + clean(json.dumps(diff,ensure_ascii=False,separators=(',',':'))) if diff else ""))
            lines.extend(template_lines + instance_lines)
        lines.extend(["", "## 수집 한계", *[f"- {x}" for x in self.data["quality"]["limitations"]], ""])
        return "\n".join(lines)


def review_markdown(data, mode='compact', dictionary_name='match.dictionary.json'):
    from .compact_review import export_review
    return export_review(data, mode, dictionary_name)[0]
