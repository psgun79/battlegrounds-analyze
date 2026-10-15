"""Semantic checks JSON Schema cannot express (cross-references and causality)."""
import re


def validate_document(d):
    errors = []
    pools = {"s": d["snapshots"], "e": d["entityStates"], "o": d["optionSets"]}
    def walk(value):
        if isinstance(value, str) and re.fullmatch(r"(?:s\d+|e\d+v\d+|o[0-9a-f]{16})",value):
            if value not in pools[value[0]]: errors.append(f"Dangling reference: {value}")
        elif isinstance(value, dict):
            for v in value.values(): walk(v)
        elif isinstance(value, list):
            for v in value: walk(v)
    walk(d)
    previous = -1
    for t in d["turns"]:
        for e in t["events"]:
            if e["sequence"] < previous: errors.append(f"Out-of-order event: {e['id']}")
            previous = e["sequence"]
            before = d["snapshots"].get(e["stateBefore"])
            if before and before["sequence"] > e["sequence"]: errors.append(f"Future state used before {e['id']}")
            if e["stateAfter"] is not None and e["stateAfter"] not in d["snapshots"]: errors.append(f"Missing after state: {e['id']}")
    if d["result"]["status"] != "completed" and d["result"]["placement"] is not None:
        errors.append("Partial game must not report live leaderboard rank as final placement")
    return errors


def validate_dictionary(d):
    """Validate sidecar references without interpreting arbitrary raw tag strings."""
    errors = []
    def require(key, pool, label):
        if key is not None and key not in pool: errors.append(f'Missing {label}: {key}')
    for e in d['entityStates'].values():
        require(e['card'], d['cards'], 'card')
        for f in e['effects']: require(f, d['effects'], 'effect')
        require(e.get('darkGift'), d['effects'], 'dark gift')
    for f, value in d['effectTemplates'].items():
        require(f, d['effects'], 'effect')
        require(value['template'], d['templates'], 'template')
    for sid in d['observations'].values(): require(sid, d['snapshots'], 'observation state')
    for s in d['snapshots'].values():
        refs = [s.get('hero'), s.get('opponentHero')]
        for zone in ('board', 'hand', 'shop', 'heroPowers', 'opponentBoard', 'lobbyHeroes', 'buttons'): refs.extend(s.get(zone, []))
        refs.extend(s.get('season', {}).get('entities', []))
        refs.extend((s.get('choices') or {}).get('offered', []))
        for ref in refs: require(ref, d['entityStates'], 'snapshot entity')
        require(s.get('options'), d.get('optionSets', {}), 'options')
    for action in d['actions'].values():
        for key in ('stateBefore', 'stateAfter'): require(action.get(key), d['snapshots'], 'action state')
        for key in ('actor', 'target'): require(action.get(key), d['entityStates'], 'action entity')
    ids = [aid for group in d['actionGroups'] for aid in group] + d['suppressedReorders']
    if len(ids) != len(set(ids)) or set(ids) != set(d['actions']): errors.append('Action groups/reorders do not partition original actions')
    return errors
