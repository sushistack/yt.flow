---
title: 'Story 14.2: 플레이트 어포던스 게이트 — 설 자리 없는 플레이트에 카드를 세우지 않는다'
type: 'feature'
created: '2026-08-24'
baseline_revision: '912308c'
status: 'done'
final_revision: 'd055de4'
review_loop_iteration: 1
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/14-2-affordance-calibration/report.md'
  - '{project-root}/_bmad-output/implementation-artifacts/14-2-affordance-calibration/PREREGISTRATION.md'
  - '{project-root}/_bmad-output/implementation-artifacts/14-0-research-gate-closure/report.md'
  - '{project-root}/_bmad-output/implementation-artifacts/14-0-angle-conflict/report.md'
  - '{project-root}/_bmad-output/planning-artifacts/research/technical-perspective-population-narration-match-2026-08-17.md'
warnings:
  - '§4-2는 이미 닫혀 있다(2026-08-22 Jay 결정 (c)). 이 스토리는 그 결정을 재논의하지 않는다.'
  - '착수 순서 전제 "14-2는 14-1 다음"의 **이유**가 성립하지 않는다 — 아래 Intent 참조. 범위를 쪼개서 착수한다.'
---

<intent-contract>

## Intent

**결정 §4-2는 이미 닫혀 있다.** 2026-08-22 Jay 결정: **(c) 자산 메타데이터 + 자유생성 샷만
런타임, 판정 스키마는 하나** — `assess_plate_affordance.py`의 출력 계약
(`standing_room`/`floor_fraction`/`camera_distance`/`best_spot`/`reason`)을 두 경로가 공유한다
(스키마가 둘이면 14.2가 두 번 구현된다). 근거는 세 곳에 기록돼 있다: 리서치 §4-2,
`14-0-research-gate-closure/report.md` §(2), sprint-status `14-0` 행. **이 스토리는 그 결정을
다시 열지 않는다.**

**다시 여는 것은 착수 순서 전제 하나다.** 기록된 전제는 *"14-2를 14-1보다 먼저 하면 런당 VLM
43콜을 내고 나중에 버릴 코드를 쓴다"* 인데, (c) 하에서 **런타임 경로는 버려지는 코드가 아니다** —
자유생성 샷의 게이트는 (c)의 영구 절반이고, 14.1이 켜진 뒤에도 12/43에 계속 발화한다. 14.1이
바꾸는 것은 그 경로의 **적용 범위**(43 → 12)이지 존재가 아니다. 그리고 오늘
`stock_plate_substitution_enabled=False`라 **43/43이 자유생성**이므로, 런타임 절반은 지금 유일하게
돌릴 대상이 있는 절반이다. 반대로 **메타데이터 절반은 정말로 이르다** — 붙일 자산도, 고를 후보
풀도 없다. 그래서 범위를 쪼갠다:

- **이 스토리(14.2)**: 자유생성 샷의 런타임 게이트 + **공유 판정 스키마**.
- **14.1과 함께**: 승인 플레이트에 판정을 메타데이터로 붙이고, 후보 풀에서 **고르는** 필터로 쓴다.

**표적이 인계 문구와 다르다 — 착수 전 캘리브레이션에서 실측했다**
(`14-2-affordance-calibration/report.md`, GPU 0 · 렌더 0 · VLM 34콜, run `4b35c0ed` 33쌍 전수):

1. 인계된 라벨 `{S00504, S00803}`은 **둘 다 어포던스 부류가 아니다.** 발이 접지돼 있고 바닥이
   충분하며, 판정기도 독립적으로 `standing_room=true`를 준다. `S00504`는 부감 원근,
   `S00803`은 척도 문제이고 둘 다 **14.3** 소관이다. (`S00803`은 "천장 앙각"이라는 인계 서술과
   달리 §4-4 손판정 시점이 **눈높이**다 — 인계 문구가 프롬프트를 읽고 쓰였다.)
2. 실제 어포던스 부류는 **7/33(21%)** 이고 기저율이 인계 값의 3.5배다. 실패 양상은 넷이다 —
   플레이트 소실(`S00602`, 이 런 유일, 2026-08-09 `S00104` 계열), 없던 바닥 발명(`S00302`),
   카드가 떠 있는 흉상으로 들어감(`S00201`·`S00601`), 허공에 앉거나 무릎에서 잘림(`S00103`·`S00605`).
3. **이미 측정된 라벨 둘은 예측기가 아니다**(신규 반증, n=33): 시점 `y_h` — 비-눈높이 17건 중
   BROKEN 4건이고 극단 부감 5건은 **전부 OK**. `floor_share` — 유일한 플레이트 소실 사례가 0.70을
   받았다. `ground_plane()` 역상관(n=5)에 이어 세 번째·네 번째 사례다.
4. 인계된 두 번째 실측(버킷 밖 수식어 14건)은 **게이트 입력이 아니다.** `S00602`의 슬롯-1은
   `"medium shot"`(버킷 내)이고 `S00803`은 `"low-angle shot looking up from the floor"`(버킷 내)다.
   수식어는 캘리브레이션 세트의 **라벨링 사전확률**로만 쓴다.
