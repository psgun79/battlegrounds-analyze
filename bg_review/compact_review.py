"""Self-contained decision transcript; optional debug details live in a sidecar.

No card ranking, truncation, or line budget is used. Only proven UI reorders and
choice-free, consecutive targeted spells may be suppressed or combined.
"""
from collections import Counter
import json
import re

from .exporter import clean
from .review_exporter import ReviewWriter, decision_points, choice_points, effect_definitions
from .mechanics import MechanicsResolver, chosen_option, choice_number


KEYWORDS = {'DIVINE_SHIELD': 'DS', 'TAUNT': 'Taunt', 'REBORN': 'Reborn',
            'DEATHRATTLE': 'DR', 'WINDFURY': 'WF', 'VENOMOUS': 'Venomous',
            'POISONOUS': 'Poisonous', 'STEALTH': 'Stealth'}
BOOKKEEPING = {'ZONE', 'ZONE_POSITION', 'CONTROLLER', 'ENTITY_ID', 'ATTACHED',
               'CREATOR', 'CREATOR_DBID', 'PLAYER_ID'}
ECONOMY = ('hp', 'armor', 'tavernTier', 'remainingGold', 'upgradeCost', 'frozen')


def semantic_entity(e):
    """Ignore identity/location bookkeeping, never unknown gameplay tags."""
    value = {k: v for k, v in e.items() if k not in
             {'entityId', 'position', 'name', 'text', 'baseAttack', 'baseHealth',
              'rawTags', 'enchantments', 'darkGift'}}
    value['tags'] = {k: v for k, v in e.get('rawTags', {}).items() if k not in BOOKKEEPING}
    value['enchantments'] = [semantic_entity(x) for x in e.get('enchantments', [])]
    if e.get('darkGift'): value['darkGift'] = semantic_entity(e['darkGift'])
    return value


def buff_delta(before, after):
    """Lossless additive trace, not an inference about an effect's meaning.

    Only existing attachments' numeric script values may accompany stat gains.
    Their endpoints are rendered explicitly; unknown tags and structural changes
    are not safe to fold. Equal traces let the reader reconstruct each boundary.
    """
    for e in (before, after):
        if any(type(e.get(k)) is not int for k in ('attack', 'health', 'maxHealth')):
            return None
    def attachments(e):
        return [(x.get('entityId'), x.get('cardId'), x.get('rawTags', {}).get('CREATOR'),
                 x.get('rawTags', {}).get('CREATOR_DBID'), x.get('rawTags', {}).get('ATTACHED'))
                for x in e.get('enchantments', [])]
    if attachments(before) != attachments(after): return None
    changes = []
    def visit(a, b, path=()):
        if a == b: return True
        if isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys():
            return all(visit(a[k], b[k], (*path, k)) for k in sorted(a))
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            return all(visit(x, y, (*path, i)) for i, (x, y) in enumerate(zip(a, b)))
        allowed = (path in (('attack',), ('health',), ('maxHealth',), ('tags', 'ATK'), ('tags', 'HEALTH'))
                   or (len(path) == 4 and path[0] == 'enchantments'
                       and path[2] in ('tags', 'mechanics')
                       and re.fullmatch(r'TAG_SCRIPT_DATA_NUM_\d+', str(path[3]))))
        if not allowed or type(a) is not int or type(b) is not int or b < a: return False
        changes.append((path, b - a))
        return True
    if not visit(semantic_entity(before), semantic_entity(after)): return None
    for path, _ in changes:
        if len(path) == 4 and path[2] == 'mechanics':
            for e in (before, after):
                effect = e['enchantments'][path[1]]
                if effect['mechanics'][path[3]] != effect.get('rawTags', {}).get(path[3]): return None
    if changes and not any(path in (('attack',), ('health',)) for path, _ in changes): return None
    return tuple(changes)


