# Battlegrounds Review Logger

하스스톤 전장 한 판의 **행동 당시 상점·손패·보드와 행동 전후 변화**를 JSON/Markdown으로 남기는 Windows용 읽기 전용 로거입니다. 게임 프로세스와 독립적으로 `Power.log`를 읽습니다. 자동 플레이, 입력 자동화, 메모리 읽기/인젝션, 패킷 처리, 외부 업로드는 없습니다.

현재 최소 동작 버전은 **솔로 전장**용입니다. HDT 플러그인이 아니므로 HDT 설치·버전·DLL 의존성이 없습니다. 소스 호환성 조사는 HDT **1.57.9 (2026-09-14)** 기준으로 했고, 이 PC의 실제 클라이언트 로그를 재생해 검증했습니다. [조사 및 선택 근거](docs/research.md), [검증 결과](docs/validation.md)를 참고하세요.

## 시작하기

### Windows 실행 파일 (추천)

Python이나 Git 설치 없이 사용할 수 있습니다.

1. [최신 릴리스](https://github.com/psgun79/battlegrounds-analyze/releases/latest)에서 `battlegrounds-review-logger-<버전>-windows-x64.zip`을 다운로드합니다. `Source code`는 개발용입니다.
2. ZIP 전체를 압축 해제한 뒤 **`bg-review.exe`**를 더블클릭합니다. `_internal` 폴더도 함께 유지하세요.
3. 처음이라면 메뉴 **2**로 로그 설정을 켜고 하스스톤을 재시작합니다.
4. 메뉴 **1**로 기록을 시작합니다. 로그 위치는 Enter로 자동 검색하거나 직접 지정합니다.
5. 경기 종료 후 **Ctrl+C**로 기록을 멈추고 메뉴 **3**으로 결과 폴더를 엽니다.
6. 해당 판의 **`.review.md`**와 [AI 복기 프롬프트](docs/review-prompt.md)를 AI에 전달합니다.

기록 위치는 `%LOCALAPPDATA%\BattlegroundsReview\output`입니다. 새 버전을 다른 폴더에 풀어도 기존 기록이 유지됩니다. 실행 파일은 서명되지 않았으며, 배포 페이지에 ZIP의 SHA256 파일을 함께 제공합니다.

아래 명령어 예시에서 `.\.venv\Scripts\python.exe -m bg_review` 대신 `.\bg-review.exe`를 사용해도 됩니다. [빌드·자동 배포 방법](docs/distribution.md)

### 소스로 실행

Python 3.11 이상이 필요합니다. 소스 ZIP을 압축 해제하거나 저장소를 clone한 뒤 진행하세요. `.venv`는 각 PC에서 새로 생성합니다.

1. 게임을 시작하기 전에 `Start-Logger.cmd`를 실행하고 창을 열어 둡니다.
2. 전장 한 판을 플레이합니다. 종료 후 파일이 자동 생성됩니다.
3. **해당 판의 `.review.md` 한 파일을 AI에 전달**하세요. 카드명 중심의 Compact 문서에 실제 선택지, 미구매·상대 카드 규칙, 당시 다음 상대와 짧은 전투 시작 요약을 포함합니다. 미해석 효과와 생략된 전투 사건은 확정 불가로 남깁니다. dictionary/audit/JSON/저널은 선택적 진단용이며 일반 복기에 추가 첨부할 필요가 없습니다.
4. 콘솔에서 `Ctrl+C`를 누르면 현재까지의 기록을 저장하고 종료합니다.

새 PC 설치:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m bg_review doctor
```

처음 사용하며 `Power.log`가 생성되지 않으면 다음을 실행한 뒤 **하스스톤을 재시작**하세요. 사용자 설정의 `log.config`만 백업 후 Power 로깅을 켭니다. 게임 실행 파일이나 에셋은 변경하지 않습니다. HDT가 이미 로그를 켜 두었다면 필요 없습니다.

```powershell
.\.venv\Scripts\python.exe -m bg_review configure-logging
```

기본 로그 검색 위치는 Hearthstone 설치 경로의 `Logs/Hearthstone_YYYY_MM_DD_HH_MM_SS/Power.log`입니다. Windows 설치 레지스트리와 기본 설치 폴더를 검색합니다. 다른 드라이브에 설치했다면:

```powershell
.\.venv\Scripts\python.exe -m bg_review watch --log-root 'D:\Games\Hearthstone\Logs'
```

백그라운드 실행/종료:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Start-Logger.ps1 -Background
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Stop-Logger.ps1
```

Windows 로그인 시 자동 시작하는 작업은 설치하지 않습니다. 게임을 할 때 로거를 실행하세요. 중복 실행은 출력 디렉터리의 OS 잠금으로 방지합니다.

## 저장 위치와 파일

기본: `%LOCALAPPDATA%\BattlegroundsReview\output` (`--output`으로 변경 가능).

```text
2026-09-14T12_00_00.0000000_<matchid>.json  # 참조가 모두 포함된 복기 데이터
2026-09-14T12_00_00.0000000_<matchid>.audit.md   # 기존 상세 Markdown, 중간 상태 포함
2026-09-14T12_00_00.0000000_<matchid>.review.md  # 기본 Compact: 카드명, 선택지, 행동, 보드·결과
2026-09-14T12_00_00.0000000_<matchid>.dictionary.json # 카드/효과 사전과 관측 상태 참조
<matchid>.events.jsonl                     # 파싱된 전체 entity/tag/event 진단 기록
capture-<id>.jsonl                        # watch의 원본 라인 write-ahead journal
watch-status.json                        # PID, 최근 입력 위치, 턴, 파싱 오류 수
errors.jsonl                             # 오류가 있었을 때만 생성
```

파일명의 match id는 source/start time/CREATE_GAME 위치의 해시로 만든 **로컬 ID**이며 서버 match id가 아닙니다. 동일 입력을 동일 경로로 재생하면 같은 파일을 갱신합니다. 경로가 달라지면 ID가 달라질 수 있으므로 여러 위치에서 수집한 로그를 합칠 때 중복에 주의하세요. 영웅명은 파일명이 아닌 문서 metadata에 들어갑니다.

기본 250ms 주기로 최대 1MiB씩 읽습니다. 먼저 원본 저널에 쓰고 flush/fsync한 뒤 해석하며, 약 5초마다 JSON/Markdown을 임시 파일+atomic replace로 갱신합니다. 강제 종료되어도 마지막 체크포인트와 저널을 복구할 수 있습니다. JSON과 Markdown은 각각 원자적으로 교체되므로 비정상 종료 직전에는 두 파일의 시점이 다를 수 있습니다. 디스크 오류는 콘솔/stderr에 기록하고 로거만 멈춥니다.

로그는 자동 삭제하지 않습니다. 상세 저널은 장시간 사용 시 커질 수 있습니다. 계정명·상대 이름·계정 식별자가 원본 저널에 포함될 수 있으므로 외부 공유 전에 확인하세요. Git에서는 실제 로그와 출력 폴더를 제외합니다.

## 재생, 복구, 카드 설명

```powershell
# 설치된 CLI 대신 python -m bg_review로도 모든 명령 실행 가능
.\.venv\Scripts\python.exe -m bg_review replay 'C:\path\Power.log' --output output
.\.venv\Scripts\python.exe -m bg_review recover 'C:\path\capture-xxxx.jsonl' --output recovered
.\.venv\Scripts\python.exe -m bg_review export 'C:\path\match.json'
# 기본 export는 audit/review/dictionary 생성. review에는 dictionary가 항상 동반:
.\.venv\Scripts\python.exe -m bg_review export 'C:\path\match.json' --format review
.\.venv\Scripts\python.exe -m bg_review export 'C:\path\match.json' --format audit --markdown 'C:\path\audit.md'
# C/F/엔티티 참조와 모든 재배치를 확인하는 Debug 모드:
.\.venv\Scripts\python.exe -m bg_review export 'C:\path\match.json' --format review --review-mode debug --markdown 'C:\path\match.debug.review.md'
.\.venv\Scripts\python.exe -m bg_review validate 'C:\path\match.dictionary.json'
.\.venv\Scripts\python.exe -m bg_review validate 'C:\path\match.json'

# 배포에 포함된 가상 2턴 경기
.\.venv\Scripts\python.exe -m bg_review replay tests/fixtures/sample.Power.log --date 2026-09-14 --output examples
```

0.4부터 `.review.md`에 **실제 카드 규칙**을 보강합니다. 선택지에는 카드·영웅 능력·Dark Gift 설명을 붙이고, 일반 규칙은 `Relevant mechanics`에 cardId별 한 번만 적습니다. 로그와 같은 빌드의 HDT 캐시 → 프로젝트 카탈로그 → 로컬 캐시 순으로 찾고, 없으면 경기 종료 또는 export 때 공개 HearthSim 데이터의 **해당 빌드 태그**를 내려받습니다. koKR 우선, 없으면 enUS를 사용합니다. `latest`로 대체하지 않으며 로그를 업로드하지 않습니다.

```powershell
# 게임 전에 정확한 빌드의 규칙 캐시 준비 (빌드는 match.build에서 확인)
.\.venv\Scripts\python.exe -m bg_review prepare-cards --build 250339
# 외부 다운로드 없이 기존 캐시만 사용
.\.venv\Scripts\python.exe -m bg_review export 'C:\path\match.json' --offline
# 직접 준비한 빌드 명시 카탈로그 또는 CardDefs XML 사용
.\.venv\Scripts\python.exe -m bg_review export 'C:\path\match.json' --card-data 'C:\data\CardDefs'
```

다운로드 실패, 미확인 표시 변수, 로그와 DB의 단계 불일치는 `unresolved` 또는 충돌 경고로 남깁니다. 같은 빌드라도 모든 서버 적용 수치가 일치한다고 가정하지 않습니다. 관측 스탯과 선택 기록은 그대로 보존합니다. [데이터 출처·버전·변수 해석](docs/card-metadata.md)을 참고하세요. 기존 `--cards`는 수집 단계의 수동 보강 옵션이며 버전 없는 cards.json은 새 규칙 resolver의 신뢰 근거로 사용하지 않습니다.

플레이어는 `BACON_DUMMY_PLAYER`가 붙은 밥과 실제 Player 엔티티를 구분하여 찾습니다. 이름에 `#`가 있다는 이유로 결정하지 않습니다. 불완전한 입력에서 자동 식별이 안 되면 `--local-player 2`처럼 로그의 **PlayerID**를 명시할 수 있습니다. 로비 순위와는 다릅니다.

## JSON schema v1

[기계 판독 스키마](bg_review/schema.json). 새 시즌 필드는 추가 가능하고, 의미 변경은 schemaVersion을 올립니다.

```text
match                 로컬 경기 ID, 영웅 참조, 빌드, 시간, 알려진 메타데이터
turns[]               turn/startState/events/shopSnapshots/decisionSnapshots/combat
snapshots[s123]       경제 상태, board/hand/shop/choices/lobbyHero 참조
entityStates[e42v3]   그 시점의 카드·스탯·키워드·인챈트 불변 버전
optionSets[o...]      기록된 선택 가능 여부(error)와 대상 엔티티
result                completed/incomplete/in_progress, 최종 순위
quality               복기 전에 확인할 누락·추론·지원 제한
telemetry             전체 진단 저널 위치/태그 수록 범위
```

`events[].stateBefore` → `snapshots` → `entityStates`를 따라가면 행동 당시 상점과 손패를 복원할 수 있습니다. `stateAfter`는 블록 해소 후 상태입니다. 미완료 행동은 null입니다. `cost`는 버튼/카드 COST 관측값, `goldDelta`는 행동 전후 잔여 골드 차이로 환급/발동 효과를 포함하며 순수 지출과 같다고 가정하면 안 됩니다.

`sourceLine`/`sequence`로 근거를 찾습니다. `decisionBoundary`는 행동/선택 화면 경계, `transient`는 효과 처리 중간 상태입니다. 화면에 실제 렌더링된 순간을 보장하는 UI 녹화는 아닙니다. 리롤 직전 상점과 해소 직후 상점은 항상 별도 상태 참조로 연결됩니다. 효과 중간의 상점도 블록 경계에서 수록하며, 그보다 세밀한 태그 변화는 전체 저널에 남습니다.

0.3부터 `.review.md`의 기본값은 **Compact**입니다. 카드명을 직접 쓰고, 동명 개체 구분에 필요한 경우만 #엔티티 번호를 남깁니다. 실제 선택 경계의 상점·발견 후보는 유지하고, 같은 상점은 Q 번호로 참조합니다. 턴 시작 보드·손패와 전투 직전 양쪽 보드는 전체를, 모집 중 변화는 차분으로 씁니다. 단순 드래그 재배치는 생략하고 다음 의사결정의 배치와 전투 최종 순서는 남깁니다. 새 선택지가 없는 동일 대상의 연속 주문에서 전장·부착 수치의 증분이 매회 같을 때만 묶으며, 행동 ID 범위·횟수와 최초/최종·누적 변화를 표시합니다. 대상 변경이나 중요한 중간 변화는 상세 기록을 유지합니다.

**`.dictionary.json`**에는 C/F/X 사전, 세부 효과와 원본 상태 참조, 생략된 재배치 및 묶인 행동의 전후 상태가 있습니다. 일반 복기는 review 한 파일로 끝내고, 이 파일은 개발·진단 시 선택적으로 조회합니다. **`.audit.md`**는 중간 상태와 전투 사건 수를 포함하며 전체 공격·죽음 순서는 JSON에 있습니다. [압축 규칙과 sidecar schema](docs/review-exporter.md)를 참고하세요.

`--review-mode compact|debug`는 export/replay/recover/watch에서 사용할 수 있고 기본은 compact입니다. Debug는 기존 C/F/엔티티 표기와 모든 재배치를 유지하지만 사전 정의는 sidecar에 둡니다. dictionary를 저장한 뒤 review를 갱신하며, 파일별로 atomic replace하므로 비정상 종료 시 파일 간 시점이 다를 수 있습니다. 전체 무손실 입력은 기존 `.json`/저널이며, Compact는 모든 내부 효과를 직접 설명하는 문서가 아닙니다.

기존 `.md`는 삭제하거나 덮어쓰지 않습니다. 예전 JSON도 export할 수 있지만, 0.1에서 제거된 옵션 경계는 JSON만으로 되살릴 수 없습니다. 전체 원본이나 저널을 0.2로 재생하면 추가 필드 `decisionSnapshots`에 보존됩니다.

`rawTags`는 복기에 관련된 태그를 담습니다. 모든 숫자 태그·내부 bookkeeping 변경은 `.events.jsonl`에 보존하며, AI용 JSON에 중복 삽입하지 않습니다. 미래 시즌 해석을 추가할 때 저널/원본을 사용하세요. **의사결정·상점·스탯 흐름은 JSON 하나로 복원**되지만, 모든 내부 태그의 전 이력까지 같은 파일에 들어가지는 않습니다.

## 수집 범위와 한계

| 항목 | 현재 구현 |
|---|---|
| 리롤 전후, 구매/판매/플레이, 주문, 업그레이드, 영웅 능력 | PLAY 블록과 전후 상태. 밥 버튼 ID, 소유자, 카드 타입으로 분류 |
| 순서 변경 | SendOption의 보드 하수인/위치 요청을 다음 선택 목록에서 위치 확인. 요청만 있으면 pending. 요청 없이 관측한 위치 변화는 `inferred_from_position_change`로 구분 |
| 빙결/해제 | 버튼 + 상점 FROZEN 변화. UI에서만 바뀌고 로그가 없으면 수집 불가 |
| Dark Gifts / Activate | 현재 버튼 및 HAS_ACTIVATE_POWER, 발견 선택지, DARK_GIFT_ENTITY/인챈트 태그 |
| 장신구/퀘스트/변형물 | 엔티티/시즌 태그·선택 기록. 시즌별 모든 효과의 전략 의미 해석은 미구현 |
| 보드·손패·상점 | 보이는 카드의 id, 위치, 현재 스탯, 키워드, 인챈트. 숨겨진 상대 손패는 수집 안 함 |
| 전투 시작 보드 | setup 태그 3533 종료 우선. 누락 시 2022 또는 첫 공격/마지막 상태로 fallback, 정확도 명시 |
| 공격·대상·죽음·보호막 | ATTACK 블록 + DEFENDING 태그 대상, GRAVEYARD/보호막 변화. ENTER_PLAY는 소환/환생을 완전히 구별하지 않음 |
| 전투 결과·피해 | 영웅 공격 블록 내 실제 체력/방어도 변화. 없으면 내 영웅 변화만 fallback. 피해 0을 무승부로 단정하지 않음 |
| 체력·방어도·골드·업 비용 | 관측된 태그. 초기 누락은 null; 버튼 비용 없으면 업 비용 추정 안 함 |
| 최종 순위 | 종료 신호 이후 내 영웅 PLAYER_LEADERBOARD_PLACE. 진행 중 순위는 최종 순위로 내보내지 않음 |
| 로비 정보 | 공개된 영웅/체력/방어도/선술집 단계/순위와 관측 시점. 전체 로비 보드 평균 성장률은 **알 수 없음** |
| MMR/지역/가능·금지 종족/승률 | 현재 null. 별도 검증된 공급자 없이는 추정하지 않음 |
| 영구/일시 버프 구분 | 인챈트는 보존하되 statDuration=unknown. 시즌별 효과 의미는 DB/추가 해석 필요 |
| 듀오/관전/특수 상점 | 듀오 정확도 보장 안 함. HearthMirror 전용 특수 선택 UI는 누락 가능 |

`GameState.DebugPrintPower`만 사용해 `PowerTaskList` 애니메이션 중복을 제거합니다. 강제 `--stream PowerTaskList`는 진단 옵션으로 제공하지만 다른 스트림의 선택 화면과 시점이 달라 **전후 상태의 정확도를 보장하지 않습니다**. 기본값을 권장합니다.

실제 클라이언트에서 일부 BLOCK_END가 빠진 사례가 있습니다. 다음 블록 들여쓰기로 경계를 복원하고 `status=boundary_inferred`로 표시합니다. 확정 상태와 구분하여 복기하세요. 재접속/중간 시작으로 CREATE_GAME 이전 구간이 없으면 복원할 수 없습니다. 잘림·교체·새 세션은 별도 기록으로 처리하며 재접속 구간을 추측해서 병합하지 않습니다.

## 시즌 패치 후 확인할 코드

- `bg_review/parser.py`: 실제 로그 문법, 태그 이름, 중복 스트림, 선택/타깃 필드.
- `bg_review/season.py`: 버튼 card id, Activate/Dark Gift 분류, 시즌 formatter.
- `bg_review/engine.py`: 밥/플레이어 매핑, 전투 setup 3533/2022, 카드 영역/소유자, 전투 피해 경계.
- `bg_review/document.py`: AI용 문서에 보존할 게임플레이 태그. 전체 신규 태그는 저널에 이미 남음.
- `tests/fixtures` 및 `tests/test_logger.py`: 새 실제 문법을 익명화한 최소 regression fixture 추가.

## 개발/검증

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m build
```

표준 라이브러리만 사용하는 런타임이며 wheel/sdist로 빌드합니다. HDT 플러그인 로딩 검사는 대상이 아닙니다. Windows CI 설정을 포함했지만 원격 CI 실행 여부는 로컬 검증과 별개입니다.

## AI 복기 프롬프트

[전체 프롬프트](docs/review-prompt.md)를 로그와 함께 전달하세요.

> 이 전장 로그를 턴별로 분석하라. 각 결정의 stateBefore에 존재한 정보와 상점/발견 선택지만 이용하고, 이후 결과를 미리 알았던 것처럼 평가하지 마라. 큰 EV 손실 후보 5개와 잘한 판단 5개를 행동 ID와 함께 제시하되, 확률 모델이 없으면 EV를 숫자로 만들지 마라. 성장 엔진이 관측 상대 대비 뒤처진 시점, 업그레이드/리롤/전환/순방 판단을 설명하라. 전체 로비 보드가 없는 경우 로비 평균 성장률은 계산할 수 없다고 말하라. 로그 누락, boundary_inferred, RNG와 배치 및 이전 성장 격차를 구분하고 불확실한 결론에는 신뢰도를 붙여라.

## TODO

- 익명화된 추가 영웅/시즌/승리·탈주·재접속 로그로 회귀 검증 확대.
- MMR·가능 종족·특수 상점·시뮬레이터 승률용 선택적 HDT 어댑터. ABI와 라이선스 확인 후 별도 구현.
- 듀오의 여러 전투 및 팀원 상태 지원.
- 영구 버프/환생/소환 분류, 클라이언트 동적 표시식과 버프 변수 해석 확장.
- 저널 보관 정책/압축과 여러 경기 집계기. 현재 파일 schema로 외부 집계 가능.
- 더 작은 JSON을 위한 카드/인챈트 템플릿 deduplication.
