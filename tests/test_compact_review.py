from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from bg_review.compact_review import CompactReviewWriter, export_review
from bg_review.review_exporter import ReviewWriter
from bg_review.validate import validate_dictionary
from test_review_exporter import match


class World:
    def __init__(self):
        self.data = {'schemaVersion': 1, 'match': {'id': 'test', 'hero': None, 'startedAt': '2026-09-15'},
                     'result': {'placement': 3, 'status': 'completed', 'endedAt': '2026-09-15'},
                     'quality': {'warnings': [], 'limitations': []}, 'entityStates': {}, 'snapshots': {}, 'optionSets': {},
                     'turns': [{'turn': 1, 'startState': None, 'events': [], 'shopSnapshots': [], 'decisionSnapshots': [], 'combat': None}]}
        self.turn = self.data['turns'][0]

    def card(self, eid, name, **kwargs):
        ref = f"e{eid}v{len(self.data['entityStates'])+1}"
        e = dict(entityId=eid,cardId=name,name=name,type='MINION',position=1,attack=1,health=1,
                 maxHealth=1,cost=None,golden=False,tavernTier=1,tribes=['BEAST'],keywords=[],
                 rawTags={},mechanics={},enchantments=[])
        e.update(kwargs); self.data['entityStates'][ref] = e
        return ref

    def state(self, seq, board, hand=(), shop=(), **kwargs):
        sid = f's{len(self.data["snapshots"])+1}'
        s = dict(id=sid,sequence=seq,sourceLine=seq,timestamp=str(seq),turn=1,phase='RECRUIT',
                 hp=30,armor=0,tavernTier=1,remainingGold=10,upgradeCost=5,frozen=False,
                 board=list(board),hand=list(hand),shop=list(shop),shopKnown=True,hero=None,heroPowers=[],
                 opponentHero=None,opponentBoard=[],choices=None,season={'entities': []},options=None)
        s.update(kwargs); self.data['snapshots'][sid] = s
        if not self.turn['startState']: self.turn['startState'] = sid
        return sid

    def action(self, kind, before, after, **kwargs):
        e = dict(id=f'a{len(self.turn["events"])+1}',action=kind,sequence=self.data['snapshots'][before]['sequence'],
                 stateBefore=before,stateAfter=after,phase='RECRUIT',status='resolved',evidence='observed')
        e.update(kwargs); self.turn['events'].append(e)
        return e

    def boundary(self, sid):
        self.turn['decisionSnapshots'].append(dict(state=sid,sequence=self.data['snapshots'][sid]['sequence'],
                                                  reason='available_options',decisionBoundary=True,transient=False))

    def combat(self, sid):
        self.turn['combat'] = dict(startState=sid,captureMethod='fixture',result='win',damageTaken=0,
                                   damageDealt=5,lethal=False,resultEvidence='fixture')


def spell_world():
    w = World()
    spells = [w.card(i,'Blood Gem',type='SPELL',attack=None,health=None,maxHealth=None,cost=0) for i in range(10,14)]
    target = w.card(1,'그리핀',attack=88,health=72,maxHealth=72)
    shop = [w.card(2,'놓치면 안 되는 카드')]
    before = w.state(10,[target],spells,shop)
    for i, spell in enumerate(spells):
        buffed = w.card(1,'그리핀',attack=89+i,health=73+i,maxHealth=73+i)
        after = w.state(11+i*10,[buffed],spells[i+1:],shop)
        w.action('SPELL_USE',before,after,actor=spell,target=target,goldDelta=0)
        target = buffed
        if i < 3: before = w.state(20+i*10,[target],spells[i+1:],shop)
    w.combat(after)
    return w


