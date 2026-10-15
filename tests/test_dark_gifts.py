"""Opponent gift identity must survive hidden entities, copies, and attachment changes."""
from copy import deepcopy

import pytest

from bg_review.compact_review import export_review
from bg_review.document import review_document
from bg_review.mechanics import MechanicsResolver
from bg_review.storage import Session
from make_fixture import fixture
from test_compact_review import World
from test_semantics import catalog, meta


def attached(cid='EFFECT',eid=60,target=2,**tags):
    return {'entityId':eid,'cardId':cid,'rawTags':{'ATTACHED':target,'ZONE':'PLAY',
            'CARDTYPE':'ENCHANTMENT','IS_NIGHTMARE_BONUS':1,**tags},'enchantments':[]}


def metadata():
    return catalog({'EFFECT':meta('EFFECT','Shield breaks after three hits.','Blessing',dbfId=101,
                                 tags={'IS_NIGHTMARE_BONUS':1}),
                    'SPELL':meta('SPELL','Spell gift text.','Blessing',dbfId=102,
                                tags={'IS_NIGHTMARE_BONUS':1}),
                    'OTHER':meta('OTHER','Gain health when playing a card.','Other gift',dbfId=103,
                                tags={'IS_NIGHTMARE_BONUS':1}),
                    'ENEMY':meta('ENEMY','Enemy base rule.'),
                    'CREATOR':meta('CREATOR','Unrelated creator text.',dbfId=999)})


def test_opponent_without_dark_gift_entity_gets_explicit_gift_and_same_file_rule():
    w=World();w.data['match']['build']=250339
    e=w.card(2,'Enemy',cardId='ENEMY',enchantments=[attached(CREATOR_DBID=999)])
    s=w.state(10,[],opponentBoard=[e]);w.combat(s)
    original=deepcopy(w.data);text,side=export_review(w.data,catalog=metadata())
    assert w.data==original
    assert 'Dark Gift: Blessing' in text
    assert 'Shield breaks after three hits.' in text.split('## Relevant mechanics')[1]
    assert 'Enemy base rule.' in text.split('## Relevant mechanics')[1]
    record=side['mechanics']['entities'][e]['darkGifts'][0]
    assert record['cardId']=='EFFECT' and record['effectEntityId']==60
    assert record['appliedToEntityId']==2 and record['linkEvidence']=='ATTACHED+IS_NIGHTMARE_BONUS'
    assert record['text']=='Shield breaks after three hits.'
    assert record['related'][0]['cardId']=='CREATOR'  # Relationship only, not substituted.
    assert 'DS' not in text.split('Opponent board')[1].split('## Result')[0]


@pytest.mark.parametrize('tags',[{'ZONE':'GRAVEYARD'},{'ZONE':'REMOVEDFROMGAME'},
                                  {'ATTACHED':99},{'IS_NIGHTMARE_BONUS':0}])
def test_inactive_wrong_target_or_explicit_false_attachment_is_not_a_gift(tags):
    w=World();w.data['match']['build']=250339
    r=MechanicsResolver(w.data,metadata())
    assert not r.gifts({'entityId':2,'enchantments':[attached(**tags)]})


def test_metadata_flag_fallback_and_unknown_effect_remains_unresolved():
    w=World();w.data['match']['build']=250339
    effect=attached();del effect['rawTags']['IS_NIGHTMARE_BONUS']
    resolver=MechanicsResolver(w.data,metadata())
    assert len(resolver.gifts({'entityId':2,'enchantments':[effect]}))==1
    unknown=attached(cid='UNMAPPED')
    assert resolver.short_effects({'entityId':2,'enchantments':[unknown]})==['Dark Gift: unresolved [cardId=UNMAPPED]']
    # Same human name is not evidence of a gift or of which cardId it belongs to.
    unknown['rawTags'].pop('IS_NIGHTMARE_BONUS');unknown['name']='Blessing'
    assert not resolver.gifts({'entityId':2,'enchantments':[unknown]})


