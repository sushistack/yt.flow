# Story 14.6 — 게이트·계약·수요를 먼저 세운다 (리뷰 루프 1 재구현 + 루프 2 패치)

스펙: `_bmad-output/implementation-artifacts/spec-14-6-dclass-object-asset-sets.md`
작성: 2026-08-29 / baseline `1bd0e84`
개정: 2026-08-29 리뷰 루프 2 — 설계는 통과했고 패치 부류만 적용했다. 이 리포트가
**Jay에게 파괴적 명령을 안전하다고 설명하고 있던 것**이 그 루프의 최대 지적이다(§5), 그리고
크래시한 스테이징이 에폭 전체를 물어 복구를 `rm -rf`로 만들던 것이 두 번째다(§10).

이 리포트가 **주장하지 않는 것**을 먼저 적는다: 카드 픽셀 **0장 렌더**, VLM/LLM 콜 **0회**,
사람 판정 **0건**, `bump_style_epoch()` 실행 **0회**, `characters.angle_*_path` 쓰기 **0회**,
`assets/manifest.json` 바이트 **불변**(md5 `93a0df7e3976eaffd73433342fa14513` 시작·종료 동일).
이 스토리는 재생성을 **실행할 수 있게** 만들었을 뿐, 실행하지 않았다.

---

## 1. GPU 부재 실측 (주장이 아니라 증거)

13.3에서 "이 머신엔 ComfyUI 없다"는 단언이 **거짓이었던 전례**가 있으므로 명령과 출력을 원문으로 남긴다.

```
$ nvidia-smi -L
NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver. Make sure that the latest NVIDIA driver is installed and running.
(exit 9)

$ ls /dev/nvidia*
zsh: no matches found: /dev/nvidia*
(exit 1)

$ cat /proc/driver/nvidia/version
cat: /proc/driver/nvidia/version: No such file or directory
(exit 1)

$ curl -s -m 4 -o /dev/null -w '%{http_code}' http://127.0.0.1:8188/system_stats
000
(exit 7 — connection refused)
```

네 채널이 모두 부재를 가리킨다. 따라서 `--stage`는 실행하지 않았고, §5의 배치는 **명령 목록 +
드라이런 증거**이지 실행 기록이 아니다.

---

## 2. 라이브러리 전수: 카드 × 계약 × 출처 × 정합

재산출: `uv run python scripts/report_card_coverage.py` (LLM 콜 0, 신규 스크립트 없음 — 기존
리포터를 **확장**했다. 같은 모집단을 두 리포터가 훑으면 갈라진다: `Settings.style_epoch`와
매니페스트 `style_epoch`가 같은 이름으로 갈라져 새 스크립트를 오도한 전례가 있다).

### 2-1. 모집단

| 축 | 모집단 | 근거 |
|---|---|---|
| 스프라이트 계약 | **52 파일** = tier A `angle_*_path` 32 ∪ 매니페스트 카드 엔트리 52 (해석 경로 기준 중복 제거) | tier A는 `standing` 카드의 **유일한 주소**이고, 매니페스트는 DB가 더 이상 가리키지 않는 카드가 남아 있는 유일한 곳 |
| 프롬프트 출처 | 매니페스트 카드 엔트리 **52** | `created_at`만이 시점 증거 |
| 레지스트리 정합 | 매니페스트 카드 엔트리 **52** (그중 standing **32**), `character_cards` 행 **20** | `character_cards`만 돌면 52 중 20만 보고 standing 32는 사각 |

`assets/manifest.json` 총 108 엔트리 = 카드 52 / 로케이션 42 / 포즈가이드 6 / 기타 8.

### 2-2. 계약 판정 — PASS 44 / FAIL 8 / 오탐 0

```
-- SPRITE CONTRACT over 52 distinct card file(s) (tier A paths + 52 manifest card entries) --
  PASS 44  FAIL 8
  SCP-1471 standing/back [tier A]          no_alpha_channel  canvas=1664x928 aspect=1.7931 transparent_fraction=None bbox=None
  SCP-1471 standing/front [tier A]         no_alpha_channel  canvas=1664x928 …
  SCP-1471 standing/side [tier A]          no_alpha_channel  canvas=1664x928 …
  SCP-1471 standing/three_quarter [tier A] no_alpha_channel  canvas=1664x928 …
  SCP-682 standing/back [tier A]           no_alpha_channel  canvas=1664x928 …
  SCP-682 standing/front [tier A]          no_alpha_channel  canvas=1664x928 …
  SCP-682 standing/side [tier A]           no_alpha_channel  canvas=1664x928 …
  SCP-682 standing/three_quarter [tier A]  no_alpha_channel  canvas=1664x928 …
  observed transparent_fraction band over the passing population: 0.4377 … 0.8556 (floor in force: 0.02)
```

**표본 밴드**(`gotcha_a-measurement-without-its-sample-band`): 통과 44장의
`transparent_fraction`(= 알파 ≤ 10인 픽셀 비율, `_normalize_subject_scale`의 `> 10` 판정과 같은
임계) 실측 밴드는 **0.4377 ~ 0.8556**. 최소는 `STOCK-d-class/hint:b0f00082b3_front`, 최대는
`STOCK-d-class/hint:475c8a9231_front`. 재산출은 위 명령이 매번 출력한다.

⚠️ 원 스펙이 인용했던 front 6장 밴드(0.7055~0.8421)에 하한을 맞췄다면 **44장 중 18장이
떨어진다** — 0.4377(`STOCK-d-class/hint:b0f00082b3_front`)부터 0.7051
(`SCP-049/hint:7031f483b8_front`)까지. **리뷰 루프 2 정정**: 앞선 반복은 이 수를 14로 적고
"(sitting·hint 카드가 먼저)"라고 부류까지 좁혔는데, 둘 다 틀렸다. 18장 중 **4장이 standing
카드**다 — `SCP-049/standing_three_quarter` 0.4810, `STOCK-researcher/standing_three_quarter`
0.7032, `STOCK-d-class/standing_side` 0.7039, `SCP-096/standing_back` 0.7050. 즉 sitting/hint에
국한된 효과가 아니라 라이브러리 전반에 걸친다. 그래서 하한
`_MIN_TRANSPARENT_FRACTION = 0.02`는 밴드 하한의 1/20이고, 걸러내는 것은 "여백이 적다"가
아니라 **"투명이 아예 없다"**뿐이다.

