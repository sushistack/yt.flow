# Story 14.1 — 승인 배경 플레이트 세트 측정 + 커버리지 리포트 (2026-08-25)

GPU 0 · 신규 렌더 0 · ComfyUI 미기동 · 런타임 프롬프트(`prompts/`) 변경 0 · VLM 84콜.
`stock_plate_substitution_enabled` 는 **`False` 그대로**다(코드 기본값, `.env` 핀 없음).

재산출:

```
uv run python .../measure_plates.py --dry-run     # 42장 열거, VLM 0
uv run python .../measure_plates.py --sheets      # sheet_1..7.jpg, VLM 0
uv run python .../measure_plates.py --commit      # CSV + 84콜 -> plate_meta.json + manifest
uv run python .../replay_coverage.py 4b35c0ed     # §2·§3·§4·§5 의 모든 수치
```

사전등록: `PREREGISTRATION.md`(플레이트를 보기 전에 작성, 이후 무수정).
판정에 쓴 콘택트 시트는 14-0 의 512px 3×3 이 아니라 **1024px 타일 2×3 · 7장**이다(보조선·순서·규칙은 동일). 0.40 경계에서 ±0.05 를 읽어야 하는 판정이라 배율이 판정 품질을 직접 좌우한다 — CLAUDE.md 의 "~512px 로 축소하되 판정 기준이 더 요구하면 예외"의 그 예외다. 합계 3.4 MB(14-0 의 2.0 MB 대비).
원자료: `viewpoint_verdicts.csv`(42행 사람 판정) · `plate_meta.json`(42행 최종 메타) · `sheet_*.jpg`(판정에 쓴 그 이미지).

---

## 0. 이 리포트가 **주장하지 않는** 것 (먼저 읽어라)

- **합성 산출물의 픽셀 판정을 0회 했다.** 플레이트 위에 카드가 어떻게 서는지, 배경 정합이
  시청에서 어떻게 보이는지는 이 스토리가 측정하지 않았다. 그것은 치환을 켠
  **E2E iteration 5** 몫이고, 그 런 없이 "고쳤다"는 문장은 이 문서에 없다.
- **"배경 불일치가 줄었다"를 주장하지 않는다.** 줄어들 **경로**가 생겼고 그 경로가 오늘
  세트로는 servable 24샷 중 17샷만 덮는다는 것까지가 측정된 전부다.
- **어포던스 42/42 판정은 재현 실험이 아니다.** 플레이트당 1콜, 반복 없음(사전등록 §3).
  14.2 가 같은 엔드포인트에서 조건 내 뒤집힘 0 을 실측했다는 사실에 기대어 반복을 사지 않았고,
  그 선택이 표본 밴드의 일부다.
- **`depicts_person` 42/42 `false` 는 `[text, image]` 봉투에 한정된 수치다.** 그 축의 순서
  효과는 미측정이고 `deferred-work.md` 로 넘겼다.
- **맹검이 완전하지 않았다** — §1-1 에 사전등록된 침해를 그대로 적었다.
- **리뷰 루프 1 에서 아무것도 다시 재지 않았다.** 시점 42행은 일회성 맹검이라 재도출이
  불가능하고(이미 본 뒤에는 다시 맹검일 수 없다), VLM 84콜도 다시 쓰지 않았다. 바뀐 수치는
  `marginal` 열 하나뿐이고 그것은 측정이 아니라 `y_h` 의 **순수 함수**다 — 사전등록된 규칙을
  코드로 다시 적용했을 뿐이다(§1-1). 그 결과가 §3 의 결론을 5장에서 **2장 + 재판독 3셀**로
  바꿨고, 옛 숫자를 보존하지 않고 새 결론을 적었다.
- **D1 은 승인 철회가 아니다.** 인물이 보이는 플레이트를 *이 샷에* 쓰지 않을 뿐, 자산의
  `status` 는 `approved` 그대로다. 철회는 §8 의 사람 판단 대기 목록에서만 일어난다.
- **`entrance-checkpoint/b` 의 2026-08-25 재판정은 존재하지 않는다.** 측정 스크립트가 그때
  `has_person` 을 버렸고(§9), 이 루프에서 스크립트는 고쳤지만 **84콜을 다시 쓰지 않았으므로
  값은 소급되지 않는다**. 오늘 D1 이 그 플레이트를 거르는 근거는 2026-08-02 라벨 하나다.

---

## 1. 42장 측정 표

표본 밴드: `location_plates` 의 `status='approved'` 42행 = 14 `location_key` × 3 variant,
`style_epoch=2`, 전부 1920×1080 PNG. 2026-08-25 스냅샷.
시점은 사람(에이전트) 판정 — 1024px 타일 콘택트 시트 + 사전등록 보조선 0.40/0.50/0.60,
`location_key/variant` 오름차순, 프롬프트·`VARIANT_CAMERAS` 비열람.
`standing_room` / `depicts_person` 은 `qwen-vl-plus`, `temperature=0`, 플레이트당 각 1콜.

