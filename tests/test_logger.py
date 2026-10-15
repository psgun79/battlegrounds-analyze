import json
from pathlib import Path

import pytest

from bg_review.cli import main
from bg_review.exporter import markdown
from bg_review.parser import PowerParser
from bg_review.storage import Journal, Session, Tail
from make_fixture import fixture


def run(tmp_path, text=None):
    s = Session(tmp_path, "fixture", "2026-09-14")
    for line in (fixture() if text is None else text).splitlines(True): s.feed(line)
    s.close()
    assert s.errors == 0
    return s, s.match.data


def test_full_match_decisions(tmp_path):
    s, d = run(tmp_path)
    events = [e for t in d["turns"] for e in t["events"]]
    assert [e["action"] for e in events] == ["ROLL","BUY","PLAY","SELL","TAVERN_UPGRADE","FREEZE","UNFREEZE","DARK_GIFT","CHOOSE","HERO_POWER"]
    assert [e["sequence"] for e in events] == sorted(e["sequence"] for e in events)
    assert d["result"]["placement"] == 7
    assert d["result"]["status"] == "completed"
    assert d["match"]["localPlayerId"] == 2
    roll = events[0]
    before, after = (d["snapshots"][roll[k]] for k in ("stateBefore","stateAfter"))
    assert [d["entityStates"][r]["cardId"] for r in before["shop"]] == ["FIX_OLD_OPTION","FIX_MISSED_ENGINE"]
    assert [d["entityStates"][r]["cardId"] for r in after["shop"]] == ["FUTURE_UNKNOWN_CARD"]
    assert (before["remainingGold"],after["remainingGold"],roll["goldDelta"]) == (10,9,-1)
    assert d["entityStates"][after["shop"][0]]["rawTags"]["NEW_SEASON_RESOURCE"] == 9
    assert d["entityStates"][after["shop"][0]]["name"] is None
    assert d["entityStates"][after["shop"][0]]["rawTags"]["ZONE"] == "PLAY"  # historical copy cannot become graveyard
    choose = events[-2]
    assert len(d["snapshots"][choose["stateBefore"]]["choices"]["offered"]) == 2
    combat = d["turns"][1]["combat"]
    start = d["snapshots"][combat["startState"]]
    assert len(start["board"]) == len(start["opponentBoard"]) == 1
    assert combat["damageTaken"] == 9 and combat["result"] == "loss"
    assert combat["captureMethod"] == "setup_tag_3533"
    assert sum(e["type"] == "ATTACK" for e in combat["events"]) == 2
    assert len(s.paths) == 1 and s.paths[0].with_suffix(".audit.md").exists()
    assert s.paths[0].with_suffix(".review.md").exists()
    md = markdown(d)
    assert "FIX_MISSED_ENGINE" in md and "FIX_CHOICE_A" in md and "Placement 7" in md


def test_animation_stream_does_not_double_actions(tmp_path):
    text = "".join(line + line.replace("GameState.DebugPrintPower", "PowerTaskList.DebugPrintPower")
                   if "GameState.DebugPrintPower" in line else line for line in fixture().splitlines(True))
    _, d = run(tmp_path, text)
    assert sum(e["action"] == "BUY" for t in d["turns"] for e in t["events"]) == 1


def test_partial_action_is_not_completed(tmp_path):
    text = fixture().split("BLOCK_START BlockType=PLAY Entity=21")[0]
    text = text.rsplit("D ",1)[0] + "D 12:01:00.0000000 GameState.DebugPrintPower() - BLOCK_START BlockType=PLAY Entity=21 EffectCardId= EffectIndex=0 Target=32 SubOption=-1\n"
    _, d = run(tmp_path,text)
    last = d["turns"][-1]["events"][-1]
    assert last["action"] == "BUY" and last["stateAfter"] is None
    assert d["result"]["status"] == "incomplete" and d["result"]["placement"] is None


def test_multiple_matches_and_non_bg(tmp_path):
    s, _ = run(tmp_path,fixture()+fixture())
    assert len(s.paths) == 2
    other = tmp_path / "other"
    text = fixture().replace("tag=BACON_DUMMY_PLAYER value=1", "tag=DUMMY value=1").replace("GT_BATTLEGROUNDS", "GT_RANKED")
    s, _ = run(other,text)
    assert not s.paths


def test_tail_partial_utf8_truncate_regrow_and_replace(tmp_path):
    p = tmp_path / "Power.log"; p.write_bytes(b"")
    tail = Tail(p)
    payload = "상점 로그\n".encode()
    p.write_bytes(payload[:2]); assert tail.poll()[0] == []
    with p.open("ab") as f: f.write(payload[2:])
    assert tail.poll()[0] == ["상점 로그\n"]
    p.write_bytes(b"new game longer than old bytes\n")
    lines, reset = tail.poll(); assert reset and lines == ["new game longer than old bytes\n"]
    other = tmp_path / "new.log"; other.write_bytes(b"replaced\n"); other.replace(p)
    assert tail.poll() == (["replaced\n"],True)


def test_journal_recovers_torn_final_row(tmp_path):
    journal_path = tmp_path / "test.jsonl"
    j = Journal(journal_path,"fixture", date="2026-09-14")
    j.append(fixture().splitlines(True)); j.close()
    with journal_path.open("a") as f: f.write('{"line":')
    output = tmp_path / "recovered"
    assert main(["recover",str(journal_path),"--output",str(output)]) == 0
    d = json.loads(next(output.glob("*.json")).read_text(encoding="utf-8"))
    assert d["result"]["placement"] == 7