**재산출 경로**: `scripts/report_card_coverage.py`가 이 반사실을 매 실행 **직접 출력한다**
(`counterfactual: a floor fitted to the front-only band (0.7055) would reject 18 of 44
passing card(s), spanning 0.4377 … 0.7051` + 18행 전수). 이 리포트에 손으로 옮겨 적은 수가
아니다 — 앞선 반복의 14는 정확히 손으로 적은 수였다.

계약에 **넣지 않은 것**: bbox 폭/높이비. `_normalize_subject_scale` docstring이 이미 반증한다 —
2인 스프라이트 0.359 vs 정상 단일 0.358. 누운 카드는 정당하게 광폭이다.

### 2-3. 프롬프트 출처 — pre-v5 45 / same-day 4 / post-v5 3

`character-generation` v5는 2026-08-16 라이브(10.8). 엔트리 `created_at` 기준:

| 버킷 | 건수 | 비고 |
|---|---|---|
| pre-v5 (< 2026-08-16) | **45** | 약한 프롬프트 산물. 비소급 상태의 크기 = 52분의 45 |
| same-day (= 2026-08-16) | **4** | `STOCK-d-class/sitting_*`. **재생성으로 세지 않는다** — 프롬프트 시딩에 타임스탬프가 없어 시딩 전후를 귀속할 수 없다 |
| post-v5 (> 2026-08-16) | **3** | `SCP-049/hint:fa04528c05`, `STOCK-d-class/hint:b0f00082b3`, `hint:f5a7540b92` (모두 2026-08-17) |

### 2-4. 레지스트리 정합 — 정방향 7행, 역방향 0행

```
-- REGISTRY RECONCILIATION over 52 manifest card entries (32 standing / 20 `character_cards` rows) --
  manifest approved / db retired: 7
    SCP-049-2/hint:475c8a9231_front, STOCK-d-class/hint:970ede32f4_front,
    STOCK-d-class/hint:a40ec9c170_front, STOCK-d-class/sitting_{front,back,side,three_quarter}
  db approved / manifest retired (HALTs reconcile_manifest.py): 0
  manifest retired / still published in angle_*_path: 0
  manifest entry with no `character_cards` row: 0
  `character_cards` row with no manifest entry: 0
```

**7행이지 4행이 아니다** — 원 스펙은 "항목 4개"를 행 수로 오독했다(`sitting_*`가 4행). 역방향
0행이므로 `reconcile_manifest.py`의 HALT 조건은 성립하지 않는다.

### 2-5. 미등록 디스크 파일 — 24개 (삭제하지 않음, 보고만)

`assets/characters/**` 전수를 매니페스트 108엔트리의 `path`와 대조:

| 부류 | 건수 |
|---|---|
| 구 에폭 카드 (`SCP-049-2/epoch_1` 4, `STOCK-d-class/epoch_1` 4, `STOCK-researcher/epoch_1` 4, `STOCK-security/epoch_1` 4) | 16 |
| **`STOCK-d-class/epoch_3/` 스테이징 잔류** (카드 4 + `_prestage_descriptor.txt` 1) | 5 |
| `.alpha_repaired` 마커 | 3 |
| **소계 (`characters/` 내)** | **24** |
| `characters/` 밖: `locations/control-room/a.depth.png`, 0바이트 `assets/yt_flow.db` | 2 |

**24개이지 21개가 아니다**(마커 3 포함). `epoch_3` 잔류는 §5 배치의 **0단계 차단 대상**이다 —
현재 `style_epoch = 2`이므로 그 디렉터리가 곧 다음 스테이징 슬롯이고, 원자적 승격이 그것을
먼저 처리하라고 요구한다. 실측으로 그 세트는 **완전하고 계약을 통과한다**(승격 가능한 상태):

```
$ (read-only) approve_stock_cast._discover(assets, epoch=3, session)
  staged    {('STOCK-d-class', 'standing'): ['back', 'front', 'side', 'three_quarter']}
  blockers  []
  dirs      {'STOCK-d-class': 'assets/characters/STOCK-d-class/epoch_3'}
  _validate -> []   # has_alpha + sprite_contract 위반 0
```

(세 번째 반환값 `dirs`는 리뷰 루프 2가 추가했다 — `--reject`는 이제 `staged`가 아니라 이
목록으로 동작한다. 블로커가 지목한 디렉터리, 즉 승격이 불가능한 디렉터리야말로 운영자가
지워야 하는 것이기 때문이다.)

---

## 3. 비소급 상태의 크기

- 라이브러리 카드 **52** 중 **45**가 v5 이전 프롬프트 산물 (86.5%).
- 그중 **8**은 스프라이트가 아니다 (§7).
- `character_cards` 20행 중 **9행이 `retired`** (10.8이 sitting 3/4 standing 오생성으로 폐기한 4행 포함).
- `characters` 9키 중 **2키(`SCP-1471`, `SCP-682`)의 `visual_descriptor` 길이가 0** — 실측
  `length(visual_descriptor)` = 0/0, 나머지 7키는 106~1513. 스펙의 **Block If**대로 이 2키는
  재생성 배치에서 제외한다(사람이 쓴 서술자 없이는 불가능). HALT는 하지 않는다.

---

## 4. run `4b35c0ed` 관측 수요와 경고 귀속

재산출: `uv run python scripts/report_card_coverage.py --demand 4b35c0ed` (체크포인트 읽기, LLM 콜 0).