| location_key | variant | viewpoint | y_h | marg | ceil | floor | standing_room | depicts_person |
|---|---|---|---|---|---|---|---|---|
| autopsy-room | a | EYE | 0.45 | ● | Y | 0.15 | true | false |
| autopsy-room | b | **HIGH** | 0.38 | ● | Y | 0.35 | true | false |
| autopsy-room | c | EYE | 0.46 | | Y | 0.20 | true | false |
| cafeteria | a | EYE | 0.43 | ● | Y | 0.20 | true | false |
| cafeteria | b | EYE | 0.41 | ● | Y | 0.10 | true | false |
| cafeteria | c | EYE | 0.42 | ● | Y | 0.12 | true | false |
| containment-chamber | a | EYE | 0.41 | ● | N | 0.25 | true | false |
| containment-chamber | b | EYE | 0.52 | | N | 0.20 | true | false |
| containment-chamber | c | EYE | 0.43 | ● | N | 0.22 | true | false |
| control-room | a | EYE | 0.46 | | Y | 0.30 | true | false |
| control-room | b | EYE | 0.45 | ● | Y | 0.30 | true | false |
| control-room | c | EYE | 0.47 | | Y | 0.28 | true | false |
| corridor | a | EYE | 0.42 | ● | Y | 0.35 | true | false |
| corridor | b | EYE | 0.42 | ● | Y | 0.42 | true | false |
| corridor | c | EYE | 0.44 | ● | Y | 0.40 | true | false |
| entrance-checkpoint | a | EYE | 0.57 | ● | Y | 0.10 | true | false |
| entrance-checkpoint | b | EYE | 0.52 | | Y | 0.15 | true | false |
| entrance-checkpoint | c | **LOW** | 0.72 | | Y | 0.05 | true | false |
| facility-exterior | a | **HIGH** | 0.19 | | N | 0.80 | true | false |
| facility-exterior | b | **LOW** | 0.66 | | N | 0.12 | true | false |
| facility-exterior | c | EYE | 0.52 | | N | 0.30 | true | false |
| interview-room | a | EYE | 0.52 | | Y | 0.35 | true | false |
| interview-room | b | EYE | 0.55 | ● | Y | 0.40 | true | false |
| interview-room | c | EYE | 0.55 | ● | Y | 0.35 | true | false |
| maintenance-tunnel | a | EYE | 0.46 | | Y | 0.30 | true | false |
| maintenance-tunnel | b | **HIGH** | 0.39 | ● | Y | 0.25 | true | false |
| maintenance-tunnel | c | EYE | 0.52 | | Y | 0.35 | true | false |
| medical-bay | a | EYE | 0.47 | | Y | 0.25 | true | false |
| medical-bay | b | EYE | 0.45 | ● | Y | 0.32 | true | false |
| medical-bay | c | EYE | 0.47 | | Y | 0.25 | true | false |
| observation-room | a | EYE | 0.45 | ● | N | 0.22 | true | false |
| observation-room | b | EYE | 0.45 | ● | Y | 0.30 | true | false |
| observation-room | c | EYE | 0.47 | | Y | 0.25 | true | false |
| office | a | EYE | 0.50 | | N | 0.05 | true | false |
| office | b | EYE | 0.50 | | N | 0.10 | true | false |
| office | c | EYE | 0.50 | | N | 0.10 | true | false |
| server-room | a | EYE | 0.44 | ● | Y | 0.12 | true | false |
| server-room | b | **HIGH** | 0.00 | | N | 0.85 | **false** | false |
| server-room | c | **LOW** | 0.70 | | Y | 0.02 | **false** | false |
| storage-vault | a | EYE | 0.48 | | Y | 0.15 | true | false |
| storage-vault | b | **LOW** | 0.68 | | Y | 0.30 | true | false |
| storage-vault | c | **LOW** | 0.62 | ● | Y | 0.25 | true | false |

**집계**: `EYE` 33 · `HIGH` 4 · `LOW` 5 · `UNREADABLE` 0.
`standing_room=true` 40 / `false` 2 / 판정불가 0.
`depicts_person=true` 0 / 판정불가 0.
경계 ±0.05 (`marginal`) **20건**(사전등록 §2 의 밴드로 재산출 — 아래 §1-1).

`camera_distance` 는 **측정하지 않았다**. `STANDING_ROOM_PROMPT` 는 그 필드를 포함하지만
런타임 함수 `plate_has_standing_room` 은 `bool | None` 만 돌려주고, 나머지 네 필드를 얻으려면
요청을 손수 다시 조립해야 한다 — 스토리 제약이 금지한 것이 정확히 그것이고(봉투가 갈리면
14.2 의 5/7 이 출하 설정의 수치가 아니게 된다), 두 번째 콜은 같은 질문에 두 답을 만든다.
모델 자유텍스트 `reason` 은 `plate_meta.json` 의 `affordance_reason` 에 남겼다(같은 콜의
로그 레코드에서 수거, 추가 콜 0).

### 1-1. 맹검의 한계 (사전등록에 미리 적은 그대로)

판정자(이 세션)의 **작업 지시문에 `VARIANT_CAMERAS` 선언이 이미 문장으로 들어 있었다**
(a=eye-level, b=low-angle, c=off-axis). 판정 중 파일을 열지는 않았지만 사전확률을 모르는
상태가 아니었다. 그러므로 §5 의 선언-대-실측 일치율은 **하한이 아니라 상한**이고,
일치가 높게 나와도 ControlNet 기하 제어의 유효성을 확증하지 않는다. 이 한계는 결과를
보기 전에 `PREREGISTRATION.md` §2 에 적었다.

두 번째 한계: `y_h` 는 1024px 타일 위 눈대중이며 실효 정밀도는 대략 **±0.05** 다.
사전등록 §2 가 `marginal` 을 정확히 그 폭으로 정의했다.

**⚠️ 이 열은 처음에 잘못 찍혀 있었다(리뷰 루프 1 정정).** 첫 판정에서 실제로 적용된 폭은
사실상 ±0.03 이었다 — 0.43 은 marginal 인데 0.44·0.45·0.55 는 아니었다. 사전등록을 결과에
맞춰 고치는 것은 금지돼 있으므로(§ 사전등록 서문) **CSV 를 사전등록에 맞춰 다시 찍었다**:
9행이 0→1 로 바뀌어 marginal 은 11 → **20**이 됐다. `y_h`·`verdict`·`ceiling_visible`·
`floor_share` 는 사람의 맹검 판정이므로 한 글자도 건드리지 않았다(marginal 은 `y_h` 의 순수
함수다). 재발 방지: `measure_plates._read_verdicts` 가 이제 매 실행마다 열을 규칙과 대조해
어긋나면 거부한다. 그래서 아래 민감도 절은 **11 이 아니라 20 위에서** 다시 유도한 것이다.

**민감도(20 marginal 기준).** 미달 5셀 중 **3셀이 측정 노이즈 안에 든다**:

| 미달 셀 | 노이즈 안? | 근거 |
|---|---|---|
| (corridor, HIGH) | **예** | corridor a·b `0.42`, c `0.44` — 세 장 전부 `EYE↔HIGH` 경계 안 |
| (medical-bay, HIGH) | **예** | medical-bay/b `0.45` |
| (observation-room, HIGH) | **예** | observation-room a·b `0.45` |
| (containment-chamber, LOW) | 아니오 | 최대 `y_h` 가 0.52, `LOW` 경계 0.60 까지 0.08 |
| (observation-room, LOW) | 아니오 | 최대 `y_h` 가 0.47, 0.60 까지 0.13 |