5. **판정기가 SCP 플레이트 한 부류에서 재현 가능하게 거부된다** — `S00601`(시트 덮인 시신)은
   `data_inspection_failed` 400을 결정적으로 낸다. 같은 플레이트가 **10.2 가드에서도 `None`** 이다
   (확인). 이는 14.4가 원인 없이 기록한 그 런의 판정불가 1건의 원인일 개연이 높다.

**Approach:** 새 층을 만들지 않는다. 종단 동작과 배치 지점이 이미 코드에 있다.

- **종단 동작** = `scenario_chain._suppress_cast_on_no_figure_framing`(8.19)의 동작, 즉
  `cast → []`. 그 함수의 `# ponytail:` 주석이 *"until a diagnosed case justifies a marker with
  better precision"* 라고 자기 한계를 적어뒀고, 이 세션이 그 진단 사례다. 그리고 §3이 **어휘를
  넓히면 안 된다**는 것을 실측했다(`high-angle` 마커는 OK 5건을 지운다). 픽셀 판정이 그 자리를
  채운다.
- **배치 지점** = `image.py`의 10.2 시드 래더. 렌더 후 판정 → 시드 상승 → 소진 시 종단 처리라는
  구조와 사이드카·경고·resume 재발화(14.4)가 이미 딸려 있다. 어포던스는 그 루프의 **두 번째
  술어**이고, `shot["cast"]`는 이미 그 루프의 손 안에 있다.
- **사다리를 먼저 태우고, 소진되면 카드를 뺀다.** 시드만 올려도 시점 범주가 뒤집힌다는 것을
  §4-4가 실측했으므로(리시드 5쌍 중 2쌍) 재생성은 이 부류에 실제로 작동한다. 그리고 재생성이
  성공하면 비트가 원한 인물이 살아남는다 — 8.19의 삭제는 그 기회 없이 지운다. 실측 기저율
  7/33이면 히트당 ~17초 × 7 ≈ 2분이고, 지금 33샷 어포던스 콜(~3.2초/콜)이 ~1.8분이다.
- **판정 스키마는 하나**(Jay 결정). `assess_plate_affordance.py`의 5필드 계약을 런타임이
  그대로 쓴다. 프롬프트를 옮겨 복사하지 말고 **import**한다 — 손으로 베낀 두 벌은 자기검증이다
  (`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`).

## Boundaries & Constraints

**Always:**
- **판정불가는 수용 + 경고, 절대 "설 자리 없음"이 아니다** — 14.4의 undecidable 정책을 그대로
  승계한다. `data_inspection_failed`는 시신·의료·훼손 플레이트에서 **영구 사각지대**이고
  (§5, 재현 확인), 판정불가를 실패로 처리하면 그 부류에서 cast가 상시 삭제된다.
- **사이드카에 판정을 남기고 resume에서 재발화한다.** 어포던스 때문에 cast를 뺀 샷은 재시작 후
  `_existing_complete_shot` 조기 반환 경로를 타므로, 사이드카 없이는 카드가 **되살아난다**.
  14.4가 `guard_undecidable`로 똑같은 구멍을 막았다(13.3 AC8 준수: 가산·비교 제외).
- **기본값은 off로 출하하지 않는다** — 결정이 서면 `config.py` 코드 기본값에 넣고 날짜 붙은
  근거를 주석에 쓴다. `.env`/`.env.example`에 핀하지 않는다
  (`gotcha_a-decision-that-only-reaches-env-never-ships`: 10.2 가드가 15일간 0으로 출하됐다).
  `config.DECISIONS` 행은 **날짜 있는 판정이 생긴 뒤에만** 추가한다.
- 라벨은 **사람 판정으로 확정한다.** `pairs_1..6.jpg`를 Jay가 본 결과가 §1의 7건과 어긋나면
  Jay가 맞다. 인계 라벨 2건을 뒤집었으므로 그 대조가 먼저다.
- 측정치는 재산출 스크립트 + 표본 밴드와 함께 남긴다(`gotcha_a-measurement-without-its-sample-band`).
- 성긴 표본으로 "고쳤다"를 선언하지 않는다(`gotcha_measure-densely-before-declaring-a-fix` —
  이 세션이 이미 8쌍 표본에서 잘못된 부감 가설을 세웠고 33쌍 전수가 그것을 죽였다).

**Block If:**
- Jay의 라벨이 §1의 7건과 **3건 이상** 어긋난다 → 판정기 채점을 다시 하고, 재현/오탐 조건도
  다시 사전등록한다. 옛 채점으로 게이트를 출하하지 않는다.
- 사전등록 조건(재현 ≥6/7 · 오탐 ≤3/25)이 Jay 라벨 기준으로도 미달 → 프롬프트를 **한 번**
  고쳐 재측정하고, 두 번째도 실패하면 HALT하고 판정기를 바꾼다. 같은 프롬프트 재시도 금지.