def test_compact_default_names_sidecar_and_debug(tmp_path):
    _, data = match(tmp_path)
    compact, dictionary = export_review(data)
    debug, debug_dictionary = export_review(data,'debug')
    assert dictionary == debug_dictionary
    assert '## 카드 사전' not in compact and '## 효과 사전' not in compact
    assert not re.search(r'\b[CFX]\d+\b',compact)
    assert re.search(r'C\d+#\d+',debug)
    assert '## 카드 사전' not in debug and '## 효과 사전' not in debug
    assert 'Missed growth engine' in compact
    assert dictionary['dictionaryVersion'] == 1
    for observation, sid in dictionary['observations'].items():
        s = dictionary['snapshots'][sid]
        for zone in ('board','hand','shop','heroPowers','opponentBoard'):
            assert all(r in dictionary['entityStates'] for r in s.get(zone,[])), observation
    assert set(dictionary['actions']) == {e['id'] for t in data['turns'] for e in t['events']}
    from jsonschema import Draft202012Validator
    Draft202012Validator(json.loads((Path(__file__).parents[1]/'bg_review/dictionary.schema.json').read_text(encoding='utf-8'))).validate(dictionary)
    assert not validate_dictionary(dictionary)


def test_pure_reorders_hidden_but_next_decision_and_final_order_retained():
    w = World(); a=w.card(1,'A'); b=w.card(2,'B')
    s1=w.state(10,[a,b]); s2=w.state(11,[b,a]); s3=w.state(20,[b,a]); s4=w.state(21,[a,b]); s5=w.state(30,[a,b])
    w.action('REORDER',s1,s2,actor=a,toPosition=2,status='confirmed_at_next_options',evidence='observed_send_option')
    w.action('HERO_POWER',s3,s3,target=b)
    w.action('REORDER',s3,s4,actor=a,toPosition=1,status='confirmed_at_next_options',evidence='observed_send_option')
    w.combat(s5)
    text, sidecar=export_review(w.data)
    assert 'REORDER' not in text
    assert sidecar['suppressedReorders'] == ['a1','a3']
    assert text.index('현재 배치: B > A') < text.index('**a2 HERO_POWER**')
    final = text.split('**Final combat board**',1)[1]
    assert final.index('1. A') < final.index('2. B')


@pytest.mark.parametrize('exception',['stats','effect','adjacent','pending','inferred'])
def test_reorder_exceptions_not_silenced(exception):
    w=World(); a=w.card(1,'A',text='Give adjacent minions +1 Health' if exception=='adjacent' else None); b=w.card(2,'B')
    new=deepcopy(w.data['entityStates'][a])
    if exception=='stats': new.update(attack=9)
    if exception=='effect': new['enchantments']=[{'cardId':'POSITION_EFFECT','rawTags':{'UNKNOWN_GAMEPLAY':1}}]
    a2=w.card(1,'A',**{k:v for k,v in new.items() if k not in ('entityId','name')})
    s1=w.state(10,[a,b]); s2=w.state(11,[b,a2])
    w.action('REORDER',s1,None if exception=='pending' else s2,actor=a,toPosition=2,
             status='pending' if exception=='pending' else 'confirmed_at_next_options',
             evidence='inferred_from_position_change' if exception=='inferred' else 'observed_send_option')
    text, sidecar=export_review(w.data)
    assert '**a1 REORDER**' in text and not sidecar['suppressedReorders']


def test_four_choice_free_buffs_are_one_action_with_final_stats():
    w=spell_world(); text, sidecar=export_review(w.data)
    assert '**a1–a4 SPELL_USE x4**' in text
    assert '88/72' in text and '92/76' in text
    assert '89/73' not in text and '90/74' not in text and '91/75' not in text
    assert sidecar['actionGroups'] == [['a1','a2','a3','a4']]
    assert len(sidecar['actions']) == 4


@pytest.mark.parametrize('interruption',['shop_return','discover','new_hand_card','target','source_effect','triple'])
def test_buff_batch_breaks_at_new_information(interruption):
    w=spell_world(); events=w.turn['events']; d=w.data
    if interruption=='shop_return':
        s=w.state(15,d['snapshots'][events[0]['stateAfter']]['board'],shop=[w.card(99,'一瞬の選択肢')]);w.boundary(s)
    if interruption=='discover':
        s=w.state(15,d['snapshots'][events[0]['stateAfter']]['board'],choices={'id':1,'offered':[w.card(98,'候補') ]});w.boundary(s)
    if interruption=='new_hand_card': d['snapshots'][events[0]['stateAfter']]['hand'].append(w.card(97,'New decision'))
    if interruption=='target': events[1]['target']=w.card(96,'Different target')
    if interruption=='source_effect': d['entityStates'][events[1]['actor']]['enchantments']=[{'cardId':'DIFFERENT_BUFF','rawTags':{}}]
    if interruption=='triple':
        r=d['snapshots'][events[0]['stateAfter']]['board'][0];d['entityStates'][r]['golden']=True
    text, sidecar=export_review(d)
    assert sidecar['actionGroups'][0] == ['a1']
    if interruption=='shop_return': assert '一瞬の選択肢' in text
    if interruption=='discover': assert '候補' in text
    if interruption=='triple': assert '황금 변환 관측' in text


