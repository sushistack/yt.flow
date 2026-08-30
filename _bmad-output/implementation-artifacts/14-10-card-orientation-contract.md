---
story_key: 14-10-card-orientation-contract
story_id: "14.10"
epic: "Epic 14: 시각 자산 층 — 샷마다 생성하는 대신 승인된 세트에서 고른다 (배경·D급·오브젝트)"
created: 2026-08-30
source_status_before: (신규)
baseline_commit: 84cbdb4
---

# Story 14.10: 카드에도 **그림의 내용**을 재는 축을 붙인다 — 방향과 컷아웃 완결성

Status: backlog

## Story

As Jay,
I want a card's **declared angle** and its **cutout completeness** both checked against its own pixels before it is approved,
so that a shot asking for a back view stops getting a front-facing figure, and the model stops being handed a reference image with someone else's room baked into it.

## Context

### A. 실측 — `back` 라벨 12장 중 **4장이 정면**이다

2026-08-30 블라인드 판정(파일명·문서 비열람, 판정마다 픽셀 증거 인용):

| 판정 | n | |
|---|---|---|
| BACK (라벨 일치) | 8 | |
| **FRONT (라벨 불일치)** | **4** | `SCP-049-2/e1` · `SCP-1471/e1` · **`STOCK-d-class/e2`** · `STOCK-security/e1` |

대조군 6장도 깨끗하지 않다 — 완전 일치 3 / 부분 불일치 2(`side` 선언인데 three-quarter) /
**완전 불일치 1**(`STOCK-d-class/e2/side_candidate_1.png` 이 정면: 두 눈·가슴 번호판 `250`이
카메라에 평평·두 부츠 앞코 정면).

`STOCK-d-class/e2/back_candidate_1.png` 은 **주 에이전트가 육안 독립 확인**했다 —
얼굴, 가슴의 `225` 번호판, 중앙 앞지퍼, 정면 부츠. 나머지 11장은 재확인 대상이다.

### A-2. ⚠️ E2E iteration 5에서 재현됐고, **원인이 그 5장보다 크다** (2026-08-30)

새 런 `780cb8b3` 실측(사이드카의 14.3 귀속 블록 + 배달 프레임 대조):
**38패스 중 14건**이 선언 각도와 배달된 자세가 어긋나고 그중 **13건이 카드 라벨에서 온다.**

**§A의 5장 목록이 원인의 전부가 아니다** — 14건 중 그 목록에서 오는 것은 **3건**뿐이다.
`three_quarter`/`side` 라벨의 **다른 4장이 실제로는 정면**이고, 특히
`SCP-049/epoch_1/three_quarter_candidate_1.png` **하나가 6패스**를 몬다.
이 런이 쓴 카드 20장 중 **6장(30%)** 이 오라벨이다 — **예외 목록이 아니라 계통적 결함이다.**

**⚠️ §A 목록 자체의 오류도 하나 나왔다**: 목록의 두 행은 `epoch_1` 파일인데 이 런은
`epoch_2` 형제를 썼고 **그 둘은 라벨이 옳다**(`S00404`·`S00804`가 진짜 뒷모습을 배달했다).
**epoch 확인 없이 목록을 인용하면 멀쩡한 카드 둘을 기소한다.**

확증 프레임: `S00303` — `back` 카드를 썼는데 D급이 정면으로 서서 가슴의 `225` 번호판을 보인다.

### A-3. 결함이 둘이다 — **컷아웃 실패 카드가 계약을 통과한다** (신규)

`three_quarter_candidate_1.png` 을 열어보니 라벨만 문제가 아니었다 — **배경이 박혀 있고
무릎에서 잘려 있다**(전신 카드가 아니다). `assets/characters` **69장 전수**,
`domain.png.alpha_profile` 의 `opaque_fraction`:

| 군 | n | 값 |
|---|---|---|
| 정상 (인물만 남은 컷아웃) | 56 | 중앙값 **0.280**, 최대 **0.390** |
| **배경이 박힌 것** | **5** | **0.443 ~ 0.562** |
| 알파 채널 없음 | 8 | — |