반대 방향도 확인했다: **뒤집기가 이미 커버된 셀을 깨뜨리지는 못한다.** 커버된 EYE 5셀은
전부 marginal 이 아닌 플레이트를 최소 한 장씩 갖는다(autopsy-room/c `0.46` ·
containment-chamber/b `0.52` · control-room/a·c · medical-bay/a·c · observation-room/c `0.47`),
그리고 그 생존 플레이트들은 전부 `standing_room=true` 다 — 즉 **C1·C2 의 PASS 는 marginal
20건의 최악 조합에도 살아남는다.** 노이즈는 미달 쪽으로만 작용한다.

### 1-2. 두 계기가 정면으로 어긋난 한 행 — `server-room/b`

| 계기 | 이 플레이트에 대해 말한 것 |
|---|---|
| 사람(맹검 시점 판정) | `HIGH`, `y_h=0.00`, `floor_share 0.85`, rule `floor_fill` — **바닥면이 프레임을 채운다** |
| VLM(`plate_has_standing_room`) | `standing_room=false`, reason: *"The frame shows a close-up of a ceiling or upper structure with **no visible floor**."* |

두 진술은 화해되지 않는다. 한쪽은 프레임의 85%가 바닥이라 하고 다른 쪽은 바닥이 아예 없다고 한다.
`server-room/c` 도 `standing_room=false` 지만 거기서는 두 계기가 어긋나지 않는다(사람 `LOW`,
`ceiling_dom`, `floor_share 0.02` ↔ VLM *"close-up of server racks with no visible floor"* — 일치).

**이 한 행이 이 리포트에서 두 계기를 대조할 수 있는 유일한 지점이다.** 시점은 사람이, 어포던스는
VLM 이 재는데 둘이 같은 대상(바닥의 존재)에 대해 말한 곳이 여기뿐이기 때문이다. 그리고
**C2 = PASS 는 바로 그 VLM 계기 위에 서 있다** — 플레이트당 1콜, 반복 없음(사전등록 §3),
9셀 전부가 그 단발 판정의 `standing_room=true` 로 통과했다. 어느 쪽이 틀렸는지는 이 스토리가
판정하지 않는다(픽셀 재판정 0회). 값싼 판별: `sheet_7.jpg` 의 `server-room/b` 타일을 사람이
다시 보고 바닥/천장을 적으면 되고, GPU·VLM 콜 0 이다. `server-room` 은 run `4b35c0ed` 의 수요
셀에 없으므로 오늘의 커버리지 수치에는 영향이 없다 — 영향받는 것은 **C2 PASS 의 신뢰도**다.

---

## 2. run `4b35c0ed` 31샷 재생 커버리지

선택기는 **출하 코드**(`image._select_plate`)를 그대로 호출한다. 오프라인, 렌더 0.

**⚠️ 리뷰 루프 1 정정**: 첫 산출은 선택기에 CLI 접두사(`4b35c0ed`)를 `run_id` 로 넘겼다.
타이브레이크는 `run_id` 를 해싱하므로 **집계는 옳지만 샷별 플레이트 이름이 그 런과 재현되지
않았다.** 이제 체크포인트에서 전체 `thread_id` 를 읽어 넘긴다. 아래 이름은 재산출된 값이다.

```
thread_id 4b35c0ed-8a1e-4448-8594-11bd9997376d  (plate_affordance_gate_enabled=False)
run 4b35c0ed: 43 shots, 31 carry a location_key, 12 do not

  match                  17
  unservable_framing      7
  no_viewpoint_match      7

servable shots (camera_angle maps to a viewpoint): 24  ->  match 17 (70.8%)
cast-bearing hits whose plate lacks standing_room=True: 0
```

마지막 줄이 **어포던스 노브가 이 재생을 바꾸지 않는다**는 증명이다: 히트한 cast 샷의 플레이트가
전부 `standing_room=true` 이므로 D2 의 필터는 노브가 위든 아래든 아무것도 거르지 않는다.
(출하 기본값은 `plate_affordance_gate_enabled=False` 이고, 위 수치는 그 값으로 얻었다.)

| 결과 | 샷 수 | 설명 |
|---|---|---|
| 정합 히트 | **17** | 전부 `EYE`. 히트한 플레이트: containment-chamber/a·b, observation-room/a·b, autopsy-room/c, medical-bay/c, control-room/c |
| `unservable_framing` | **7** | `close-up` 6 + `POV` 1 — **설계상 영구 폴백** |
| `no_viewpoint_match` | **7** | `high-angle` 4 + `low-angle` 3 — 해당 키에 그 시점 플레이트가 0장 |
| `no_standing_room` | 0 | 히트한 `EYE` 후보는 전부 `standing_room=true` — 노브 값과 무관(위 참조) |
| `plate_shows_person` | 0 | 수요 7키에 `has_person`/`depicts_person` 플레이트가 없다. `entrance-checkpoint/b`(라벨 `has_person: true`)는 이 런의 수요 셀 밖이다 — D1 은 **이 런에서 발화하지 않으며**, 단위 테스트로만 고정돼 있다 |
| `no_metadata` | 0 | 42/42 측정 완료 |
| `partial_metadata` | 0 | 같은 이유 — 부분 측정된 키가 없다 |
| `unknown_framing` | 0 | 43/43 이 `camera_angle` 을 갖는다(14.0) |
| `stock_plate_missing` | 0 | 수요 7키 전부 승인 플레이트 보유. 승인 플레이트 0 인 키는 선택기 사유가 아니라 이 코드로 센다(런타임과 동일) |

**AC 확인**: `close-up` 6샷과 `POV` 1샷은 전부 생성 폴백이다 — 7/7.

`no_viewpoint_match` 7샷의 내역: `high-angle` = corridor(1) · medical-bay(1) · observation-room(2);
`low-angle` = containment-chamber(2) · observation-room(1).

**결정성**: 같은 씬·같은 `location_key`·같은 `viewpoint` 는 같은 플레이트를 받는다
(씬 6 의 3샷이 전부 `autopsy-room/c`, 씬 7 의 3샷이 전부 `medical-bay/c`) — 8.17 이
"spatial continuity" 라고 부르던 성질은 **씬당 1장이 아니라 (런, 씬, 키, 시점, 후보집합)당
1장**으로 살아남았다. 씬이 다르면 다를 수 있다: `containment-chamber` 는 씬 3 이 `/b`,
씬 2·4·8·9 가 `/a` 다.

