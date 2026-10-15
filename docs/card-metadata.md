# 카드 규칙 데이터와 정확도 경계 (0.4)

규칙은 모델이 생성하지 않는다. cardId를 기본 키로 삼고, 경기 `match.build`와 데이터 build가 일치할 때만 사용한다. 이름이 같아도 다른 cardId의 규칙을 가져오지 않는다. 일반/황금/토큰/전장 카드는 해당 ID의 정의를 각각 사용한다. 관측 JSON과 audit는 이 보강 단계에서 수정하지 않는다.

## 출처와 조회 순서

1. 명시한 `--card-data`의 빌드·locale이 맞는 정규화 JSON 또는 CardDefs XML/폴더.
2. `%APPDATA%` 또는 `%LOCALAPPDATA%`의 `HearthstoneDeckTracker/CardDefs`. XML 루트 build가 일치하는 경우만 사용.
3. 프로젝트 `cards/<build>/<locale>.json`.
4. `%LOCALAPPDATA%/BattlegroundsReview/card-data/<build>/<locale>.json`.
5. 다운로드가 허용된 경우 HearthSim hsdata의 정확한 build 태그를 immutable commit으로 해석하고 해당 CardDefs.xml, CardDefs.Bacon.xml 및 GLOBAL localization을 다운로드.