**0.39와 0.443 사이가 비어 있다** — 임계값을 데이터에 맞춰 깎은 것이 아니라 간극이 실재한다.
그리고 **5장 전부 `sprite_contract` 통과**(`True: ok`)다.
`three_quarter_candidate_1` 의 `alpha_bbox` 는 `(12, 20, 728, 1204)` 로 832×1216 캔버스를
거의 채운다(정상 카드는 `(214, 51, 597, 1204)` 처럼 인물에 붙는다).

**계약의 버그가 아니라 누락된 축이다.** `sprite_contract` 는 *"투명 픽셀이 존재하는가"* 를
묻고 그 목적(완전 불투명 RGBA 검출)에는 옳다. *"불투명 영역이 인물 모양인가"* 는 묻지 않는다.

**부수**: 알파 없는 8장(`SCP-1471` 4 + `SCP-682` 4)은 계약이 **정확히 거부**하는데
(`no_alpha_channel`) 그중 하나가 `characters.angle_back_path` 에 등록돼 있다 —
계약이 **비소급**이라 이전 승인분은 검사받은 적이 없다.

### A-4. 왜 컷아웃이 방향보다 무거울 수 있는가

recompose는 카드를 **참조 이미지**로 받는다. 배경이 박힌 카드를 주면 모델에게
*"이 방 안의 이 인물"* 이 아니라 *"다른 방이 뒤에 붙은 인물"* 을 참조하라고 주는 것이다.
그 카드가 이 런에서 6패스를 돌았다. **얼마나 새어 나오는지는 미측정이다.**

### B. 왜 이것이 화면에 닿는가

`character_service.py:1500`이 샷의 `camera_angle`을 앵글 선택 카탈로그에 실어
`_select_entity_angles`가 `angle_*_path`를 고르고, **그 PNG가 recompose의 참조 이미지**가 된다.
recompose는 참조의 자세를 보존하므로 라벨 오류가 **그대로 프레임에 나온다.**

**실증**: `S00504`. Jay 2026-08-30 판정에서 *"위에서 아래를 내려다보는 앵글인데 캐릭터는
앞모습"* 으로 **세 arm 전부 기각**한 유일한 행이고, 그 샷이 쓴 카드가 위 4장 중 하나다.
즉 *"모델이 플레이트 시점을 무시했다"* 로 보이던 것의 **절반은 자산 라벨 문제**다.

### C. 구조적 갭 — 플레이트에는 있고 카드에는 없다

14.1이 플레이트에 붙인 것: 승인 시점에 `viewpoint` · `standing_room` · `depicts_person` 을
**측정**해 자산 메타데이터로 달고, 안 맞으면 배정을 거부한다(`_select_plate`).

카드의 승인 게이트(`approve_stock_cast.py`)가 재는 것: **`has_alpha` + `sprite_contract` 둘뿐**이다.
둘 다 *"이 PNG가 스프라이트인가"* 를 묻고, *"이 그림이 라벨대로 뒤를 보고 있는가"* 는
**아무도 묻지 않는다.** 그래서 `back` 라벨의 정면 카드가 승인을 통과해
`angle_back_path` 에 앉는다.

### D. 함께 드러난 것 — 애초에 카드가 아닌 파일 둘

`SCP-1471/e1/back_candidate_1.png` 은 **알파 없는 5인 시트**,
`SCP-682/e1/back_candidate_1.png` 은 **풍경 장면**(해변·산·행인)이다. 라벨 축과 별개의 결함이고,
`sprite_contract` 가 알파를 보는데도 살아 있다면 그 계약의 적용 범위를 확인해야 한다.

## Acceptance Criteria

1. **Given** 승인된 카드 전수, **when** 방향 판정을 돌리면, **then** 각 카드의 **선언 각도**와
   **측정된 방향**이 나란히 기록되고, 불일치가 `(scp_id, epoch, pose, 선언, 측정)`으로 열거된다.
   판정은 **파일명·프롬프트·저장소 문서 비열람**이어야 한다.
2. **Given** 방향 축, **when** 승인 게이트(`approve_stock_cast.py`)를 통과시키면, **then**
   선언 각도와 측정 방향이 어긋나는 카드는 **승인되지 않고** 사유와 함께 남는다.
   `has_alpha`/`sprite_contract` 는 그대로 유지된다(어느 것도 다른 것을 포섭하지 않는다).
