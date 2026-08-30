---
story_key: 14-10-card-orientation-contract
story_id: "14.10"
epic: "Epic 14: 시각 자산 층 — 샷마다 생성하는 대신 승인된 세트에서 고른다 (배경·D급·오브젝트)"
created: 2026-08-30
source_status_before: (신규)
baseline_commit: 84cbdb4
---

# Story 14.10: 카드에도 승인 시점 측정 축을 붙인다 — 라벨이 픽셀과 어긋난다

Status: backlog

## Story

As Jay,
I want a card's angle label to be checked against its own pixels before it is approved,
so that a shot asking for a back view stops getting a front-facing figure composited into it.

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