HDT의 [CardDefsManager](https://github.com/HearthSim/Hearthstone-Deck-Tracker/blob/master/Hearthstone%20Deck%20Tracker/Utility/Assets/CardDefsManager.cs)와 [HearthDb Card](https://github.com/HearthSim/HearthDb/blob/master/HearthDb/Card.cs)의 로컬 데이터·문자열 처리를 조사했다. 이 PC에는 일치하는 설치 HDT 캐시가 없어 공개 hsdata를 사용했다. [HearthstoneJSON 형식](https://hearthstonejson.com/docs/cards.html)도 확인했지만 build 250339 JSON URL은 당시 접근 실패했고, 최신 버전으로 대체하지 않았다.

실제 표본은 **build 250339**, [hsdata commit bc742d57e0b057326b8cbf74fdf5f995310720f3](https://github.com/HearthSim/hsdata/tree/bc742d57e0b057326b8cbf74fdf5f995310720f3)를 사용했다. [CardDefs.Bacon.xml](https://github.com/HearthSim/hsdata/blob/bc742d57e0b057326b8cbf74fdf5f995310720f3/CardDefs.Bacon.xml)이 전장 규칙을 제공한다. 모든 다운로드 URL/파일 hash/commit은 카탈로그와 dictionary에 기록한다. 카드명/텍스트는 koKR 우선, 없으면 enUS fallback이다. 카드 원문은 Blizzard 자료이며 전체 DB를 배포 패키지에 포함하지 않는다.

## 실행과 실패

`prepare-cards --build 250339`로 미리 캐시를 만들 수 있다. `--card-data`, `--card-cache`, `--locale`, `--offline`은 export/replay/recover/watch에서 지원한다. 수집 중에는 로컬 데이터만 조회하고 완료된 경기 저장 시 필요한 공개 데이터를 가져온다. export는 캐시가 없으면 다운로드한다. 이때 공개 빌드·locale URL만 요청하며 게임 로그를 보내지 않는다. 네트워크/버전/파싱 오류는 unresolved로 남기고 경기 기록은 저장한다. 불완전하게 종료된 경기는 자동 다운로드하지 않으며 별도 export로 보강할 수 있다.

`--cards`는 예전 수집 보강 옵션이다. 버전 정보가 없는 cards.json 배열을 새 resolver에 직접 넣을 수 없다. `--card-data` JSON은 catalogVersion=1, build, locale, cardId를 키로 한 cards 객체를 가져야 한다. XML은 루트 build가 필수다.

## 규칙과 표시 변수

- CARDTEXT의 HTML/강조용 표시는 정리하지만 의미를 새로 쓰지 않는다. 원문 rawText도 sidecar에 보존한다.
- `{0}` 등의 숫자 문맥은 해당 TAG_SCRIPT_DATA_NUM 값과 관측값으로 해석한다. 관측값이 DB 기본값과 다르면 본문 카드에 수치를 표시한다. Relevant mechanics는 템플릿과 DB 기준값을 제공하므로 미래 관측 수치를 과거 카드에 덮어쓰지 않는다.
- 값이 숫자여도 종족/개체 참조일 수 있다. 금도금 나침반의 `{0}`은 종족이므로 출처를 적은 작은 parameter_bindings.json에서 타입을 선언했다. Race enum과 정확한 빌드 GLOBAL 문자열로 변환한다. 다른 카드의 숫자를 무조건 종족으로 바꾸지 않는다.
- Dark Gift의 entity 링크는 카드 정체성과 적용 대상을 복원하는 데 사용한다. 다른 시점의 수치는 가져오지 않는다. CREATOR_DBID는 관계 근거로만 보존하고 생성자의 능력을 인챈트 효과로 바꾸지 않는다. 선물 대상 entity ID를 버프 숫자로 해석하지 않는다.
- 0.4.1부터 상대 전투 복사본처럼 DARK_GIFT_ENTITY가 없어도, 부착된 효과의 ATTACHED와 IS_NIGHTMARE_BONUS로 선물을 식별한다. 효과 이름/접미사로 연결하지 않고 부착 효과 자체의 cardId로 규칙을 찾는다. 여러 선물은 `mechanics.entities[ref].darkGifts` 배열에 적용 대상·효과 entityId/cardId·rawTags·linkEvidence와 함께 보존한다. 직접 링크와 같은 선물의 부착 효과는 명시적 entityId/CREATOR_DBID 연결이 있을 때만 묶고 attachmentEvidence를 남긴다. 제거된 효과나 다른 대상의 효과는 제외한다.
- `@`의 숫자 문맥은 HearthDb가 사용하는 script/score 값으로 처리한다. 여러 설명 분기와 `#ALT/#PL/#EXPANDLIST` 문법은 일반 문자열 분할로 해석하지 않는다. 확정할 수 없는 분기는 원문과 unresolved 표시를 보존하며, 복잡한 매크로 원문은 sidecar에 둔다.
- 미확인 효과/수치는 unresolved다. 도사린 거대괴수의 본체 규칙을 찾았더라도 특정 인챈트 수치가 불명확하면 그 문제를 별도로 남긴다.
- 같은 build의 공개 DB가 서버에서 적용된 모든 단계·수치와 같다는 보장은 없다. 표본의 하이에나, 골드린, 겁 없는 미식가, 비밀스러운 창조술사에서 관측 단계와 DB 단계 불일치가 확인됐다. 원인을 hotfix라고 단정하지 않으며 관측값을 유지하고 적용 규칙을 미확정으로 표시한다.

## 한 파일로 읽을 범위

BUY/PLAY/ACTIVATE/영웅 능력/주문/선택 후보/시즌 효과/주요 내 보드에서 관련 cardId를 모은다. 한 ID는 한 번만 Relevant mechanics에 적는다. 후보에는 카드 설명과 연결된 선물·modifier를 inline으로 보여주고 긴 설명만 같은 파일의 mechanics로 안내한다. 상대 보드 전체 tooltip은 본문에 추가하지 않지만 sidecar의 해당 관측에서 조회할 수 있다.

상대 전투 보드에 부착된 Dark Gift는 예외적으로 Relevant mechanics에 포함한다. 보드의 `Dark Gift: 이름`과 같은 파일의 규칙 설명을 연결하여 dictionary 없이도 효과를 이해할 수 있게 한다. 선물이 있다는 사실만으로 현재 DS/DR 등의 키워드를 추가하지 않으며, 남은 보호 횟수도 추정하지 않는다.

## 반복 가능한 표본 비교

```powershell
python -m scripts.verify_semantic_review match.json before.review.md --baseline-audit before.audit.md --output metrics.json
```

동일 JSON의 audit 바이트 일치, action 행/묶음과 Q/D 순서, 원본의 모든 선택 경계 상점·후보, 턴 시작 보드/손패, 양측 전투 시작 보드·결과·피해, sidecar 참조/행동 분할과 raw 속성을 검사한다. 실제 사용자 경기는 배포 예제에 넣지 않는다.
