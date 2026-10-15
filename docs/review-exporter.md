# Compact review / dictionary / audit

기본 Compact는 Chat에 `.review.md` 한 파일만 올리는 복기를 지원한다. 선택지는 설명을 inline으로, 실제 상점의 미구매 카드와 상대 전장까지 포함한 규칙은 문서 뒤 `Relevant mechanics`에 cardId별 한 번 제공한다. 일반/황금 cardId는 별도다. 카드·선택지를 잘라 용량을 맞추지 않고, 반복 상태를 증감으로 압축한다. [버전·출처·변수 해석](card-metadata.md).

| 파일 | 역할 |
|---|---|
| `match.review.md` | AI가 기본적으로 읽을 선택지·행동·상태 변화·전투 결과. C/F/X 사전과 raw tag dump 없음 |
| `match.dictionary.json` | 필요할 때 조회할 카드·효과 사전, 관측별 entity revision과 상태, 묶인 행동과 생략된 재배치 |
| `match.audit.md` | 선택적 진단용 상세 렌더러. 중간 효과 상태와 전투 사건 수(전체 공격 순서는 JSON) |
| `match.json` / events 저널 | 전체 복기 그래프 / 전체 원본 태그 이력 |

`export match.json`은 세 출력 파일을 함께 생성한다. `--format review`는 review와 dictionary, `--format audit`는 audit만 생성한다. `--review-mode compact|debug`는 export/replay/recover/watch에서 지원한다. 파일명에 `.debug.review.md`를 주면 `.debug.dictionary.json`을 나란히 생성한다.

## 보존 및 압축 기준

- **상점:** 선택 가능한 옵션 목록과 행동 전후 경계를 합친다. 순서·개체·스탯·효과·단계·빙결 상태가 같은 상점만 반복 생략한다. A→B→A는 Q 번호의 재등장으로 명시한다. 미구매 카드, 리롤 결과, 업그레이드·시즌 효과 후 상점도 남긴다. 위치/생성자 같은 내부 관리 필드만 다른 버전은 같은 상태로 취급하되, 알 수 없는 gameplay 태그가 변하면 보수적으로 구분한다.
- **발견:** 같은 선택 ID의 끊기지 않은 접두 목록 생성 과정만 완성 목록으로 합친다. 후보의 실제 Entities[index]를 보존하고, CHOOSE는 같은 선택 ID의 고유한 대상 entityId를 찾아 `Chosen: 1. 카드명`으로 쓴다. choice ID를 후보 번호로 출력하지 않는다. 구형 JSON은 저장된 후보 목록 순서를 사용하며, 중복·누락·불일치로 확정할 수 없으면 번호를 생략한다. 미응답 선택, Dark Gift, 영웅·장신구·주문 후보도 보존한다.
- **보드/손패:** 턴 시작 전체 상태와 이후 추가·제거·변경만 쓴다. 변경 카드의 스탯·키워드는 현재값이며 이전 키워드가 빠지면 제거된 상태다. 강화 효과는 효과Δ로 추가·제거만 쓰고 나머지는 유지한다. `@`는 새 개체의 자리다. 관측된 황금 획득/변환은 표시하고, 트리플의 손패·개체 변화는 주문 묶기에서 제외한다. 로그에 없는 황금 생성 원인을 트리플로 지어내지는 않는다.
- **재배치:** `observed_send_option` + `confirmed_at_next_options`이며 순서 외 변화가 없을 때만 숨긴다. 전후뿐 아니라 사이 snapshot도 검사한다. 스탯·효과·상점·경제·선택 상태 변화, 다른 gameplay 행동 중첩, 설명에 확인된 인접/위치 효과, 미확인 요청이면 남긴다. 다음 실제 행동 당시 순서와 마지막 전투 순서는 명시한다.
- **주문 묶기:** 관측되고 명시적으로 resolved인 연속 SPELL_USE 중 같은 source 카드/효과와 같은 보드 target만 후보로 삼는다. 손패 소스 1장만 소모하고, 전장 전체의 스탯 및 기존 부착 효과 수치가 매회 같은 증분으로 증가할 때만 묶는다. 대상 변경, 개체·효과 추가/제거, 황금·종족·키워드 변경, 감소·불균등 증분, 미해석 태그 변경은 상세 출력을 유지한다. 경제·상점·영웅·버튼·시즌·선택 가능한 옵션도 같아야 하며, 잠시 바뀌었다 돌아오는 중간 관측이나 중첩 행동도 묶기를 막는다. 다른 행동과 재배치를 건너뛰어 묶지 않는다.
- **묶음 표기:** 행동 ID 범위(불연속 ID는 전체 목록), 횟수, 직접 대상과 대상별 횟수, 전후 골드, 영향받은 각 하수인의 최초/최종 스탯·누적 증분을 남긴다. 기존 부착 효과의 숫자 태그도 최초/최종 값으로 남긴다(`S1` = `TAG_SCRIPT_DATA_NUM_1`). 매회 증분이 같으므로 각 행동 경계의 중간값은 복원 가능하다. 이 수치는 관측값이며 강화 원인이나 자동 시전 횟수를 추론하지 않는다. 대상 변경 시 새 묶음으로 나누므로 대상 사이의 순서를 잃지 않는다. 원본 행동과 모든 전후 snapshot은 기존 dictionary에 그대로 보존한다.
- **전투:** 왼쪽→오른쪽 최종 보드와 상대 시작 보드 전체, 캡처 방식·결과·피해·치명상·종료 HP를 남긴다. 마지막 HP는 전투 종료 snapshot이 있을 때만 쓰며 음수를 0으로 바꾸지 않는다. 승률은 생성하지 않는다.
- **시간 순서:** 중첩 행동의 stateAfter는 실제 관측 sequence에 둔다. 바깥 Dark Gift의 결과 손패가 안쪽 CHOOSE보다 먼저 나오지 않는다. `⇒`는 이후 관측 변화이며 앞으로 나올 상대 보드는 당시 정보로 취급하지 않는다.