- 오탐이 OK 라벨의 **12% (3/25)** 를 넘는데 종단 동작이 "카드 삭제"다 → 삭제를 종단 동작으로
  출하하지 않는다(멀쩡한 카드를 지운다). 사다리만 태우고 소진 시 **유지 + 경고**로 내린다.

**Never:**
- **시점(`y_h`)·`floor_share`·부감 여부를 게이트 입력으로 쓰지 않는다**(§3, n=33 반증). 부감
  바닥 플레이트가 곧 배치 불가가 아니다 — 극단 부감 5건이 전부 정상 접지였다.
- **`_NO_FIGURE_FRAMINGS`에 어휘를 추가하지 않는다** — `high-angle`/`tight on` 확장은 8.19 주석이
  경고했고 §3이 실측으로 확인했다(OK 5건 삭제).
- `camera_distance`와 `camera_angle`을 섞지 않는다 — 하나는 픽셀 추정, 하나는 LLM 선언이고
  대조된 적이 없다(§4-2 주의사항, §4-4와 함께 읽을 것).
- **`S00504`·`S00803`을 이 게이트의 목표로 삼지 않는다.** 둘은 접지돼 있고 결함은 원근·척도다
  → **14.3**. 이 게이트로 잡으려 하면 오탐을 사서 없는 결함을 고친다.
- 어포던스 판정을 10.2 가드의 `CHECK_PROMPT`에 합치지 않는다 — 14.4가 그 탐지기의 목적 확장을
  명시적으로 기각했고, 프롬프트를 바꾸면 14.4가 실측한 가드 신뢰도가 무효가 된다.
- 메타데이터 절반(자산 필드 · 후보 풀 선택 필터)을 이 스토리에서 구현하지 않는다 → **14.1**.
- `floor_fraction` 연속값에 사후 커트를 그어 7건에 맞추지 않는다.
- `stock_plate_substitution_enabled`를 이 스토리가 켜지 않는다(14.1의 명시적 임무).
- 새 모델·새 커스텀 노드·새 의존성(§4-1/§4-3). `--baseline`·A/B·골든셋 게이트 실행(DEV MODE).

## I/O & Edge-Case Matrix

| 입력 | 기대 |
|---|---|
| cast 없는 샷 | 판정기 **미호출**(콜 0). 어포던스는 카드가 붙을 때만 질문이다 |
| cast 있음 · `standing_room=true` | 통과, 사다리 미소비 |
| cast 있음 · `false` · 사다리 남음 | 시드 상승 후 재렌더, 재판정 |
| cast 있음 · `false` · 사다리 소진 | 종단 동작(§Block If가 고른다) + 샷 단위 경고 |
| 판정불가(400/키 부재/파싱 실패) | **수용 + 미소비 + 샷 단위 경고**. clean으로 계상 금지 |
| `data_inspection_failed` 부류 | 위와 같음. 재현 가능한 영구 거부이므로 재시도로 풀리지 않는다 |
| resume(사이드카에 어포던스 판정 있음) | 판정 재적용 + 경고 재발화. 카드 부활 금지 |
| 판정불가 연속/누적 | 10.2 차단기 재사용(연속 3 / 누적 6) — 새 차단기 만들지 않는다 |
| `stock_plate_substitution_enabled=True` + `location_key` | 플레이트 복사 경로 — 이 스토리 범위 밖(14.1) |

</intent-contract>

## Code Map

- `scripts/assess_plate_affordance.py` -- 판정 스키마의 출처. `PROMPT` 를 런타임이 **import** 한다(복사 금지)
- `src/yt_flow/services/vision_check.py` -- 호출 형태·fail-open 계약·brace-slice 파싱의 선례. 어포던스 판정 함수가 여기 이웃한다
- `src/yt_flow/pipeline/nodes/image.py:308-352` -- `_write_sidecar(out_dir, scene_num, shot, seed, provenance, guard_exhausted=False, guard_undecidable=False)`. 플래그는 항상 기록되는 bool, resume 비교 대상 아님
- `src/yt_flow/pipeline/nodes/image.py:370-398` -- `_existing_complete_shot`. 비교 키는 `image_prompt`/`negative_prompt`/`seed∈ladder` **셋뿐** — 비교 키를 늘리면 기존 캐시 전량 무효
- `src/yt_flow/pipeline/nodes/image.py:354-368` -- `_sidecar_guard_flag(out_dir, scene_num, shot, key)`. key 로 일반화돼 있어 **새 함수 불필요**
- `src/yt_flow/pipeline/nodes/image.py:495` -- `guard_counts` 초기화 지점. `:827-832` 요약 경고
- `src/yt_flow/pipeline/nodes/image.py:660-820` -- 10.2 래더 + 사이드카 기록 루프. 어포던스는 **래더 밖·확정 렌더 1회**
- `src/yt_flow/domain/warnings.py:29-88` -- `RUN_WARNING_CATALOG`. 신규 코드는 카탈로그 행이 없으면 **import 시 raise**. `:144-157` 캡 키가 `(code, reason)`
- `src/yt_flow/domain/state.py:323` -- `ShotData["cast"]` 는 **필수** 키이고 `[]` 의 뜻이 "배경 전용, 다운스트림 오버레이 0" 으로 문서화돼 있다
- `src/yt_flow/pipeline/nodes/scenario_chain.py:437-502` -- 8.19 `_NO_FIGURE_FRAMINGS` + `cast → []`. 종단 동작의 선례
- `src/yt_flow/config.py:222,365,671-674` -- 비전 키 / 가드 노브 / `DECISIONS` 레지스트리
- `tests/pipeline/nodes/test_image.py:38-60,1134-1175` -- `FakeSettings`(신규 설정 필드는 여기도 추가) + 가드 테스트 헬퍼