@pytest.mark.parametrize('action',['ROLL','BUY','SELL','TAVERN_UPGRADE','HERO_POWER','CHOOSE','DARK_GIFT','ACTIVATE'])
def test_other_decisions_never_batch(action):
    w=spell_world()
    for e in w.turn['events']: e['action']=action
    _, sidecar=export_review(w.data)
    assert sidecar['actionGroups'] == [['a1'],['a2'],['a3'],['a4']]


def test_actionable_unbought_shops_and_all_darkgift_candidates_survive():
    w=World(); a=w.card(1,'Existing'); shop=w.card(2,'First shop'); unseen=w.card(3,'Never bought')
    sa=w.state(10,[a],shop=[shop]);sb=w.state(20,[a],shop=[unseen]);sc=w.state(30,[a],shop=[shop])
    for s in (sa,sb,sc):w.boundary(s)
    offered=[w.card(i,'Gift '+str(i)) for i in (4,5,6)]
    sd=w.state(40,[a],shop=[shop],choices={'id':7,'offered':offered})
    w.action('DARK_GIFT',sc,sd,actor=a)
    w.action('CHOOSE',sd,sd,target=offered[1],choiceId=7)
    transient=w.state(35,[a],shop=[w.card(7,'Transient only')])
    w.turn['shopSnapshots'].append(dict(state=transient,sequence=35,reason='state_update',transient=True,decisionBoundary=False))
    text, sidecar=export_review(w.data)
    assert 'Never bought' in text and '**Shop Q1.1 재등장**' in text
    assert 'Transient only' not in text
    for i in (4,5,6):assert f'Gift {i}' in text
    assert 'Chosen: 2. Gift 5' in text
    assert set(k for k in sidecar['observations'] if k.startswith('Q')) == {'Q1.1','Q1.2'}


def test_sidecar_effect_text_escaped_for_markdown_is_not_parsed_as_json():
    w=spell_world()
    first=w.data['snapshots'][w.turn['startState']]['board'][0]
    w.data['entityStates'][first]['enchantments']=[{'cardId':'TEST','name':'A | B\n한글','rawTags':{'TAG_SCRIPT_DATA_NUM_1':9}}]
    _, sidecar=export_review(w.data)
    sidecar=json.loads(json.dumps(sidecar,ensure_ascii=False))
    effect=next(e for e in sidecar['effects'].values() if e.get('cardId')=='TEST')
    assert effect['name']=='A | B\n한글' and effect['tags']['TAG_SCRIPT_DATA_NUM_1']==9
    for fid, instance in sidecar['effectTemplates'].items():
        expanded={**sidecar['templates'][instance['template']],**instance['overrides']}
        assert expanded.get('cardId')==sidecar['effects'][fid].get('cardId')


def test_nested_choice_is_not_preceded_by_outer_result(tmp_path):
    _, data=match(tmp_path)
    turn=data['turns'][1]
    outer=next(e for e in turn['events'] if e['action']=='DARK_GIFT')
    choose=next(e for e in turn['events'] if e['action']=='CHOOSE')
    after=deepcopy(data['snapshots'][choose['stateAfter']]);after.update(id='s999',sequence=choose['sequence']+1)
    source=deepcopy(data['entityStates'][after['shop'][0]]);source.update(entityId=999,cardId='FUTURE_RESULT',name='Future result')
    data['entityStates']['e999v1']=source;after['hand']=['e999v1'];data['snapshots']['s999']=after;outer['stateAfter']='s999'
    text,_=export_review(data)
    assert text.index(f"**{choose['id']} CHOOSE**") < text.index('Future result')