**D3 이 이 런에서 실제로 보인다**: 씬 4 의 `S00400`(cast 있음)과 `S00401`(cast 없음)이
둘 다 `containment-chamber/a` 를 받고, 씬 7 의 `S00700`(cast 없음)과 `S00701`·`S00703`
(cast 있음)이 둘 다 `medical-bay/c` 를 받는다. 타이브레이크 digest 가 자기가 인덱싱하는
후보 풀 자체를 키에 포함하므로, 필터가 두 샷에게 같은 후보를 남기는 한 둘은 반드시 같은
플레이트를 받는다.

---

## 3. 부족분 — (location_key, viewpoint) 셀

사전등록 §5 의 기준 판정:

```
C1 cell coverage      : FAIL (5/10 cells)
C2 affordance coverage: PASS
C3 servable share >= 90%: FAIL (17/24 = 70.8%)
```

| location_key | viewpoint | 수요 샷 | cast 샷 | C1 | C2 |
|---|---|---|---|---|---|
| autopsy-room | EYE | 3 | 3 | OK (2장) | OK (2장) |
| containment-chamber | EYE | 7 | 6 | OK (3장) | OK (3장) |
| containment-chamber | LOW | 2 | 2 | **MISS** | **MISS** |
| control-room | EYE | 1 | 1 | OK (3장) | OK (3장) |
| corridor | HIGH | 1 | 0 | **MISS** | – |
| medical-bay | EYE | 3 | 2 | OK (3장) | OK (3장) |
| medical-bay | HIGH | 1 | 1 | **MISS** | **MISS** |
| observation-room | EYE | 3 | 3 | OK (3장) | OK (3장) |
| observation-room | HIGH | 2 | 1 | **MISS** | **MISS** |
| observation-room | LOW | 1 | 1 | **MISS** | **MISS** |

### 증설 배치가 렌더해야 할 것 (렌더 전에 확정된 명세)

**§1-1 의 정정된 marginal 집합(20건) 위에서 다시 유도했다.** 미달 5셀은 두 부류로 갈린다.

| 셀 | 필요 | 조건 | 판정 |
|---|---|---|---|
| (containment-chamber, LOW) | ≥1장 | 설 자리 필요(cast 2샷) | **확정 부족** — 최대 `y_h` 0.52, 경계까지 0.08 |
| (observation-room, LOW) | ≥1장 | 설 자리 필요(cast 1샷) | **확정 부족** — 최대 `y_h` 0.47, 경계까지 0.13 |
| (corridor, HIGH) | ≥1장? | cast 없음 | **측정 노이즈 안** — a·b `0.42`, c `0.44` |
| (medical-bay, HIGH) | ≥1장? | 설 자리 필요(cast 1샷) | **측정 노이즈 안** — b `0.45` |
| (observation-room, HIGH) | ≥1장? | 설 자리 필요(cast 1샷) | **측정 노이즈 안** — a·b `0.45` |

**확정 최소는 5장이 아니라 2장이다** — 두 `LOW` 셀. 나머지 3셀은 "플레이트가 없다"가 아니라
**"이 정밀도로는 있는지 없는지 말할 수 없다"** 이고, 그 셀들의 다음 수는 GPU 배치가 아니라
**해당 플레이트 6장(corridor a·b·c, medical-bay/b, observation-room a·b)의 `y_h` 재판독**이다
(더 큰 배율 또는 두 번째 판정자, GPU 0 · VLM 0). 재판독이 `EYE` 로 확정되면 그때 3장을 더
렌더하고 총 5장이 된다.

**두 `LOW` 는 어떤 재판독 결과에서도 필요하다.** 세 `HIGH` 셀이 전부 노이즈 뒤집기로 채워진다고
가정해도 히트는 4샷 늘어 21/24 = **87.5% 로 C3 의 90% 에 못 미친다**. C3 를 넘기는 것은
`LOW` 3샷(containment-chamber 2 · observation-room 1)뿐이고, 그것을 채우면 24/24 = 100% 다.
즉 **증설 배치의 필수 명세는 `LOW` 2장이고, `HIGH` 0~3장은 재판독에 달려 있다.**

C1 은 10셀 전부를 요구하므로 `HIGH` 3셀이 재판독에서 `EYE` 로 확정되면 C1 을 위해 그 3장도
필요해진다 — C3 는 2장으로 넘지만 C1 은 최대 5장을 요구할 수 있다. 어느 경우든 기준 (a)는
**도달 가능하다**(14.2 의 "구성상 도달 불가" 사례가 아니다). 그래도 이 스토리는 플래그를
켜지 않는다: (b) Jay 의 E2E 시청 판정이 AND 조건이다. ~~여기에 **(c) 릴라이트 결합 수정**이 붙는다(§7 — 증설이 도착하면 한 키가 여러 플레이트를 갖게 되어 그 결함의 발화 빈도가 오른다).~~ **⚠️ 2026-08-29 Story 14.3 정정 — 이 조건은 성립하지 않는다.** 문제의 페어 키(`composite_harmonization.py:613`)는 `precompute_relights`(`:504`) 안에 있고, 그 함수는 `video.py`가 `composite_harmonization_tier >= 3`에서만 호출한다. 출하 기본값은 **1**이고 tier 3(IC-Light)은 10.1b가 시청 판정으로 기각했다. **그 한 줄로 도달 불가는 성립하고, 그 뒤에 아무것도 필요하지 않다.** ⚠️ 이 정정의 초판은 여기에 *"게다가 recompose ON 하에서 0/43 샷이 카드 컴포지팅 체인에 진입하지 않으므로 두 이유 중 어느 하나만으로도 충분"*이라는 두 번째 다리를 붙였는데, **그것은 불변식이 아니라 run `4b35c0ed`의 관찰이다** — `recompose_run_shots`의 `remaining.pop(shot_key)`는 성공·재진입 분기에서만 실행되므로 `failed`(스윕 중 ComfyUI 사망, 플레이트 판독 실패)나 `skipped`(`card_key`가 `CARD_LOOKS` 밖)로 세어진 샷은 cast를 그대로 들고 오버레이/하모나이제이션 체인에 **진입한다**. 실패가 하나라도 나는 런에서는 0/43이 아니다. **0/43은 관찰로 강등하고, 반증은 `tier >= 3` 하나로 선다.** 이 프로젝트에서 이 형태(기록된 원인이 뒤집힘)는 이번이 **세 번째**이고, 세 번째는 **정정하는 문서 자신이 심은 과장**이었다 — `replay_coverage.py`가 보여준 것은 **플레이트 배정**의 공유이지 릴라이트 캐시의 발화가 아니다. **이 인계 항목의 두 번째 발화 조건 정정이다**(첫 번째는 14.1 리뷰 루프 1의 '씬 내부'→'런 전체'), 그래서 원문을 지우지 않고 취소선으로 남긴다(`gotcha_recorded-root-cause-can-be-inverted`). 결합 자체는 **여전히 결함이고 여전히 미수정**이며 tier 3을 켜면 발화한다 — 인계는 유지된다. 바뀐 것은 플래그 해제와의 결합이 끊긴 것이다. 고정: `test_precompute_relights_is_unreachable_at_the_shipped_tier`. 근거: `14-3-art-style-contract/report.md` §6. 남는 조건은 (a)·(b) 둘뿐이다.

