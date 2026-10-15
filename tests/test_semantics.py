from copy import deepcopy
import json
from pathlib import Path

import pytest

from bg_review.card_data import read_catalog, catalog_from_xml, catalog_or_unresolved
from bg_review.compact_review import export_review
from bg_review.mechanics import MechanicsResolver, chosen_option
from bg_review.storage import Session
from test_compact_review import World
from make_fixture import fixture


@pytest.mark.parametrize('kind',['normal','hero','dark_gift','triple_reward','trinket'])
@pytest.mark.parametrize('index',[0,1,2])
def test_choice_index_is_candidate_ordinal_not_event_id(kind,index):
    w=World()
    offered=[w.card(n,f'{kind}{n}',type='HERO' if kind=='hero' else 'MINION') for n in (1,2,3)]
    s=w.state(10,[],choices={'id':77,'offered':offered,'offeredIndices':[0,1,2]})
    # Selected entity may have a later revision with different stats.
    target=w.card(index+1,f'{kind}{index+1}',attack=12)
    e=w.action('CHOOSE',s,s,target=target,choiceId=77)
    text,_=export_review(w.data,catalog={})
    assert chosen_option(w.data,e)==index+1
    assert f'Chosen: {index+1}. {kind}{index+1}' in text
    assert '(choice 77)' not in text


@pytest.mark.parametrize('problem',['absent','wrong_choice','duplicate','bad_indices'])
def test_choice_does_not_guess(problem):
    w=World();a=w.card(1,'Same name');b=w.card(2,'Same name')
    choice={'id':7,'offered':[a],'offeredIndices':[0]}
    if problem=='duplicate':choice['offered']=[a,a];choice['offeredIndices']=[0,1]
    if problem=='bad_indices':choice['offeredIndices']=[]
    s=w.state(10,[],choices=choice)
    e=w.action('CHOOSE',s,s,target=b if problem=='absent' else a,choiceId=9 if problem=='wrong_choice' else 7)
    text,_=export_review(w.data,catalog={})
    assert chosen_option(w.data,e) is None
    assert 'Chosen: Same name' in text


def test_parser_keeps_actual_indices_when_items_arrive_out_of_order(tmp_path):
    text=fixture();lines=text.splitlines(True)
    i=next(i for i,line in enumerate(lines) if 'Entities[0]=' in line and 'id=40 ' in line)
    lines[i],lines[i+1]=lines[i+1],lines[i]
    session=Session(tmp_path,'fixture','2026-09-14',metadata_options={'offline':True})
    for line in lines:session.feed(line)
    session.close()
    d=session.match.data
    e=next(e for t in d['turns'] for e in t['events'] if e['action']=='CHOOSE')
    assert d['snapshots'][e['stateBefore']]['choices']['offeredIndices']==[0,1]
    assert chosen_option(d,e)==2


def catalog(cards,build='250339'):
    return {'catalogVersion':1,'build':build,'locale':'koKR','sources':[],'cards':cards,'races':{'20':'야수','92':'나가'}}


def meta(cid,text,name=None,**kwargs):
    result={'id':cid,'dbfId':1,'name':name or cid,'text':text,'textLocale':'koKR','tags':{},'techLevel':1}
    result.update(kwargs);return result


def test_build_and_id_are_required_never_resolve_by_name():
    w=World();r=w.card(1,'Known name',cardId='ACTUAL');w.state(10,[r]);w.data['match']['build']=250339
    c=catalog({'OTHER':meta('OTHER','Wrong text','Known name')})
    resolver=MechanicsResolver(w.data,c)
    assert resolver.rule(w.data['entityStates'][r])['status']=='unresolved'
    c=catalog({'ACTUAL':meta('ACTUAL','Wrong patch')},build='123')
    assert MechanicsResolver(w.data,c).rule(w.data['entityStates'][r])['text'] is None


def test_xml_locale_fallback_bacon_override_and_build_mismatch(tmp_path):
    base=tmp_path/'base.xml';bg=tmp_path/'bacon.xml'
    base.write_text('<CardDefs build="250339"><Entity CardID="X" ID="123"><Tag enumID="185" type="LocString"><enUS>English</enUS></Tag><Tag enumID="184" type="LocString"><enUS>Old ability</enUS></Tag></Entity></CardDefs>',encoding='utf-8')
    bg.write_text('<CardDefs build="250339"><Entity CardID="X" ID="123"><Tag enumID="185" type="LocString"><koKR>한국어 이름</koKR></Tag><Tag enumID="184" type="LocString"><enUS>Current BG ability</enUS></Tag></Entity></CardDefs>',encoding='utf-8')
    c=catalog_from_xml([base,bg],'250339')
    assert c['cards']['X']['name']=='한국어 이름'
    assert c['cards']['X']['text']=='Current BG ability' and c['cards']['X']['textLocale']=='enUS'
    with pytest.raises(ValueError):catalog_from_xml([base],'999')
    plain=tmp_path/'cards.json';plain.write_text('[]')
    with pytest.raises(ValueError):read_catalog(plain,'250339','koKR')