**41 placements / 9 scenes / UNMET 4.** 이 41은 §2의 72셀 전 어휘 분모와 **분리된 수**이고 서로
대조해서는 안 된다(72는 9키×2포즈×4앵글의 목표치이지 관측 수요가 아니다).

`served` 판정은 **계약을 참조한다**: 컬럼이 비어 있지 않은 것으로는 부족하고, 파일이 존재하고
`sprite_contract`를 통과해야 한다. 그리고 앵글은 video 시점에 LLM이 고르므로 **4앵글 전부**가
서빙 가능해야 `served: yes`다 — 2/4는 동전던지기이고 그것이 나중에 `cast_card_fallback`으로
나타난다.

| shot | card_key | 요청 | 미충족 사유 | 대응 경고 |
|---|---|---|---|---|
| S00301 | STOCK-researcher | sitting | 4앵글 모두 `no approved row` | `cast_card_fallback` reason=`asset` |
| S00504 | STOCK-d-class | sitting + `hint:a6f1ed6a29` | `no approved hint card` | `cast_card_fallback` reason=`asset+pose_hint` |
| S00701 | SCP-049-2 | sitting | 4앵글 모두 `no approved row` | `cast_card_fallback` reason=`asset` |
| S00901 | STOCK-researcher | sitting | 4앵글 모두 `no approved row` | `cast_card_fallback` reason=`asset` |

`warnings with no unmet placement: 0` — 4건이 정확히 4행에 대응한다.

**대응 키는 `(shot_id, card_key)`이고 `shot_id` 단독이 아니다.** 이 런은 8샷이 다중 cast이며
`S00504`가 그중 하나다(`SCP-049 standing` + `STOCK-d-class sitting`). `shot_id`만으로 키잉하면
한 행의 경고가 다른 행을 대신하고 두 번째가 조용히 사라진다.

