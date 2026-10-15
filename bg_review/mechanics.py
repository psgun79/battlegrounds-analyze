"""Semantic projection over immutable observations; no state mutation or inferred rules."""
import html
import json
from pathlib import Path
import re

BINDINGS = json.loads(Path(__file__).with_name('parameter_bindings.json').read_text(encoding='utf-8'))


def plain_text(text):
    text = html.unescape(text or '').replace('[x]','').replace('\\n',' ')
    text = re.sub(r'<[^>]*>', '', text).replace('_',' ')
    text = re.sub(r'\|\d+\(([^,]*),([^)]*)\)',r'(\1/\2)',text)
    return re.sub(r'\s+',' ',text).strip()


def choice_number(choice, position):
    indices = choice.get('offeredIndices')
    if indices is None: return position + 1  # Legacy JSON: ordinal in the actual displayed list.
    if len(indices) != len(choice['offered']) or len(set(indices)) != len(indices): return None
    index = indices[position]
    return index + 1 if isinstance(index,int) and index >= 0 else None


def chosen_option(data, event):
    s = data['snapshots'].get(event.get('stateBefore'), {})
    choice = s.get('choices') or {}
    if choice.get('id') != event.get('choiceId'): return None
    target = data['entityStates'].get(event.get('target'), {}).get('entityId')
    if target is None: return None
    hits = [i for i, ref in enumerate(choice.get('offered', []))
            if data['entityStates'].get(ref, {}).get('entityId') == target]
    return choice_number(choice,hits[0]) if len(hits) == 1 else None