def test_same_name_different_card_ids_are_unambiguous():
    w=World();a=w.card(1,'Twin',cardId='NORMAL');b=w.card(2,'Twin',cardId='GOLDEN',golden=True)
    s=w.state(10,[a,b]);w.action('HERO_POWER',s,s,target=b);w.combat(s)
    text,_=export_review(w.data)
    assert 'Twin#1' in text and 'Twin#2' in text and '→ Twin#2' in text


def test_debug_cli_custom_sidecar_and_modes(tmp_path):
    from bg_review.cli import main
    session, _=match(tmp_path);p=session.paths[0]
    audit=p.with_suffix('.audit.md').read_bytes()
    dest=tmp_path/'inspection.review.md'
    assert main(['export',str(p),'--format','review','--review-mode','debug','--markdown',str(dest)]) == 0
    assert 'inspection.dictionary.json' in dest.read_text(encoding='utf-8')
    sidecar=dest.with_name('inspection.dictionary.json')
    assert main(['validate',str(sidecar)]) == 0
    assert p.with_suffix('.audit.md').read_bytes() == audit
    with pytest.raises(ValueError):export_review({},'invalid')


def test_reorder_with_net_zero_intermediate_effect_is_retained():
    w=World();a=w.card(1,'A');b=w.card(2,'B')
    before=w.state(10,[a,b]);changed=w.card(1,'A',attack=9)
    w.state(11,[b,changed]);after=w.state(12,[b,a])
    w.action('REORDER',before,after,actor=a,toPosition=2,status='confirmed_at_next_options',evidence='observed_send_option')
    text,side=export_review(w.data)
    assert '**a1 REORDER**' in text and not side['suppressedReorders']


def test_shop_during_last_spell_prevents_batching_even_when_it_returns():
    w=spell_world();last=w.turn['events'][-1]
    w.data['snapshots'][last['stateAfter']]['sequence']=45
    middle=w.state(43,w.data['snapshots'][last['stateBefore']]['board'],shop=[w.card(99,'Mid-action actionable offer')])
    w.boundary(middle)
    text,side=export_review(w.data)
    assert side['actionGroups'][-1] == ['a4'] and 'Mid-action actionable offer' in text


def repeated_board_world():
    """Generic fixed gains plus an uninterpreted attachment counter, no card rules."""
    w = World()
    spells = [w.card(i, 'Repeated spell', type='SPELL', attack=None, health=None, maxHealth=None)
              for i in range(10, 20)]
    shop = [w.card(30, 'Unbought alternative'), w.card(31, 'Another alternative')]
    def board(n):
        effect = dict(entityId=50, cardId='UNKNOWN_EFFECT',
                      rawTags={'TAG_SCRIPT_DATA_NUM_1': n * 2},
                      mechanics={'TAG_SCRIPT_DATA_NUM_1': n * 2})
        return [w.card(1, 'Target', attack=10+3*n, health=20+4*n, maxHealth=20+4*n),
                w.card(2, 'Other', attack=5+2*n, health=6+2*n, maxHealth=6+2*n,
                       enchantments=[effect])]
    for i, spell in enumerate(spells):
        before = w.state(10*i+10, board(i), spells[i:], shop)
        w.boundary(before)
        after = w.state(10*i+11, board(i+1), spells[i+1:], shop)
        w.action('SPELL_USE', before, after, actor=spell, target=w.data['snapshots'][before]['board'][0])
    w.combat(after)
    return w