증설 방식에 대한 제약: **한 장에서 변형을 파생하지 마라**(`project_stock-plate-reuse-is-intent`).
그리고 §5 가 보여주듯 **프롬프트에 "low angle" 을 쓴다고 LOW 가 나오지 않는다**(2/14) —
증설 배치는 렌더 후 `y_h` 를 재고 밴드 밖이면 시드를 올리는 형태여야 하고, 그 판정에
쓸 규칙과 시트 빌더는 이 디렉터리에 이미 있다(`measure_plates.py --sheets`).

---

## 4. `location_key` 미보유 12/43 의 성격과 감수 리스크

12샷 = 씬 1 전체(6) + 씬 5 전체(5) + `S00903`.

**어휘 갭이 아니라 발화 갭이다.** 12샷 중 **7샷의 `image_prompt` 가 `LOCATION_KEYS` 의 방
이름을 문자 그대로 쓰고 있는데도** 필드가 비어 있다:
`S00101`·`S00103`·`S00104`·`S00105`·`S00501`·`S00502` → `containment-chamber`,
`S00903` → `observation-room`. 나머지 5샷(`S00100`·`S00102`·`S00500`·`S00503`·`S00504`)은
`containment testing chamber` / `containment wall` / `containment cell` / `empty air` 로
쓰여 정확한 키 문자열은 아니지만, 넷은 같은 방을 서술한다. 즉 이 12샷은 **어휘에 없는
장소라서 빠진 것이 아니라 시나리오 단계가 필드를 채우지 않아서 빠졌다.**

이것이 왜 중요한가: 승인 게이트(③⑤⑦ + 14.4 가 넘긴 "그림 속 인물")는 **플레이트에만**
걸린다. `location_key` 가 없는 샷은 자유생성이고 승인 게이트에 도달하지 않는다.
오늘 그 갭은 12/43 이 아니라 사실상 **43/43** 이다(치환이 꺼져 있으므로).
치환을 켜도 17/43 만 게이트 뒤로 들어오고, §3 의 확정 부족분 `LOW` 2장을 증설하면 20/43,
재판독 뒤 `HIGH` 3셀까지 채우면 최대 24/43 이 된다.
**나머지 19/43(unservable 7 + 미발화 12)은 감수 리스크로 남는다** — 이 스토리는 그 숫자를
줄이지 않았고, 줄이는 방법은 두 가지다: (i) 시나리오 단계가 `location_key` 를 더 자주
발화하게 하기(7샷은 이미 텍스트에 답이 있으므로 값싼 표적), (ii) 자유생성 샷을 덮는
런타임 경로 — 14.2 가 이미 출하했고 14.4 가 명시적으로 감수 리스크로 등재했다.
부정 프롬프트는 해법이 아니다(`gotcha_negative-prompt-overstuffing`).

---

## 5. 선언 vs 실측 — `VARIANT_CAMERAS` 는 절반만 지켜졌다

```
a: declared EYE              measured {'EYE': 13, 'HIGH': 1}          agreement 13/14
b: declared LOW              measured {'HIGH': 3, 'EYE': 9, 'LOW': 2} agreement  2/14
c: declared off-axis framing measured {'EYE': 11, 'LOW': 3}           agreement n/a
```

`VARIANT_CAMERAS` 는 a = *"wide establishing shot from the doorway, eye level"*,
b = *"three-quarter view from a corner of the room, low angle looking slightly up"*,
c = *"closer asymmetric framing … camera off to one side"*(시점 미선언).

- **a 는 13/14 (93%)** — eye-level 요청은 거의 그대로 왔다.
- **b 는 2/14 (14%)** — low-angle 요청은 **거의 오지 않았다**. 9장이 `EYE`, 3장이 오히려
  `HIGH`(요청과 정반대)다.
- 세트에 `LOW` 가 5장, `HIGH` 가 4장 있는데 그중 b 변형은 각각 2장·3장뿐이고
  나머지는 a·c 에서 **우연히** 나왔다(facility-exterior/a 는 HIGH, storage-vault/c 는 LOW).

**해석(주장 강도: 관찰이며 확정 아님).** 이 파이프라인의 플레이트는 ControlNet 기하 제어로
렌더되므로 자유생성보다 시점 신뢰도가 높을 것이라는 개연이 있었다 — a 에 대해서는 성립하고
b 에 대해서는 성립하지 않는다. 그럴듯한 이유는 `seed_location_plates.py` 자신이 적어 둔
구조다: 기하는 프롬프트가 아니라 **컨트롤 이미지**(큐레이션 사진 또는 절차적 블록아웃)가
정하고, 큐레이션 참조 사진은 대부분 눈높이로 촬영된 실내 사진이다. b 의 텍스트가 "low angle"
을 말해도 컨트롤 이미지가 눈높이면 눈높이가 이긴다. **이 해석은 검정하지 않았다** —
검정하려면 `data/refs/locations/<key>/ref_b.png` 들의 시점을 같은 규칙으로 재고 b 플레이트와
대조하면 되고, GPU 0 이다.

**직접적인 실무 결론 두 가지.**
1. **증설 배치를 "b 를 더 뽑으면 LOW 가 생긴다"로 계획하지 마라.** 2/14 다.
   LOW/HIGH 컨트롤 이미지를 먼저 확보하거나, 렌더 후 `y_h` 판정 + 시드 상승 루프를 써라.
