"""Single-upload review: preserve decisions while removing repeated state text."""
from copy import deepcopy

from bg_review.compact_review import CompactReviewWriter, export_review
from test_compact_review import World
from test_semantics import catalog, meta


def test_effect_removal_and_keyword_loss_are_explicit_without_repeating_old_effects():
    w = World()
    w.data['match']['build'] = 250339
    persistent = {'cardId': 'KEEP', 'rawTags': {}}
    removed = {'cardId': 'REMOVE', 'rawTags': {}}
    added = {'cardId': 'ADD', 'rawTags': {}}
    before = w.card(1, 'Unit', attack=10, health=10, maxHealth=10, keywords=['DIVINE_SHIELD'],
                    enchantments=[persistent, removed])
    after = w.card(1, 'Unit', attack=12, health=14, maxHealth=14, enchantments=[persistent, added])
    start = w.state(10, [before])
    end = w.state(20, [after])
    w.action('SPELL_USE', start, end, actor=before)
    c = catalog({k: meta(k, 'Effect rule', name=k) for k in ('KEEP', 'REMOVE', 'ADD')})
    original = deepcopy(w.data)
    text, _ = export_review(w.data, catalog=c)
    delta = next(line for line in text.splitlines() if '**a1 SPELL_USE**' in line)
    assert '10/10→12/14 [T1]' in delta and 'DS' not in delta
    assert '−REMOVE' in delta and '+ADD' in delta and 'KEEP' not in delta
    assert w.data == original


def test_shop_removal_is_compact_but_new_options_and_reorders_are_full():
    w = World()
    cards = [w.card(i, 'Long descriptive card ' + str(i)) for i in range(1, 5)]
    s = w.state(10, [], shop=cards)
    w.boundary(s)
    s2 = w.state(20, [], shop=cards[1:])
    w.boundary(s2)
    new = w.card(5, 'Never purchased alternative')
    s3 = w.state(30, [], shop=[*cards[1:], new])
    w.boundary(s3)
    s4 = w.state(40, [], shop=[new, *cards[1:]])
    w.boundary(s4)
    text, _ = export_review(w.data, catalog={})
    assert '**Shop Q1.2**: Δ(Q1.1): −Long descriptive card 1' in text
    assert '**Shop Q1.3**: 1. Long descriptive card 2' in text
    assert '**Shop Q1.4**: 1. Never purchased alternative' in text


def test_unbought_and_opponent_rules_are_available_without_other_files():
    w = World()
    w.data['match']['build'] = 250339
    offered = w.card(1, 'Unbought', cardId='OFFER')
    enemy = w.card(2, 'Enemy', cardId='ENEMY')
    s = w.state(10, [], shop=[offered], opponentBoard=[enemy])
    w.boundary(s)
    w.combat(s)
    c = catalog({'OFFER': meta('OFFER', 'Remove a large enemy.'),
                 'ENEMY': meta('ENEMY', 'Summon another body.')})
    text, side = export_review(w.data, catalog=c)
    assert 'Remove a large enemy.' in text and 'Summon another body.' in text
    assert 'offered shop' in side['mechanics']['relevant']['OFFER']['reasons']
    assert '.dictionary.json' not in text and 'sidecar' not in text


def test_next_opponent_uses_start_state_not_future_combat():
    w = World()
    known = w.card(1, 'Known opponent', cardId='KNOWN', rawTags={'PLAYER_ID': 8})
    future = w.card(2, 'Future opponent', cardId='FUTURE', rawTags={'PLAYER_ID': 9})
    start = w.state(10, [], nextOpponentPlayerId=8, lobbyHeroes=[known])
    end = w.state(20, [], opponentHero=future)
    w.action('ROLL', start, end)
    w.combat(end)
    text, _ = export_review(w.data, catalog={})
    assert '다음 상대: Known opponent (이전 직접 대전 기록 없음)' in text
    assert '다음 상대: Future opponent' not in text
    writer = CompactReviewWriter(w.data, catalog={})
    writer.encounters['KNOWN'] = 3
    assert '3턴 전투 참조·현재 전장 아님' in writer.next_opponent(w.data['snapshots'][start])


def test_combat_opening_is_bounded_labeled_and_does_not_claim_all_events():
    w = World()
    w.data['match']['localPlayerId'] = 5
    own = w.card(1, 'Own', rawTags={'CONTROLLER': 5})
    enemy = w.card(2, 'Enemy', rawTags={'CONTROLLER': 13})
    s = w.state(10, [own], opponentBoard=[enemy])
    w.combat(s)
    w.turn['combat']['firstAttacker'] = own
    w.turn['combat']['events'] = [dict(type='ATTACK', attacker=own, target=enemy) for _ in range(5)]
    w.turn['combat']['events'] += [dict(type='DEATH', entity=enemy)]
    text, _ = export_review(w.data, catalog={})
    opening = next(line for line in text.splitlines() if line.startswith('첫 공격 최대'))
    assert opening.count('→') == 3 and '전체 전투·중간 효과 생략' in opening
    assert '공격 5회/사망 1회' in text and '선공 내 Own' in text
    assert '내 치명피해=' in text


def test_invisible_gameplay_tag_change_is_not_silenced():
    w = World()
    before = w.card(1, 'Unit', rawTags={'UNKNOWN_COUNTER': 1})
    after = w.card(1, 'Unit', rawTags={'UNKNOWN_COUNTER': 2})
    s1 = w.state(10, [before])
    s2 = w.state(20, [after])
    w.action('ACTIVATE', s1, s2, actor=before)
    text, _ = export_review(w.data, catalog={})
    assert 'UNKNOWN_COUNTER:1→2' in text