def test_numeric_slots_and_race_are_distinct_and_use_current_observation():
    w=World();w.data['match']['build']=250339
    c=catalog({'BUFF':meta('BUFF','부여 +{0}/+{1}',tags={'TAG_SCRIPT_DATA_NUM_1':2,'TAG_SCRIPT_DATA_NUM_2':1}),
               'BG32_MagicItem_901':meta('BG32_MagicItem_901','내가 사는 다음 {0}을 황금으로 만듭니다.',tags={'TAG_SCRIPT_DATA_NUM_1':92}),
               'UNKNOWN_NOUN':meta('UNKNOWN_NOUN','다음 {0}을 얻습니다.',tags={'TAG_SCRIPT_DATA_NUM_1':20})})
    resolver=MechanicsResolver(w.data,c)
    rule=resolver.rule({'cardId':'BUFF','rawTags':{'TAG_SCRIPT_DATA_NUM_1':7,'TAG_SCRIPT_DATA_NUM_2':8}})
    assert rule['text']=='부여 +7/+8'
    assert rule['parameters']['0']['source']=='observed'
    rule=resolver.rule({'cardId':'BG32_MagicItem_901','rawTags':{'TAG_SCRIPT_DATA_NUM_1':20}})
    assert '다음 야수' in rule['text'] and '20' not in rule['text']
    assert resolver.rule({'cardId':'UNKNOWN_NOUN'})['status']=='parameters_unresolved'


def test_gift_target_reference_not_misread_as_numeric_buff():
    w=World();w.data['match']['build']=250339
    resolver=MechanicsResolver(w.data,catalog({'GIFT':meta('GIFT','부여 +{0}/+{1}') }))
    r=resolver.rule({'cardId':'GIFT','rawTags':{'IS_NIGHTMARE_BONUS':1,'TAG_SCRIPT_DATA_NUM_1':7777,'TAG_SCRIPT_DATA_NUM_2':2}})
    assert '7777' not in r['text'] and '{0}?' in r['text'] and '+2' in r['text']


def test_hero_gift_rules_inline_golden_separate_and_no_truth_mutation():
    w=World();w.data['match']['build']=250339
    gift={'entityId':50,'cardId':'GIFT','rawTags':{}}
    a=w.card(1,'Minion',cardId='NORMAL',darkGift=gift)
    b=w.card(2,'Minion',cardId='GOLD',golden=True)
    h=w.card(3,'Hero',cardId='HERO')
    s=w.state(10,[a],choices={'id':55,'offered':[a,b,h]});w.action('CHOOSE',s,s,target=a,choiceId=55)
    c=catalog({'NORMAL':meta('NORMAL','부여 +1/+1','Minion'), 'GOLD':meta('GOLD','부여 +2/+2','Minion'),
               'GIFT':meta('GIFT','2턴마다 하수인을 얻습니다.','친화력'),
               'HERO':meta('HERO',None,'Hero',tags={'HERO_POWER':99}),
               'HP':meta('HP','하수인에게 보호막을 부여합니다.','Power',dbfId=99)})
    before=deepcopy(w.data);text,side=export_review(w.data,catalog=c)
    assert w.data==before
    assert 'Dark Gift: 친화력 — 2턴마다 하수인을 얻습니다.' in text
    assert 'Hero Power: Power — 하수인에게 보호막을 부여합니다.' in text
    section=text.split('## Relevant mechanics')[1]
    assert section.count('[NORMAL]')==1 and section.count('[GOLD]')==1
    assert side['mechanics']['entities'][a]['darkGift']['appliedToEntityId']==1


def test_creator_is_evidence_not_a_replacement_effect_and_future_values_not_borrowed():
    w=World();w.data['match']['build']=250339
    parent=w.card(1,'M',rawTags={'DARK_GIFT_ENTITY':50})
    w.card(50,'Gift',cardId='GIFT',rawTags={'TAG_SCRIPT_DATA_NUM_1':9999})
    c=catalog({'CREATOR':meta('CREATOR','Unrelated creator ability',dbfId=88),
               'GIFT':meta('GIFT','부여 +{0}',tags={'TAG_SCRIPT_DATA_NUM_1':2})})
    resolver=MechanicsResolver(w.data,c)
    rule=resolver.rule({'cardId':'UNKNOWN','rawTags':{'CREATOR_DBID':88}})
    assert rule['text'] is None and rule['related'][0]['cardId']=='CREATOR'
    gift=resolver.gift(w.data['entityStates'][parent]);assert gift['rawTags']=={}
    assert '9999' not in resolver.rule(gift)['text']