**`S00504`와 `special_pose_cap_exceeded`는 같은 사건이다.** 캡(`special_pose_max_per_run`, 기본
3)을 `hint:f5a7540b92`(S00103, "collapsing to floor")·`hint:b0f00082b3`(S00104, "dead on
floor")·`hint:fa04528c05`(S00502, "reaching to grab D-class hand")가 소진했고,
`hint:a6f1ed6a29`("collapsed dead", S00504)가 밀렸다. 그래서 S00504는 hint 카드를 못 얻고
sitting으로 내려갔는데 `STOCK-d-class`의 sitting 행 4개가 모두 `retired`라 다시 standing으로
내려갔다 — `asset+pose_hint`가 그 두 단계다.

**캡을 올리지 않은 이유**: `_ensure_special_pose_cards`(`run_service.py:586`)는 **승인 카드가 있는
hint를 건너뛴다**. 세트를 미리 채우면 그 hint들이 캡 계산에 들어오지도 않는다. 캡을 올리는 것은
런당 GPU를 더 쓰는 일이고, 세트를 채우는 것은 한 번 쓰는 일이다. 캡은 세트가 채워진 뒤에 다시
재는 것이 옳고, 그때가 날짜 붙은 판정을 적을 자리다. `config.DECISIONS` 행도 추가하지 않았다.

---

## 5. 재생성 배치 — 드라이런으로 통과를 확인한 명령만 적는다

⚠️ 앞선 반복은 실은 **exit 1인 배치**를 인계했다(단일 `--key` × 전역 고아 검사 충돌). 아래 목록은
전부 `_bmad-output/implementation-artifacts/14-6-dclass-object-asset-sets/dryrun_batch.py`가
**라이브와 같은 모양의 tmp 라이브러리**(style_epoch 2 + `epoch_3` 잔류)에 대해 같은 argv로
실행해 종료코드를 확인한 것이다. 두 갈래(0단계 reject / promote) 모두 확인했다.

```
$ uv run python .../dryrun_batch.py --residue reject     -> BATCH OK (모든 명령이 기대 종료코드)
$ uv run python .../dryrun_batch.py --residue promote    -> BATCH OK
```

**0단계 — 2026-08-16 스테이징 잔류를 먼저 정리한다.** 에폭은 원자적으로 승격되므로 이것을 남긴
채로는 아무것도 스테이징할 수 없다. 둘 중 하나를 사람이 고른다(Jay 판정 필요 — 그 4장이 쓸
만한지는 이 스토리가 판정하지 않았다). **어느 쪽도 "부작용 없음"이 아니다. 리뷰 루프 2가
양쪽의 부수 효과를 실측했고, 앞선 반복은 둘 다 안전하다고 적었다:**

```bash
uv run python scripts/approve_stock_cast.py            # 잔류를 승격 (epoch_3 라이브, style_epoch → 3)
# 또는
uv run python scripts/approve_stock_cast.py --reject   # 잔류를 폐기 (아래 A 참조)
```

**A. `--reject`는 "라이브 무변경"이 아니다 — `visual_descriptor`를 건드릴 수 있다.** 그 문구는
앞선 반복의 오류다. `_reject`는 사이드카가 있으면 `visual_descriptor`를 그 텍스트로 되돌리고,
`assets/characters/STOCK-d-class/epoch_3/_prestage_descriptor.txt`(1600바이트, 2026-08-16 21:11)는
라이브 서술자(701자)와 **문자 380부터 갈린다** — 앞 380자는 `STOCK_DESCRIPTORS`의 authored
텍스트로 동일하고, 그 뒤가 라이브는 구조형 `build:/head:/clothing:/marks:` 읽기-되받기,
사이드카는 옛 산문형이다(`prompts/character/vision_enrichment.md`가 2026-08-16 18:46 커밋
`9042143`에서 산문 → 구조형으로 바뀌었다).

읽기 전용 실측으로 **한 가지는 더 말할 수 있다**: 라이브 서술자는 *그 스테이징 자신의 산물*이다
— `characters.updated_at`이 `2026-08-16T12:50:07Z`(= 21:50:07 KST)이고 그 스테이징의 front 카드
mtime이 21:50:05.896이라 **1.7초 차**다. 즉 되돌리기 자체는 "그 스테이징을 무르는 것"이라는
원래 의도와 부합한다. 그럼에도 이번에 그것을 **자동으로 하지 않기로** 했다: 디렉터리 안의 어떤
파일도 그 사실을 말해주지 않고, 승인기는 시각 증거가 아니라 사이드카 하나만 보고 살아 있는
칼럼을 덮으려 하고 있었다.

**14.6이 넣은 가드**(`scripts/approve_stock_cast.py._reject`): 라이브 서술자가 사이드카와도,
그 스테이징이 남긴 텍스트(`_poststage_descriptor.txt`, `seed_stock_cast.py`가 이번에 추가)와도
다르면 **경고를 크게 찍고 복원하지 않는다**. 스테이징 파일은 그대로 삭제된다. `epoch_3`은
14.6 이전에 스테이징됐으므로 그 기록이 없고, 따라서 `--reject`는 아래를 출력하고 서술자를
**건드리지 않는다**(드라이런 실측):

```
WARNING: NOT restoring the descriptor for STOCK-d-class — the live `visual_descriptor`
(701 chars) is neither the pre-stage sidecar (1600 chars) nor any recorded staging text
(_poststage_descriptor.txt is absent, so this directory was staged before Story 14.6). …
```

사이드카 텍스트를 되살리고 싶으면 사람이 손으로 붙여넣는다. 반대 방향(승인기가 덮어쓴
서술자)은 되살릴 방법이 없다.

**B. 승격은 `STOCK-d-class`의 승인된 `hint:*` 카드 3장을 폐기한다 — 그중 2장은 §4가 `served
yes`로 찍는 카드다.** `_retire_special_pose_cards`는 **모든 standing 승격**에서 발화하고
(hint 카드는 standing front에서 파생되므로 설계상 옳다), `STOCK-d-class`의 승인 hint 행은 지금
셋이다:

| hint | §4에서 | 폐기 후 |
|---|---|---|
| `hint:b0f00082b3` (`humanoid_lying_supine`) | **S00104 `served yes`** | 다음 런이 재생성 대상으로 되돌아온다 |
| `hint:f5a7540b92` (`humanoid_collapsed`) | **S00103 `served yes`** | 동일 |
| `hint:475c8a9231` (§9의 광폭 누운 카드) | 이 런의 수요에는 없음 | 동일 |

**코드는 이대로가 옳다 — 바꾸지 않았다.** 다만 이것은 §4의 캡 논지를 **뒤집는다**:
`_ensure_special_pose_cards`(`run_service.py:586`)가 캡 계산에서 건너뛰는 것은 *승인 카드가 있는*
hint이므로, 승인 hint 3장을 비우면 다음 런의 `special_pose_cap_exceeded` 압력이 **줄지 않고
늘어난다**. 세트를 미리 채워 캡을 무의미하게 만든다는 이 스토리의 논지는 sitting 세트에 대해서만
성립하고, 0단계에서 승격을 고르면 hint 축에서는 그 반대가 된다. 판단 재료로 적어둘 뿐, 어느
쪽이 옳은지는 그 4장을 본 사람이 정한다.

**1단계 — 관측 수요가 가리키는 sitting 세트를 스테이징한다 (GPU 필요).** 세 명령이 모두 같은
에폭에 쓴다(범프가 없으므로):

```bash
uv run python scripts/seed_stock_cast.py --stage --key STOCK-researcher --pose sitting
uv run python scripts/seed_stock_cast.py --stage --key SCP-049-2       --pose sitting
uv run python scripts/seed_stock_cast.py --stage --key STOCK-d-class   --pose sitting
```

**2단계 — Jay가 본다.** 10.8의 실측 경고를 여기에 그대로 옮긴다: 같은 명령으로 만든
`STOCK-d-class` sitting 4장 중 **3장이 서 있는 인물**이었고 네 번째는 `back` 라벨인데 정면으로
앉아 있었다(전부 폐기됨 — 그것이 §2-4의 7행 중 4행이다). `_POSE_DESCRIPTIONS["sitting"]`은 모델에
**텍스트로만** 닿고, 이 에픽의 결론은 텍스트 포즈 지시가 무시된다는 것이다. 즉 이 배치는 후보를
만들 뿐이고, 통과율은 예측하지 않는다.

**3단계 — 에폭 전체를 한 번에 승격한다.** 일부만 승격하려 하면 거부된다(확인됨: exit 1):

```bash
uv run python scripts/approve_stock_cast.py --key STOCK-researcher   # -> exit 1, "refusing partial promotion"
uv run python scripts/approve_stock_cast.py                          # -> exit 0, 3키 동시 승격 + style_epoch 범프
```

**배치에서 제외한 것과 이유:**

- `SCP-1471`, `SCP-682` — `visual_descriptor` 길이 0. 스펙의 Block If. 게다가 14.6의 가드가 이제
  그 상태에서의 생성을 **거부**하므로, 사람이 서술자를 쓰기 전에는 스테이징 자체가 0장을 만든다.
- `SCP-049`, `SCP-096`, `SCP-999` — `STOCK_DESCRIPTORS`/`DERIVED_DESCRIPTORS` 어느 표에도 없어
  `--descriptor`를 손으로 넘겨야 한다(이 거부는 의도적으로 유지했다). 관측 수요에 이들의 sitting
  요청이 없으므로 이번 배치의 대상이 아니다.
- **pre-v5 45장의 standing 재생성** — 이 리포트는 크기만 적고 배치를 만들지 않았다. 같은
  스테이징/승격 절차를 키별로 반복하는 모양이지만, 45장 규모의 GPU 예산과 사람 판정 분량은 이
  스토리가 견적하지 않았다.

---

## 6. 오브젝트 세트: 만들지 않았다 — 측정된 부재와 필요한 seam

**소비자가 없다.** 만들면 아무 코드도 그것을 요청할 수 없다.

| 계층 | 오브젝트 축의 상태 | 실측 |
|---|---|---|
| `ShotData` (`domain/state.py:303-325`) | 엔티티 축은 `cast`(사람)·`location_key`(방) **둘뿐** | run `4b35c0ed` 43샷의 키 전수에 오브젝트 필드 없음 |
| 시나리오 프롬프트 | 오브젝트를 발행하는 필드가 없음 | 오브젝트는 `image_prompt` 자유텍스트로만 픽셀에 닿는다 |
| `AssetService._SUBDIRS` | `("characters", "locations", "anchors", "pose_guides")` — 오브젝트 없음 | — |
| 매니페스트 엔트리 | **`kind` 필드 자체가 없다** — 종류는 `card_key`/`location_key`/`guide_key` 중 무엇이 있는지로 추론된다 | `report_card_coverage._card_entries`가 그 추론을 코드로 적고 있다 |

필요한 선행 seam 셋: ① `ShotData`의 오브젝트 축, ② 시나리오 프롬프트가 그 축을 발행하는 것,
③ `AssetService`의 실제 `kind` 필드. 셋 다 이 스토리보다 크고, ②는 14.5가 기각으로 끝낸 그
프롬프트 층이다. `deferred-work.md`에 등재했다.

---

## 7. `SCP-1471`/`SCP-682` 정정 — 그려지는 게 아니라 런을 죽인다

`deferred-work.md:715`가 *"any run whose entity is one of these keys **draws** them"*이라고
적었다. **거짓이고, 진실은 더 나쁘다.**

`video.py:2528-2542`는 해결된 카드 경로를 `has_alpha`로 하드 검증하고 실패 시 **raise**한다.
8장 전부 `RGB 1664×928`(§2-2 실측)이고 `has_alpha`는 IHDR 색상타입을 읽으므로 8장 모두 False다.
따라서 이 키가 캐스팅되는 순간 나쁜 프레임이 나오는 게 아니라 **video 스테이지가 죽는다**.

이 차이가 중요한 이유: "그려진다"로 읽으면 미관 결함으로 값이 매겨져 픽셀 작업 뒤로 밀리고,
"런을 죽인다"로 읽으면 1471/682를 캐스팅하는 모든 런의 **블로커**다.
(`gotcha_recorded-root-cause-can-be-inverted`)

같은 정정이 `has_alpha`의 **진짜 사각지대**도 뒤집는다: 이 8장이 아니라 **정반대 모양** — 완전
불투명 RGBA다. 빈 서술자로 생성된 카드가 그 모양으로 돌아오고, `has_alpha`의 모든 검사를 통과해
라이브러리에 들어온다. 14.6은 그것을 위해 `domain.png.sprite_contract`를 추가했고
**`has_alpha`를 대체하지 않고 나란히 세웠다** — 리뷰 루프 1이 교체했다가 정확히 반대 구멍을
열었다(잘린 PNG / IEND CRC 깨짐은 Pillow가 열어버려 계약이 통과시키고 `has_alpha`만 잡는다;
`tests/domain/test_png.py::test_the_contract_is_strictly_weaker_than_has_alpha_on_a_broken_container`가
그 비대칭을 실행 가능한 주장으로 고정한다). 원문은 지우지 않고 정정 주석을 붙였다.

---

## 8. 생산자 전수조사 — 무엇이 카드를 쓰고, 무엇이 가드에 덮이는가

`gotcha_deleting-a-constant-needs-a-reader-census`의 쌍대: **가드는 독자가 아니라 생산자
전수를 요구한다.** 리뷰 루프 1은 가드를 `generate_cards_from_descriptor`에 달았는데 그 함수는
빈 서술자로는 **프로덕션 도달 불가**였고(두 호출부 모두 서술자를 보장한다), 실제로 1471/682를
만든 경로는 가드 없이 지나갔다. 그러고도 리포트·`epics.md`·`deferred-work.md` 세 문서가 "이제
거부한다"고 적었다.

### 8-1. `characters.angle_*_path`를 쓰는 경로 전수 (5개)

| # | 위치 | 무엇을 쓰는가 | 빈-서술자 가드에 덮이는가 |
|---|---|---|---|
| 1 | `character_service.py` `generate_cards_from_descriptor` 말미 (standing 발행절) | 4앵글 + `selected_image_path` | **덮인다 (간접)** — 앵글별로 funnel을 부르고, 가드가 발화하면 `angle_paths`가 비어 발행절이 실행되지 않는다 |
| 2 | `character_service.py` `select_candidate` | `angle_{angle}_path` = 후보 경로 | **덮인다 (간접)** — 후보는 `status="ready"`이고 `image_path`가 있어야 선택 가능하며, 그 상태는 funnel이 경로를 반환했을 때만 만들어진다. `select_candidate` 자체에는 가드가 없다 |
| 3 | `run_service.py:517-519` (5.8 자동 프로비저닝) | 4앵글 + `selected_image_path` | **덮인다** — funnel을 직접 부르고 반환이 비면 `LookupError` → 행 롤백 + `character_provisioning_failed`. **1471/682를 만든 바로 그 경로이며, 리뷰 루프 1에서 유일하게 열려 있던 곳** |
| 4 | `scripts/approve_stock_cast.py` (승격) | 4앵글 + `selected_image_path` | **덮이지 않는다 — 그리고 옳다.** 사람이 스테이징하고 본 파일을 발행하는 유일한 승인 게이트이고, 대신 `has_alpha` + `sprite_contract`를 전 대상에 대해 검증한다 |
| 5 | `scripts/migrate_assets.py:81` | `angle_{angle}_path` | **덮이지 않는다.** 8.2 워크스페이스 카드를 자산 라이브러리로 옮기는 **일회성 마이그레이션**이고 카드를 생성하지 않는다(디스크에 이미 있는 파일을 등록). 서술자와 무관 |

### 8-2. 카드 **파일**을 쓰는 경로 전수 (2개)

| # | 위치 | 무엇을 쓰는가 | 가드 |
|---|---|---|---|
| A | `character_service.generate_candidates_from_reference` | 카드 PNG + 매니페스트 add/approve + (비-standing) `save_card` | **덮인다 — 여기가 가드의 자리다.** 위 1·2·3이 모두 이 함수를 지난다 |
| B | `character_service.generate_special_pose_card` | hint 카드 PNG + 매니페스트 add/approve + `save_card` | **덮인다 (별도 가드).** funnel을 지나지 않고 자기 프롬프트를 컴파일하므로 공유가 불가능하다. 이 전수조사가 없었으면 놓쳤을 경로다: 1471/682는 `angle_front_path`를 **가지고 있어서** 이 함수의 선행 조건을 통과하고, 빈 서술자로 hint 카드를 찍을 수 있었다 |

### 8-3. 경고가 실제로 발화하는가

`_warn`은 `warnings=` 없이 만든 `CharacterService`에서 **무발화 no-op**이다. 따라서 "가드가
있다"와 "운영자가 듣는다"는 서로 다른 주장이다. 발화 경로 확인:

- `run_service._ensure_character_reference` — `CharacterService(session, settings=settings, warnings=warnings)` ✅
- `run_service._ensure_derived_entity_cards` — 동일 ✅
- `run_service._ensure_special_pose_cards` — 동일 ✅
- `api/routes/characters.py:324` (후보 배치) — `warnings=` **없음**. 가드는 동작하지만 경고는
  수집되지 않고 후보가 `failed`로 표시된다(런 경고 채널이 없는 호출부이므로 정상)

셋 다 `scenario` 스테이지를 소유하는 호출부이고, 형제 코드
(`character_provisioning_failed`, `derived_entity_generation_failed`)와 같다. 그래서
`character_descriptor_missing`의 카탈로그 스테이지는 **유추가 아니라 호출부 실측으로**
`scenario`다. 실제 발화는
`tests/services/test_run_service_character_provisioning.py::test_enrichment_failure_no_longer_generates_a_descriptorless_card_set`가
런 경고 리스트에서 코드를 꺼내 확인한다.

### 8-4. 행동 변화 (과대주장 금지)

- 이전: 비전 enrichment 실패 → 서술자 없이 4앵글 생성 → 발행. AD-10은 지켰지만 **나쁜 카드가
  출하됐다**.
- 이후: 생성 스킵 → `character_descriptor_missing` 발화 → `angle_paths` 비어
  `LookupError` → 행 롤백 + `character_provisioning_failed`. 런은 여전히 죽지 않고,
  그 배역만 화면에서 빠진다. **조용한 나쁜 카드 대신 시끄러운 부재.**
- ⚠️ **"행 롤백"의 값을 앞선 반복이 적게 매겼다(리뷰 루프 2).** `_ensure_character_reference`의
  총실패 분기는 `svc.delete_character(character.id)`이고, 이것은 방금 만든 행 **하나**만
  지우는 게 아니라 그 아래 `reference_images`까지 함께 지운다(`ondelete="CASCADE"`). 즉 처음
  보는 키에서 enrichment가 실패하면 이제 **카드 0장 + 캐릭터 행 없음**이고, 그러면
  `check_existing_character`가 다시 `None`을 주므로 **다음 런이 DuckDuckGo 검색과 레퍼런스
  이미지 다운로드를 통째로 반복한다**. 그 롤백 자체는 5.8의 의도(일시적 실패 후 재시도 가능)이지
  14.6이 만든 것이 아니지만, 14.6이 **실패의 빈도를 바꿨다** — 전에는 서술자가 없어도 생성이
  진행돼 롤백까지 가지 않았다. 영구 실패(키가 없거나 잘못된 키) 환경에서는 이것이 **매 런
  반복되는 네트워크 작업**이 된다.
- 그 영구 실패가 가설이 아닌 이유: `.env.example`은 2026-08-22 Story 14.4가 주석 처리하기
  전까지 `YTFLOW_CHARACTER_VISION_API_KEY=<YOUR_VISION_API_KEY>`를 **출하하고 있었고**,
  플레이스홀더는 truthy다(14.4가 기록한 그 부류). 그 이전 `.env.example`에서 복사해 만든 `.env`를
  아직 쓰는 환경에서는 비전 호출이 잘못된 키로 나가 **모든 신규 엔티티에 대해** enrichment가
  실패하고, 위 반복이 그 환경의 기본 동작이 된다. 리포에 남은 파일 자체는 이미 고쳐져 있다
  (`.env.example:83`, 주석). 캐싱이나 백오프는 이 스토리가 만들지 않았다 — 관측된 사례가 없다.
- 부수: Character Management UI의 `/generate`도 같은 가드를 받는다. 서술자가 없는 캐릭터의 후보
  생성은 이제 `failed`로 끝난다. UI에는 `PATCH /characters/{id}`로 `visual_descriptor`를 먼저
  넣는 길이 있다.

---

## 9. 프레이밍 수정 `_SIDE_GUTTER` — 한계 명기

`_normalize_subject_scale`은 `new_w > width`일 때 **폭에 딱 맞춰** 축소하고 `x=(width-new_w)//2
= 0`에 붙였다. 즉 누운 카드의 alpha bbox가 양끝에 닿는 것은 생성 결함이 아니라 **가로 여백이 0이라
구조적으로** 그런 것이었다. `_BOTTOM_GUTTER=8`의 가로 대응물이 없었다.

실측 (재산출: `alpha_profile(...)['alpha_bbox']`, `assets/characters/STOCK-d-class/epoch_2/hint_475c8a9231_front.png`):

| | alpha_bbox (l, t, r, b) | 좌우가 캔버스에 닿는가 |
|---|---|---|
| 수정 전 (= 파일 현재 상태, 구 코드 산물) | **(0, 821, 832, 1208)** | 예 (0 과 832) |
| 수정 후 (`_SIDE_GUTTER = 8`) | **(8, 828, 824, 1208)** | 아니오 |

**한계**: 이것은 **프레이밍만** 고친다. 생성기가 이미 캔버스 밖으로 잘라낸 해부(프레임 밖의 손 등)는
살아남은 픽셀을 다시 축소한다고 복원되지 않는다.

양방향 고정은 합성 픽스처로 실제 코드 경로를 지나며 한다
(`test_normalize_subject_scale_keeps_a_side_gutter_too` — 수정 후 `left == _SIDE_GUTTER`,
`_SIDE_GUTTER`를 0으로 몽키패치한 "수정 전" 다리는 `(0, width)`). 라이브 PNG는 `.gitignore`
대상이라 테스트가 의존할 수 없어 위 실측은 리포트에만 남는다.

---

## 10. 원자적 에폭 승격 — 리뷰 루프 1이 재현한 3건과 그 폐쇄

`staged_dir`은 `epoch_{style_epoch + 1}`이다. **스테이징 자리와 다음 라이브 자리는 같은
디렉터리**이고 둘을 가르는 것은 승격이 마지막에 던지는 `bump_style_epoch()`뿐이다.

| # | 재현된 실패 | 이제 무엇이 막는가 | 회귀 테스트 |
|---|---|---|---|
| ① | standing 승격이 전역 범프를 하는데 고아 검사가 포즈별이라 스테이징된 sitting이 라이브 `epoch_N`에 **영구 고립**(승격도 `--reject`도 `nothing staged`) | 승격은 그 에폭에 스테이징된 **모든 키·모든 포즈**를 함께 대상으로 하고, `--key`/`--pose`로 좁힌 뒤 남는 스테이징이 있으면 **거부** | `test_standing_and_sitting_staged_together_are_promoted_together` |
| ② | 범프 없는 승격 → `--reject`가 같은 에폭을 재계산해 **라이브 승인 카드 4장 삭제** + `visual_descriptor`를 `None`으로 덮음 + exit 0 | 승격이 **항상** 범프로 닫으므로 `--reject`는 구조적으로 다른 에폭을 본다. 더해서 사이드카가 없으면 서술자를 **건드리지 않는다**(부재는 "서술자가 없었다"가 아니라 "승격이 소비했다"일 수 있다) | `test_reject_after_a_promotion_does_not_delete_the_live_cards`, `test_reject_without_a_sidecar_leaves_the_descriptor_alone` |
| ③ | 재스테이징이 **승인된 매니페스트 엔트리가 가리키는 픽셀을 덮어** `verify_asset`을 깨뜨림 | 같은 범프 | `test_restaging_a_promoted_pose_cannot_overwrite_the_approved_pixels` |

추가로 닫은 것:

- **`has_alpha`와 `sprite_contract`가 함께 선다.** 스펙의 Never였고 리뷰 루프 1이 위반했다.
  `test_corrupt_container_refuses_even_though_the_sprite_contract_passes`가 계약이 그 바이트를
  `(True, "ok")`로 통과시킨다는 것까지 단언한다 — 누가 게이트를 계약 하나로 "단순화"하면 실패한다.
- **사이드카만 남은 실패 스테이징**도 차단한다(파일 존재만 보면 놓친다):
  `test_a_sidecar_only_directory_blocks_the_promotion`.
- **비-standing 승격 행의 `style_epoch`이 파일이 사는 에폭과 같다.** `save_card`는 현재 매니페스트
  에폭을 찍는데 범프는 마지막이므로, 명시적으로 스탬프하지 않으면 라이브러리에서 가장 새 카드가
  off-epoch로 보고된다: `test_non_standing_promotion_stamps_the_epoch_the_files_live_in`.
- **비-standing 승격은 `angle_*_path`를 건드리지 않는다**(같은 테스트가 확인).

**리뷰 루프 2가 추가로 닫은 것 — 크래시한 스테이징이 에폭 전체를 물지 않게 한다.**

| # | 무엇이었나 | 이제 무엇이 막는가 | 회귀 테스트 |
|---|---|---|---|
| ④ | `_discover` 블로커가 **승격뿐 아니라 `--reject`까지** 막았다. `seed_stock_cast.py`는 사이드카를 쓰고 서술자를 교체한 **뒤** 4장 미만이면 raise하므로(5.23 ComfyUI 크래시), 불완전/사이드카-only 디렉터리 + 이미 교체된 라이브 서술자 + 게이트 뒤에 갇힌 유일한 복구 경로가 정확히 그 상태다. 복구가 `assets/` 안에서 `rm -rf`가 된다 — 이 게이트가 막으려던 바로 그것 | 블로커는 **승격만** 막는다. `--reject`는 블로커가 지목한 디렉터리까지 포함해 디스크의 모든 `epoch_{N}` 디렉터리를 대상으로 하고(캐릭터 행이 없는 디렉터리도), 좁힌 `--key`는 형제 세트가 스테이징돼 있어도 허용된다(거절은 아무것도 발행하지 않으므로 전부-아니면-전무 규칙의 근거가 없다) | `test_a_blocked_epoch_can_still_be_rejected`, `test_a_narrowed_reject_leaves_a_staged_sibling_alone` |
| ⑤ | 빈 서술자 가드가 `chars_dir.mkdir(...)` **뒤에** 있어서, 거부 경로가 빈 에폭 디렉터리를 남겼다 → ④의 블로커가 된다 | mkdir을 가드 아래로 옮겼다 | `TestEmptyDescriptorGuard::test_a_character_with_no_descriptor_generates_nothing` (`characters/SCP-096`이 아예 생기지 않는지) |
| ⑥ | 승격 루프 중간의 raise가 닫는 `bump_style_epoch()`를 건너뛰었다 — 앞선 키들은 **이미 라이브**인데 스테이징 슬롯이 그 디렉터리로 남는다(이 모듈 docstring의 실패 모드 3을 실패 경로로 재현) | 승격 루프를 `try/finally`로 감쌌다. 범프는 실패 경로에서도 발생하고, 어디까지 갔는지를 `PARTIAL PROMOTION: n/m …`으로 출력한다. 사이드카 삭제는 **실제로 승격된 키에 대해서만** | `test_a_failure_mid_promotion_still_bumps_the_epoch` |
| ⑦ | ③의 재스테이징 회귀 테스트가 스테이징 디렉터리에 **직접 써서** `N+1 != N`을 재진술할 뿐이었다 | `seed.run(--stage)`를 실제로 통과시킨다(파일명·에폭 산술이 코드 것) | `test_restaging_a_promoted_pose_cannot_overwrite_the_approved_pixels` |

**스테이징 게이트를 넓힌 것**(`--pose sitting`, 비-STOCK 키): 게이트를 좁히고 있던 것은 정책이
아니라 승인기의 파일명 조회 한 줄이었다. `_validate_stage_target`을 삭제하되 그 docstring이
경고한 고립 위험은 **지우지 않고 재서술**해 `run()`의 `--stage` 분기 위에 남겼다 — 무엇이 지금
그것을 막는지(원자적 승격 + 항상 범프)와 함께. 파일명 규약은 건드리지 않았다(매니페스트 108
엔트리의 경로가 통째로 마이그레이션 대상이 되고, 이미 미등록 파일 24개가 떠 있다).

---

## 11. 검증 (실행 명령과 결과)

| 명령 | 결과 |
|---|---|
| `uv run pytest tests/domain/ tests/services/test_character_service_generation.py tests/test_seed_stock_cast.py tests/test_approve_stock_cast.py tests/test_report_card_coverage.py -q` | 전량 통과 |
| `uv run pytest -q` | `1 failed, 3373 passed, 1 skipped` — 실패는 `tests/test_render_pose_guides.py::test_render_is_deterministic_and_content_pinned[humanoid_lying_supine]`의 PNG SHA 핀 1건뿐(14.1/14.5가 기록한 기존 결함) |
| `uv run ruff check src tests scripts _bmad-output/implementation-artifacts/14-6-dclass-object-asset-sets` | clean. 인계용 두 스크립트가 원래 이 명령 밖에 있었다(리뷰 루프 2) — 운영자에게 넘기는 파일이 린트를 안 받고 있었다. 경로를 추가했고 지적 0건 |
| `uv run python scripts/report_card_coverage.py` | exit 0, 계약 FAIL 8 / 오탐 0, 정합 모집단 52, LLM 콜 0. 신규 출력 3종: 반사실 `18 of 44` 전수, 출처 `unknown` 버킷(라이브 0), 정합 기타-불일치 버킷(라이브 0) |
| `uv run python scripts/report_card_coverage.py --demand 4b35c0ed` | 41 placements / 9 scenes / UNMET 4, 경고 4건과 `(shot_id, card_key)` 대응, 미대응 0 |
| `uv run python .../reconcile_manifest.py --dry-run` (from `/tmp`) | 7행 열거, 역방향 0, exit 0, 매니페스트 md5 불변 |
| `uv run python .../reconcile_manifest.py --dry-run --commit` | **파서 거부**, exit 2, 매니페스트 불변 |
| `uv run python .../dryrun_batch.py --residue {reject,promote}` | BATCH OK — §5의 모든 명령이 기대 종료코드 |
| `md5sum assets/manifest.json` | `93a0df7e…` 시작·종료 동일 |
| `git diff --stat prompts/ assets/` | 비어 있음 |
| `uv run python scripts/report_decision_drift.py` | exit 0, 표류 0 / env-sourced 0 / 잠재 핀 0 |

---

## 12. 미주장 / 열린 것

- 픽셀 **0장**, 사람 판정 **0건**, GPU **0**, VLM·LLM 콜 **0**.
- `bump_style_epoch()` **실행 0회** (호출하는 코드는 작성했고 tmp 라이브러리에서만 돌렸다).
- `characters.angle_*_path` 쓰기 **0회** (같음).
- **열린 것**: ① §5 배치의 실제 렌더와 Jay 판정, ② pre-v5 45장의 standing 재생성(크기만 적었고
  견적하지 않았다), ③ `SCP-1471`/`SCP-682`의 사람 작성 서술자, ④ 오브젝트 자산 seam 3종,
  ⑤ `epoch_3` 잔류 4장의 승격/폐기 판정 — **§5-A/§5-B의 부수 효과를 읽은 뒤에** 고를 것,
  ⑥ 미등록 24파일의 GC(삭제하지 않았다), ⑦ `reconcile_manifest.py --commit` 실행(7행은 열거만
  했다 — `retire_asset`은 역함수가 없고 이 스토리의 Never는 "안전한 방향으로만"이지 "지금 하라"가
  아니다), ⑧ `STOCK-d-class`의 라이브 서술자와 `epoch_3` 사이드카 중 어느 쪽을 남길 것인가
  (`--reject`는 이제 자동으로 정하지 않고 경고만 한다 — §5-A).
- **리뷰 루프 2에서 새로 인계한 것**(`deferred-work.md`): 매니페스트 `created_at`이 렌더 시각이
  아니라 등록 시각이라 출처 축이 프록시라는 것 / `--demand`의 얇은 체크포인트 방어(라이브 197
  thread·9323 cast 엔트리 실측 0건) / `dryrun_batch.py`가 라이브의 상태 행렬(승인된 엔트리 위의
  `add_asset`, `retired` 행을 되살리는 `save_card`)을 재현하지 않는다는 것 / 파생 엔티티 무게이트
  출판의 기록된 이유 정정.