def test_unknown_tag_and_numeric_entity_syntax():
    p = PowerParser()
    r = p.parse("D 12:00:00.0000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=27 tag=999999 value=-7")
    assert r["entity"]["id"] == 27 and r["tag"] == "999999" and r["value"] == -7


def test_reorder_is_observation_not_intent(tmp_path):
    text = fixture().replace("tag=3533 value=1", "tag=3533 value=1", 1)
    needle = "D 12:00:"
    insertion = "D 12:00:10.0000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=33 tag=ZONE_POSITION value=2\n"
    index = text.index("GameState.DebugPrintPower() - TAG_CHANGE Entity=4 tag=TURN value=2")
    start = text.rfind("D ",0,index)
    text = text[:start]+insertion+text[start:]
    _,d = run(tmp_path,text)
    event = next(e for t in d["turns"] for e in t["events"] if e["action"] == "REORDER")
    assert event["evidence"] == "inferred_from_position_change"


def test_zero_damage_not_fabricated_tie(tmp_path):
    _,d = run(tmp_path,fixture().replace("tag=DAMAGE value=6","tag=DAMAGE value=0").replace("tag=ARMOR value=0","tag=ARMOR value=3"))
    assert d["turns"][1]["combat"]["result"] == "unknown"


def test_persisted_schema_and_reference_integrity(tmp_path):
    import jsonschema
    from bg_review.validate import validate_document
    s, _ = run(tmp_path)
    d = json.loads(s.paths[0].read_text(encoding="utf-8"))
    schema = json.loads((Path(__file__).parents[1]/"bg_review/schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(d)
    assert not validate_document(d)


def test_missing_block_end_does_not_swallow_following_actions(tmp_path):
    text = fixture()
    lines = text.splitlines(True)
    first_end = next(i for i,line in enumerate(lines) if " - BLOCK_END" in line)
    lines.pop(first_end)
    _,d = run(tmp_path,"".join(lines))
    events = d["turns"][1]["events"]
    assert events[0]["action"] == "ROLL" and events[0]["status"] == "boundary_inferred"
    assert events[1]["action"] == "BUY" and events[1]["stateAfter"]


def test_opponent_name_changes_and_bob_restore_preserve_combat_result(tmp_path):
    text = fixture().replace("TAG_CHANGE Entity=6 tag=HERO_ENTITY value=50", "TAG_CHANGE Entity=NewOpponent tag=HERO_ENTITY value=50")
    text = text.replace("TAG_CHANGE Entity=11 tag=DAMAGE value=6", "TAG_CHANGE Entity=50 tag=DAMAGE value=0")
    text = text.replace("TAG_CHANGE Entity=11 tag=ARMOR value=0", "TAG_CHANGE Entity=11 tag=ARMOR value=3")
    marker = "GameState.DebugPrintPower() - TAG_CHANGE Entity=4 tag=TURN value=3"
    at = text.rfind("D ",0,text.index(marker))
    hit = ["BLOCK_START BlockType=ATTACK Entity=11 EffectCardId= EffectIndex=0 Target=0 SubOption=-1",
           "TAG_CHANGE Entity=50 tag=DEFENDING value=1", "TAG_CHANGE Entity=50 tag=DAMAGE value=7", "BLOCK_END",
           "TAG_CHANGE Entity=50 tag=ARMOR value=0", "TAG_CHANGE Entity=NewOpponent tag=HERO_ENTITY value=12"]
    text = text[:at]+"".join(f"D 12:00:59.0000000 GameState.DebugPrintPower() - {line}\n" for line in hit)+text[at:]
    _,d = run(tmp_path,text)
    combat = d["turns"][1]["combat"]
    assert combat["result"] == "win" and combat["damageDealt"] == 7


def test_explicit_reorder_inside_unclosed_effect_is_still_recorded(tmp_path):
    text = fixture()
    index = text.index("GameState.DebugPrintPower() - TAG_CHANGE Entity=4 tag=TURN value=2")
    at = text.rfind("D ",0,index)
    rows = [
        ("GameState.DebugPrintOptions", "id=99"),
        ("GameState.DebugPrintOptions", "option 3 type=POWER mainEntity=[entityName=Board id=33 zone=PLAY zonePos=1 cardId=FIX_BOARD player=2] error=NONE"),
        ("GameState.SendOption", "selectedOption=3 selectedSubOption=-1 selectedTarget=0 selectedPosition=2"),
        ("GameState.DebugPrintPower", "TAG_CHANGE Entity=33 tag=ZONE_POSITION value=2"),
        ("GameState.DebugPrintOptions", "id=100"),
        ("GameState.DebugPrintOptions", "option 3 type=POWER mainEntity=[entityName=Board id=33 zone=PLAY zonePos=2 cardId=FIX_BOARD player=2] error=NONE"),
    ]
    text=text[:at]+"".join(f"D 12:00:20.0000000 {method}() - {body}\n" for method,body in rows)+text[at:]
    _,d=run(tmp_path,text)
    events=[e for t in d['turns'] for e in t['events'] if e['action']=='REORDER']
    assert len(events)==1 and events[0]['status']=='confirmed_at_next_options'
    assert events[0]['stateAfter'] is not None


def test_midnight_date_rollover(tmp_path):
    s=Session(tmp_path,'fixture','2026-09-14')
    s.feed('D 23:59:59.0000000 GameState.DebugPrintPower() - CREATE_GAME\n')
    s.feed('D 00:00:01.0000000 GameState.DebugPrintPower() - CREATE_GAME\n')
    assert s.match.data['match']['startedAt'].startswith('2026-09-15')
    s.close()