## 단일 파일 압축 보강

- 같은 상점에서 카드가 제거되거나 속성만 바뀌면 `Shop Qn.m: Δ(Qn.k)`로 표시한다. 남은 순서는 유지하며 자리가 당겨진다. 새 카드가 추가되거나 순서가 바뀌면 전체 목록을 쓴다. 차분은 전체보다 짧을 때만 사용한다.
- 행동 후 경제는 바뀐 항목만 쓴다. 카드 스탯과 키워드는 현재값을 쓰되 강화 효과 이름은 `효과Δ: −제거, +추가`만 쓴다. 목록에 없는 효과는 유지된다. 효과만 표시한 행에서는 기존 스탯과 키워드도 유지된다. 효과 이름 개수는 합체 횟수를 뜻하지 않는다. 턴 시작과 전투 전장은 계속 전체 표기한다.
- 턴 시작에 관측한 다음 상대와 이전 직접 대전 턴을 표시한다. 이전 전장을 현재 상대 전장으로 오인하지 않도록 구분한다.
- 전투에는 관측된 선공, 공격/사망/천보 소멸 사건 수와 첫 공격 최대 3회를 추가한다. 전체 전투 재현이 아니며 생략된 중간 효과와 공격 결과를 추론해서는 안 된다. `내 치명피해`는 로컬 플레이어 기준이다.
- 본문은 다른 파일 조회를 요구하지 않는다. 미해석 효과와 수집 누락은 판단 한계로 남긴다. 파서·원본 JSON·audit 형식은 변경하지 않는다.

## Sidecar schema v1

[JSON Schema](../bg_review/dictionary.schema.json). 본문에 내부 번호가 없더라도 `observations`를 Q/D/행동 ID로 조회하면 시점별 상세를 찾을 수 있다. 과거 스탯에 미래 버프 값을 섞지 않는다.