def test_ten_repeated_board_buffs_preserve_decisions_endpoints_and_observed_counters():
    w = repeated_board_world()
    original = deepcopy(w.data)
    text, side = export_review(w.data, catalog={})
    class Detailed(CompactReviewWriter):
        def can_join(self, *args): return False
    detailed = Detailed(w.data, catalog={})
    before = detailed.render()
    assert side['actionGroups'] == [[f'a{i}' for i in range(1, 11)]]
    assert '**a1–a10 SPELL_USE x10**' in text
    assert '직접 대상 Target x10' in text and 'G10→10' in text
    assert 'Target 10/20→40/60' in text and '(누적 +30/+40)' in text
    assert 'Other 5/6→25/26' in text and '(누적 +20/+20)' in text
    assert 'UNKNOWN_EFFECT#50 S1 0→20' in text
    assert '매회 관측 증분 동일' in text and '원인 해석이 아님' in text
    assert 'Target 13/24' not in text
    assert text.split('**Final combat board**')[1] == before.split('**Final combat board**')[1]
    assert [x for x in text.splitlines() if '**Shop ' in x] == [x for x in before.splitlines() if '**Shop ' in x]
    assert 'Unbought alternative' in text and 'Another alternative' in text
    assert side['observations'] == detailed.observations
    assert not validate_dictionary(side)
    assert len(text) < len(before) and len(text.splitlines()) < len(before.splitlines())
    assert w.data == original


@pytest.mark.parametrize('change', ['keyword', 'tribe', 'golden', 'new_unit', 'removed_unit',
                                  'new_effect', 'unknown_tag', 'counter_only', 'unmirrored_counter',
                                  'nonlinear', 'decrease', 'evidence', 'gold', 'buttons', 'hero',
                                  'target', 'automatic'])
def test_repeated_buffs_keep_meaningful_or_uncertain_changes_separate(change):
    w = repeated_board_world()
    events = w.turn['events']
    e = events[1]
    before, after = [w.data['snapshots'][e[k]] for k in ('stateBefore', 'stateAfter')]
    unit = w.data['entityStates'][after['board'][1]]
    if change == 'keyword': unit['keywords'] = ['DIVINE_SHIELD']
    if change == 'tribe': unit['tribes'] = ['DRAGON']
    if change == 'golden': unit['golden'] = True
    if change == 'new_unit': after['board'].append(w.card(99, 'New unit'))
    if change == 'removed_unit': after['board'].pop()
    if change == 'new_effect': unit['enchantments'].append({'entityId': 51, 'cardId': 'NEW', 'rawTags': {}})
    if change == 'unknown_tag': unit['rawTags']['UNKNOWN_GAMEPLAY'] = 1
    if change == 'counter_only':
        old = w.data['entityStates'][before['board'][1]]
        for k in ('attack', 'health', 'maxHealth'): unit[k] = old[k]
    if change == 'unmirrored_counter': unit['enchantments'][0]['mechanics']['TAG_SCRIPT_DATA_NUM_1'] = 999
    if change == 'nonlinear': unit['attack'] += 10
    if change == 'decrease': unit['attack'] = 1
    if change == 'evidence': e['evidence'] = 'inferred'
    if change == 'gold': after['remainingGold'] = 9
    if change == 'buttons': after['buttons'] = [w.card(90, 'New button')]
    if change == 'hero': after['hero'] = w.card(91, 'Changed hero')
    if change == 'target': e['target'] = before['board'][1]
    if change == 'automatic':
        # A spell not consumed from the observed hand is not a direct use.
        before['hand'].remove(e['actor'])
    text, side = export_review(w.data, catalog={})
    assert side['actionGroups'][:2] == [['a1'], ['a2']]
    if change == 'tribe': assert '종족: BEAST→DRAGON' in text


@pytest.mark.parametrize('kind', ['ROLL', 'BUY', 'SELL', 'CHOOSE', 'REORDER', 'ACTIVATE'])
def test_intervening_actions_never_join_even_when_state_returns(kind):
    w = repeated_board_world()
    after = w.turn['events'][0]['stateAfter']
    e = w.action(kind, after, after, actor=w.turn['events'][0]['actor'])
    w.turn['events'].insert(1, w.turn['events'].pop())
    _, side = export_review(w.data, catalog={})
    assert side['actionGroups'][:2] == [['a1'], [e['id']]]


