"""Streaming lexical parser. GameState is authoritative; animation duplicates are ignored.

No dependency on a versioned enum: unfamiliar symbolic/numeric tags remain strings.
This module knows log syntax only, never game strategy.
"""
import re

LINE = re.compile(r"^[DWI] (?P<time>\d\d:\d\d:\d\d\.\d+) (?P<method>[\w.]+)\(\) - (?P<body>.*)$")
PAIR = re.compile(r"(\w+)=([^=]*?)(?=\s+\w+=|$)")


def scalar(value):
    return int(value) if re.fullmatch(r"-?\d+", value) else value


def reference(value):
    value = value.strip().removeprefix("UNKNOWN ENTITY ")
    if value.startswith("["):
        fields = dict(PAIR.findall(value[1:-1]))
        return {"id": int(fields["id"]), "cardId": fields.get("cardId", ""),
                "name": fields.get("entityName"), "zone": fields.get("zone"),
                "position": scalar(fields.get("zonePos", "0")),
                "controller": scalar(fields.get("player", "0"))} if "id" in fields else {"name": value}
    return {"id": int(value)} if value.isdigit() else {"name": value}


class PowerParser:
    def __init__(self, stream="GameState"):
        self.stream = stream
        self.current_entity = None
        self.line_number = 0

    def parse(self, line):
        self.line_number += 1
        m = LINE.match(line.rstrip("\r\n"))
        if not m:
            return None
        time, method, body = m.group("time", "method", "body")
        depth = (len(body) - len(body.lstrip())) // 4
        body = body.strip()
        prefix = {"line": self.line_number, "time": time, "depth": depth}
        def out(kind, **fields):
            return {**prefix, "kind": kind, **fields}
        if method == "GameState.DebugPrintGame":
            if match := re.search(r"PlayerID=(\d+), PlayerName=(.*)", body):
                return out("player_name", playerId=int(match[1]), name=match[2])
            if "=" in body:
                return out("metadata", values=dict(PAIR.findall(body)))
            return None
        if method in ("GameState.DebugPrintEntityChoices", "GameState.DebugPrintEntitiesChosen", "GameState.SendChoices"):
            chosen = not method.endswith("DebugPrintEntityChoices")
            if match := re.match(r"(?:m_chosen)?Entities\[(\d+)\]=(.+)", body, re.I):
                return out("choice_item", chosen=chosen, index=int(match[1]), entity=reference(match[2]))
            if body.startswith("Source="):
                return out("choice_source", entity=reference(body[7:]))
            if match := re.match(r"id=(\d+)(.*)", body):
                count = re.search(r"EntitiesCount=(\d+)", body)
                player = re.search(r"Player=(.*?) (?:TaskList|EntitiesCount)=", body)
                return out("choice_header", chosen=chosen, choiceId=int(match[1]),
                           player=reference(player[1]) if player else None,
                           count=int(count[1]) if count else None, raw=body)
        if method == "GameState.DebugPrintOptions":
            if body.startswith("id="):
                return out("options_start", raw=body)
            if match := re.search(r"(?:mainEntity|entity)=(\[.*?\]).*?error=(\w+)", body):
                index = re.match(r"option (\d+) ", body)
                return out("option", entity=reference(match[1]), error=match[2],
                           optionIndex=int(index[1]) if index else None, raw=body)
            return None
        if method == "GameState.SendOption":
            return out("send_option", values={k: scalar(v) for k,v in PAIR.findall(body)}, raw=body)
        if method != f"{self.stream}.DebugPrintPower":
            return None
        if body == "CREATE_GAME":
            self.current_entity = None
            return out("create_game")
        if match := re.match(r"GameEntity EntityID=(\d+)", body):
            self.current_entity = int(match[1])
            return out("entity", entity={"id": self.current_entity, "name": "GameEntity"}, role="game")
        if match := re.match(r"Player EntityID=(\d+) PlayerID=(\d+)", body):
            self.current_entity = int(match[1])
            return out("entity", entity={"id": self.current_entity}, role="player", playerId=int(match[2]))
        if match := re.match(r"FULL_ENTITY - Creating ID=(\d+) CardID=(\w*)", body):
            self.current_entity = int(match[1])
            return out("entity", entity={"id": self.current_entity, "cardId": match[2]}, role="card")
        if match := re.match(r"(FULL_ENTITY|SHOW_ENTITY|CHANGE_ENTITY) - Updating (?:Entity=)?(.+?) CardID=(\w*)", body):
            ref = reference(match[2])
            ref["cardId"] = match[3]
            self.current_entity = ref.get("id")
            return out("entity", entity=ref, role="card", change=match[1])
        if match := re.match(r"TAG_CHANGE Entity=(.+) tag=(\w+) value=(\S+)", body):
            self.current_entity = None
            return out("tag", entity=reference(match[1]), tag=match[2], value=scalar(match[3]))
        if match := re.match(r"tag=(\w+) value=(\S+)", body):
            if self.current_entity is not None:
                return out("tag", entity={"id": self.current_entity}, tag=match[1], value=scalar(match[2]), initial=True)
            return out("unparsed", raw=body)
        self.current_entity = None
        if match := re.match(r"BLOCK_START BlockType=(\w+) Entity=(.+?) EffectCardId=.*? EffectIndex=.*? Target=(.+?)(?: SubOption=.*)?$", body):
            return out("block_start", blockType=match[1], entity=reference(match[2]), target=reference(match[3]))
        if body == "BLOCK_END":
            return out("block_end")
        if match := re.match(r"HIDE_ENTITY - Entity=(.+) tag=ZONE value=(\w+)", body):
            return out("tag", entity=reference(match[1]), tag="ZONE", value=match[2], hidden=True)
        return out("unparsed", raw=body)