class MechanicsResolver:
    def __init__(self, data, catalog=None):
        self.data = data
        self.catalog = catalog or {}
        build = data.get('match',{}).get('build')
        self.compatible = bool(catalog and build is not None and str(build)==str(catalog.get('build')))
        self.cards = self.catalog.get('cards',{}) if self.compatible else {}
        self.by_dbf = {c['dbfId']:c for c in self.cards.values() if c.get('dbfId') is not None}
        self.relevant = {}
        self.records = {}
        self.entity_ids = {}
        for e in data.get('entityStates',{}).values():
            if e.get('cardId'): self.entity_ids.setdefault(e['entityId'],set()).add(e['cardId'])

    def hero_power(self, entity):
        meta=self.cards.get(entity.get('cardId'),{})
        card=self.by_dbf.get(meta.get('tags',{}).get('HERO_POWER'))
        return {'cardId':card['id'],'name':card.get('name'),'rawTags':{}} if card else None

    def rule(self, entity):
        cid = entity.get('cardId')
        meta = self.cards.get(cid,{})
        template = plain_text(meta.get('text'))
        params, defaults = {}, {}
        for slot in sorted(set(re.findall(r'\{(\d+)\}',template)),key=int):
            tag = f'TAG_SCRIPT_DATA_NUM_{int(slot)+1}'
            # A slot is bound only if the versioned card definition declares its numeric
            # tag. An arbitrary observed script value may instead be an entity ID.
            binding=BINDINGS['cards'].get(cid,{}).get(slot)
            default=meta.get('tags',{}).get(tag)
            observed=entity.get('rawTags',{}).get(tag)
            token=re.escape('{'+slot+'}')
            numeric=bool(re.search(r'(?:[+/$]|(?:사용|복수|Activate|Avenge)\s*\()'+token+r'|'+token+r'\s*(?:/|%|골드|턴|번|개|마리|장|단계)',template,re.I))
            if binding and binding['type']=='race':
                races=self.catalog.get('races',{})
                if str(default) in races:defaults[slot]=races[str(default)]
                value=races.get(str(observed))
                if value:params[slot]={'value':value,'source':'observed','tag':tag,'type':'race','rawValue':observed}
                # A randomized race default is not the race offered in this match.
                continue
            if not numeric:continue
            if entity.get('rawTags',{}).get('IS_NIGHTMARE_BONUS') and slot=='0' and default is None:continue
            if isinstance(default,int):defaults[slot]=default
            if isinstance(observed,int) or slot in defaults:
                params[slot]={'value':observed if isinstance(observed,int) else defaults[slot],
                              'source':'observed' if isinstance(observed,int) else 'database_default','tag':tag,'type':'number'}
        def bind(m):
            slot=m[1]
            return str(params[slot]['value']) if slot in params else '{'+slot+'}?'
        text = re.sub(r'\{(\d+)\}',bind,template)
        unresolved = sorted(set(re.findall(r'\{(\d+)\}',text)),key=int)
        conflicts = []
        tier = entity.get('tavernTier')
        if tier is not None and meta.get('techLevel') is not None and tier != meta['techLevel']:
            conflicts.append(f"관측 T{tier} / DB T{meta['techLevel']}")
        status = 'resolved' if template else 'no_rules_text' if meta else 'unresolved'
        if unresolved: status = 'parameters_unresolved'
        dynamic = None
        if re.search(r'#(?:ALT|PL|EXPANDLIST)\(', template):
            # Client display macros have their own grammar. Preserve the original
            # template in the sidecar; never split @3 into supposed display branches.
            dynamic = 'client_macro'
            text = 'unresolved (클라이언트 동적 표시식; 효과 자동 해석 불가)'
        elif '@' in template:
            numeric_at = r'@(?!\d)(?=\s*(?:단계|장|개|마리|회|턴|골드|Tier|cards?\b))'
            if len(re.findall(numeric_at, template, re.I)) == template.count('@'):
                tags = entity.get('rawTags', {})
                for tag in ('TAG_SCRIPT_DATA_NUM_1', 'SCORE_VALUE_1'):
                    value = tags.get(tag, meta.get('tags', {}).get(tag))
                    if isinstance(value, int):
                        params['@'] = {'value':value, 'source':'observed' if tag in tags else 'database_default', 'tag':tag,'type':'number'}
                        if isinstance(meta.get('tags',{}).get(tag),int): defaults['@']=meta['tags'][tag]
                        text = re.sub(numeric_at, str(value), text, flags=re.I)
                        break
                else: dynamic = 'numeric_at_unresolved'
            else: dynamic = 'display_variant_unresolved'
        if dynamic:
            status = dynamic
            if dynamic != 'client_macro':text += ' (unresolved: 동적 표시/적용 분기 미확정)'
        if conflicts and status == 'resolved': status = 'resolved_with_metadata_conflict'
        related = []
        for tag in ('CREATOR_DBID','ENCHANTMENT_SOURCE_DBID'):
            other = self.by_dbf.get(entity.get('rawTags',{}).get(tag))
            if other: related.append({'relation':tag,'cardId':other['id'],'name':other.get('name'),
                                      'note':'relationship only; never substituted for this effect'})
        return {'cardId':cid,'dbfId':meta.get('dbfId'), 'name':meta.get('name') or entity.get('name'),
                'text':text or None,'template':template or None,'rawText':meta.get('text'),
                'status':status,'locale':meta.get('textLocale'), 'build':self.catalog.get('build') if meta else None,
                'parameters':params,'defaults':defaults,'unresolvedParameters':unresolved,'dynamicFormat':dynamic,'conflicts':conflicts,
                'related':related,'sourceFile':meta.get('sourceFile')}

    def gift(self, entity):
        if entity.get('darkGift'): return entity['darkGift']
        linked = entity.get('rawTags',{}).get('DARK_GIFT_ENTITY')
        if linked:
            ids = self.entity_ids.get(linked,set())
            # Static identity may be recovered, but never borrow future parameter values.
            return {'entityId':linked,'cardId':next(iter(ids)) if len(ids)==1 else None,'rawTags':{}}
        return None

    def gifts(self, entity):
        """Observed gift links, including opponent combat copies with no spell link.

        An attached enchantment's own cardId/text remains authoritative. A creator
        DBID is relationship evidence, never a replacement tooltip or parameter set.
        """
        result = []
        direct = self.gift(entity)
        if direct:
            result.append({'entity':direct, 'evidence':'DARK_GIFT_ENTITY', 'attachments':[]})
        direct_dbf = self.cards.get((direct or {}).get('cardId'),{}).get('dbfId')
        for effect in entity.get('enchantments',[]):
            tags = effect.get('rawTags',{})
            if tags.get('ZONE') in ('GRAVEYARD','REMOVEDFROMGAME'):continue
            if tags.get('ATTACHED') is not None and tags['ATTACHED'] != entity.get('entityId'):continue
            meta = self.cards.get(effect.get('cardId'),{})
            # An explicit false flag overrides metadata. No name/suffix/stat guessing.
            flag = tags.get('IS_NIGHTMARE_BONUS',meta.get('tags',{}).get('IS_NIGHTMARE_BONUS'))
            if flag != 1:continue
            if direct and (effect.get('entityId') == direct.get('entityId') or
                           (direct_dbf is not None and tags.get('CREATOR_DBID') == direct_dbf)):
                result[0]['attachments'].append(effect)
            else:
                result.append({'entity':effect,'evidence':'ATTACHED+IS_NIGHTMARE_BONUS','attachments':[]})
        return result

    def gift_record(self, link, target):
        effect=link['entity']
        return {**self.rule(effect), 'effectEntityId':effect.get('entityId'),
                'appliedToEntityId':target['entityId'], 'linkEvidence':link['evidence'],
                'rawTags':effect.get('rawTags',{}),
                'attachmentEvidence':[{'entityId':e.get('entityId'),'cardId':e.get('cardId'),
                                       'rawTags':e.get('rawTags',{}),'rule':self.rule(e)} for e in link['attachments']]}

    def short_effects(self, entity):
        names = []
        for e in entity.get('enchantments',[]):
            rule=self.rule(e)
            name=rule.get('name')
            if name and not re.search(r'\[DNT\]|dummy|player ench',name,re.I): names.append(name)
        labels = []
        for link in self.gifts(entity):
            gift=link['entity']
            rule=self.rule(gift)
            names = [name for name in names if name != rule.get('name')]
            labels.append('Dark Gift: '+rule['name'] if rule.get('text') and rule.get('name') else
                         f"Dark Gift: unresolved [cardId={gift.get('cardId') or '?'}]")
        return list(dict.fromkeys(labels + names))

    def parameter_summary(self, entity):
        rule = self.rule(entity)
        values = [f"{{{slot}}}={p['value']}" for slot,p in rule['parameters'].items()
                  if p['source']=='observed' and p['value'] != rule['defaults'].get(slot)]
        return ('수치 '+','.join(values)) if values else ''

    def include(self, entity, reason, required=True, _seen=None):
        cid=entity.get('cardId')
        if not cid: return
        seen=_seen or set()
        if cid in seen:return
        seen=seen|{cid}
        rule=self.rule(entity)
        if cid not in self.relevant:
            if not required and (not rule.get('text') or re.search(r'\[DNT\]|dummy|player ench',rule.get('name') or '',re.I)): return
            self.relevant[cid]={'entity':entity,'rule':rule,'reasons':[]}
        entry=self.relevant[cid]
        if reason not in entry['reasons']: entry['reasons'].append(reason)
        for warning in rule['conflicts']:
            if warning not in entry['rule']['conflicts']:entry['rule']['conflicts'].append(warning)
        for link in self.gifts(entity):self.include(link['entity'],'Dark Gift',_seen=seen)
        if power:=self.hero_power(entity):self.include(power,'hero choice power',_seen=seen)
        for effect in entity.get('enchantments',[]): self.include(effect,'modifier',required=False,_seen=seen)

    def collect(self):
        from .review_exporter import choice_points, decision_points
        entities=self.data['entityStates']
        for turn in self.data['turns']:
            for sid in (turn.get('startState'),(turn.get('combat') or {}).get('startState')):
                if not sid: continue
                s=self.data['snapshots'][sid]
                for zone in ('board','hand','heroPowers'):
                    for ref in s.get(zone,[]):self.include(entities[ref],zone)
                for ref in s.get('season',{}).get('entities',[]):self.include(entities[ref],'season')
            if combat:=turn.get('combat'):
                s=self.data['snapshots'][combat['startState']]
                for ref in s.get('opponentBoard',[]):
                    self.include(entities[ref], 'opponent board')
            # Unbought options need rules too: a single uploaded review must let
            # the reader compare an actual choice with its available alternatives.
            for point in decision_points(self.data, turn):
                s = self.data['snapshots'][point['state']]
                if s['phase'] == 'RECRUIT':
                    for ref in s.get('shop', []): self.include(entities[ref], 'offered shop')
            for event in turn['events']:
                fields = {'BUY':('target',),'PLAY':('actor',),'ACTIVATE':('actor','target'),
                          'HERO_POWER':('actor',),'SPELL_USE':('actor',),'TRINKET_USE':('actor',),
                          'DARK_GIFT':('actor',),'CHOOSE':('target',)}.get(event['action'],())
                for key in fields:
                    if event.get(key):self.include(entities[event[key]],event['action'])
            for point in choice_points(self.data,turn):
                for ref in self.data['snapshots'][point['state']]['choices']['offered']:
                    self.include(entities[ref],'choice')

    def choice_lines(self, entity):
        rule=self.rule(entity)
        if rule.get('text'):
            text=rule['text'] if len(rule['text'])<=220 else f"Relevant mechanics [{entity.get('cardId')}] 참조"
            if rule['conflicts']:text+=' (DB/관측 단계 불일치; 적용 규칙 미확정)'
            lines=['   Card: '+text]
        elif rule['status']=='no_rules_text' and not self.hero_power(entity):
            lines=['   Card: 규칙 텍스트 없음(데이터)']
        elif self.catalog and not self.hero_power(entity):
            lines=[f"   Card: unresolved [cardId={entity.get('cardId') or '?'}]"]
        else: lines=[]
        if power:=self.hero_power(entity):
            p=self.rule(power)
            lines.append('   Hero Power: '+(p['name'] or power['cardId'])+' — '+(p['text'] or 'unresolved'))
        gift_links=self.gifts(entity)
        gift_entities={link['entity'].get('entityId') for link in gift_links}
        for link in gift_links:
            gift=link['entity']
            g=self.rule(gift)
            text=(g['name'] or gift.get('cardId') or '?')+' — '+g['text'] if g.get('text') else f"unresolved [cardId={gift.get('cardId') or '?'}]"
            lines.append('   Dark Gift: '+text)
        for effect in entity.get('enchantments',[]):
            if effect.get('entityId') in gift_entities:continue
            r=self.rule(effect)
            if r.get('text') and r.get('name') and not re.search(r'\[DNT\]|dummy|player ench',r['name'],re.I):
                lines.append('   Modifier: '+r['name']+' — '+r['text'])
        return lines

    def section(self):
        if not self.catalog: return ['', '규칙 데이터: unresolved (이 빌드에 맞는 카드 카탈로그 없음).']
        self.collect()
        lines=['','## Relevant mechanics','',
               f"카드 데이터: build {self.catalog.get('build')} · {self.catalog.get('locale')} 우선/enUS fallback · cardId 기준.",
               '규칙의 {0}, {1} 등은 카드별 변수. DB 기준값과 다른 관측값은 본문 카드의 ‘수치’에 표시. DB 기준은 당시 관측값을 대체하지 않음.',
               '스탯·단계는 로그 우선. DB와 충돌한 규칙은 현행 적용 여부를 확정하지 말 것. 미확인 변수/효과는 unresolved.', '']
        if self.catalog.get('error'):lines.append('규칙 데이터 unresolved: '+self.catalog['error'])
        all_text=' '.join(x['rule'].get('template') or '' for x in self.relevant.values())
        seen=set()
        for key,entry in self.catalog.get('keywords',{}).items():
            name=plain_text(entry['name']);needle=name.split('(')[0].strip()
            if len(needle)>1 and needle in all_text and name not in seen:
                lines.append(f"- 용어 {name}: {plain_text(entry['text'])}");seen.add(name)
        for cid,entry in self.relevant.items():
            rule=entry['rule']; e=entry['entity']
            if rule['status']=='no_rules_text':continue
            label=(rule['name'] or e.get('name') or cid)+f' [{cid}]'
            if e.get('golden'):label+=' Golden'
            text=(rule['text'] if rule['dynamicFormat']=='client_macro' else rule.get('template')) or 'unresolved (일치하는 실제 규칙 텍스트 없음)'
            if rule['defaults']:text+=' · DB 기준 '+','.join('{'+k+'}='+str(v) for k,v in rule['defaults'].items())
            if rule['unresolvedParameters']:text+=' · unresolved 변수 '+','.join(rule['unresolvedParameters'])
            if rule['dynamicFormat'] and rule['dynamicFormat'] != 'client_macro':text+=' · unresolved 동적 표시/적용 분기 (@ 원문 유지)'
            if rule['conflicts']:text+=' · ⚠ '+', '.join(rule['conflicts'])+'; 규칙 적용 버전 미확정'
            if rule.get('locale')=='enUS':text+=' [enUS fallback]'
            lines.append('- '+label+' — '+text)
        return lines

    def sidecar(self, refs):
        entities=self.data['entityStates']
        records={ref:self.rule(entities[ref]) for ref in refs}
        for ref in refs:
            e=entities[ref]
            records[ref]['enchantments']=[self.rule(x) for x in e.get('enchantments',[])]
            links=self.gifts(e)
            records[ref]['darkGifts']=[self.gift_record(link,e) for link in links]
            # Keep the legacy singular field only when the connection is unambiguous.
            if len(links)==1:records[ref]['darkGift']=records[ref]['darkGifts'][0]
            if power:=self.hero_power(e):records[ref]['heroPower']=self.rule(power)
        return {'catalogVersion':self.catalog.get('catalogVersion'),'build':self.catalog.get('build'),
                'locale':self.catalog.get('locale'),'sources':self.catalog.get('sources',[]),
                'commit':self.catalog.get('commit'),'entities':records,
                'error':self.catalog.get('error'),
                'relevant':{cid:{'rule':e['rule'],'reasons':e['reasons']} for cid,e in self.relevant.items()}}