def test_multiple_gifts_retained_and_direct_link_dedup_uses_dbid_not_name():
    w=World();w.data['match']['build']=250339
    direct={'entityId':59,'cardId':'SPELL','rawTags':{}}
    effect=attached(CREATOR_DBID=102)
    other=attached(cid='OTHER',eid=61)
    e=w.card(2,'Enemy',cardId='ENEMY',darkGift=direct,enchantments=[effect,other])
    s=w.state(10,[],opponentBoard=[e]);w.combat(s)
    _,side=export_review(w.data,catalog=metadata())
    record=side['mechanics']['entities'][e]
    assert [r['cardId'] for r in record['darkGifts']]==['SPELL','OTHER']
    assert 'darkGift' not in record  # Do not silently choose one of multiple effects.
    assert record['darkGifts'][0]['attachmentEvidence'][0]['cardId']=='EFFECT'
    del effect['rawTags']['CREATOR_DBID']
    assert len(MechanicsResolver(w.data,metadata()).gifts(w.data['entityStates'][e]))==3


def test_effect_parameters_belong_to_each_observation_and_metadata_build_must_match():
    w=World();w.data['match']['build']=250339
    c=metadata();c['cards']['EFFECT']['text']='부여 +{0}'
    resolver=MechanicsResolver(w.data,c)
    a=resolver.gift_record({'entity':attached(TAG_SCRIPT_DATA_NUM_1=4),'evidence':'test','attachments':[]},{'entityId':2})
    b=resolver.gift_record({'entity':attached(TAG_SCRIPT_DATA_NUM_1=7),'evidence':'test','attachments':[]},{'entityId':3})
    # These are marked gift enchants without a declared slot 0 default: no entity-ID guessing.
    assert a['text']=='부여 +{0}?' and b['text']=='부여 +{0}?'
    c['cards']['EFFECT']['tags']['TAG_SCRIPT_DATA_NUM_1']=1
    assert resolver.rule(attached(TAG_SCRIPT_DATA_NUM_1=4))['text']=='부여 +4'
    assert resolver.rule(attached(TAG_SCRIPT_DATA_NUM_1=7))['text']=='부여 +7'
    c['build']='999';resolver=MechanicsResolver(w.data,c)
    assert resolver.rule(attached())['text'] is None


def test_full_show_attached_pipeline_and_retarget_does_not_rewrite_combat_snapshot(tmp_path):
    session=Session(tmp_path,'fixture','2026-09-14',metadata_options={'offline':True})
    prefix='D 12:00:02.9999999 GameState.DebugPrintPower() - '
    def feed(body):session.feed(prefix+body+'\n')
    for line in fixture().splitlines(True):
        if 'tag=3533 value=0' in line:break
        session.feed(line)
    feed('FULL_ENTITY - Creating ID=60 CardID=')
    feed('    tag=ZONE value=SETASIDE')
    feed('SHOW_ENTITY - Updating Entity=60 CardID=EFFECT')
    for key,value in [('CARDTYPE','ENCHANTMENT'),('ATTACHED',51),('CONTROLLER',10),('IS_NIGHTMARE_BONUS',1)]:
        feed(f'    tag={key} value={value}')
    feed('TAG_CHANGE Entity=60 tag=ZONE value=PLAY')
    feed('TAG_CHANGE Entity=4 tag=3533 value=0')
    m=session.match;s=m.data['snapshots'][m.current_turn()['combat']['startState']]
    ref=next(ref for ref in s['opponentBoard'] if m.data['entityStates'][ref]['entityId']==51)
    original=deepcopy(m.data['entityStates'][ref])
    assert original['enchantments'][0]['cardId']=='EFFECT' and 'darkGift' not in original
    projected=review_document(m.data)
    assert projected['entityStates'][ref]['enchantments'][0]['rawTags']['IS_NIGHTMARE_BONUS']==1
    assert projected['entityStates'][ref]['enchantments'][0]['rawTags']['ATTACHED']==51
    feed('TAG_CHANGE Entity=60 tag=ATTACHED value=33')
    assert not m.card_view(m.entities[51])['enchantments']
    assert m.card_view(m.entities[33])['enchantments'][0]['entityId']==60
    feed('TAG_CHANGE Entity=60 tag=ZONE value=GRAVEYARD')
    assert not m.card_view(m.entities[33])['enchantments']
    assert m.data['entityStates'][ref]==original
    session.close();assert session.errors==0