2. **선언을 게이트 입력으로 쓰지 않은 것이 옳았다.** `_select_plate` 가 `VARIANT_CAMERAS`
   를 읽었다면 b 를 LOW 로 믿고 12/14 를 틀린 시점으로 서빙했을 것이다.

---

## 6. 8.19 임베딩 전제 — 반증

epics.md 의 Story 14.1 항목은 *"8.19의 임베딩 검색층이 후보 랭킹의 기반"* 이라고 적고 있었다.
**그런 층은 존재한 적이 없다.** 확인한 근거:

- `8-19-embedding-asset-retrieval-layer.md` Completion Notes: Task 0 이 AC5 의 게이팅 조건을
  **false** 로 해소했고 *"no `SequenceMatcher`, no threshold and no score therefore exist in
  this implementation"*. 같은 파일의 검증란: *"AC12/AC13 verified clean: no
  `asset_retrieval_service.py`, no `pyproject.toml`, `config.py`, `image.py`,
  `location_service.py` … change. Diff is 3 source files + 1 test file."*
- 같은 문서 Task 3: Stage 2(로컬 임베딩 도입)는 *"only measured residual semantic misses …
  may open a separate decision to add a local embedding implementation"* 로 **조건부 미착수**였고
  그 조건은 충족된 적이 없다.
- 오늘 확인: `src/yt_flow/services/asset_retrieval_service.py` 부재, `pyproject.toml` 과
  `config.py` 에 임베딩 의존성·설정 0건.

8.19 가 실제로 출하한 것은 결정론적 마커 억제 `_suppress_cast_on_no_figure_framing` 하나이고,
그 함수의 **어휘 확장은 14.2 가 실측으로 금지**했다(`high-angle` 을 마커로 넣으면 정상 5건을 지운다).

**후보 랭킹의 실제 기반은 측정된 플레이트 메타데이터다.** 점수도 임계값도 없다 —
`camera_angle → viewpoint` 정합 맵 룩업 + `standing_room` 필터 + 결정적 tie-break 이고,
맞는 후보가 없으면 생성으로 폴백한다. epics.md 는 원문을 지우지 않고 취소선 + 반증 주석으로
정정했다(`gotcha_recorded-root-cause-can-be-inverted`: 거짓 원인은 한 곳만 고치면 다시 인용된다).

---

## 7. 릴라이트 결합 — 미주장, 이관

**⚠️ 이 절의 첫 서술(리뷰 루프 1 이전)은 발화 조건을 세 군데 틀리게 적었다.** 정정한다.

`composite_harmonization.py:613` 은 페어를 `pairs.setdefault((variant, location_key), …)` 로
잡는다 — **씬 성분이 없다.** 따라서:

1. 결합의 범위는 **씬 내부가 아니라 런 전체**다. 같은 `card_variant` 가 같은 키의 서로 다른
   플레이트 위에 서면, 어느 씬이든 전부 **먼저 잡힌 하나의 배경**으로 릴라이트된다.
2. **"14.1 이전에는 무해했다"도 거짓이다.** 8.17 의 `_plate_variant_index` 도 키에
   `scene_num` 을 넣었으므로 씬이 다르면 플레이트가 달랐고, 결합은 그때도 있었다.
3. ~~**이 런에서 이미 발화한다.**~~ **반증됨 — 아래 2026-08-29 정정 참조.** §2 의 재산출 배정이 `containment-chamber` 를 씬 3 `/b` ·
   씬 2·4·8·9 `/a` 로 나누고, `SCP-049`/`standing` 카드가 양쪽에 모두 선다:
   `S00300`(`wide`, `/b`) 와 `S00802`·`S00900`(`wide`, `/a`) 는 pose·camera_angle 이 같아
   `card_variant` 가 동일하므로 **셋이 릴라이트 스프라이트 하나를 공유한다.**
   재산출: `replay_coverage.py 4b35c0ed` 의 `-- matched shots --` 절 + 체크포인트의 `cast`.

고치지 않았고 `deferred-work.md` 에 14.3 라우팅으로 등재했다 — 페어 키를 넓히는 것은
릴라이트 캐시의 히트율·비용 결정이지 플레이트 선택의 결정이 아니다. ~~**다만 이제 이것은 플래그를 켜기 위한 선행 조건 (c)다**(§3): 부족분을 채우면 한 키가 여러 시점 플레이트를 갖게 되어 이 스토리 자신의 해제 조건이 발화 빈도를 올린다. 오늘 이 결함이 화면에 닿지 않는 유일한 이유는 `stock_plate_substitution_enabled=False` 라는 것뿐이다.~~

**⚠️ 2026-08-29 Story 14.3 정정 — 이 조건은 성립하지 않는다.** 문제의 페어 키(`composite_harmonization.py:613`)는 `precompute_relights`(`:504`) 안에 있고, 그 함수는 `video.py`가 `composite_harmonization_tier >= 3`에서만 호출한다. 출하 기본값은 **1**이고 tier 3(IC-Light)은 10.1b가 시청 판정으로 기각했다. **그 한 줄로 도달 불가는 성립하고, 그 뒤에 아무것도 필요하지 않다.** ⚠️ 이 정정의 초판은 여기에 *"게다가 recompose ON 하에서 0/43 샷이 카드 컴포지팅 체인에 진입하지 않으므로 두 이유 중 어느 하나만으로도 충분"*이라는 두 번째 다리를 붙였는데, **그것은 불변식이 아니라 run `4b35c0ed`의 관찰이다** — `recompose_run_shots`의 `remaining.pop(shot_key)`는 성공·재진입 분기에서만 실행되므로 `failed`(스윕 중 ComfyUI 사망, 플레이트 판독 실패)나 `skipped`(`card_key`가 `CARD_LOOKS` 밖)로 세어진 샷은 cast를 그대로 들고 오버레이/하모나이제이션 체인에 **진입한다**. 실패가 하나라도 나는 런에서는 0/43이 아니다. **0/43은 관찰로 강등하고, 반증은 `tier >= 3` 하나로 선다.** 이 프로젝트에서 이 형태(기록된 원인이 뒤집힘)는 이번이 **세 번째**이고, 세 번째는 **정정하는 문서 자신이 심은 과장**이었다 — `replay_coverage.py`가 보여준 것은 **플레이트 배정**의 공유이지 릴라이트 캐시의 발화가 아니다. **이 인계 항목의 두 번째 발화 조건 정정이다**(첫 번째는 14.1 리뷰 루프 1의 '씬 내부'→'런 전체'), 그래서 원문을 지우지 않고 취소선으로 남긴다(`gotcha_recorded-root-cause-can-be-inverted`). 결합 자체는 **여전히 결함이고 여전히 미수정**이며 tier 3을 켜면 발화한다 — 인계는 유지된다. 바뀐 것은 플래그 해제와의 결합이 끊긴 것이다. 고정: `test_precompute_relights_is_unreachable_at_the_shipped_tier`. 근거: `14-3-art-style-contract/report.md` §6.