2a. **Given** **컷아웃 완결성 축**, **when** 같은 게이트를 통과시키면, **then** 배경이 박힌
   카드가 **승인되지 않고** 사유와 함께 남는다. 임계값은 **측정 전에 사전등록**한다 —
   후보는 `opaque_fraction ≤ 0.40`(56/5 간극이 실재하나 사후 적합이 아님을 보이는 것은
   이 스토리 몫이다). ⚠️ **다섯 장을 육안 확인하라**: 넓은 옷·앉은 자세는 정상적으로도
   불투명 비율이 높고 실제로 5장 중 2장이 `sitting_*` 이다. 오탐이면 임계값이 아니라
   **측정 대상**을 바꿔야 한다(예: bbox 대 캔버스 비, 테두리 픽셀의 불투명도).
2b. **Given** 알파 채널이 없어 계약이 이미 거부하는 8장, **when** 확인하면, **then**
   그중 `angle_*_path` 에 등록된 것이 열거되고, **계약 비소급의 범위**가 기록된다.
3. **Given** 이미 승인된 카드 중 불일치가 확인된 것, **when** 스토리가 끝나면, **then**
   `angle_*_path` 를 **말없이 고쳐 쓰지 않는다** — `gotcha_standing-cards-have-no-approval-gate`:
   그 경로에 쓰는 것이 곧 출판이다. 정정 경로는 14.6이 출하한 스테이징 게이트를 탄다.
4. **Given** 라벨 정정 후, **when** `S00504`를 같은 매니페스트로 재렌더하면, **then**
   시점 불일치가 **얼마나 남는지**가 측정된다 — 라벨이 설명하는 몫과 남는 몫이 갈린다.
   **남는 몫이 0이면 그것이 결론이고 새 층을 만들지 않는다.**
5. **Given** 방향 축을 못 만들 때(재현 오차가 범주 폭보다 크면), **when** 스토리가 끝나면,
   **then** 그것이 결론으로 기록되고 게이트를 만들지 않는다 — 14.8이 `viewpoint` 에서 겪은 형태다.
6. **Given** `SCP-1471/e1` · `SCP-682/e1`, **when** 확인하면, **then** 이 둘이 카드 계약을
   통과한 경위가 기록된다(`sprite_contract` 의 적용 범위 확인).
7. **Given** 오라벨·컷아웃 실패 목록, **when** 인용하면, **then** **epoch까지 명시**된다 —
   `epoch_1` 의 결함을 `epoch_2` 형제에 전가하면 멀쩡한 카드를 기소한다(§A-2 실측).
8. **Given** 배경이 박힌 카드가 참조로 쓰인 샷, **when** 그 카드를 정상 컷아웃으로 바꿔
   재렌더하면, **then** 배경 누출이 프레임에 얼마나 닿았는지가 측정된다.
   **차이가 없으면 그것이 결론이고 컷아웃 축의 우선순위를 내린다.**

## Tasks / Subtasks

- [ ] **T1 — 방향 축의 판정 가능성 심사** (AC: 1, 5) · GPU 0
  - 재현 오차 < 범주 폭인지 **먼저** 확인한다. 14.8이 `viewpoint` 에서 이 검사를 안 하고
    시작했다가 축을 통째로 은퇴시켰다.
  - 방향은 시점보다 유리할 근거가 있다 — 범주가 연속값이 아니라 **이산**(front/back/side/
    three-quarter)이고, 판정 증거가 국소적이며(얼굴 유무, 가슴 폐쇄부, 발끝 방향) 실제로
    2026-08-30 판정이 12장 전부에 **픽셀 증거를 인용**했다. 그래도 **측정으로 확인**하라.
  - ⚠️ 함정: BACK 8장 중 3장이 **몸은 뒤인데 머리만 돌려 얼굴이 보인다**. 얼굴 유무로
    판정하면 이 셋을 FRONT로 뒤집는다. 판정 규칙은 **몸 단서**(어깨선·의복 폐쇄부·발 방향)여야 한다.