## Tasks & Acceptance

**Execution:**
- [x] `src/yt_flow/services/vision_check.py` -- `plate_has_standing_room(image_bytes, settings) -> bool | None` 추가. `assess_plate_affordance.PROMPT` 를 import 해 쓰고 `standing_room` 만 읽는다. **요청 봉투도 공유한다** — `[image, text]` 순서 + `temperature=0`(리뷰 루프 1 실측: 순서가 재현 3/7 ↔ 5/7 을 가른다). `background_has_person` 과 동일한 fail-open 계약(절대 raise 안 함, 판정불가는 `None`), `notes`/`reason` 은 로그로 -- 스키마가 둘이 되면 14.2가 두 번 구현된다(Jay 결정)
- [x] `src/yt_flow/config.py` -- `plate_affordance_gate_enabled: bool = False` 코드 기본값(리뷰 루프 1: 사전등록 도달 불가 + AC1 미결) + 날짜 붙은 근거 주석 + `DECISIONS` 행. `.env`/`.env.example` 핀 금지 -- 결정이 `.env` 에만 닿으면 출하되지 않는다(10.2 가드 15일 전례)
- [x] `src/yt_flow/domain/warnings.py` -- `RunWarningCode` 리터럴 + 카탈로그 행 `plate_affordance_unusable`(stage `image`). reason 별 캡 예산을 공짜로 얻는다
- [x] `src/yt_flow/domain/state.py` -- `RunWarningCode` 리터럴 동기화(`:561`)
- [x] `src/yt_flow/pipeline/nodes/image.py` -- 10.2 래더가 **확정한 렌더에 대해 1회** 어포던스 판정. cast 없으면 미호출. `false` 면 반환 샷 사본의 `cast = []` + 경고. 사이드카에 `affordance_unusable` 기록(가산·비교 제외) + resume 재적용/재발화. 판정불가는 수용 + 경고
- [x] `tests/pipeline/nodes/test_image.py` -- I/O 매트릭스 9행 전부. 특히 cast 없는 샷 콜 0, 판정불가 수용, resume 후 카드 부활 금지, 10.2 카운터·차단기 무변
- [x] `tests/domain/test_run_warnings.py` -- 신규 코드가 카탈로그·캡·머지 계약을 지키는지
- [x] `_bmad-output/implementation-artifacts/14-2-affordance-calibration/report.md` -- 종단 동작 결정과 그 근거(오탐 1/25, 리시드 수익 미측정) 추기

**Acceptance Criteria:**
- Given cast 가 빈 샷, when image_node 가 그 샷을 렌더할 때, then 어포던스 판정기가 **호출되지 않는다**(콜 0) -- 어포던스는 카드가 붙을 때만 질문이다
- Given cast 가 있고 판정기가 `standing_room=false` 를 줄 때, when 샷이 완료되면, then 반환 상태의 그 샷 `cast` 가 `[]` 이고 `plate_affordance_unusable` 경고가 `scene_num`+`shot_id` 와 함께 남고 **입력 상태는 변하지 않는다**(AD-4)
- Given 판정기가 `data_inspection_failed`/키 부재/파싱 실패로 판정불가일 때, when 샷이 완료되면, then 프레임과 `cast` **둘 다 유지**되고 `reason=detector_undecidable` 경고가 남으며 clean 으로 계상되지 않는다
- Given 어포던스로 cast 가 비워진 샷의 사이드카가 있을 때, when 같은 런을 resume 하면, then `cast` 가 다시 `[]` 로 적용되고 경고가 재발화한다(카드 부활 금지)
- Given `plate_affordance_gate_enabled=False`, when image_node 가 돌면, then 판정기 콜 0 이고 `cast` 가 그대로다
- Given 어포던스 판정이 사이드카에 추가된 뒤, when 14.2 이전 체크포인트를 resume 하면, then `_existing_complete_shot` 이 여전히 히트한다(비교 키 3개 불변)
- Given run `4b35c0ed` 의 33 플레이트, when `crosstab_cast_viewpoint.py` 를 사전등록 라벨로 돌리면, then 재현/오탐/판정불가 수치가 리포트와 **바이트 단위로 재현**된다