---

## 8. 사람 판단 대기 목록 (승인 철회는 하지 않았다)

측정에서 `depicts_person=true` 는 **0건**이었다. 다만 두 가지가 사람 앞에 가야 한다.

**(1) `entrance-checkpoint/b` — 방 안에 사람이 있어 보인다.** 콘택트 시트 판정 중 경비 부스
안에 서 있는 인물 두 명이 눈에 띄었고(시점 판정과 무관한 부수 관찰), 확인해 보니
2026-08-02 의 8.17 자동 라벨이 **이미 `has_person: true` 와 `decision: draft` 를 기록**해 두었는데
플레이트는 `approved` 다. 즉 사람이 라벨러의 반대를 넘겨 승인했거나, 승인 경로가
그 판정을 보지 않았다. **승인은 건드리지 않았다**(Block-If). 이 플레이트는 run `4b35c0ed`
수요 셀에 들어가지 않으므로 오늘의 커버리지에는 영향이 없다.

**(2) 승인 상태와 라벨러 판정이 어긋난 플레이트 14/42.** 위 스윕에서 함께 드러난 사전 상태다
(14.1 이 만든 것이 아니다). `decision=draft` 인데 `approved` 인 것들:

| 플레이트 | 라벨러가 지적한 것 |
|---|---|
| cafeteria/a·b·c, facility-exterior/a, maintenance-tunnel/c | `has_duplicated_architecture` |
| entrance-checkpoint/a, observation-room/b | `has_legible_text` |
| entrance-checkpoint/b | `has_person` + `has_duplicated_architecture` |
| entrance-checkpoint/c | `has_legible_text` + `has_duplicated_architecture` |
| interview-room/b | `matches_location=false`, `quality=poor`, conf 0.70 |
| interview-room/a·c, medical-bay/a·c | `quality=acceptable` (규칙은 `good` 만 자동승인) |

이 중 **`observation-room/b`(legible text)와 `medical-bay/a·c`(acceptable)는 §3 의 커버된
셀에 들어 있다** — 즉 치환을 켜면 화면에 나간다. 철회 여부는 사람 판단이다.
재산출: `assets/manifest.json` 의 `source.label` 을 42행 스윕하면 된다.

---

## 9. 코드 변경 요약 (이 리포트가 의존하는 부분만)

- `image._plate_variant_index` → `image._select_plate(shot, plates, run_id, scene_num, *, affordance_gate)`.
  씬 키잉 폐기, 샷의 `camera_angle` 기준, 미달 시 `stock_plate_unfit` + 생성 폴백.
  순수 함수이므로 `replay_coverage.py` 가 **출하 코드 그대로** 오프라인 재생한다.
  **`_existing_complete_shot` 의 비교 키 3개는 불변**이므로 14.1 이전 사이드카는 그대로 히트한다
  (테스트로 고정).
- **D1**(리뷰 루프 1): `has_person`/`depicts_person` 플레이트는 후보에서 빠지고 사유는
  `plate_shows_person`. 플레이트 경로가 10.2/14.4 사람 가드를 `continue` 로 건너뛰므로 이 필터가
  유일한 방벽이다. **배정 거부는 승인 철회가 아니다** — 자산의 `status` 는 손대지 않는다.
  노브와 무관하게 항상 건다(방 안의 사람은 어포던스 축이 아니다).
- **D2**: `standing_room` 필터는 `plate_affordance_gate_enabled` 노브 뒤에 있다. 14.2 가
  오탐 1/25 의 **유일한 복구 경로**로 설계한 "노브를 내리면 카드가 돌아온다"를 두 번째 하드
  필터가 무효화하면 안 되고, 노브 OFF 에서 `no_standing_room` 폴백은 **판정 자체가 없는**
  생성 프레임을 낳는 역전이 된다.
- **D3**: 타이브레이크 digest 키가 **자기가 인덱싱하는 후보 풀 자체를 포함**한다. 이전 형태는
  cast 필터 이후 풀에 modulo 를 걸면서 키에는 cast 축이 없어, 한 씬에서 cast 샷과 cast-free
  샷이 다른 플레이트를 받을 수 있었다(40/42 가 room=true 라 잠복). docstring 의 주장도
  "(씬, 시점)당 1장"에서 "(런, 씬, 키, 시점, 후보집합)당 1장"으로 코드와 일치시켰다.
- **D4**: resume 이 사이드카의 `provenance.stock_plate.standing_room` 을 읽는다. 그전에는
  플레이트로 서빙된 cast 캐시 샷을 전부 `unjudged` 로 세어, 14.2 가 없앤 결함(판정된 것과 안 된
  것이 집계에서 구분 안 됨)이 방향만 바꿔 되살아났다 — `affordance_undecidable=False` 라
  설명 경고조차 없이.
- 사유 어휘는 5종이 아니라 **7종**이다. 추가: `partial_metadata`(일부만 측정된 키 — 처방이
  "렌더"가 아니라 "재기"), `plate_shows_person`. 그리고 어휘 밖 `camera_angle` 은
  `unservable_framing` 이 아니라 `unknown_framing` 이다(전자는 close-up/POV 전용으로 문서화된
  **설계상 영구** 사유이므로 파서 갭을 거기 숨기면 영원히 안 보인다).
- `warnings.py` 카탈로그 문안을 **사유 중립**으로 바꿨다. *"맞는 승인 배경이 없어"* 는 가장 흔한
  사유(`unservable_framing`, 7/31)에서 거짓이다 — 그 키의 승인 배경은 멀쩡하고 샷이 클로즈업일
  뿐이다.