class CompactReviewWriter(ReviewWriter):
    def __init__(self, data, dictionary_name='match.dictionary.json', catalog=None):
        super().__init__(data)
        self.resolver = MechanicsResolver(data,catalog)
        self.dictionary_name = dictionary_name
        self.observations = {}
        self.groups = []
        self.suppressed = []
        self.used_refs = set()
        self._fingerprints = {}
        self.ambiguous = set()
        self.encounters = {}
        for s in self.states.values():
            for refs in (s['board'] + s['hand'] + s['shop'], s.get('opponentBoard', []),
                         (s.get('choices') or {}).get('offered', [])):
                counts = Counter(self.base_name(self.entities[r]) for r in refs)
                self.ambiguous.update(k for k, n in counts.items() if n > 1)

    @staticmethod
    def identity(e):
        return e.get('cardId') or f"unknown-{e['entityId']}"

    def base_name(self, e):
        return self.names.get(self.identity(e)) or e.get('name') or self.resolver.cards.get(e.get('cardId'),{}).get('name') or e.get('cardId') or '이름 미관측'

    def name(self, ref):
        if ref not in self.entities: return '? (미관측)'
        e = self.entities[ref]
        name = clean(self.base_name(e))
        if self.base_name(e) in self.ambiguous or not e.get('cardId'): name += f"#{e['entityId']}"
        return name

    def card(self, ref, *, effects=True):
        if ref not in self.entities: return '? (미관측)'
        self.used_refs.add(ref)
        e = self.entities[ref]
        label = self.name(ref)
        if e.get('attack') is not None or e.get('health') is not None:
            label += f" {clean(e.get('attack'))}/{clean(e.get('health'))}"
        facts = [KEYWORDS.get(k, k) for k in e.get('keywords', [])]
        if e.get('golden'): facts.append('Golden')
        if e.get('tavernTier') is not None: facts.append(f"T{e['tavernTier']}")
        if e.get('cost') is not None: facts.append(f"cost={e['cost']}")
        if e.get('maxHealth') is not None and e['maxHealth'] != e.get('health'):
            facts.append(f"maxHP={e['maxHealth']}")
        tags = e.get('rawTags', {})
        if tags.get('CANT_PLAY'): facts.append('사용불가')
        if tags.get('COOLDOWN'): facts.append(f"쿨다운={tags['COOLDOWN']}")
        # HAS_ACTIVATE_POWER is also set on ordinary cards by this client; it is not
        # sufficient evidence to label every card as an available Activate button.
        if e.get('type') == 'HERO_POWER' and tags.get('EXHAUSTED'): facts.append('소진')
        if tags.get('FROZEN'): facts.append('Frozen')
        if facts: label += ' [' + ','.join(facts) + ']'
        names = self.effect_labels(e) if effects else []
        if names: label += ' {' + ', '.join(names) + '}'
        return label

    def effect_labels(self, entity):
        names = [clean(x) for x in self.resolver.short_effects(entity)]
        if parameters := self.resolver.parameter_summary(entity): names.append(parameters)
        return names

    def changed_card(self, before, after, *, repeated=False):
        """Full current core attributes, but only added/removed effect labels.

        These are observed labels, never a count of Magnetic applications. Hidden
        semantic changes remain explicitly unresolved instead of requiring a file.
        """
        oe, ne = self.entities[before], self.entities[after]
        a, b = self.card(before, effects=False), self.card(after, effects=False)
        old, new = self.effect_labels(oe), self.effect_labels(ne)
        changes = ['−' + x for x in old if x not in new] + ['+' + x for x in new if x not in old]
        if a == b:
            label = self.name(after)
        elif ((oe.get('attack'), oe.get('health')) != (ne.get('attack'), ne.get('health'))
              and self.name(before) == self.name(after)):
            label = f"{self.name(after)} {clean(oe.get('attack'))}/{clean(oe.get('health'))}→{b[len(self.name(after)):].lstrip()}"
        else:
            label = b + ' (상태 변경)'
        if changes:
            label += ' {효과Δ: ' + ', '.join(changes) + '}'
        elif a == b:
            # Preserve the existence of unrendered gameplay changes. Do not invent
            # their meaning, nor silently drop them as if the state were identical.
            tags = []
            ot, nt = oe.get('rawTags', {}), ne.get('rawTags', {})
            for key in sorted((ot.keys() | nt.keys()) - BOOKKEEPING):
                if ot.get(key) != nt.get(key):
                    tags.append(f'{key}:{clean(ot.get(key))}→{clean(nt.get(key))}')
            label += ' {태그Δ: ' + ', '.join(tags) + '}' if tags else ' (효과 상태 변경·세부 미해석)'
        if oe.get('tribes') != ne.get('tribes'):
            label += ' {종족: ' + '/'.join(oe.get('tribes') or ['?']) + '→' + '/'.join(ne.get('tribes') or ['?']) + '}'
        if repeated:
            label += f" (누적 +{ne['attack']-oe['attack']}/+{ne['health']-oe['health']})"
            effects = []
            for old, new in zip(oe.get('enchantments', []), ne.get('enchantments', [])):
                ot, nt = old.get('rawTags', {}), new.get('rawTags', {})
                keys = sorted(k for k in ot if k.startswith('TAG_SCRIPT_DATA_NUM_') and ot[k] != nt.get(k))
                if keys:
                    slots = '/'.join(k.replace('TAG_SCRIPT_DATA_NUM_', 'S') for k in keys)
                    values = '/'.join(str(ot[k]) for k in keys) + '→' + '/'.join(str(nt[k]) for k in keys)
                    effects.append(f"{new.get('cardId')}#{new.get('entityId', '?')} {slots} {values}")
            if effects: label += ' {부착 수치: ' + '; '.join(effects) + '}'
        return label

    def next_opponent(self, state):
        pid = state.get('nextOpponentPlayerId')
        if pid is None: return '다음 상대: ? (턴 시작 미관측)'
        matches = [self.entities[r] for r in state.get('lobbyHeroes', [])
                   if self.entities[r].get('rawTags', {}).get('PLAYER_ID') == pid]
        if len(matches) != 1: return f'다음 상대: player {pid} (이름 미확정)'
        enemy = matches[0]
        prior = self.encounters.get(enemy.get('cardId'))
        history = f'{prior}턴 전투 참조·현재 전장 아님' if prior is not None else '이전 직접 대전 기록 없음'
        return f'다음 상대: {clean(self.base_name(enemy))} ({history})'

    def combat_summary(self, combat, state):
        """Bounded opening evidence, explicitly not a complete combat replay."""
        events = combat.get('events', [])
        attacks = [e for e in events if e.get('type') == 'ATTACK']
        counts = Counter(e.get('type') for e in events)
        own = self.data['match'].get('localPlayerId')
        enemy_controllers = {self.entities[r].get('rawTags', {}).get('CONTROLLER')
                             for r in state.get('opponentBoard', [])} - {None, own}
        def unit(ref):
            e = self.entities.get(ref, {})
            controller = e.get('rawTags', {}).get('CONTROLLER')
            side = '내' if own is not None and controller == own else '상대' if controller in enemy_controllers else '?측'
            stats = f"{clean(e.get('attack'))}/{clean(e.get('health'))}"
            return f'{side} {self.name(ref)} {stats}'
        first = combat.get('firstAttacker')
        lines = [f"전투 관측: 선공 {unit(first) if first else '?'} · 공격 {len(attacks)}회/사망 {counts['DEATH']}회/천보 소멸 {counts['DIVINE_SHIELD_LOST']}회 (수집된 사건 수)"]
        if attacks:
            lines.append('첫 공격 최대 3회(각 공격 직전 관측; 전체 전투·중간 효과 생략): ' +
                         '; '.join(f"{i}. {unit(e.get('attacker'))} → {unit(e.get('target'))}" for i, e in enumerate(attacks[:3], 1)))
        return lines

    def cards_line(self, refs):
        return '; '.join(f'{i}. {self.card(r)}' for i, r in enumerate(refs, 1)) or '∅ (빈 영역/미관측)'

    def shop_text(self, refs, previous=None, previous_id=None):
        full = self.cards_line(refs)
        if previous is None or not previous_id: return full
        old = {self.entities[r]['entityId']: r for r in previous}
        new = {self.entities[r]['entityId']: r for r in refs}
        # Only same-shop removals/updates: every newly offered card and any actual
        # reorder gets a fresh full list. Surviving positions shift left in order.
        if not new or [eid for eid in old if eid in new] != list(new): return full
        parts = ['−' + self.name(r) for eid, r in old.items() if eid not in new]
        parts += [self.changed_card(old[eid], r) for eid, r in new.items()
                  if self.fingerprint(old[eid]) != self.fingerprint(r)]
        delta = f'Δ({previous_id}): ' + ('; '.join(parts) if parts else '같음')
        return delta if len(delta) < len(full) else full

    def fingerprint(self, ref):
        if ref not in self._fingerprints:
            self._fingerprints[ref] = json.dumps(semantic_entity(self.entities[ref]), sort_keys=True, ensure_ascii=False)
        return self._fingerprints[ref]

    def area(self, refs, ordered=True):
        values = [(self.entities[r]['entityId'], self.fingerprint(r)) for r in refs]
        return tuple(values if ordered else sorted(values))

    def shop_signature(self, s):
        return self.area(s['shop']), s.get('frozen'), s.get('tavernTier'), s.get('shopKnown')

    def observe(self, key, sid):
        self.observations[key] = sid
        s = self.states[sid]
        for zone in ('board', 'hand', 'shop', 'heroPowers', 'opponentBoard', 'lobbyHeroes', 'buttons'):
            self.used_refs.update(s.get(zone, []))
        self.used_refs.update(s.get('season', {}).get('entities', []))
        self.used_refs.update((s.get('choices') or {}).get('offered', []))
        self.used_refs.update(r for r in (s.get('hero'), s.get('opponentHero')) if r in self.entities)

    def plain_reorder(self, e, turn):
        if (e['action'] != 'REORDER' or e.get('phase') != 'RECRUIT'
                or e.get('status') != 'confirmed_at_next_options'
                or e.get('evidence') != 'observed_send_option' or not e.get('stateAfter')):
            return False
        before, after = self.states[e['stateBefore']], self.states[e['stateAfter']]
        # An overlapping gameplay action makes attribution uncertain; keep the reorder.
        if any(e['sequence'] < x['sequence'] < after['sequence'] and x['action'] != 'REORDER'
               for x in turn['events']): return False
        for r in before['board']:
            text = self.entities[r].get('text') or ''
            if re.search(r'adjacent|neighbor|left.?most|right.?most|양옆|인접|가장 왼쪽|가장 오른쪽', text, re.I):
                return False
        # Also inspect transient observations: an immediate positional effect that later
        # cancels out must not be mistaken for a harmless UI drag.
        candidates = [after] + [s for s in self.states.values()
                               if s['turn'] == before['turn'] and e['sequence'] < s['sequence'] < after['sequence']]
        for state in candidates:
            if any(before.get(k) != state.get(k) for k in (*ECONOMY, 'phase', 'choices', 'season')): return False
            if self.area(before['board'], False) != self.area(state['board'], False): return False
            for zone in ('hand', 'shop', 'heroPowers', 'buttons'):
                if self.area(before.get(zone, [])) != self.area(state.get(zone, [])): return False
        return True

    def batchable_spell(self, e):
        if e['action'] != 'SPELL_USE' or e.get('status') != 'resolved' or not e.get('target') or not e.get('actor'):
            return False
        if not e.get('stateAfter'): return False
        if e.get('evidence') not in ('observed', 'observed_send_option'): return False
        if self.entities[e['actor']].get('type') != 'SPELL': return False
        b, a = self.states[e['stateBefore']], self.states[e['stateAfter']]
        if b['phase'] != 'RECRUIT' or a['phase'] != 'RECRUIT': return False
        if any(b.get(k) != a.get(k) for k in (*ECONOMY, 'choices', 'season')): return False
        if b.get('choices'): return False
        if self.shop_signature(b) != self.shop_signature(a): return False
        if self.area(b.get('heroPowers', [])) != self.area(a.get('heroPowers', [])): return False
        if self.batch_context(b) != self.batch_context(a): return False
        actor_id = self.entities[e['actor']]['entityId']
        target_id = self.entities[e['target']]['entityId']
        if target_id not in [self.entities[r]['entityId'] for r in b['board']]: return False
        remaining_hand = [r for r in b['hand'] if self.entities[r]['entityId'] != actor_id]
        if len(remaining_hand) != len(b['hand']) - 1 or self.area(remaining_hand) != self.area(a['hand']): return False
        if [self.entities[r]['entityId'] for r in b['board']] != [self.entities[r]['entityId'] for r in a['board']]: return False
        for br, ar in zip(b['board'], a['board']):
            if buff_delta(self.entities[br], self.entities[ar]) is None: return False
        return True

    @staticmethod
    def batch_context(s):
        # Future/unknown snapshot fields default to blocking compression.
        return {k: v for k, v in s.items() if k not in
                {'id', 'sequence', 'timestamp', 'sourceLine', 'options', 'board', 'hand'}}

    def option_signature(self, s, consumed, *, only=None):
        oid = s.get('options')
        if oid is None: return None
        if oid not in self.data.get('optionSets', {}): return ('missing', oid)
        rows = []
        for row in self.data['optionSets'][oid]:
            entity = self.entities.get(row.get('entity'), {})
            if entity.get('entityId') in consumed: continue
            if only is not None and entity.get('entityId') != only: continue
            value = {k: v for k, v in row.items() if k not in ('entity', 'optionIndex')}
            value['entity'] = entity.get('entityId', row.get('entity'))
            rows.append(json.dumps(value, sort_keys=True))
        # Target rows repeat for each remaining copy of a spell; consuming a copy
        # changes multiplicity/option indices, not the available alternatives.
        return tuple(sorted(set(rows)))

    def can_join(self, previous, following, turn):
        if not self.batchable_spell(previous) or not self.batchable_spell(following): return False
        if self.entities[previous['actor']].get('cardId') != self.entities[following['actor']].get('cardId'): return False
        if self.fingerprint(previous['actor']) != self.fingerprint(following['actor']): return False
        if not self.entities[previous['actor']].get('cardId'): return False
        if self.entities[previous['target']]['entityId'] != self.entities[following['target']]['entityId']: return False
        if any(previous.get(k) != following.get(k) for k in ('evidence', 'cost', 'goldDelta')): return False
        def trace(e):
            before, after = self.states[e['stateBefore']], self.states[e['stateAfter']]
            return [buff_delta(self.entities[x], self.entities[y]) for x, y in zip(before['board'], after['board'])]
        if trace(previous) != trace(following): return False
        a, b = self.states[previous['stateAfter']], self.states[following['stateBefore']]
        if a['sequence'] > following['sequence']: return False
        if any(a.get(k) != b.get(k) for k in (*ECONOMY, 'choices', 'season')): return False
        for zone in ('board', 'hand', 'shop', 'heroPowers'):
            if self.area(a.get(zone, [])) != self.area(b.get(zone, [])): return False
        if self.batch_context(a) != self.batch_context(b): return False
        start = self.states[previous['stateBefore']]
        end = self.states[following['stateAfter']]
        consumed = {self.entities[e['actor']]['entityId'] for e in (previous, following)}
        options = self.option_signature(start, consumed)
        source_options = {eid: self.option_signature(start, set(), only=eid) for eid in consumed}
        # Keep transient changes and overlapping actions too, even if endpoints agree.
        endpoints = [start, a, b, end]
        last_index = 0
        for s in sorted(self.states.values(), key=lambda s: s['sequence']):
            if start['sequence'] <= s['sequence'] <= end['sequence']:
                if self.batch_context(s) != self.batch_context(start): return False
                if self.option_signature(s, consumed) != options: return False
                for ref in s['hand']:
                    eid = self.entities[ref]['entityId']
                    if eid in consumed and self.option_signature(s, set(), only=eid) != source_options[eid]: return False
                matches = [i for i, x in enumerate(endpoints) if i >= last_index and
                           self.area(s['board']) == self.area(x['board']) and self.area(s['hand']) == self.area(x['hand'])]
                if not matches: return False
                last_index = matches[0]
        if any(e not in (previous, following) and e.get('stateAfter') and
               e['sequence'] <= end['sequence'] and
               self.states[e['stateAfter']]['sequence'] > previous['sequence'] for e in turn['events']): return False
        # Even a briefly offered shop/discover interrupts batching, including an A→B→A return.
        end_sequence = self.states[following['stateAfter']]['sequence']
        for p in decision_points(self.data, turn):
            if previous['sequence'] < p['sequence'] <= end_sequence:
                s = self.states[p['state']]
                if self.shop_signature(s) != self.shop_signature(a) or s.get('choices'): return False
        return not any(previous['sequence'] < p['sequence'] <= end_sequence for p in choice_points(self.data, turn))

    def action_groups(self, turn):
        groups = []
        for e in turn['events']:
            if groups and self.can_join(groups[-1][-1], e, turn): groups[-1].append(e)
            else: groups.append([e])
        return groups

    def state_delta(self, s, *, order=False, repeated=False):
        changes = []
        if self.previous_economy != tuple(s.get(k) for k in ECONOMY):
            if self.previous_economy is None:
                changes.append(self.economy(s))
            else:
                labels = ('HP ', '방어도 ', 'T', 'G', '업 ', '빙결 ')
                changes.append(' · '.join(label + clean(s.get(key))
                                         for key, label, old in zip(ECONOMY, labels, self.previous_economy)
                                         if s.get(key) != old))
            self.previous_economy = tuple(s.get(k) for k in ECONOMY)
        for zone, label in (('board', 'Board'), ('hand', 'Hand'), ('heroPowers', 'Hero Power'), ('season', 'Season')):
            refs = s.get('season', {}).get('entities', []) if zone == 'season' else s.get(zone, [])
            oldrefs = self.previous.get(zone, [])
            old = {self.entities[r]['entityId']: r for r in oldrefs}
            new = {self.entities[r]['entityId']: r for r in refs}
            parts = ['−' + self.name(r) for eid, r in old.items() if eid not in new]
            for i, (eid, ref) in enumerate(new.items(), 1):
                if eid not in old:
                    parts.append(f'+{self.card(ref)} @{i}')
                    if self.entities[ref].get('golden'): parts[-1] += ' (황금 획득 관측)'
                elif self.fingerprint(old[eid]) != self.fingerprint(ref):
                    oe, ne = self.entities[old[eid]], self.entities[ref]
                    parts.append(self.changed_card(old[eid], ref, repeated=repeated and zone == 'board'))
                    if self.entities[ref].get('golden') and not self.entities[old[eid]].get('golden'):
                        parts[-1] += ' (황금 변환 관측)'
            if parts: changes.append(label + ' Δ: ' + '; '.join(parts))
            if order and zone == 'board' and set(old) == set(new) and list(old) != list(new):
                changes.append('현재 배치: ' + ' > '.join(self.name(r) for r in refs))
            # Keep the last represented order through suppressed pure UI moves. Membership
            # changes use explicit @positions and therefore establish the new order.
            if zone == 'board' and not order and set(old) == set(new):
                self.previous[zone] = [new[eid] for eid in old]
            else: self.previous[zone] = list(refs)
        return ' | '.join(changes)

    def render_turn(self, turn):
        lines = ['', f"## Turn {turn['turn']}" + (' · 영웅 선택' if turn['turn'] == 0 else ''), '']
        self.previous = {}
        self.previous_economy = None
        if sid := turn.get('startState'):
            self.observe(f"turn:{turn['turn']}:start", sid)
            s = self.states[sid]
            lines += [self.economy(s), 'Board: ' + self.cards_line(s['board']), 'Hand: ' + self.cards_line(s['hand'])]
            if turn['turn']: lines.append(self.next_opponent(s))
            for zone, refs in (('heroPowers', s.get('heroPowers', [])), ('season', s.get('season', {}).get('entities', []))):
                if refs: lines.append(('Hero Power: ' if zone == 'heroPowers' else 'Season: ') + self.cards_line(refs))
                self.previous[zone] = list(refs)
            self.previous.update(board=list(s['board']), hand=list(s['hand']))
            self.previous_economy = tuple(s.get(k) for k in ECONOMY)
        groups = self.action_groups(turn)
        hidden = {e['id'] for e in turn['events'] if self.plain_reorder(e, turn)}
        self.suppressed.extend(e['id'] for e in turn['events'] if e['id'] in hidden)
        intervals = [(g[0]['sequence'], self.states[g[-1]['stateAfter']]['sequence']) for g in groups if len(g) > 1]
        timeline = [(p['sequence'], 0, 'state', p) for p in decision_points(self.data, turn)
                    if not any(start < p['sequence'] < end for start, end in intervals)]
        timeline += [(p['sequence'], 1, 'choice', p) for p in choice_points(self.data, turn)]
        for group in groups:
            e, last = group[0], group[-1]
            for member in group:
                self.observe(member['id'] + ':before', member['stateBefore'])
                if member.get('stateAfter'): self.observe(member['id'] + ':after', member['stateAfter'])
                self.used_refs.update(member[k] for k in ('actor', 'target') if member.get(k))
            if e['id'] in hidden: continue
            timeline.append((e['sequence'], 2, 'action', group))
            if after := self.states.get(last.get('stateAfter')):
                timeline.append((after['sequence'], -1 if after['sequence'] > e['sequence'] else 3, 'after', group))
        shops, choices, active_shop = {}, set(), None
        previous_shop, previous_shop_id = None, None
        previous_action = None
        for seq, priority, kind, obj in sorted(timeline, key=lambda row: (row[0], row[1])):
            if kind == 'state':
                s = self.states[obj['state']]
                if s['phase'] != 'RECRUIT': continue
                signature = self.shop_signature(s)
                if signature == active_shop: continue
                if delta := self.state_delta(s): lines.append('State: ' + delta)
                self.metrics['shopOccurrences'] += 1
                active_shop = signature
                if signature not in shops:
                    qid = f"Q{turn['turn']}.{len(shops)+1}"; shops[signature] = qid
                    self.metrics['uniqueShops'] += 1
                    self.observe(qid, obj['state'])
                    lines.append(f"**Shop {qid}**: " + self.shop_text(s['shop'], previous_shop, previous_shop_id))
                else: lines.append(f"**Shop {shops[signature]} 재등장**")
                previous_shop, previous_shop_id = list(s['shop']), shops[signature]
                previous_action = None
            elif kind == 'choice':
                s = self.states[obj['state']]; choice = s['choices']
                signature = choice['id'], self.area(choice['offered'])
                if signature in choices: continue
                choices.add(signature)
                if delta := self.state_delta(s, order=True): lines.append('State: ' + delta)
                did = f"D{choice['id']}.{len(choices)}"; self.observe(did, obj['state'])
                self.metrics['choices'] += 1
                lines.append(f"**Discover/Choice {did}**:")
                for i, r in enumerate(choice['offered']):
                    number=choice_number(choice,i)
                    lines.append(f"{number if number is not None else '?'}. {self.card(r)}")
                    lines.extend(clean(x) for x in self.resolver.choice_lines(self.entities[r]))
                previous_action = None
            elif kind == 'after':
                e = obj[-1]; s = self.states[e['stateAfter']]
                if delta := self.state_delta(s, repeated=len(obj) > 1):
                    if previous_action == obj[0]['id']: lines[-1] += ' ⇒ ' + delta
                    else: lines.append('State: ' + delta)
                previous_action = None
            else:
                e, last = obj[0], obj[-1]; before = self.states[e['stateBefore']]
                if delta := self.state_delta(before, order=True): lines.append('State: ' + delta)
                self.metrics['actions'] += len(obj)
                ids = ','.join(x['id'] for x in obj)
                self.groups.append([x['id'] for x in obj])
                action = e['action'] + (f' x{len(obj)}' if len(obj) > 1 else '')
                actor = self.name(e['actor']) if e.get('actor') else ''
                target = ' → ' + self.name(e['target']) if e.get('target') else ''
                if len(obj) > 1:
                    numbers = [re.fullmatch(r'a(\d+)', member['id']) for member in obj]
                    if all(numbers) and [int(m[1]) for m in numbers] == list(range(int(numbers[0][1]), int(numbers[0][1])+len(obj))):
                        ids = e['id'] + '–' + last['id']
                    actor = clean(self.base_name(self.entities[e['actor']]))
                    target = f" → 직접 대상 {self.name(e['target'])} x{len(obj)} (매회 관측 증분 동일)"
                if e['action'] in ('BUY', 'SELL'):
                    actor = ''
                    target = self.name(e['target']) if e.get('target') else '?'
                if e['action'] == 'CHOOSE':
                    number=chosen_option(self.data,e)
                    target = 'Chosen: ' + (f'{number}. ' if number is not None else '') + self.card(e.get('target'))
                if e.get('toPosition') is not None: target += f" → slot {e['toPosition']}"
                marker = ' †' if e.get('status') == 'boundary_inferred' else ''
                if not last.get('stateAfter'): marker += ' [완료 미확인]'
                if e.get('evidence') not in ('observed', 'observed_send_option'): marker += f" [{e.get('evidence')}]"
                cost = f" · cost={e['cost']}" if e.get('cost') is not None else ''
                gold = clean(before.get('remainingGold'))
                if len(obj) > 1: gold += '→' + clean(self.states[last['stateAfter']].get('remainingGold'))
                lines.append(f"- **{ids} {action}**{marker} {actor}{target} · G{gold}{cost}")
                previous_action = e['id']
        if c := turn.get('combat'):
            self.metrics['combats'] += 1
            sid = c['startState']; s = self.states[sid]
            self.observe(f"turn:{turn['turn']}:combat", sid)
            end = self.states.get(c.get('endState'))
            if end: self.observe(f"turn:{turn['turn']}:combatEnd", c['endState'])
            lines += ['', '**Final combat board** (왼쪽→오른쪽):']
            lines.extend(f'{i}. {self.card(r)}' for i, r in enumerate(s['board'], 1))
            if not s['board']: lines.append('∅ (빈 영역/미관측)')
            lines += [f"**Combat vs {self.name(s.get('opponentHero'))}** · {self.economy(s)} · {c['captureMethod']}",
                      'Opponent board (왼쪽→오른쪽):']
            lines.extend(f'{i}. {self.card(r)}' for i, r in enumerate(s['opponentBoard'], 1))
            if not s['opponentBoard']: lines.append('∅ (빈 영역/미관측)')
            enemy = self.entities.get(s.get('opponentHero'), {})
            et = enemy.get('rawTags', {})
            lines.append(f"상대 HP {clean(enemy.get('health'))}+방어도 {clean(et.get('ARMOR'))} · T{clean(et.get('PLAYER_TECH_LEVEL'))}")
            end_hp = f" · 종료 HP {clean(end.get('hp'))}+방어도 {clean(end.get('armor'))}" if end else ''
            lines.append(f"Result: **{c['result']}** · 받은 피해 {clean(c['damageTaken'])} · 준 피해 {clean(c['damageDealt'])} · 내 치명피해={clean(c.get('lethal'))}{end_hp} · {c.get('resultEvidence','?')}")
            lines.extend(self.combat_summary(c, s))
            if enemy.get('cardId'): self.encounters[enemy['cardId']] = turn['turn']
        elif turn['turn']:
            lines.append('전투 시작 미수집: 최종 전투 배치는 확정할 수 없음.')
        return lines

    def render(self):
        body = []
        for t in self.data['turns']:
            if t['events'] or t['shopSnapshots'] or t.get('decisionSnapshots') or t.get('combat') or choice_points(self.data, t):
                body.extend(self.render_turn(t))
        m, result = self.data['match'], self.data['result']
        hero = self.entities.get(m.get('hero'), {})
        lines = ['# Battlegrounds AI Review', '',
                 f"Hero: {clean(hero.get('name') or hero.get('cardId'))} · Placement: {clean(result['placement'])}",
                 f"Match: {m['id']} · {m['startedAt']} → {result['endedAt']} · {result['status']}",
                 'Legend: DS=천상의 보호막, Taunt=도발, Reborn=환생, DR=죽음의 메아리, WF=질풍, Golden=황금, Venomous=독소, Poisonous=독성. #는 동명 개체 구분.',
                 '행동 전 정보만으로 판단할 것. ⇒는 이후 관측된 변화. ?는 미관측이며 0이 아님. †는 종료 경계 추론.',
                 '상점은 로그의 선택 가능 경계 관측. Board/Hand Δ는 추가·제거·변경, @는 자리. 스탯·[]를 재표시하면 현재 속성(빠진 키워드는 제거), 효과만 표시하면 기존 스탯·키워드 유지. 효과Δ는 이름의 추가/제거이며 나머지 효과 유지. 수치 교체도 −/+로 표시. 턴 시작·전투 전장은 전체 표기.',
                 '단순 드래그는 생략하되 다음 실제 행동 시 배치와 최종 전투 순서는 보존. cost 태그는 구매 가격과 다를 수 있음.',
                 'Shop Δ(Q)는 같은 턴의 해당 상점에서 제거/변경만 적용하며 나머지는 동일, 남은 순서대로 자리가 당겨짐. 새 카드·순서 변경은 전체 상점 표기. 경제 변화도 달라진 항목만 표시.',
                 '이 파일만으로 복기할 것. 규칙은 아래 Relevant mechanics에 포함. 다음 상대는 턴 시작 관측이며 상대 전투 전장은 사후 정보. 전투 요약은 첫 공격 최대 3회만 포함하므로 생략된 공격·발동·사망 원인을 추측하지 말 것.',
                 '⇒는 관측 경계 사이 변화로, 앞 행동만의 인과를 보장하지 않음. 미해석 효과·사용 가능 여부·손 넘침·남은 시간은 기록 없으면 미확정. 효과 이름 목록은 합체 횟수가 아님.',
                 '주문 묶음은 같은 직접 대상·매회 동일한 관측 증분만 집계. 부착 수치 S번호=TAG_SCRIPT_DATA_NUM_번호이며 원인 해석이 아님. 대상 외 변화에서 자동 시전 여부·횟수를 추정하지 말 것.',
                 f"보존: 행동 {self.metrics['actions']}개(표시 {len(self.groups)}행, 순수 재배치 {len(self.suppressed)}개 별도 보존) · 상점 {self.metrics['shopOccurrences']}회 · 선택 목록 {self.metrics['choices']}개 · 전투 {self.metrics['combats']}회."]
        warnings = {
            'Unresolved named entity in tag changes; inspect events.jsonl / player mapping.':
                '태그 변경의 일부 개체/플레이어 식별 미확정.',
        }
        lines.extend('- 수집 주의: ' + warnings.get(x, x) for x in self.data['quality']['warnings'])
        lines += body + ['', '## Result', f"Placement: {clean(result['placement'])} · {result['status']}"]
        last_combat = next((t['combat'] for t in reversed(self.data['turns']) if t.get('combat')), {})
        end = self.states.get(last_combat.get('endState'), {})
        final_hp = clean(end.get('hp')) if result['status'] == 'completed' and end.get('phase') == 'COMBAT' else '?'
        lines += [f'Final HP: {final_hp} (마지막 전투 종료 로그값; 치명피해 후 음수 가능)',
                  '승률·EV·전체 로비 평균 성장률은 미관측. 미해석 규칙에 좌우되는 판단은 이 파일에서 확정할 수 없음.', '']
        lines.extend(self.resolver.section())
        lines.append('')
        return '\n'.join(lines)