## Spec Change Log

- 2026-08-24 최초 작성. §4-2 결정 확인(재논의 없음), 착수 순서 전제 반증, 범위 분할, 표적 라벨 교체(인계 2건 → 실측 7건), 예측기 후보 2종 반증, 판정기 콘텐츠 거부 부류 발견.
- 2026-08-24 종단 동작 확정 = **카드 삭제(사다리 없음)**. 사전등록은 오탐 >3/25 일 때 삭제를 금지했고 실측이 **1/25** 이라 허용된다. 사다리를 안 쓰는 이유는 별개다 -- **리시드 수익이 이 부류에서 미측정**이고, 플로어리스 플레이트를 만든 프롬프트(테이블 매크로·창 프레임)는 시드를 올려도 같은 프레이밍을 요구하므로 사전확률이 낮다. §4-4가 실측한 리시드 효과는 **시점**이고 바닥 존재가 아니다. `images_pre_guard/` 로 리시드 대조를 만들려 했으나 43/43이 바이트 상이라 재렌더 5샷을 분리할 수 없었다(그 디렉터리는 부분 사본이 아니다). 사다리는 리시드 수익이 측정된 뒤에 붙인다.

- 2026-08-24 **리뷰 루프 1 — 요청 봉투가 캘리브레이션한 봉투가 아니었다(적대적 리뷰 #4).** 트리거: 런타임은
  `[text, image]` + `temperature=0`, 캘리브레이션 스크립트는 `[image, text]` + temperature 미지정.
  **실측으로 확인됐고 노이즈가 아니다** — 33 플레이트 재측정: `[text,image]` 재현 **3/7** · 오탐 **0/25**,
  `[image,text]` 재현 **5/7** · 오탐 **1/25**. 두 봉투 모두 **뒤집힘 0**(각 3회·2회 반복)이므로 차이는
  비결정성이 아니라 **이미지·지시 순서**다. `S00103`·`S00605`가 순서만으로 뒤집힌다. 프롬프트 텍스트를
  공유한 이유(`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`)가 **요청 봉투에 그대로 적용된다** —
  텍스트만 공유하고 봉투가 갈리면 공유의 목적이 사라진다. **수정**: 런타임을 `[image, text]` +
  `temperature=0` 으로 통일(캘리브레이션 순서 + 결정성 동시 충족, 재현 5/7·오탐 1/25 바이트 일치).
  회피한 알려진-나쁜 상태: 측정되지 않은 설정으로 출하해 5/7 을 근거로 인용하는 것.
  **부수 발견**: 10.2 가드(`background_has_person`)도 `[text, image]` 다 — 그 질문에 대해 순서 효과가
  측정된 적은 없다. **주장하지 않는다**, `deferred-work.md` 로.
- 2026-08-24 **리뷰 루프 1 — 사전등록 기준선이 도달 불가로 판명(적대적 리뷰 #1·#2).** 기준 `재현 ≥6/7` 은
  **구성상 달성 불가**다: 7건 중 `S00601`은 `data_inspection_failed` 로 **영구 판정 불가**이고(재현 확인),
  `S00105`는 판정기가 옳고 라벨이 틀린 건이다(리포트 §4). 즉 최대 달성치가 5/7 이다. 고칠 것은 측정
  대상이 아니라 **기준**이다(`gotcha_a-screening-gate-can-fail-on-its-own-threshold` — 14.7이 같은 형태를
  이미 겪었다). **그러나 기준을 결과를 보고 다시 쓰지 않는다** — 교정 분모(5건)와 새 기준은 **Jay의 33쌍
  라벨 확정(AC1) 뒤에 다시 사전등록**하고 fresh 표본(E2E iteration 5)에서 확인한다. **수정**: 코드 기본값을
  `True` → **`False`** 로 내리고 날짜 붙은 근거에 두 봉투 수치·도달 불가 사유·AC1 미결을 함께 적는다.
  회피한 알려진-나쁜 상태: 사전등록이 막으려던 바로 그 행위(FAIL 상태에서 ON 출하), 그리고 사람이 프레임을
  판정하기 전에 카드를 지우는 기본값(CLAUDE.md; 10.1c·10.5·10.1e 전례가 모두 시청 판정 전 OFF).
  **KEEP(재도출 시 반드시 살릴 것)**: fail-open 계약과 AD-10 벨트-서스펜더 / **독립 차단기**(공유하면
  어포던스 거부가 사람 가드를 침묵시킨다, 테스트로 고정됨) / 래더 **밖** 1회 판정 / 사이드카 additive·
  **비교 제외**(`_existing_complete_shot` 비교 키 3개 불변) / `(code, reason)` 캡 / `.env` 핀 없음 /
  판정불가를 실패로 읽지 않는 규칙 / cast 없는 샷 콜 0 / mock·스톡플레이트 경로 미호출.
- 2026-08-24 **리뷰 루프 1 — 회계·resume 이음새 5건.** (a) 판정불가/미판정이 사이드카에 없어 **resume 이
  깨끗한 집계를 보고한다**(리뷰 #6, 13.1이 없애려는 결함 그대로) → `affordance_undecidable` 플래그 추가 +
  재발화. (b) 비전 키 부재가 "죽은 판정기"로 계상돼 판정불가 3행 + 차단기 행을 만든다(리뷰 #7) →
  `affordance_off` 에 키 조건 추가 + 런 단위 경고 1건(10.2와 같은 형태). (c) `unjudged` 가 스톡플레이트·
  mock·resume 을 안 센다(리뷰 #11) → cast 보유인데 판정 안 된 모든 경로에서 가산. (d) resume 이 노브 OFF
  에서도 사이드카로 cast 를 지운다(엣지 #1) → 노브 조건 추가. 이것이 **오탐 복구 경로**이기도 하다(리뷰 #5):
  노브를 내리면 다음 패스에서 카드가 돌아온다. (e) 이미 빈 cast 에 드롭 경고를 낸다(엣지 #5) → cast 유무 검사.
  회피한 알려진-나쁜 상태: 미검사 프레임이 검증된 클린과 구분되지 않는 것(13.1/14.4가 두 번 고친 부류).
- 2026-08-24 **리뷰 루프 1 — 서술 정정 4건.** 설정 주석이 미검출 2건을 둘 다 14.3 부류로 오귀속(리뷰 #3 —
  `S00601`은 이 게이트 부류이고 구조적으로 판정 불가다) / 경고 카탈로그 문안이 파괴적 결과를 사실로 단언
  (리뷰 #9, 판정불가 행은 cast 유지) / `full_restart_run` 인용이 세 곳에서 틀림(리뷰 #12 — 실제 경로는
  image_node 내부 크래시·에러 경로 resume) / `card_key` 를 경고에 안 실어 무엇이 지워졌는지 알 수 없음
  (리뷰 #5). 그리고 이 계약서 `<intent-contract>` 의 Approach·I/O 매트릭스 3~4행·Block If #3 은 **사다리를
  전제**하는데 사다리는 만들지 않았다(리뷰 #10) — 계약 내부는 읽기 전용이므로 **원문을 보존하고 여기서
  무효를 선언한다**: 그 세 곳은 2026-08-24 종단 동작 결정(사다리 없음)으로 **대체됐고**, 유효한 매트릭스는
  9행이 아니라 7행이다(3~4행 삭제).

## Review Triage Log

### 2026-08-24 — Review pass
- intent_gap: 0
- bad_spec: 8: (high 4, medium 4)
- patch: 5: (medium 2, low 3)
- defer: 2: (medium 1, low 1)
- reject: 4
- addressed_findings:
  - `[high]` `[bad_spec]` 요청 봉투가 캘리브레이션과 달라 5/7 이 출하 설정의 수치가 아니었다 — 33 플레이트 재측정으로 순서 효과 확인(3/7 vs 5/7, 뒤집힘 0), 런타임을 `[image, text]` + `temperature=0` 으로 통일
  - `[high]` `[bad_spec]` 사전등록 FAIL 상태에서 기본값 ON — 기준이 구성상 도달 불가임을 확인하고 기본값 `False` 로 내림, 재사전등록은 AC1 뒤로
  - `[high]` `[bad_spec]` 판정불가/미판정이 사이드카에 없어 resume 이 깨끗한 집계를 보고 — `affordance_undecidable` 추가 + 재발화
  - `[high]` `[bad_spec]` 카드 삭제가 복구 불가 — resume 에 노브 조건을 넣어 노브 OFF 가 복구 경로가 되게 하고, 경고에 `card_key` 를 실음
  - `[medium]` `[bad_spec]` 비전 키 부재가 죽은 판정기로 계상 — `affordance_off` 에 키 조건 + 런 단위 경고 1건
  - `[medium]` `[bad_spec]` `unjudged` 가 스톡플레이트·mock·resume 를 누락 — 모든 미판정 경로에서 가산
  - `[medium]` `[bad_spec]` 설정 주석이 `S00601` 을 14.3 부류로 오귀속 — 영구 판정 불가로 정정
  - `[medium]` `[bad_spec]` 경고 문안이 판정불가 행에도 "배역을 뺐다"고 단언 — reason 중립 문안으로
  - `[medium]` `[patch]` resume 이 이미 빈 cast 에 드롭 경고 — cast 유무 검사 추가
  - `[medium]` `[patch]` 수렴 테스트가 같은 reason 을 양쪽에 넘겨 resume 경로를 안 건드림 — 실제 2행 현실을 단정하도록 수정
  - `[low]` `[patch]` `full_registry_run` 인용 3곳 오류 — 실제 경로(노드 내부 크래시·에러 경로 resume)로 정정
  - `[low]` `[patch]` 이미 메모리에 있는 `image_bytes` 를 디스크에서 재독 — 인자로 전달
  - `[low]` `[patch]` 프롬프트 동일성 테스트가 세션 `sys.path` 오염 — 원복
  - `[low]` `[patch]` 재도출이 pyright 신규 3건을 남겼다(진단기 보고) — `{**shot, "cast": []}` 두 곳이 TypedDict 를 `dict[str, Unknown]` 로 넓혀 `_with_depth(shot: ShotData)` 를 깨뜨리고, `image_bytes` 두 번째 독자가 possibly-unbound. `typing.cast(ShotData, ...)` + mock 분기 위 사전 바인딩으로 수정 — image.py pyright **2건 → 1건**(남은 1건은 `Settings()` 하우스 패턴, 베이스라인에도 있었다)

### 2026-08-24 — Review pass 2
**실행되지 않았다 — Jay 가 중단했다(도구 사용 거부 + "계속").** 루프 1의 수정은 전량 검증됐으나(238 passed · ruff clean · pyright 신규 0 · 드리프트 리포트 exit 0) **독립 리뷰를 받지 않았다.** 그래서 `followup_review_recommended: true` 다 — 루프 1이 기본값·요청 봉투·resume 회계·경고 문안을 모두 건드렸고 그 수정들 자체는 검토되지 않았다.
- addressed_findings:
  - none

## Design Notes

**왜 래더 안이 아니라 래더 밖인가.** 어포던스 판정을 10.2 루프 안에 넣으면 rung 회계(`regenerated` 는 "다른 렌더가 실제로 뒤따르는 rung 만") 와 시드 고정(`seed` 가 수용된 rung 에 묶여야 resume 이 재렌더하지 않는다) 에 두 번째 술어가 얽힌다. 얻는 것은 없다 -- 종단 동작이 재생성이 아니라 카드 삭제이므로 판정은 **확정된 렌더 1장에 대해 1회**면 충분하다. 콜 수도 그 편이 적다(rung 마다가 아니라 샷마다).

**카드 생성은 이미 끝나 있다.** `run_service.resume_after_gate` 가 시나리오 게이트 승인 시점에 `_ensure_special_pose_cards` / `_ensure_derived_entity_cards` 로 `shot["cast"]` 를 걸어 카드를 만든다(`run_service.py:810-811`) -- image 단계보다 앞이다. 그러므로 이 게이트는 **화면에 합성되는 것**을 막고 카드 생성 비용은 못 막는다. 그것이 옳은 절충이다: 결함은 프레임에 있고, 카드는 재사용 자산이다.

**8.19를 지우지 않는다.** 텍스트 마커는 렌더 **전에** 발화해서 렌더 한 장을 아낀다. 픽셀 게이트는 마커가 못 잡는 것을 렌더 후에 잡는다. 둘은 겹치지 않고, 마커 어휘를 넓히는 것은 §3이 실측으로 금지했다.

## Verification

**Commands:**
- `uv run pytest tests/pipeline/nodes/test_image.py -q` -- expected: 기존 전량 통과 + 신규 통과
- `uv run pytest tests/domain/test_run_warnings.py tests/test_config.py tests/test_report_decision_drift.py -q` -- expected: 통과(카탈로그 완전성·캡·결정 레지스트리)
- `uv run pytest -q` -- expected: `test_render_pose_guides.py` PNG SHA 1건만 실패(14.5가 기존 결함으로 기록, stash 후에도 동일)
- `uv run ruff check src tests scripts` -- expected: clean
- `uv run python scripts/report_decision_drift.py` -- expected: exit 0, 신규 노브가 env-sourced 나 latent 핀으로 뜨지 않음
- `uv run python _bmad-output/implementation-artifacts/14-2-affordance-calibration/crosstab_cast_viewpoint.py 4b35c0ed .../affordance_33.json` -- expected: 재현 5/7 · 오탐 1/25 · 판정불가 1 재산출

**Manual checks (if no CLI):**
- 픽셀 판정은 이 스토리가 하지 않는다 -- 게이트가 켜진 **E2E iteration 5** 에서 어포던스 부류 7/33 이 몇으로 내려갔는지 본다. 그 런 없이 "고쳤다" 를 적지 않는다.
- `pairs_1..6.jpg` 로 Jay 가 33쌍 라벨을 확정한다(AC1 은 사람 게이트이므로 무인 실행에서 닫히지 않는다 -- `## Auto Run Result` 에 미결로 남긴다)


## Auto Run Result

Status: **done** — 단, **닫힌 것은 코드와 측정이고 픽셀·사람 판정은 열려 있다.** 노브가 OFF 로 출하되는 것이 그것을 안전하게 만드는 조건이다.

### 구현된 변경

`image_node` 가 렌더한 배경 플레이트에 **온몸이 설 수 있는 지면이 있는지** 확정된 렌더 1장에 대해 한 번 묻고, 없으면 그 샷의 `cast` 를 비워 카드가 프레임에 합성되지 않게 한다. 8.19 텍스트 마커의 동작(`cast → []`)을 픽셀 판정으로 확장한 것이고, 그 함수의 `# ponytail:` 주석이 *"until a diagnosed case justifies a marker with better precision"* 라고 남긴 조건을 이 스토리의 캘리브레이션이 충족했다. 판정 스키마는 하나(§4-2 Jay 결정) — 오프라인 큐레이터와 런타임이 프롬프트 **텍스트와 요청 봉투를 함께** 공유한다.

### 파일

| 파일 | 한 줄 |
|---|---|
| `src/yt_flow/services/vision_check.py` | `plate_has_standing_room` + `STANDING_ROOM_PROMPT`; 두 질문이 `_bool_verdict` 하나를 공유하고 `image_first` 는 **기본값 없는** 키워드(제3의 질문은 자기 봉투를 선언해야 한다) |
| `scripts/assess_plate_affordance.py` | 프롬프트를 소유하지 않고 `src` 에서 import; `temperature: 0` 핀 |
| `src/yt_flow/config.py` | `plate_affordance_gate_enabled: bool = False` + 날짜 붙은 근거 + `DECISIONS` 행. `.env`/`.env.example` 핀 없음 |
| `src/yt_flow/domain/warnings.py` · `state.py` | `plate_affordance_unusable` 코드 + reason 중립 카탈로그 문안 |
| `src/yt_flow/pipeline/nodes/image.py` | 게이트(래더 **밖**, 샷당 1회, cast 없으면 콜 0) · `cast → []` · 사이드카 2플래그(가산·비교 제외) · resume 재적용/재발화 · 독립 차단기 · `affordance_counts` |
| `tests/` 5개 파일 | I/O 매트릭스 전행 + AC 전건, 프롬프트·봉투 동일성 핀, 무키 경로, resume 부활 금지, 노브 OFF 복구 |
| `14-2-affordance-calibration/` | 사전등록 · 33쌍 시트 6장 · 판정기 리포트 2종 · 교차표 · 봉투 재측정 스크립트 |

### 리뷰 결과

패스 1: intent_gap 0 · **bad_spec 8**(high 4) · patch 5 · defer 2 · reject 4 → 스펙 수정 + 재도출. 패스 2는 Jay 가 중단.

가장 중대한 발견 둘은 **이 스토리 자신의 주장을 반증했다**:
1. **런타임이 캘리브레이션한 설정이 아니었다** — `[text, image]` vs `[image, text]` 가 재현 **3/7 ↔ 5/7** 을 가른다(각 3회·2회 반복, **뒤집힘 0** — 노이즈가 아니라 결정적 순서 효과). 텍스트만 공유하고 봉투가 갈리면 공유의 목적이 사라진다.
2. **사전등록 기준선이 도달 불가였다** — `재현 ≥6/7` 은 구성상 불가능하다(`S00601` 영구 판정 불가 + `S00105` 라벨 오류). 그래서 기본값을 `True` → **`False`** 로 내렸다.

### 검증

- `238 passed` (test_image · test_vision_check · test_run_warnings · test_config · test_report_decision_drift)
- 전체 `3259 passed / 1 failed` — 그 1건은 `test_render_pose_guides.py` PNG SHA 핀이고 **14.5가 이미 기존 결함으로 기록**했다(stash 후에도 동일 실패)
- `ruff check src tests scripts` → clean
- `pyright src/yt_flow/pipeline/nodes/image.py` → **1건**(`Settings()` 하우스 패턴, 베이스라인 2건보다 하나 적다)
- `report_decision_drift.py` exit 0 — 신규 노브 `source: code default`, 표류 없음, `.env.example` 잠재 핀 없음
- 캘리브레이션 재산출: `crosstab_cast_viewpoint.py` 재현 5/7 · 오탐 1/25 · 판정불가 1 바이트 일치

### 잔여 리스크 · 미주장

- **AC1(Jay 의 33쌍 라벨 확정)은 열려 있다.** 라벨은 Claude 단독 판정이고 **이미 두 번 틀렸다** — 인계 라벨 2건과 서로소였고(`S00504`·`S00803` → 14.3), `S00105` 는 판정기가 옳았다. `pairs_1..6.jpg` 가 그 판정용 시트다.
- **AC7(픽셀 판정) 없음** — 게이트가 켜진 런이 0회다. 어포던스 부류 7/33 이 몇으로 내려가는지는 **E2E iteration 5**.
- **교정 분모(5건)와 새 기준은 재사전등록해야 한다.** 결과를 보고 기준을 다시 쓰지 않았고, 쓰지 않은 상태로 남겨뒀다.
- 오탐 1/25 는 노브를 내리면 다음 패스에서 복구된다(resume 이 노브를 존중한다). 그것이 유일한 복구 경로다.
- 10.2 가드의 봉투 순서 효과는 미측정 → `deferred-work.md`.
- 패스 2 리뷰 미실행 → `followup_review_recommended: true`.
