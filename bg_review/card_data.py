"""Build-pinned, localized card metadata. Never silently substitute `latest`."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
import xml.etree.ElementTree as ET

_CACHE = {}


def default_cache():
    return Path(os.getenv('LOCALAPPDATA', Path.home())) / 'BattlegroundsReview/card-data'


def build_id(value):
    if value is None: return None
    value = str(value)
    if not re.fullmatch(r'[1-9][0-9]*', value): raise ValueError('Expected a numeric Hearthstone build')
    return value


def read_xml(path, locale='koKR'):
    """Read base, Bacon, or HDT locale CardDefs without loading the whole XML tree."""
    cards = {}
    context = ET.iterparse(path, events=('start', 'end'))
    _, root = next(context)
    build = build_id(root.get('build'))
    for event, entity in context:
        if event != 'end' or entity.tag != 'Entity': continue
        cid = entity.get('CardID')
        if not cid: continue
        tags, localized = {}, {}
        for tag in entity.findall('Tag'):
            name = tag.get('name') or tag.get('enumID')
            # Enum IDs are stable even when a dump uses CARDTEXT vs CARDTEXT_INHAND.
            name = {'184':'CARDTEXT', '185':'CARDNAME'}.get(tag.get('enumID'), name)
            if tag.get('type') == 'LocString':
                localized[name] = {x.tag: x.text or '' for x in tag}
            elif tag.get('value') is not None:
                raw = tag.get('value')
                tags[name] = int(raw) if re.fullmatch(r'-?\d+', raw) else raw
        name_values, text_values = localized.get('CARDNAME', {}), localized.get('CARDTEXT', {})
        text_locale = locale if text_values.get(locale) else 'enUS' if text_values.get('enUS') else None
        cards[cid] = {'id': cid, 'dbfId': int(entity.get('ID')) if entity.get('ID') else None,
                      'name': name_values.get(locale) or name_values.get('enUS'),
                      'text': text_values.get(text_locale) if text_locale else None,
                      'textLocale': text_locale, 'englishText': text_values.get('enUS'),
                      'names': name_values, 'texts': text_values, 'tags': tags,
                      'techLevel': tags.get('TECH_LEVEL'), 'typeId': tags.get('CARDTYPE'),
                      'sourceFile': Path(path).name}
        entity.clear(); root.clear()
    return build, cards


def read_keywords(path):
    strings = {}
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        parts = line.split('\t')
        if len(parts) >= 2: strings[parts[0]] = parts[1]
    return {key: {'name': value, 'text': strings[key+'_TEXT']}
            for key, value in strings.items() if key.startswith('GLOBAL_KEYWORD_')
            and not key.endswith(('_TEXT','_TOOLTIP')) and strings.get(key+'_TEXT')}


def read_races(path):
    # HearthSim Race enum/name_global; BEAST is localized under the historical PET key.
    keys={11:'UNDEAD',14:'MURLOC',15:'DEMON',17:'MECHANICAL',18:'ELEMENTAL',20:'PET',
          23:'PIRATE',24:'DRAGON',26:'ALL',43:'QUILBOAR',92:'NAGA'}
    strings={line.split('\t')[0]:line.split('\t')[1] for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if '\t' in line}
    return {str(n):strings['GLOBAL_RACE_'+key] for n,key in keys.items() if 'GLOBAL_RACE_'+key in strings}


def catalog_from_xml(paths, build, locale='koKR', sources=None, keywords=None):
    build = build_id(build)
    cards = {}
    for path in paths:
        actual, rows = read_xml(path, locale)
        if actual != build: raise ValueError(f'CardDefs build {actual} != match build {build}')
        for cid, row in rows.items():
            previous = cards.get(cid, {})
            merged = {**previous, **row}
            for field in ('tags','names','texts'): merged[field] = {**previous.get(field,{}),**row.get(field,{})}
            merged['textLocale'] = locale if merged['texts'].get(locale) else 'enUS' if merged['texts'].get('enUS') else None
            merged['text'] = merged['texts'].get(merged['textLocale'])
            merged['name'] = merged['names'].get(locale) or merged['names'].get('enUS')
            merged['techLevel'] = merged['tags'].get('TECH_LEVEL')
            merged['typeId'] = merged['tags'].get('CARDTYPE')
            cards[cid] = merged
    return {'catalogVersion': 1, 'build': build, 'locale': locale, 'cards': cards,
            'keywords': keywords or {}, 'sources': sources or [{'path':str(Path(p).resolve()),
             'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()} for p in paths]}


def read_catalog(path, build, locale):
    path = Path(path)
    if path.is_dir():
        paths = [path/x for x in ('CardDefs.base.xml','CardDefs.xml','CardDefs.Bacon.xml',f'CardDefs.{locale}.xml') if (path/x).exists()]
        if not paths: raise ValueError(f'No CardDefs in {path}')
        return catalog_from_xml(paths, build, locale)
    if path.suffix.lower() == '.xml': return catalog_from_xml([path], build, locale)
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict) or data.get('catalogVersion') != 1:
        raise ValueError('Rules require a versioned catalog, not an unversioned cards.json list')
    if str(data.get('build')) != build: raise ValueError('Card catalog build mismatch')
    if data.get('locale') != locale: raise ValueError('Card catalog locale mismatch')
    return data


def _download(url, path):
    request = urllib.request.Request(url, headers={'User-Agent':'BattlegroundsReview/0.4'})
    with urllib.request.urlopen(request, timeout=25) as response: data = response.read()
    path.write_bytes(data)
    return {'url':url, 'sha256':hashlib.sha256(data).hexdigest()}


def prepare_catalog(build, locale='koKR', cache=None, source=None):
    build = build_id(build)
    if not build: raise ValueError('A known match build is required')
    if not re.fullmatch(r'[a-z]{2}[A-Z]{2}',locale): raise ValueError('Invalid locale')
    directory = Path(cache or default_cache()) / build
    directory.mkdir(parents=True,exist_ok=True)
    if source:
        catalog = read_catalog(source,build,locale)
    else:
        # Resolve an exact build tag to an immutable commit; do not fetch master/latest.
        url = f'https://api.github.com/repos/HearthSim/hsdata/git/ref/tags/{build}'
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'BattlegroundsReview/0.4'}),timeout=20) as r:
            tag = json.load(r)
        obj = tag['object']
        if obj['type'] == 'tag':
            with urllib.request.urlopen(obj['url'],timeout=20) as r: obj = json.load(r)['object']
        commit = obj['sha']
        if obj['type'] != 'commit' or not re.fullmatch(r'[0-9a-f]{40}',commit): raise ValueError('Invalid hsdata commit')
        base = f'https://raw.githubusercontent.com/HearthSim/hsdata/{commit}/'
        paths, sources = [], []
        for name in ('CardDefs.xml','CardDefs.Bacon.xml'):
            path = directory / name
            sources.append(_download(base+name,path)); paths.append(path)
        keywords, races = {}, {}
        for lang in dict.fromkeys(('enUS',locale)):
            name = f'GLOBAL.{lang}.txt'; path = directory/name
            try:
                sources.append(_download(base+f'Strings/{lang}/GLOBAL.txt',path))
                for key, value in read_keywords(path).items(): keywords[key] = {**value,'locale':lang}
                races.update(read_races(path))
            except (OSError,ValueError): pass  # Card rules remain usable without global strings.
        catalog = catalog_from_xml(paths,build,locale,sources,keywords)
        catalog['commit'] = commit
        catalog['races'] = races
    catalog['cachedAt'] = datetime.now(timezone.utc).isoformat()
    dest = directory / f'{locale}.json'; temp = dest.with_suffix('.json.tmp')
    temp.write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    os.replace(temp,dest)
    return catalog


def load_catalog(build, locale='koKR', cache=None, source=None, fetch=False):
    build = build_id(build)
    if not build: return None
    if source: return read_catalog(source,build,locale)
    # The installed HDT cache wins when its XML build actually matches the match.
    for root in (os.getenv('APPDATA'), os.getenv('LOCALAPPDATA')):
        if not root: continue
        path = Path(root)/'HearthstoneDeckTracker/CardDefs'
        if path.is_dir():
            signature = tuple((str(p),p.stat().st_mtime_ns) for p in path.glob('*.xml'))
            key = ('hdt',build,locale,signature)
            if key not in _CACHE:
                try: _CACHE[key] = read_catalog(path,build,locale)
                except (OSError,ValueError,ET.ParseError): _CACHE[key] = None
            if _CACHE[key]: return _CACHE[key]
    for path in (Path('cards')/build/f'{locale}.json',Path(cache or default_cache())/build/f'{locale}.json'):
        if path.exists():
            key = str(path.resolve()),path.stat().st_mtime_ns,build,locale
            if key not in _CACHE: _CACHE[key] = read_catalog(path,build,locale)
            return _CACHE[key]
    return prepare_catalog(build,locale,cache) if fetch else None


def catalog_or_unresolved(build, **kwargs):
    """Metadata outages must never prevent saving the gameplay truth/decision log."""
    try:return load_catalog(build,**kwargs)
    except (OSError,ValueError,KeyError,ET.ParseError) as exc:
        return {'catalogVersion':1,'build':str(build),'locale':kwargs.get('locale','koKR'),
                'cards':{},'sources':[],'error':f'{type(exc).__name__}: {exc}'}