def test_missing_metadata_and_network_failure_remain_unresolved(monkeypatch,tmp_path):
    import bg_review.card_data as module
    def fail(*args,**kwargs):raise OSError('offline')
    monkeypatch.setattr(module,'load_catalog',fail)
    c=catalog_or_unresolved(250339,fetch=True)
    assert not c['cards'] and 'offline' in c['error']
    w=World();w.data['match']['build']=250339;a=w.card(1,'Unknown');w.state(10,[a])
    text,_=export_review(w.data,catalog=c)
    assert 'unresolved' in text and 'Unknown' in text


def test_conflicts_and_display_branches_are_never_reported_as_certain():
    w=World();w.data['match']['build']=250339
    resolver=MechanicsResolver(w.data,catalog({'X':meta('X','첫 설명@조건부 설명',techLevel=6)}))
    r=resolver.rule({'cardId':'X','tavernTier':5})
    assert r['status']=='display_variant_unresolved' and r['conflicts']
    assert r['template']=='첫 설명@조건부 설명'


def test_numeric_at_and_client_macros_are_not_split_as_branches():
    w=World();w.data['match']['build']=250339
    resolver=MechanicsResolver(w.data,catalog({
        'TIER':meta('TIER','@단계 하수인을 발견합니다.',tags={'TAG_SCRIPT_DATA_NUM_1':2}),
        'MACRO':meta('MACRO','#EXPANDLIST(@3,@4,"또는")단계'),
        'COUNT':meta('COUNT','무료 새로고침 {0}번과 혈석 {1}개',tags={'TAG_SCRIPT_DATA_NUM_1':2,'TAG_SCRIPT_DATA_NUM_2':3})}))
    r=resolver.rule({'cardId':'TIER','rawTags':{'TAG_SCRIPT_DATA_NUM_1':6}})
    assert r['text']=='6단계 하수인을 발견합니다.' and r['status']=='resolved'
    r=resolver.rule({'cardId':'MACRO'})
    assert r['status']=='client_macro' and '#EXPANDLIST(@3,@4' in r['rawText']
    assert '#EXPANDLIST' not in r['text']
    assert resolver.rule({'cardId':'COUNT'})['text']=='무료 새로고침 2번과 혈석 3개'


@pytest.mark.parametrize('offline',[False,True])
def test_session_fetches_only_after_completed_and_keeps_truth_when_metadata_fails(monkeypatch,tmp_path,offline):
    import bg_review.storage as storage
    calls=[]
    def missing(build,**options):
        assert 'offline' not in options
        calls.append(options['fetch'])
        return {'catalogVersion':1,'build':str(build),'locale':'koKR','cards':{},'error':'test offline'}
    monkeypatch.setattr(storage,'catalog_or_unresolved',missing)
    s=Session(tmp_path,'fixture','2026-09-14',metadata_options={'offline':offline})
    lines=fixture().splitlines(True)
    for line in lines:
        s.feed(line)
        if s.match and s.match.is_bg and not s.match.ended:s.save();break
    for line in lines[s.parser.line_number:]:s.feed(line)
    s.close()
    assert calls==[False,not offline]
    p=s.paths[0]
    data=json.loads(p.read_text(encoding='utf-8'))
    assert data['result']['status']=='completed' and s.errors==0
    assert p.with_suffix('.audit.md').exists()
    assert 'unresolved' in p.with_suffix('.review.md').read_text(encoding='utf-8')


def test_opponent_and_own_rules_are_unique_in_same_file():
    w=World();w.data['match']['build']=250339
    a=w.card(1,'Own',cardId='OWN');b=w.card(2,'Opponent',cardId='ENEMY')
    s=w.state(10,[a],opponentBoard=[b])
    w.combat(s)
    c=catalog({'OWN':meta('OWN','My rule'),'ENEMY':meta('ENEMY','Enemy exclusive rule')})
    text,side=export_review(w.data,catalog=c)
    assert text.count('[OWN]')==1 and text.count('Enemy exclusive rule')==1
    assert side['mechanics']['entities'][b]['text']=='Enemy exclusive rule'