@pytest.mark.parametrize('kind', ['stats', 'keyword', 'options', 'economy', 'hand', 'shop'])
def test_transient_observations_prevent_batching_even_if_they_revert(kind):
    w = repeated_board_world()
    first = w.turn['events'][0]
    s = deepcopy(w.data['snapshots'][first['stateAfter']])
    s.update(id='transient', sequence=15)
    if kind in ('stats', 'keyword'):
        unit = deepcopy(w.data['entityStates'][s['board'][1]])
        if kind == 'stats': unit['attack'] += 99
        else: unit['keywords'] = ['TAUNT']
        w.data['entityStates']['transient_unit'] = unit
        s['board'][1] = 'transient_unit'
    if kind == 'options':
        s['options'] = 'new_options'
        w.data['optionSets']['new_options'] = [{'entity': s['board'][0], 'error': 'NEW_REQUIREMENT'}]
    if kind == 'economy': s['remainingGold'] = 8
    if kind == 'hand': s['hand'].append(w.card(99, 'Temporary hand card'))
    if kind == 'shop': s['shop'] = [w.card(99, 'Temporary offer')]
    w.data['snapshots']['transient'] = s
    _, side = export_review(w.data, catalog={})
    assert side['actionGroups'][0] == ['a1']


def test_choice_candidates_chosen_and_uncertainty_survive_between_runs():
    w = repeated_board_world()
    w.data['quality']['warnings'] = ['Capture gap: unknown effect']
    offered = [w.card(90+i, f'Choice {i}') for i in range(3)]
    state = deepcopy(w.data['snapshots'][w.turn['events'][0]['stateAfter']])
    state.update(id='choice', sequence=15, choices={'id': 7, 'offered': offered})
    w.data['snapshots']['choice'] = state
    w.action('CHOOSE', 'choice', 'choice', target=offered[1], choiceId=7)
    w.turn['events'].insert(1, w.turn['events'].pop())
    text, side = export_review(w.data, catalog={})
    assert side['actionGroups'][0] == ['a1']
    for i in range(3): assert f'{i+1}. Choice {i}' in text
    assert 'Chosen: 2. Choice 1' in text and 'Capture gap: unknown effect' in text
    assert text.index('**a1 SPELL_USE**') < text.index('Chosen: 2.') < text.index('SPELL_USE x9')


def test_nonconsecutive_ids_remain_explicit():
    w = spell_world()
    w.turn['events'][1]['id'] = 'a99'
    text, _ = export_review(w.data, catalog={})
    assert '**a1,a99,a3,a4 SPELL_USE x4**' in text


def test_overlapping_action_result_is_not_absorbed_into_a_spell_batch():
    w = repeated_board_world()
    first, second = w.turn['events'][:2]
    outer = w.action('HERO_POWER', first['stateBefore'], second['stateAfter'])
    outer['sequence'] -= 1
    w.turn['events'].insert(0, w.turn['events'].pop())
    _, side = export_review(w.data, catalog={})
    assert side['actionGroups'][:3] == [[outer['id']], ['a1'], ['a2']]


def test_action_verifier_expands_ranges_and_checks_order():
    from scripts.verify_semantic_review import action_sequence
    assert action_sequence('**a1–a3 SPELL_USE x3**\n**a4 BUY**') == action_sequence(
        '**a1,a2 SPELL_USE x2**\n**a3 SPELL_USE**\n**a4 BUY**')
    assert action_sequence('**a1,a3,a2 SPELL_USE x3**') != action_sequence('**a1–a3 SPELL_USE x3**')


def test_transient_return_to_an_earlier_endpoint_is_not_hidden():
    w = repeated_board_world()
    first = w.turn['events'][0]
    state = deepcopy(w.data['snapshots'][first['stateBefore']])
    state.update(id='reverted', sequence=15)
    w.data['snapshots']['reverted'] = state
    _, side = export_review(w.data, catalog={})
    assert side['actionGroups'][0] == ['a1']


def test_next_spell_availability_change_is_not_hidden_as_consumed_hand_card():
    w = repeated_board_world()
    first, second = w.turn['events'][:2]
    ref = second['actor']
    w.data['optionSets'] = {'unavailable': [{'entity': ref, 'error': 'REQ_NOT_EXHAUSTED'}],
                            'available': [{'entity': ref, 'error': 'NONE'}]}
    for event in (first, second):
        for key in ('stateBefore', 'stateAfter'):
            w.data['snapshots'][event[key]]['options'] = 'available'
    w.data['snapshots'][first['stateBefore']]['options'] = 'unavailable'
    _, side = export_review(w.data, catalog={})
    assert side['actionGroups'][0] == ['a1']