def dictionary_document(data, writer, debug_writer):
    """Stable JSON schema v1. Expanded effects are authoritative; X aids debug refs."""
    for ref in sorted(writer.used_refs): debug_writer.card(ref)
    cards = {}
    for cid, alias in debug_writer.cards.items():
        e = debug_writer.card_details[cid]
        cards[alias] = {'cardId': e.get('cardId'), 'name': e.get('name'), 'tier': e.get('tavernTier'),
                        'tribes': e.get('tribes'), 'text': e.get('text'), 'baseAttack': e.get('baseAttack'), 'baseHealth': e.get('baseHealth')}
    entities = {}
    for ref in sorted(writer.used_refs):
        e = data['entityStates'][ref]
        cid = e.get('cardId') or f"unknown-entity-{e['entityId']}"
        entities[ref] = {k: v for k, v in e.items() if k not in ('enchantments', 'darkGift')}
        entities[ref]['card'] = debug_writer.cards[cid]
        entities[ref]['effects'] = [debug_writer.effect(x) for x in e.get('enchantments', [])]
        if e.get('darkGift'): entities[ref]['darkGift'] = debug_writer.effect(e['darkGift'])
    effects = {alias: json.loads(key) for key, alias in debug_writer.effects.items()}
    templates, effect_templates = effect_definitions(debug_writer.effects)
    for value in cards.values():
        meta=writer.resolver.cards.get(value.get('cardId'),{})
        value.update(dbfId=meta.get('dbfId'),localizedName=meta.get('name'),rulesText=meta.get('text'),
                     rulesLocale=meta.get('textLocale'),rulesBuild=writer.resolver.catalog.get('build') if meta else None)
    return {'dictionaryVersion': 1, 'matchId': data['match']['id'], 'cards': cards, 'effects': effects,
            'templates': templates, 'effectTemplates': effect_templates, 'entityStates': entities,
            'snapshots': {sid: data['snapshots'][sid] for sid in sorted(set(writer.observations.values()))},
            'optionSets': data.get('optionSets', {}),
            'observations': writer.observations,
            'actions': {e['id']: e for t in data['turns'] for e in t['events']},
            'actionGroups': writer.groups, 'suppressedReorders': writer.suppressed,
            'combats': {str(t['turn']): {k: c.get(k) for k in ('startState', 'endState', 'captureMethod', 'startIsExact',
                        'result', 'damageTaken', 'damageDealt', 'lethal', 'resultEvidence')}
                        for t in data['turns'] if (c := t.get('combat'))},
            'result': data['result'], 'mechanics':writer.resolver.sidecar(writer.used_refs)}


def export_review(data, mode='compact', dictionary_name='match.dictionary.json', catalog=None):
    if mode not in ('compact', 'debug'): raise ValueError('review mode must be compact or debug')
    if catalog is None:
        from .card_data import load_catalog
        try: catalog=load_catalog(data.get('match',{}).get('build'))
        except (OSError,ValueError): catalog=None
    compact = CompactReviewWriter(data, dictionary_name,catalog)
    compact_text = compact.render()
    debug = ReviewWriter(data)
    debug_text = debug.render()
    dictionary = dictionary_document(data, compact, debug)
    if mode == 'debug':
        # Keep old C/F/X notation and the complete action stream; definitions live beside it.
        debug_text = debug_text.split('\n## 카드 사전\n', 1)[0]
        debug_text = debug_text.replace('C=아래 카드 사전', 'C=sidecar 카드 사전')
        debug_text += f'\n\n사전: [{dictionary_name}]({dictionary_name})\n'
    return (compact_text if mode == 'compact' else debug_text), dictionary