- [ ] **T2 — 전수 판정과 불일치 목록** (AC: 1)
- [ ] **T3 — 승인 게이트에 방향 축 추가** (AC: 2) · `scripts/approve_stock_cast.py`
- [ ] **T3a — 같은 게이트에 컷아웃 완결성 축 추가** (AC: 2a, 2b) · 임계값 사전등록 + 5장 육안 확인
- [ ] **T5a — 배경 누출의 크기 측정** (AC: 8) · GPU — 정상 컷아웃으로 교체 후 페어 렌더
- [ ] **T4 — 기존 불일치의 정정 경로** (AC: 3) — 14.6의 스테이징 게이트를 탄다
- [ ] **T5 — `S00504` 재렌더로 잔여 시점 불일치 측정** (AC: 4) · GPU
- [ ] **T6 — 카드 아닌 두 파일의 경위 확인** (AC: 6)
- [ ] **T7 — 기록**

## Dev Notes

### 🚫 하지 말 것

- **`angle_*_path` 에 말없이 쓰지 마라** — 그 경로에 쓰는 것이 곧 출판이다.
- **얼굴 유무를 방향 판정 규칙으로 쓰지 마라**(§T1 함정).
- **프롬프트를 고쳐 방향을 만들려 하지 마라** — 텍스트가 픽셀 속성을 보장하지 못한다는 것이
  이 에픽에서 세 번 실측됐다(14.0 §4-4 시점 2/5 뒤집힘, 14.1 변형 `b` 2/14, 14.1 증설 `d`/`e` 2/20).
- **오라벨 목록을 epoch 없이 인용하지 마라** — §A-2에서 실제로 두 장을 잘못 기소할 뻔했다.
- **임계값을 데이터에 맞춰 깎지 마라** — `opaque_fraction` 의 56/5 간극은 실재하지만,
  그것을 보고 0.40을 고른 것과 사전등록한 것은 다르다(AC2a).
- **판정을 사람 없이 닫지 마라** — 이 에픽에서 Claude 단독 시각 라벨이 **네 번** 뒤집혔다
  (14.2 인계 2건 · 14.2 미검출 1건 · 14.3 `S00105`).

### 이 스토리가 3번 항목(`S00504` 시점 불일치)을 흡수한 이유

라벨 결함이 그 결함의 **절반을 설명**하고, 나머지 절반의 크기는 **라벨을 고치고 다시 렌더해야**
알 수 있다. 따로 스토리를 파면 크기를 모르는 결함에 스토리를 배정하는 것이다. AC4가
그 분리를 담당하고, **남는 몫이 0이면 새 층을 만들지 않는 것이 정답**이다.

### 소스 트리

| 경로 | 역할 |
|---|---|
| `scripts/approve_stock_cast.py` | **T3 수정 지점.** 현재 `has_alpha` + `sprite_contract` 둘만 잰다 |
| `scripts/seed_stock_cast.py` | 스테이징(`--stage`). 14.6이 임의 키·임의 포즈로 넓혔다 |
| `src/yt_flow/services/character_service.py:1500` | 읽기 전용. `camera_angle` → 앵글 선택 카탈로그 |
| `src/yt_flow/domain/png.py` | 읽기 전용. `alpha_profile` · `has_alpha` · `sprite_contract` |
| `scripts/report_card_coverage.py` | 14.6이 출하한 라이브러리 감사기. 방향 축을 여기에도 실어야 한다 |

### References

- [Source: _bmad-output/implementation-artifacts/14-9-recompose-placement-scale/CARD-ANGLE-LABELS-2026-08-30.md] — **전수 판정 결과와 증거**
- [Source: _bmad-output/implementation-artifacts/14-9-recompose-placement-scale/SCALE-AND-VIEWPOINT-2026-08-30.md] — `S00504` 진단(플레이트 near-nadir, 인물 눈높이 입면), 카드에 pitch 축이 없다는 확인
- [Source: _bmad-output/implementation-artifacts/14-9-recompose-placement-scale/VERDICT.md] — Jay 2026-08-30 판정 원문
- [Source: _bmad-output/implementation-artifacts/spec-14-6-dclass-object-asset-sets.md] — 스테이징·승인 게이트가 무엇이 됐는지
- [Source: _bmad-output/implementation-artifacts/14-8-plate-reuse-shipping.md] — 축을 만들기 전 판정 가능성을 먼저 심사하는 형태

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
