from copy import deepcopy
import json
from pathlib import Path
import re

from bg_review.cli import main
from bg_review.document import review_document
from bg_review.exporter import markdown, audit_markdown
from bg_review.review_exporter import ReviewWriter, decision_points, choice_points
from bg_review.storage import Session
from make_fixture import fixture


def match(tmp_path):
    session = Session(tmp_path, 'fixture', '2026-09-14')
    for line in fixture().splitlines(True): session.feed(line)
    session.close()
    return session, session.match.data


def test_two_exports_preserve_audit_and_every_action_combat(tmp_path):
    session, data = match(tmp_path)
    document = review_document(data)
    assert audit_markdown(document) == markdown(document)
    p = session.paths[0]
    assert p.with_suffix('.audit.md').read_text(encoding='utf-8') == markdown(document)
    review = p.with_suffix('.review.md').read_text(encoding='utf-8')
    assert not p.with_suffix('.md').exists()
    events = [e for t in data['turns'] for e in t['events']]
    positions = []
    for event in events:
        token = f"**{event['id']} {event['action']}**"
        assert review.count(token) == 1
        positions.append(review.index(token))
    assert positions == sorted(positions)
    assert review.count('**Final combat board** (왼쪽→오른쪽):') == 2
    assert review.count('Opponent board (왼쪽→오른쪽):') == 2
    assert 'Missed growth engine' in review and 'Choice 0' in review and 'Choice 1' in review
    assert '받은 피해 9' in review
    assert main(['export',str(p)]) == 0
    assert main(['export',str(p),'--format','review','--markdown',str(tmp_path/'custom.md')]) == 0
    custom = (tmp_path/'custom.md').read_text(encoding='utf-8')
    assert custom == review.replace(p.with_suffix('.dictionary.json').name, 'custom.dictionary.json')
    assert (tmp_path/'custom.dictionary.json').exists()


def test_transient_removed_but_unbought_actionable_shop_and_return_retained(tmp_path):
    _, data = match(tmp_path)
    turn = data['turns'][1]
    original = deepcopy(data['snapshots'][turn['events'][0]['stateBefore']])
    # A settled options screen with a never-bought card must survive even without a next action.
    for sid, eid, cardid, seq in [('s990',990,'NEVER_BOUGHT_CHOICE',990000),('s991',991,'TRANSIENT_ONLY_CARD',990001)]:
        entity = deepcopy(data['entityStates'][original['shop'][0]])
        entity.update(entityId=eid,cardId=cardid,name=cardid)
        data['entityStates'][f'e{eid}v1'] = entity
        state = deepcopy(original); state.update(id=sid,sequence=seq,shop=[f'e{eid}v1'])
        data['snapshots'][sid] = state
    turn['decisionSnapshots'].append({'state':'s990','sequence':990000,'reason':'available_options','transient':False})
    turn['shopSnapshots'].append({'state':'s991','sequence':990001,'reason':'state_update','transient':True,'decisionBoundary':False})
    # Return to the original shop: reference the original Q rather than silently omitting the return.
    turn['decisionSnapshots'].append({'state':original['id'],'sequence':990002,'reason':'available_options','transient':False})
    writer = ReviewWriter(data); text = writer.render()
    assert 'NEVER_BOUGHT_CHOICE' in text and 'TRANSIENT_ONLY_CARD' not in text
    assert '**상점 Q1.1 재등장**' in text
    assert writer.metrics['shopOccurrences'] > writer.metrics['uniqueShops']


def test_discover_hydration_coalesces_without_losing_offers(tmp_path):
    _, data = match(tmp_path)
    turn = data['turns'][1]
    points = choice_points(data, turn)
    assert len(points) == 1
    choice = data['snapshots'][points[0]['state']]['choices']
    assert len(choice['offered']) == 2
    writer = ReviewWriter(data); writer.render()
    assert writer.metrics['choices'] == 1
    # Last captured, unanswered choice still keeps the complete available list.
    turn['events'] = [e for e in turn['events'] if e['action'] != 'CHOOSE']
    assert any(len(data['snapshots'][p['state']]['choices']['offered']) == 2 for p in choice_points(data,turn))


def test_effect_dictionary_encoding_round_trips(tmp_path):
    _, data = match(tmp_path)
    ref = data['snapshots'][data['turns'][1]['startState']]['shop'][0]
    data['entityStates'][ref]['enchantments'] = [
        {'cardId':'EFFECT_TEST','name':'Aura','rawTags':{'TAG_SCRIPT_DATA_NUM_1':7,'TAUNT':1}},
        {'cardId':'EFFECT_TEST','name':'Aura','rawTags':{'TAG_SCRIPT_DATA_NUM_1':9,'TAUNT':1}},
    ]
    writer = ReviewWriter(data); text = writer.render()
    templates = {m[1]:json.loads(m[2]) for m in re.finditer(r'^- (X\d+): (.+)$',text,re.M)}
    decoded = {}
    for m in re.finditer(r'^- (F\d+): (X\d+)(?: \+ (.+))?$',text,re.M):
        decoded[m[1]] = {**templates[m[2]],**(json.loads(m[3]) if m[3] else {})}
    assert len(decoded) == len(writer.effects)
    variants = [v for v in decoded.values() if v.get('cardId') == 'EFFECT_TEST']
    assert {v['t.S1'] for v in variants} == {7,9}
    assert all(v['t.TAUNT'] == 1 for v in variants)


def test_decision_observations_survive_document_pruning(tmp_path):
    _, data = match(tmp_path)
    document = review_document(data)
    assert sum(len(t['decisionSnapshots']) for t in document['turns']) > 0
    for turn in document['turns']:
        for point in decision_points(document, turn):
            assert point['state'] in document['snapshots']


def test_nested_choice_precedes_outer_action_result(tmp_path):
    _, data = match(tmp_path)
    turn = data['turns'][1]
    outer = next(e for e in turn['events'] if e['action'] == 'DARK_GIFT')
    choice = next(e for e in turn['events'] if e['action'] == 'CHOOSE')
    after = deepcopy(data['snapshots'][choice['stateAfter']])
    after.update(id='s999',sequence=choice['sequence']+1,hand=['e999v1'])
    entity = deepcopy(data['entityStates'][data['snapshots'][outer['stateBefore']]['shop'][0]])
    entity.update(entityId=999,cardId='CHOICE_RESULT',name='선택 결과')
    data['entityStates']['e999v1'] = entity
    data['snapshots']['s999'] = after
    outer['stateAfter'] = 's999'
    text = ReviewWriter(data).render()
    assert text.index(f"**{outer['id']} DARK_GIFT**") < text.index(f"**{choice['id']} CHOOSE**") < text.index('#999')


def test_card_base_stats_do_not_replace_tier_and_defaults(tmp_path):
    _, data = match(tmp_path)
    ref = data['snapshots'][data['turns'][1]['startState']]['shop'][0]
    data['entityStates'][ref].update(baseAttack=5,baseHealth=6,tavernTier=4)
    writer = ReviewWriter(data)
    writer.card(ref)
    text = writer.render()
    definition = next(line for line in text.splitlines() if line.startswith('- C1:'))
    assert 'T4' in definition and '기본 5/6' in definition