- `_ANGLE_VIEWPOINT` 와 `scenario_chain._CAMERA_ANGLES` 의 관계를 테스트로 고정했다.
  매핑되지 않은 2개(`close-up`/`POV`)가 **의도된 부재**라는 것까지 단언하므로, 어휘에 8번째
  값이 추가되면 조용히 `unservable_framing` 이 되는 대신 실패한다.
- 스톡 히트한 cast 샷은 이제 **어포던스 판정됨**으로 계상된다 —
  `affordance_counts["unjudged"]` 증가 없음, 사이드카 `affordance_undecidable` 미기록.
  14.2 가 남긴 §4-2 결정의 메타데이터 절반이 여기서 닫혔다.
- `LocationService.resolve_stock_plates` 가 `{**plate_meta, has_person, variant, path}` 를 낸다.
  **미측정 플레이트는 `viewpoint` 키 자체가 없다** — 빈 dict 도 null 도 아니다.
  `source.label.has_person` 을 함께 내보내는 것은 D1 이 그것 없이는 발화할 수 없기 때문이고
  (측정 dict 와 라벨 dict 는 매니페스트에서 서로 다른 자리에 있다), 두 기록이 어긋나면
  **어느 쪽이든 true 가 이긴다**(재판정이 옛 플래그를 조용히 지우지 못하게).
  fail-open `except` 는 `assets` 가 dict 가 아니거나 엔트리가 `None`/문자열인 손상 매니페스트의
  `AttributeError`/`TypeError` 까지 잡는다 — 안 그러면 선언한 `no_metadata` 폴백 대신 전 키가
  `stock_plate_resolution_failed` 가 된다(테스트 12건으로 고정).
- `AssetService.record_source(key, field, value)` — 라벨러가 손으로 갖고 있던 load/mutate/save 를
  서비스로 승격. `add_asset` 재호출 금지 근거(`status` 리셋 + `approved_at` 삭제)는 테스트로 고정.
  기존 엔트리의 `source` 가 dict 가 아닐 때(`None`/문자열/리스트) `setdefault` 가 `TypeError` 를
  던져 큐레이션 스윕이 매니페스트 중간에서 죽던 것을 고쳤다 — 비-dict 는 교체하고 `LookupError`
  계약(기록하거나 raise 하거나, 조용한 no-op 은 없다)을 지킨다.
- `scripts/label_location_plates.py` — `depicts_person` 축 신설(신규 플레이트 **자동승인만** 차단),
  `temperature: 0` 핀.
- `measure_plates.py` — (i) `score_plate` 의 `has_person` 도 `plate_meta` 에 싣는다(첫 판에서
  버렸고, 하필 그 값이 가장 필요한 `entrance-checkpoint/b` 에서 버려졌다. **오늘 커밋된
  `plate_meta.json` 에는 그 값이 없다** — 재실행 없이는 소급되지 않으므로 D1 은 지금
  `source.label.has_person` 으로 그 플레이트를 거른다), (ii) 플레이트별 본문을 예외로 감싸고
  `META_PATH` 를 `finally` 에서 쓴다(중간 실패가 84콜을 다시 물리던 것), (iii) 콘택트 시트 행
  높이가 이제 그 시트의 최대 타일 높이다(종횡비가 다른 플레이트가 들어와도 판정용 이미지가
  깨지지 않는다), (iv) `_read_verdicts` 가 `marginal` 열을 사전등록 밴드와 대조해 어긋나면 거부한다.
- `replay_coverage.py` — 전체 `thread_id` 를 `run_id` 로 넘기고(§2), D1 제외 규칙을 C1/C2 와
  선택기가 **한 술어**로 공유하며, 승인 플레이트 0 인 키를 `stock_plate_missing` 으로 세고,
  미키 샷 비율을 (샷,키) 조합이 아니라 **샷 단위**로 센다(분자가 1을 넘을 수 있었다).
- `config.stock_plate_substitution_enabled` — 날짜 붙은 주석 갱신, **기본값 `False` 유지**,
  `.env`/`.env.example` 핀 없음, `DECISIONS` 행 추가 없음(날짜 붙은 *승격* 판정이 아직 없다).
- `state.ShotData.camera_angle` 과 `scenario_chain` 의 소비자 서술에 **세 번째 경로**를 덧붙였다
  (원 서술 삭제 없음, `gotcha_camera-angle-reaches-pixels-by-a-second-path`).

---

## 10. 검증

```
uv run pytest tests/pipeline/nodes/test_image.py -q                     167 passed
uv run pytest tests/services/test_location_service.py \
              tests/services/test_asset_service.py \
              tests/domain/test_run_warnings.py \
              tests/test_label_location_plates.py -q                    120 passed
uv run pytest -q                        3329 passed / 1 failed / 1 skipped  (398s)
uv run ruff check src tests scripts \
       _bmad-output/.../14-1-approved-plate-sets/                       All checks passed!
uv run python scripts/report_decision_drift.py                          exit 0, 표류 0 / env-sourced 0 / 잠재 핀 0
uv run python .../measure_plates.py --dry-run                           42 approved plates, 0 VLM calls
uv run python .../replay_coverage.py 4b35c0ed                           17 / 7 / 7, servable 24, 70.8%
git diff --stat prompts/                                                (비어 있음)
```

전체 실행의 실패 1건은 `tests/test_render_pose_guides.py::…[humanoid_lying_supine]` PNG SHA 핀이며
**14.5 가 기존 결함으로 기록**한 것이다. 가정하지 않고 확인했다: `HEAD`(`80ee501`) 를 detached
워크트리로 꺼내 `PYTHONPATH` 로 **그 워크트리의 `src` 를 강제**하고(전역 editable 설치가 메인
트리 `src` 를 가리는 알려진 함정 회피 — `worktree-editable-install-shadowing`) 돌리면 같은 1건이
동일한 SHA 로 실패한다(`1 failed, 14 passed`, 실제 `48c55bc2…` vs 핀 `fbeb030b…`).

`--commit` 은 **재실행하지 않았다.** 시점 42행은 재도출 불가능한 일회성 맹검이고, 다시 돌리면
84콜을 쓰면서 증거의 품질은 떨어진다. 이 루프에서 바뀐 산출물 값은 `marginal` 열 하나뿐이며
그것은 VLM 도 사람도 아닌 `y_h` 의 순수 함수다(§0·§1-1).
