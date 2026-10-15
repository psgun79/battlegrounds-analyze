"""Invented protocol fixture, not a game balance simulation or copied third-party log."""
from pathlib import Path


def fixture():
    lines = []
    def put(body, method="GameState.DebugPrintPower"):
        lines.append(f"D 12:00:{len(lines)//100:02d}.{len(lines)%100:07d} {method}() - {body}\n")
    def entity(eid, cid, **tags):
        put(f"FULL_ENTITY - Creating ID={eid} CardID={cid}")
        for k, v in tags.items(): put(f"    tag={k} value={v}")
    def tag(eid, key, value): put(f"TAG_CHANGE Entity={eid} tag={key} value={value}")
    def block(eid, target=0, kind="PLAY"):
        put(f"BLOCK_START BlockType={kind} Entity={eid} EffectCardId= EffectIndex=0 Target={target} SubOption=-1")
    def end(): put("BLOCK_END")
    def options(ids):
        put("id=1", "GameState.DebugPrintOptions")
        for eid, cid, name, owner, pos in ids:
            put(f"option {eid} type=POWER mainEntity=[entityName={name} id={eid} zone=PLAY zonePos={pos} cardId={cid} player={owner}] error=NONE errorParam=", "GameState.DebugPrintOptions")
    put("CREATE_GAME")
    put("GameEntity EntityID=4"); put("tag=CARDTYPE value=GAME")
    put("Player EntityID=5 PlayerID=2 GameAccountId=[hi=0 lo=0]"); put("tag=PLAYER_ID value=2")
    put("Player EntityID=6 PlayerID=10 GameAccountId=[hi=0 lo=0]"); put("tag=PLAYER_ID value=10"); put("tag=BACON_DUMMY_PLAYER value=1")
    put("BuildNumber=fixture", "GameState.DebugPrintGame")
    put("GameType=GT_BATTLEGROUNDS", "GameState.DebugPrintGame")
    put("PlayerID=2, PlayerName=FixturePlayer", "GameState.DebugPrintGame")
    entity(11, "FIX_HERO", CARDTYPE="HERO", CONTROLLER=2, ZONE="PLAY", HEALTH=30, ARMOR=3, PLAYER_TECH_LEVEL=1, PLAYER_LEADERBOARD_PLACE=1)
    entity(12, "TB_BaconShopBob", CARDTYPE="HERO", CONTROLLER=10, ZONE="PLAY", HEALTH=30, ARMOR=0)
    tag(5, "HERO_ENTITY", 11); tag(6, "HERO_ENTITY", 12)
    for eid, cid, cost in [(20,"TB_BaconShop_8p_Reroll_Button",1),(21,"TB_BaconShop_DragBuy",3),(22,"TB_BaconShop_DragSell",0),(23,"TB_BaconShopTechUp02_Button",4),(24,"TB_BaconShopLockAll_Button",0),(25,"BG36_Button_DarkGift",1),(26,"FIX_POWER",0)]:
        entity(eid, cid, CARDTYPE="HERO_POWER", CONTROLLER=2, ZONE="PLAY", COST=cost)
    tag(4,"TURN",1); tag(5,"RESOURCES",10); tag(5,"RESOURCES_USED",0)
    for eid, cid, atk, hp, pos in [(30,"FIX_OLD_OPTION",2,3,1),(31,"FIX_MISSED_ENGINE",1,5,2)]:
        entity(eid,cid,CARDTYPE="MINION",CONTROLLER=10,ZONE="PLAY",ZONE_POSITION=pos,ATK=atk,HEALTH=hp,TECH_LEVEL=1,FROZEN=0)
    options([(30,"FIX_OLD_OPTION","Old option",10,1),(31,"FIX_MISSED_ENGINE","Missed growth engine",10,2)])
    block(20)
    tag(5,"RESOURCES_USED",1); tag(30,"ZONE","SETASIDE"); tag(31,"ZONE","SETASIDE")
    entity(32,"FUTURE_UNKNOWN_CARD",CARDTYPE="MINION",CONTROLLER=10,ZONE="PLAY",ZONE_POSITION=1,ATK=4,HEALTH=4,TECH_LEVEL=1,FROZEN=0,NEW_SEASON_RESOURCE=9)
    end()
    block(21,32); tag(5,"RESOURCES_USED",4); tag(32,"CONTROLLER",2); tag(32,"ZONE","HAND"); end()
    block(32); tag(32,"ZONE","PLAY"); tag(32,"ZONE_POSITION",1); end()
    block(22,32); tag(32,"ZONE","GRAVEYARD"); tag(5,"RESOURCES_USED",3); end()
    entity(33,"FIX_BOARD",CARDTYPE="MINION",CONTROLLER=2,ZONE="PLAY",ZONE_POSITION=1,ATK=5,HEALTH=5,DIVINE_SHIELD=1)
    block(23); tag(11,"PLAYER_TECH_LEVEL",2); tag(5,"RESOURCES_USED",7); end()
    entity(34,"FIX_SHOP_TWO",CARDTYPE="MINION",CONTROLLER=10,ZONE="PLAY",ZONE_POSITION=1,ATK=2,HEALTH=2,FROZEN=0)
    block(24); tag(34,"FROZEN",1); end(); block(24); tag(34,"FROZEN",0); end()
    block(25); tag(5,"RESOURCES_USED",8); end()
    entity(40,"FIX_CHOICE_A",CARDTYPE="MINION",CONTROLLER=2,ZONE="SETASIDE",ATK=6,HEALTH=6)
    entity(41,"FIX_CHOICE_B",CARDTYPE="MINION",CONTROLLER=2,ZONE="SETASIDE",ATK=7,HEALTH=7)
    put("id=7 Player=FixturePlayer TaskList=10 ChoiceType=GENERAL CountMin=1 CountMax=1","GameState.DebugPrintEntityChoices")
    for i,eid in enumerate([40,41]): put(f"Entities[{i}]=[entityName=Choice {i} id={eid} zone=SETASIDE zonePos=0 cardId=FIX_CHOICE_{'A' if i==0 else 'B'} player=2]","GameState.DebugPrintEntityChoices")
    put("id=7 ChoiceType=GENERAL","GameState.SendChoices")
    put("m_chosenEntities[0]=[entityName=Choice 1 id=41 zone=SETASIDE zonePos=0 cardId=FIX_CHOICE_B player=2]","GameState.SendChoices")
    put("id=7 Player=FixturePlayer EntitiesCount=1","GameState.DebugPrintEntitiesChosen")
    put("Entities[0]=41","GameState.DebugPrintEntitiesChosen")
    block(26,33); tag(33,"ATK",8); end()
    tag(4,"TURN",2); tag(4,"3533",1); tag(34,"ZONE","SETASIDE")
    entity(50,"FIX_OPP_HERO",CARDTYPE="HERO",CONTROLLER=10,ZONE="PLAY",HEALTH=30,ARMOR=0,PLAYER_TECH_LEVEL=2)
    tag(6,"HERO_ENTITY",50)
    entity(51,"FIX_ENEMY",CARDTYPE="MINION",CONTROLLER=10,ZONE="PLAY",ZONE_POSITION=1,ATK=8,HEALTH=9)
    tag(4,"3533",0)
    block(51,33,"ATTACK"); tag(33,"DIVINE_SHIELD",0); end()
    block(33,51,"ATTACK"); tag(33,"ZONE","GRAVEYARD"); end()
    tag(11,"ARMOR",0); tag(11,"DAMAGE",6)
    tag(4,"TURN",3); tag(6,"HERO_ENTITY",12); tag(51,"ZONE","SETASIDE"); tag(5,"RESOURCES_USED",0)
    tag(33,"ZONE","PLAY")
    entity(35,"FIX_FINAL_OPTION",CARDTYPE="MINION",CONTROLLER=10,ZONE="PLAY",ZONE_POSITION=1,ATK=2,HEALTH=2,FROZEN=0)
    options([(35,"FIX_FINAL_OPTION","Final choice",10,1)])
    tag(4,"TURN",4); tag(35,"ZONE","SETASIDE"); tag(4,"3533",1); tag(6,"HERO_ENTITY",50); tag(51,"ZONE","PLAY"); tag(4,"3533",0)
    block(51,33,"ATTACK"); tag(33,"ZONE","GRAVEYARD"); end()
    tag(11,"DAMAGE",30); tag(11,"PLAYER_LEADERBOARD_PLACE",7)
    tag(5,"PLAYSTATE","LOST"); tag(4,"STATE","COMPLETE")
    return "".join(lines)


if __name__ == "__main__":
    dest = Path(__file__).parent / "fixtures" / "sample.Power.log"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(fixture(), encoding="utf-8")
