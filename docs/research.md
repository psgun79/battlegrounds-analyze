# Architecture decision — 2026-09-14/15

요청한 프로젝트들의 README뿐 아니라 파서, 이벤트 API, 상태 추출 코드와 라이선스 표시를 확인했습니다. 작업 시작 시 프로젝트 디렉터리는 비어 있었습니다. 참고 소스는 `.research/`에 분리했고 제품 패키지에는 포함하지 않습니다.

## 검토 결과

| 프로젝트 | 확인한 내용 | 채택 여부 / 라이선스 |
|---|---|---|
| [DeepBattler](https://github.com/william-Dic/DeepBattler) | HDT 플러그인으로 현재 상점/손패를 추출하며 LLM 코칭을 제공. `DeepBattlerPlugin/Class1.cs`는 폴링·턴 기록·별도 경로를 사용. 선택 직전 이력과 원본 저널에는 추가 작업 필요 | fork하지 않음. README의 custom non-commercial terms 확인. 코드 복사 없음 |
| [hearthstone-bg-tracker](https://github.com/shufunk-dev/hearthstone-bg-tracker) | `src/parser/bgEventParser.js`와 watcher 확인. Power.log 이벤트로 보드·공격·buy/sell 복원 가능. 기존 history는 턴별 보드/행동 배열 위주여서 모든 상점과 action-before state schema는 별도 필요 | MIT (2026 Shufelt Designs LLC). Electron UI 없이 독립 로거로 새 구현. 코드 복사 없음 |
| [Battlegrounds-Match-Data 원본](https://github.com/jawslouis/Battlegrounds-Match-Data), [권장 fork](https://github.com/benluiwj/Battlegrounds-Match-Data) | HDT GameEvents, CSV, 전투/순위/MMR 추출 사례. README가 benluiwj fork를 권장. `BgMatchDataPlugin.cs`/`BgMatchData.cs` 확인 | repo 루트의 명시적 LICENSE는 확인하지 못함. 참고만 하고 소스 재사용 안 함 |
| [HDT](https://github.com/HearthSim/Hearthstone-Deck-Tracker) | `API/GameEvents.cs`, `LogReader/LogConstants.cs`, `PowerHandler.cs`, `TagChangeActions.cs`, `Live/BoardStateWatcher.Battlegrounds.cs` 확인. GameEvents에는 모든 리롤/상점 직전 상태를 보장하는 전용 공개 이벤트가 없음. net472/host DLL 의존. 3533·2022 setup, PLAYER_TECH_LEVEL, Dark Gift 태그 해석 근거 | README는 HearthSim All Rights Reserved. host 코드 복사·배포 없음. 현재 HDT 1.57.9 changelog 확인 |
| HearthMirror | HDT는 외부 `HearthMirror.dll`과 watcher 인터페이스를 사용. [HDT 빌드 스크립트](https://github.com/HearthSim/Hearthstone-Deck-Tracker/tree/master/build-scripts)와 프로젝트 참조 확인. 공개 소스 API만으로 배포 가능성을 보장할 수 없음 | 직접 연결하지 않음. 메모리 접근 없이 목적의 핵심을 달성할 수 있어 이번 범위에서 제외 |
| [Firestone](https://github.com/Zero-to-Heroes/firestone) | 공개 UI/서비스 코드 존재. `DiskCacheService`에 여러 개별 캐시 키가 있고 `user-match-history.json`은 deprecated 표시. Electron 서비스는 `app.getPath('userData')/data` 사용. replay 업로드와 앱 캐시가 분리됨 | 안정된 단일 로컬 export 계약으로 간주하지 않음. 내부 후킹 없음. 루트 LICENSE 미확인, 코드 재사용 없음 |
| [HearthSim/hslog](https://github.com/HearthSim/hslog) | Power 문법, entity/choice/send-choice 필드 표현을 검토. 범용 parser 기반 대안 | MIT (Jerome Leclanche). 새 숫자/문자 태그에 관대한 소규모 파서를 직접 작성하여 런타임 의존성 제거. 소스 복사 없음 |

Firestone에서 확인한 직접 소스: [disk-cache.service.ts](https://github.com/Zero-to-Heroes/firestone/blob/master/libs/shared/common/service/src/lib/services/disk-cache.service.ts), [electron-disk-cache.service.ts](https://github.com/Zero-to-Heroes/firestone/blob/master/apps/electron-app/src/app/services/electron-disk-cache.service.ts), [replay-upload.service.ts](https://github.com/Zero-to-Heroes/firestone/blob/master/libs/app/common/src/lib/services/replay-upload.service.ts). Firestone 전체가 폐쇄 소스라고 단정하지 않습니다. 로컬 캐시가 버전별로 바뀔 수 있고, 현재 목적에 필요한 행동 직전 수집 계약을 확인하지 못했기 때문에 채택하지 않았습니다.

현재 시즌의 Dark Gifts는 [Blizzard 시즌 14 공지](https://hearthstone.blizzard.com/en-gb/news/24290433)와 HDT/실제 로그 양쪽에서 확인했습니다. 실제 로그에 `BG36_Button_DarkGift`, `HAS_ACTIVATE_POWER`, `IS_NIGHTMARE_BONUS`가 있습니다. 시즌 데이터는 core parser와 분리했습니다.

## 선택: 독립적인 Power.log 로거

실행 중인 게임과 완전히 별도인 Python 프로세스가 표준 로그를 읽습니다. 서버 상태인 GameState 스트림을 사용하고 애니메이션 PowerTaskList 중복을 버립니다. 공개되지 않은 내부 메모리 구조와 HDT 플러그인 ABI에 의존하지 않습니다. API 키, 네트워크 서비스, Firestone/HDT 실행도 필요 없습니다.

핵심 설계는 `lexical parser → generic event journal → match reducer → immutable state/entity versions → JSON/Markdown projection`입니다. 사라지는 상점은 플레이 행동의 시작과 끝, 효과 블록 경계, 선택 목록에서 보존합니다. 상태가 수십 번 바뀌어도 과거 버전은 바뀌지 않습니다. 카드 id를 모르는 경우에도 엔티티와 태그를 보존합니다.

이 선택의 대가는 메모리 전용 UI, MMR, 가능 종족, 일부 시즌 특수 상점 정보의 누락입니다. 이를 추정해서 채우지 않고 null/quality로 표시합니다. 모든 로비의 비공개 보드 평균이나 실제 EV를 계산할 수 있다고 주장하지 않습니다. 이후 검증된 HDT 어댑터는 같은 schema에 부가 정보만 추가할 수 있습니다.

## 조사한 커밋

```text
HDT              b3535b18e794c318b5ec00a942f128315ca6c21c
DeepBattler       da31b8cfebab9ef30ce7af5cc57a19ef8dd9ef07
bg-tracker        fd3d3f0d7ff1475a67c25c3278a8ac2a5657d1b8
match-data fork   6829a3e77aae925fa34cfbbc3b0dd18abbc4ffdb
Firestone         0a30f066eb77a417637d95cec86444456f607ba1
hslog             015c0dec197779c90cd3131ecda2c990292342b6
```

Firestone 전체 checkout은 네트워크 오류로 완료되지 않아 Git tree와 필요한 raw source를 웹에서 직접 확인했습니다. 최신 카드 풀 전체나 모든 영웅을 조사/검증한 것은 아닙니다.
