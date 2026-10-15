"""Compare an enriched export to a saved compact review and immutable source JSON.

Run from the project root: python -m scripts.verify_semantic_review INPUT BASELINE_REVIEW
The optional --output writes a local verification report (may contain card names).
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re

from bg_review.card_data import catalog_or_unresolved
from bg_review.compact_review import CompactReviewWriter, export_review
from bg_review.exporter import markdown
from bg_review.mechanics import chosen_option, choice_number
from bg_review.review_exporter import decision_points, choice_points
from bg_review.validate import validate_document, validate_dictionary


def action_sequence(text):
    """Expand compact ranges without requiring the old grouping boundaries."""
    result = []
    for ids, action in re.findall(r'\*\*(a\d+(?:,a\d+)*(?:–a\d+)?) ([A-Z_]+)', text):
        if '–' in ids:
            first, last = ids.split('–')
            members = [f'a{i}' for i in range(int(first[1:]), int(last[1:])+1)]
        else: members = ids.split(',')
        result.extend((aid, action) for aid in members)
    return result


def verify(data, baseline, dictionary_name='match.dictionary.json'):
    original=deepcopy(data)
    catalog=catalog_or_unresolved(data['match'].get('build'))
    writer=CompactReviewWriter(data,dictionary_name,catalog)
    text=writer.render()
    exported,side=export_review(data,dictionary_name=dictionary_name,catalog=catalog)
    assert text==exported and data==original
    assert not validate_document(data) and not validate_dictionary(side)
    # Grouping can change; the complete action order and shop/choice boundaries cannot.
    assert action_sequence(text) == action_sequence(baseline)
    for pattern in (r'\*\*Shop (Q\d+\.\d+)',r'(D\d+\.\d+)'):
        assert re.findall(pattern,text)==re.findall(pattern,baseline),pattern
    events=[e for t in data['turns'] for e in t['events']]
    shown=[aid for group in side['actionGroups'] for aid in group]
    hidden=set(side['suppressedReorders'])
    assert shown==[e['id'] for e in events if e['id'] not in hidden]
    assert all(e['action']=='REORDER' for e in events if e['id'] in hidden)
    assert side['result']==data['result']
    choices=[]
    for turn in data['turns']:
        n=turn['turn']
        section=text.split(f'## Turn {n}',1)[1].split('\n## Turn ',1)[0]
        shops=[side['snapshots'][sid] for q,sid in side['observations'].items() if q.startswith(f'Q{n}.')]
        for point in decision_points(data,turn):
            s=data['snapshots'][point['state']]
            if s['phase']=='RECRUIT':
                assert any(writer.shop_signature(x)==writer.shop_signature(s) for x in shops)
        # Every printed shop (including reappearances) must expand from its own
        # observed state, and deltas may only reference the preceding shown shop.
        previous, previous_id = None, None
        for qid, repeated, payload in re.findall(r'\*\*Shop (Q\d+\.\d+)( 재등장)?\*\*(?:: ([^\n]*))?', section):
            s = data['snapshots'][side['observations'][qid]]
            if not repeated:
                assert payload == writer.shop_text(s['shop'], previous, previous_id), qid
            previous, previous_id = s['shop'], qid
        for point in choice_points(data,turn):
            choice=data['snapshots'][point['state']]['choices']
            for i,ref in enumerate(choice['offered']):
                assert f'{choice_number(choice,i)}. {writer.card(ref)}' in section
        if sid:=turn.get('startState'):
            s=data['snapshots'][sid]
            assert 'Board: '+writer.cards_line(s['board']) in section
            assert 'Hand: '+writer.cards_line(s['hand']) in section
        if c:=turn.get('combat'):
            s=data['snapshots'][c['startState']]
            own,enemy=section.split('**Final combat board**',1)[1].split('Opponent board',1)
            for i,ref in enumerate(s['board'],1):assert f'{i}. {writer.card(ref)}' in own
            for i,ref in enumerate(s['opponentBoard'],1):assert f'{i}. {writer.card(ref)}' in enemy
            assert f"Result: **{c['result']}**" in section
            for key in ('damageTaken','damageDealt','result'):assert side['combats'][str(n)][key]==c[key]
        for e in turn['events']:
            if e['action']=='CHOOSE':
                index=chosen_option(data,e)
                assert 'Chosen: '+(f'{index}. ' if index is not None else '')+writer.card(e['target']) in section
                choices.append({'action':e['id'],'turn':n,'index':index,'name':writer.base_name(data['entityStates'][e['target']])})
    for ref,e in side['entityStates'].items():
        for key in ('cardId','entityId','attack','health','keywords','golden','cost','rawTags'):
            assert e.get(key)==data['entityStates'][ref].get(key)
    relevant=side['mechanics']['relevant']
    issues=[{'cardId':cid,'name':entry['rule']['name'],'status':entry['rule']['status'],
             'unresolvedParameters':entry['rule']['unresolvedParameters'],'conflicts':entry['rule']['conflicts']}
            for cid,entry in relevant.items() if entry['rule']['status'] not in ('resolved','no_rules_text') or entry['rule']['conflicts']]
    return text,side,{'before':{'lines':len(baseline.splitlines()),'chars':len(baseline)},
                      'after':{'lines':len(text.splitlines()),'chars':len(text)},
                      'coverage':writer.metrics,'actions':dict(Counter(e['action'] for e in events)),
                      'choices':choices,'mechanicIssues':issues,'checks':'passed'}


def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('baseline',type=Path)
    p.add_argument('--output',type=Path);p.add_argument('--baseline-audit',type=Path)
    args=p.parse_args();data=json.loads(args.input.read_text(encoding='utf-8'))
    if args.baseline_audit:assert markdown(data).encode('utf-8')==args.baseline_audit.read_bytes()
    text,side,metrics=verify(data,args.baseline.read_text(encoding='utf-8'),args.input.with_suffix('.dictionary.json').name)
    if args.output:args.output.write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