```text
dictionaryVersion       1
matchId                 원본 경기 ID
cards[C69]              cardId/name/tier/tribes/text/baseAttack/baseHealth
effects[F36]            펼친 효과 속성, tags는 원래 태그명
templates[X1]           Debug F 표현을 위한 평탄화 템플릿
effectTemplates[F36]    template + overrides; t=tags, t.S1=TAG_SCRIPT_DATA_NUM_1
entityStates[e5217v3]   해당 시점 속성/rawTags/card(C)/effects(F)/darkGift(F)
observations[Q8.5]      상점 snapshot ID
observations[D7.1]      발견 snapshot ID
observations[a75:before / a75:after]  행동 전후 snapshot ID
observations[turn:8:start / turn:8:combat / turn:8:combatEnd]
snapshots[s123]         경제·board/hand/shop/season 등의 entity revision 참조
optionSets             snapshot에 연결된 선택 가능 옵션 기록
actions[a75]            원본 행동 전체
actionGroups            본문 각 행동 행에 합쳐진 원본 ID 목록
suppressedReorders      본문에서 생략한 재배치 ID 목록
combats                 턴별 전투 시작/종료 참조와 결과·피해
result                  원본 경기 결과
mechanics               빌드·locale·commit·출처 URL/hash·실패 정보
mechanics.entities[ref]  관측별 실제 규칙 원문/템플릿/해석값/미확인 변수/충돌
mechanics.entities[ref].darkGifts  모든 선물의 실제 effect cardId/entityId, 적용 대상, 연결 근거, rawTags
mechanics.relevant[id]   본문에 수록한 cardId별 규칙 및 포함 근거
```

`effects`는 이미 펼친 값이므로 일반 조회에서는 X를 해석할 필요가 없다. 모든 action은 `actionGroups` 또는 `suppressedReorders` 중 하나에 정확히 한 번 속한다. `python -m bg_review validate match.dictionary.json`은 참조와 행동 분할을 검사한다.

0.4.1부터 상대의 선물은 DARK_GIFT_ENTITY가 없는 전투 복사본도 부착 효과로 식별한다. 본문 버프 목록 앞에 `Dark Gift:`로 표시하며 해당 효과의 설명을 Relevant mechanics에 포함한다. darkGifts는 복수형 배열이고, 단일 선물일 때만 호환용 darkGift 필드도 제공한다. 생성자의 cardId를 부착 효과 cardId로 대체하지 않는다.

Debug는 모든 재배치를 포함한 기존 review의 행동 흐름과 C/F/엔티티 표기를 사용한다. 사전 정의는 Compact와 동일한 sidecar로 옮겼다. Python API `export_review(data, mode='compact', dictionary_name='match.dictionary.json', catalog=None)`은 `(markdown, dictionary)`를 반환한다. 이 투영 API는 다운로드하지 않으며 기본적으로 정확한 빌드의 로컬 캐시만 조회한다. CLI/Session이 필요한 다운로드를 수행한다.

## 범위와 한계

Compact는 미해석 내부 효과를 일반 이름·스탯만으로 설명할 수 있다고 가정하지 않는다. 미해석 효과에 좌우되는 결론은 파일 내에서 확정 불가로 남긴다. 추가 진단 파일은 선택 사항이다. UI 클릭 가능 시간을 영상과 대조하지 않았으므로 선택 가능 상태는 로그 경계에 근거한 관측이다.

0.1 JSON에서는 제거된 옵션 경계를 되살릴 수 없다. 원본 또는 capture 저널을 새 버전으로 재생해야 한다. 원본 JSON의 `decisionSnapshots`는 선택적 추가 필드라 schemaVersion 1을 유지하며, sidecar dictionaryVersion과는 별개다.

실제 원본과 비교 산출물은 Git 제외 경로에만 둔다. 배포 예제는 가상 fixture다.
