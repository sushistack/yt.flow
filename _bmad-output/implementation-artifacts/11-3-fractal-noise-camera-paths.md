---
baseline_commit: ce4bcefba60dcc8ed0f02ffd61fdaf0d5b619c13
---

# Story 11.3: 프랙탈 노이즈 카메라 경로 — 사인파 상수 대체

Status: done

## Story

As a **yt.flow 운영자 (Jay)**,
I want **카메라 모션이 단일 주파수 사인파 + "eyeball-tuned" 상수 대신 표준 근거 기반 2대역 fBm(fractional Brownian motion) 노이즈(저주파 sway + 미세 tremor)로 구동되고, 스팅어 히트에 동기한 trauma 이벤트 셰이크와 11.2 shake 아키타입의 실제 구현이 함께 배선**되도록,
so that **"vibration이 아니라 사람이 든 카메라"로 읽히는 1/f 스펙트럼 구조의 핸드헬드 모션이 전 샷에 깔리고, 스케어 비트의 셰이크가 유기적으로 램프다운하며, 조잡한 슬라이드쇼 신호(기계적 등속 모션)가 사라진다**.

## Acceptance Criteria

1. **신규 모듈 `camera_path.py` — fBm 프리미티브 + 아키타입 노이즈 프로파일**: `src/yt_flow/pipeline/nodes/camera_path.py` 신설(character_motion.py와 동일한 성격: 순수 함수 + 데이터만, I/O 없음, domain/config 외 import 없음 [AD-1]). 내용물: ① `fbm_expr(...)` — 2–3옥타브 value-noise fBm을 **ffmpeg 표현식 문자열**로 산출하는 결정론 빌더(해시 기반 value noise: `sin(격자인덱스*12.9898)` 해시 — character_motion `_term_expr`의 glitch 스테어케이스 관용구의 보간 확장판 — 를 smoothstep 보간, persistence 0.5, 옥타브 진폭 합이 지정 amp를 넘지 않게 정규화). **백색잡음(프레임 독립 랜덤) 금지, `random` 모듈 금지, ffmpeg `random()` 금지** — 모든 항은 t의 연속 결정론 함수. ② `CAMERA_NOISE_PROFILES` — 아키타입별 2대역 프로파일(sway 격자주파수 0.5–2 steps/s @ 프레임폭 0.3–1%(다큐)~1–2%(shake) + tremor 8–12 steps/s 미량, rotation ≤1°, micro-zoom 소량; Gavant IEEE 2대역 + AE wiggle 모델). `locked`는 전부 0(트라이포드 — 이것이 locked의 존재 이유). **락스텝 assert**: `set(CAMERA_NOISE_PROFILES) == set(CAMERA_ARCHETYPES)` (7.2 KeyError 불변식, scenario_chain.py:79 선례). ③ 분석적 excursion 상한 함수(옥타브 진폭 합 + trauma 피크) — AC2의 오버스캔 마진이 이 값에서 **by construction**으로 유도된다(7.3 CHAR_MAX_W 계보). **레이어링 판정(epics 원문 수정)**: epics의 "노이즈 프로파일을 11.2 아키타입 테이블에 병합"은 물리적으로 불가 — `CAMERA_PREFERENCES`는 scenario_chain.py에 살고 video는 scenario_chain을 import할 수 없다(LLM 스택, 11-2 Dev Notes 확정). 프로파일은 video가 import 가능한 이 leaf 모듈에 **아키타입 키**로 두는 것이 병합 의도의 올바른 구현(아키타입이 이미 무드 유도값이므로 무드→프로파일 연결은 성립). `scenario_chain.py:66`의 스테일 주석("Story 11.3 merges per-mood noise profiles into this table")을 실제 배치로 정정할 것.
2. **video.py 카메라 스테이지 — 4개 렌더 분기 전부**: `_camera_shake_filter(hint, duration, *, k, trauma=0.0)` 신설 — 합성 완료된 프레임에 적용하는 후단 스테이지(카메라는 bg+카드를 **함께** 흔든다 — 레이어별 수정 불필요, 기존 카드/패럴랙스 수식 무변경). 체인 형태: 오버스캔 scale(마진 M + micro-zoom 노이즈, `eval=frame` — `_character_zoom_filter` 선례) → `rotate=a='fBm'` → `crop=1920:1080:x='중심+fBm':y='중심+fBm'`. 삽입 지점 4곳: `_compose_shot_clip` 카드 분기(chain 말미)·bg-only 분기(zp_chain 뒤), `_render_scene_fast` 카드 분기(prev_label 뒤, post_label/subtitles **앞**)·bg-only 분기(zp_chain 뒤, post_frag **앞**). **순서 불변식: shake → post-fx → subtitles** — 자막은 스크린-스페이스 UI라 흔들리면 안 되고, 비네트/그레인(7.2)은 렌즈-스페이스라 셰이크 뒤에 와야 한다. 두 경로(fast/multi-clip) 모두 이 순서가 되는지 확인(multi-clip은 pass 2에서 post-fx/자막이 붙으므로 자동 충족). 프로파일이 전부 0(locked/"static")이거나 기능 off면 **빈 문자열 반환 → 스테이지 미부착 → 기존 체인과 byte-identical** (`_motion_scale_filter`의 "" 스킵 관용구). 샷별 위상 탈상관: select_effect가 이미 받는 인덱스(fast: `scene_index`, multi-clip: `scene_index * _EFFECT_INDEX_STRIDE + local_i`)를 `k`로 재사용해 격자 오프셋 — 인접 샷이 같은 곡선을 타지 않는다.
3. **trauma 이벤트 셰이크 — 7.1 스팅어 동기**: `TRAUMA_BY_MOOD` 테이블(camera_path.py, 락스텝 assert vs `MOOD_VALUES` — sound_design.py:12에서 import, video.py와 같은 방향). trauma(t) = trauma₀·max(0, 1−t/τ), 이벤트 진폭 = trauma(t)² × 이벤트 계수, x/y/rot에 가산. **적용 규칙(동기 by construction)**: 씬의 **첫 클립에만**, `sound_design_enabled=True` **그리고** `include_stinger=True`일 때만 — 스팅어 원샷은 씬 세그먼트 t=0에서 재생되므로(sound_design.py `build_sound_design_args` 원샷 입력) 첫 클립 t=0 감쇠 시작이 곧 히트 동기다. `include_stinger=False`(챕터 카드가 스팅어를 가져간 씬, 5.17 AC:7)는 trauma **생략** — 히트가 카드 구간에서 울리므로 씬 셰이크는 오히려 비동기가 된다(이 근거를 독스트링에 기록). 챕터 카드 자체는 흔들지 않는다(텍스트 카드, `_compose_chapter_card` 무변경).
4. **shake 아키타입 실구현 — 11-2 리뷰 LOW 해소**: `_HINT_MAP`의 `"shake": "in-center"`는 유지하되(셰이크 밑에 깔리는 베이스 푸시 — 더 이상 플레이스홀더가 아님) video.py:226-228 주석을 정정. 카메라 스테이지가 shake 전용 프로파일(1–2% + tremor 강 + rot)을 공급하므로 **shake와 push_in의 렌더 체인이 최종적으로 상이**해진다. 11-2 회귀 가드 `test_camera_preferences_first_alternate_renders_distinct`는 green 유지 + 비교 대상을 (EffectSpec, `_camera_shake_filter` 출력) 튜플로 확장해 "렌더 수준 상이"를 직접 고정. `CAMERA_PREFERENCES["escalation"]`의 "Revisit when 11.3 ships a real shake" 주석(scenario_chain.py:70-73) 정정 — 순서 재배열은 선택(현행 유지 가능), 주석 스테일만 금지.
5. **character_motion.py tremble 스펙트럼 교정**: `tremble`의 단일 사인 tremor 항 2개(`TREMBLE_AMP=3.0`px @ `TREMBLE_FREQ=6.0`rad/s x/y)를 2옥타브 fBm tremor 대역으로 교체 — `MotionTerm`에 노이즈 표현(예: `octaves: int = 0` 필드, 0=기존 사인)을 추가하고 `_term_expr`가 camera_path의 fbm 프리미티브로 위임. **총 진폭은 3.0px 유지** → `max_excursion()` 상한과 `CHAR_MAX_W/H`(video.py:168-169) 값이 수치 불변(모션-세이프 박스 회귀 없음 — 테스트로 고정). **sway/breath/pulse/glitch/hold는 무변경** — `test_sway_medium_matches_legacy_sway_bob_constants`(1.9c byte-for-byte)와 glitch의 의도적 스테어케이스(디지털 아티팩트 = 스타일)는 그대로. `MOTION_TABLE_VERSION` "1"→"2" 범프(모듈 주석의 범프 규칙 그대로 — 트레이스 메타데이터 video.py:702가 자동 반영). `test_tremble_is_breath_plus_shake`는 갱신 필요 — 갱신 사유를 테스트 주석에 기록(7.5 교훈).
6. **config 킬스위치**: `camera_noise_enabled: bool = True` (config.py — `sound_design_enabled`/`post_fx_enabled`/`parallax_enabled` L114-123 패턴 그대로, 주석에 Story 11.3 명기). video_node(video.py:1526-1639)에서 읽어 `_compose_scene` → 두 렌더 경로로 스레딩. False → 카메라 스테이지 미부착 = pre-11.3 byte-identical 체인(AC2의 "" 스킵과 같은 경로).
7. **결정론 + resume 하위호환**: 모든 노이즈는 (hint, k, duration, trauma) 순수 함수 — `random` 금지(11-1 sha256-not-hash 교훈: resume된 런은 다른 프로세스). 레거시 체크포인트(`camera_movement=None`/자유텍스트)는 기본 다큐 프로파일 적용 — select_effect의 폴백 철학과 동일하게 어떤 값도 스테이지를 실패시키지 않고, 과거 run의 video retry도 그대로 동작(이미지 자산 캐시 무관 — 렌더 시점 소비, 11-2와 동일). 트레이스 메타데이터(video.py:690-715 `_record_trace`)에 `camera_path` 블록(버전 상수 + camera_noise_enabled) 추가 — 8.8 table_version과 같은 "이 렌더가 왜 달라 보이나" 추적 목적.
8. **회귀 가드 + 라이브 표현식 검증**: 전체 스위트 green(`PYTHONPATH=$PWD/src pytest tests/`). 신규 테스트는 순수 함수 단위(표현식 결정론/구조, 프로파일 락스텝, excursion 상한, "" 스킵, trauma 규칙, 삽입 순서) — 픽셀 비교 없음(11-1 방침). **단, ffmpeg 표현식 문법은 유닛 테스트가 못 잡는 리스크** — 생성된 체인으로 실제 ffmpeg 렌더 1회(작은 PNG, ~2초, GPU 불요) rc==0 확인을 dev 태스크로 필수 수행하고 Debug Log에 증거 기록(5-9 교훈: 증거는 코드 변경 이후 시점). `camera_noise_enabled=False`(또는 locked)에서 기존 필터 체인 문자열이 pre-11.3과 동일함을 고정하는 테스트 포함.

## Tasks / Subtasks

- [x] Task 1: camera_path.py — fBm 프리미티브 + 프로파일 + trauma 테이블 (AC: 1, 3, 7)
  - [x] `fbm_expr(amp, lattice_freq, octaves, offset, t_var="t")` — value-noise 해시(`sin((i+offset)*12.9898)` 계열, 축별 해시 배수 분리 12.9898/78.233 관용구) + smoothstep 보간(`u*u*(3-2*u)`) + persistence 0.5 옥타브 합성, 진폭 정규화. ffmpeg 표현식 유틸: `floor`/`mod`/`st()`/`ld()`(격자 인덱스 재계산 회피), `frac(x)`는 `mod(x,1)` — 문법 확인은 Task 5 라이브 검증에서
  - [x] `CAMERA_NOISE_PROFILES` 시작점(`# ponytail:` 라이브 튜닝 대상 표기, 진폭은 프레임폭 분율): `locked`=전부 0 / `push_in`·`pull_back`·`drift`=다큐 밴드(sway 0.005 @1.0steps/s ×2oct, tremor 0.0008 @10steps/s, rot 0.15°, zoom 0.003) / `shake`=핸드헬드 밴드(sway 0.015 @1.5steps/s ×3oct, tremor 0.002 @10steps/s, rot 0.8°, zoom 0.008). None/자유텍스트/"static" 해석 함수(`noise_profile_for(hint)`): 아키타입 소속 → 해당 프로파일, "static" → locked, 그 외 → 다큐 기본
  - [x] `TRAUMA_BY_MOOD` 시작점(`# ponytail:`): dread 0.5 / clinical 0.25 / escalation 0.8 / revelation 0.6, τ=1.0s, amplitude=trauma²
  - [x] 락스텝 assert 2개(프로파일 키==CAMERA_ARCHETYPES, trauma 키==MOOD_VALUES) + `CAMERA_PATH_VERSION = "1"`
  - [x] excursion 상한 함수(x_px, y_px, rot_rad, zoom) — 옥타브 진폭 합 + trauma 피크, 오버스캔 마진 산출 근거
  - [x] 단위 테스트: 결정론(같은 입력 2회 == 동일 문자열), 락스텝 파라미터라이즈, locked/all-zero → 빈 표현식, 진폭 정규화(옥타브 합 ≤ amp), 문자열에 `random` 부재
- [x] Task 2: video.py 카메라 스테이지 배선 (AC: 2, 6)
  - [x] `_camera_shake_filter(hint, duration, *, k, trauma=0.0)` — 오버스캔 scale(M은 excursion 상한에서 유도) → rotate → crop 체인, all-zero → ""
  - [x] 삽입 4곳: `_compose_shot_clip`(video.py:1037-1063 두 분기), `_render_scene_fast`(video.py:953 카드 분기 prev_label 뒤 / video.py:965·1002 bg-only의 post_frag 앞). diff는 이 구획들로 국소화(8-16 병렬 편집 대비 — 11-1/11-2 관행)
  - [x] `camera_noise_enabled` config 필드 + video_node(L1526-1639)→`_compose_scene`→두 경로 스레딩
  - [x] `k` 배선: fast 경로 `scene_index`, multi-clip 경로 `scene_index * _EFFECT_INDEX_STRIDE + local_i`(video.py:1228과 동일 값)
  - [x] 단위 테스트: 삽입 순서(shake→post→subtitles 문자열 순서 검사), off/locked → pre-11.3 체인 동일성, k 상이 → 표현식 상이
- [x] Task 3: trauma 씬 첫 클립 배선 (AC: 3)
  - [x] `_compose_scene`: 첫 클립(fast 경로 포함)에 `trauma=TRAUMA_BY_MOOD[resolve_mood(mood)]` — `sound_design_enabled and include_stinger`일 때만, 이후 클립은 0
  - [x] 독스트링에 동기-by-construction 근거(스팅어 원샷 t=0)와 include_stinger=False 생략 근거 기록
  - [x] 단위 테스트: 첫 클립만 trauma, 조건 4조합(sound off / stinger off / 둘 다 on / 카드 씬), trauma=0 → 이벤트 항 부재
- [x] Task 4: shake 아키타입 + character_motion tremble (AC: 4, 5)
  - [x] video.py:226-228 플레이스홀더 주석 정정, scenario_chain.py:66·70-73 스테일 주석 정정
  - [x] `test_camera_preferences_first_alternate_renders_distinct`를 (EffectSpec, shake_filter) 튜플 비교로 확장 — shake vs push_in 렌더 상이 고정
  - [x] `MotionTerm`에 노이즈 표현 추가 + `_term_expr` 위임, tremble tremor 2옥타브화(총 3.0px 유지), `MOTION_TABLE_VERSION="2"`
  - [x] 테스트: `CHAR_MAX_W/H` 수치 불변, sway/medium 레거시 byte-for-byte 무수정 통과, tremble 테스트 갱신(사유 주석), glitch 무변경
- [x] Task 5: 라이브 검증 + 전체 회귀 (AC: 7, 8)
  - [x] 생성 체인으로 실제 ffmpeg 렌더 1회(작은 PNG→2s mp4, shake 프로파일+trauma): rc==0 + 출력 존재 — 표현식 문법(st/ld/mod/clip, rotate·crop의 t 지원) 실증, Debug Log에 명령/결과 기록
  - [x] `_record_trace`에 `camera_path` 블록 추가(버전+enabled)
  - [x] `PYTHONPATH=$PWD/src pytest tests/` 전체 green (워크트리 시 PYTHONPATH 필수 — 글로벌 editable install이 메인 트리 src를 가림)
  - [x] ruff 변경 파일 clean

## Dev Notes

### 이 스토리가 존재하는 이유 (리서치 근거)

2026-08-01 품질 리서치 `research/technical-yt-flow-quality-strategy-research-2026-08-01.md` §4.1: 백색잡음 지터는 "broken"으로, coherent(Perlin/fractal) 노이즈는 핸드헬드로 읽힌다(실제 모션은 관성을 가짐 — Roystan). AE `wiggle(freq, amp, octaves)` 기준 모델: subtle handheld ≈ 1Hz, 10–25px@1080p, 2–3옥타브, **position+rotation+slight zoom 동시**, rot ≤1°. 생리학 근거(Gavant et al., IEEE): 손떨림 tremor ~8–12Hz 저진폭 + 자세 동요 파워의 ~99%가 2Hz 미만 → 2대역 구성이 필수고 2–3옥타브 fBm이 1/f 감쇠를 자연 근사. trauma 스칼라(0–1, 시간 감쇠, amplitude=trauma², 채널별 독립 노이즈)는 game-dev 표준 이벤트 셰이크 — **rotational shake가 픽셀당 효과가 가장 큼**. §4.6 우선순위 1번: "~30 lines of Python, kills the 'crude' look". §5.4 현행 진단: "'Shake' = deterministic fixed-amplitude sinusoids ... spectrally wrong (single frequency, no 1/f structure) and identical curve per style".

### 핵심 설계 판정 3건 (epics 원문과 코드 현실의 조정)

1. **"per-frame float 사전 계산 주입"의 실현 형태**: 프레임별 float 테이블을 ffmpeg에 넘길 실용 통로가 없다(수백 프레임 × if-체인은 비현실, sendcmd는 zoompan/crop 표현식과 안 맞음). 올바른 등가물은 **닫힌 형식 ffmpeg 표현식으로서의 value-noise fBm** — Python이 "사전 계산"하는 것은 표현식 계수(옥타브 진폭/격자주파수/오프셋)다. 이는 기존 아키텍처(`_term_expr`/`_overlay_filter`의 t-기반 표현식, `eval=frame`) 그대로의 확장이고, glitch의 해시 스테어케이스(character_motion.py:80-91)가 이미 같은 기법의 비보간판이다. 표현식이 과도하게 길어지면 `st()`/`ld()` 레지스터로 격자 인덱스를 1회 계산해 재사용.
2. **프로파일 배치**: AC1에 기술 — scenario_chain이 아니라 camera_path.py에 아키타입 키로. epics의 "11.2 테이블에 병합"은 의도(무드→모션 문법의 단일 소유)를 취하고 물리 배치는 레이어링을 따른다.
3. **주파수 단위**: 기존 상수는 rad/s(SWAY_FREQ 0.8rad/s ≈ 0.13Hz), 리서치 대역은 Hz. 노이즈 격자주파수는 **steps/s**(GLITCH_STEP_FREQ=4.0 선례와 동일 단위) — sway 0.5–2 steps/s, tremor 8–12 steps/s. 단위를 섞으면 대역이 6.3배 틀어진다. MotionTerm의 노이즈 항 freq 의미 변화를 docstring에 명기할 것.

### 수정 대상 파일 현황

**`src/yt_flow/pipeline/nodes/camera_path.py`** (NEW — 유일한 신규 파일):
- character_motion.py(Story 8.8)와 같은 성격의 leaf: 순수 함수+데이터, no I/O, no LangGraph state. import는 `domain.state`(CAMERA_ARCHETYPES)와 `sound_design`(MOOD_VALUES)만 — 순환 없음(sound_design은 자체 leaf, character_motion이 이 모듈을 import하므로 이 모듈은 character_motion을 import하지 말 것).

**`src/yt_flow/pipeline/nodes/video.py`** (UPDATE — 국소화 필수, 8-16 병렬 편집 경고):
- `_HINT_MAP` L226-228: shake 플레이스홀더 주석 정정(엔트리 자체는 유지 — 셰이크의 베이스 푸시).
- 카메라 스테이지 삽입 4곳: `_compose_shot_clip` L1037-1063(카드 분기 chain_parts 말미 / bg-only `-vf` 문자열), `_render_scene_fast` L953(카드: `[{prev_label}]` 뒤, post_label 앞) / L965·L1002(bg-only: zp_chain 뒤, post_frag 앞).
- `_compose_scene` L1196-1236: 첫 클립 trauma + k 배선(L1228의 `scene_index * _EFFECT_INDEX_STRIDE + local_i` 값 재사용).
- `video_node` L1526-1639: `camera_noise_enabled` 스레딩(기존 s.sound_design_enabled 등과 나란히).
- `_record_trace` L690-715: `camera_path` 블록(8.8/8.9 table_version 블록과 같은 형태).
- **접근 금지**: `_zoompan_filter`/`_overlay_filter`/`_build_card_chain` 내부 수식, CARD_EDGE_FEATHER(11-1), CHAR_MAX_W/H 산식 — 카메라 스테이지는 합성 **뒤에** 붙는 별개 스테이지라 이들 불변이 설계의 핵심 증거다.

**`src/yt_flow/pipeline/nodes/character_motion.py`** (UPDATE — tremble만):
- `MotionTerm`(L22-26)에 노이즈 표현 추가, `_term_expr`(L80-91) 위임 분기, `_STYLE_TERMS["tremble"]`(L64-69)의 tremor 항 교체(총 진폭 3.0px 유지 → `max_excursion()` L118-135 수치 불변), `MOTION_TABLE_VERSION` L19 "1"→"2".
- **불변**: SWAY/BOB/BREATH/PULSE 상수와 항 구성(1.9c byte-for-byte 재현 테스트), glitch 스테어케이스(의도적 디지털 아티팩트).

**`src/yt_flow/config.py`** (UPDATE — 필드 1개): `camera_noise_enabled: bool = True`, L114-123 플래그 군 옆.

**`src/yt_flow/pipeline/nodes/scenario_chain.py`** (UPDATE — 주석 2곳만): L66 "merges into this table" 스테일 정정, L70-73 escalation "Revisit when 11.3" 정정. **코드 무변경** — CAMERA_PREFERENCES 순서 재배열은 하지 않는다(11-2 리뷰가 잡은 escalation 단조는 shake 실구현으로 자연 해소, 재배열은 라이브 튜닝에서 Jay 판단).

**무변경 확인 대상**: `_compose_chapter_card`(카드는 흔들지 않음), sound_design.py(스팅어 입력 구조 그대로 — trauma는 video 쪽에서만 동기), shot_timing.py, scenario 스테이지 전체(이 스토리는 렌더 전용 — 11.2가 배선한 camera_movement 값을 소비만 한다), 사이드카 `_done.json` 캐시 키(렌더 시점 소비라 무관).

### 시스템 무결성 (명시 AC 밖이지만 깨지면 안 되는 것)

- **오버스캔 마진은 by construction**: crop 윈도우가 소스를 벗어나면 ffmpeg이 **런타임에** 실패하거나 가장자리가 깨진다. 마진 M ≥ (x/y excursion 상한 + 회전 코너 변위 ≈ (W/2)·θ_max + micro-zoom 최소치 보상)을 분석적으로 유도하고 테스트로 고정 — 7.3의 "not by eyeball" 원칙. belt-and-suspenders로 crop x/y에 `clip()` 클램프 허용.
- **multi-clip 경계 연속성**: 샷 클립별 독립 노이즈(k 오프셋)라 컷 지점에서 카메라 위치가 점프한다 — 이는 **의도된 동작**(하드 컷은 카메라가 바뀌는 순간, 8.11의 다큐 컷 문법과 정합). 클립 내부 연속성만 보장하면 된다(value noise는 C0 연속).
- **AD-1 레이어 규칙**: 전부 pipeline/nodes + config — services/api 경계 넘는 코드 없음. camera_path는 video/character_motion만이 import.
- **AD-4**: 순수 문자열 빌더 — state 변형 없음.
- **성능**: 표현식 복잡도 증가는 ffmpeg 표현식 평가(프레임당 수십 연산)라 인코딩 대비 무시 가능. 새 스테이지 3개(scale/rotate/crop)는 기존 8000px 슈퍼샘플 zoompan 대비 미미 — 단 오버스캔 scale은 1920 기준 소폭(1+M)이지 8000이 아님을 확인.
- **eval=frame 함정**: `_overlay_filter` docstring이 경고하는 "eval=init에서 t가 NAN" 함정이 scale 스테이지에 그대로 적용 — 명시적 `eval=frame` 필수. rotate/crop은 표현식에 t가 있으면 프레임별 평가되나 **라이브 검증(Task 5)으로 실증**할 것(이 ffmpeg 빌드의 버릇은 11-1 gblur 힙 크래시 전례처럼 문서와 다를 수 있음).

### Previous Story Intelligence (11-2, done)

- TDD red→green을 태스크 단위로 — 11-2는 "index 0에서 폴백과 우연 일치해 가짜 green"을 잡았다(shake 테스트는 k≠0으로 강화). 이 스토리도 k=0 우연 일치를 경계.
- 11-2 리뷰 MEDIUM의 교훈: **아키타입이 다른데 렌더가 같은** 조합이 단조를 재생산한다 — AC4의 렌더-수준 distinctness 가드가 그 재발 방지 장치이고 이 스토리가 그 가드의 비교 차원을 확장한다.
- sprint-status.yaml 동시편집 충돌 상습 — 커밋 시 부분 스테이징으로 대응.
- 전체 스위트 기준선: 1374 passed, 1 skipped(YTFLOW_QWEN_TTS_SMOKE 게이트, 무관).
- 워크트리 작업 시 `PYTHONPATH=$PWD/src` 필수(글로벌 editable install이 메인 트리 src를 가림).

### Git Intelligence

- `ce4bcef`(11.2): domain/state.py CAMERA_ARCHETYPES, scenario_chain CAMERA_PREFERENCES/_resolve_camera_movement/_enforce_camera_variety, video.py _PAN_POOL/select_effect 아키타입 분기 — 이 스토리의 직접 토대.
- `3bd41aa`(11.1): video.py diff 국소화 관행(CARD_EDGE_FEATHER 구획), 파라미터-단위 검증 방침, sha256-not-hash 결정론 교훈 — 전부 이 스토리에 계승.

### Testing

- 위치: `tests/pipeline/nodes/test_camera_path.py`(신규), `test_video.py`(select_effect 구획 L209+ 및 신규 카메라 스테이지 구획), `test_character_motion.py`(tremble/version/excursion).
- 전부 순수 함수 단위(문자열/수치) — 렌더·픽셀 비교 없음. 유일한 예외가 Task 5의 라이브 ffmpeg 스모크 1회(dev 수행, CI 테스트화는 선택 — ffmpeg 의존 테스트 선례가 없으므로 무리하게 fixture화하지 말 것).
- 기존 무수정-통과가 증거인 테스트: `test_sway_medium_matches_legacy_sway_bob_constants`(1.9c), `test_select_effect_*` 전부(EffectSpec 로직 무변경), `test_camera_preferences_*`(11-2). 갱신 필요한 테스트는 `test_tremble_is_breath_plus_shake`뿐이어야 하며 — 그 외가 깨지면 카메라 스테이지가 기존 수식을 침범했다는 신호다.

### Project Structure Notes

- 신규 파일 1개(camera_path.py), 신규 의존성 0 — `ponytail:` opensimplex/noise 도입은 value-noise 품질 부족이 **실측**(라이브 렌더 시청)으로 확인될 때만. DepthFlow는 11.5 스코프 — 이 스토리에서 훅/스캐폴딩 금지(YAGNI; 11.5가 이 모듈의 경로 생성기를 소비할 예정이지만 지금은 ffmpeg 표현식 산출만).
- 프로파일/trauma 수치는 전부 `# ponytail:` 라이브 튜닝 시작점(ZOOM_IN_MAX 1.08→1.15 이력과 같은 반복 스타일) — 리서치 대역 안에서 Jay 시청 판정으로 수렴.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 11.3] — 스토리 원문 ①–④
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#4.1] — fBm/AE wiggle/Gavant 2대역/trauma 모델·수치 대역
- [Source: research §4.6, §5.4] — 우선순위 1번 판정, "spectrally wrong" 현행 진단
- [Source: src/yt_flow/pipeline/nodes/character_motion.py:19-91] — MOTION_TABLE_VERSION 규칙, MotionTerm, glitch 해시 관용구(_term_expr), 상수 군
- [Source: src/yt_flow/pipeline/nodes/video.py:209-262] — _HINT_MAP shake 플레이스홀더, select_effect(무변경 대상)
- [Source: src/yt_flow/pipeline/nodes/video.py:791-1017] — _build_card_chain/_render_scene_fast 체인 형태와 삽입 지점
- [Source: src/yt_flow/pipeline/nodes/video.py:1019-1244] — _compose_shot_clip/_assemble_scene_from_clips/_compose_scene, k 인덱스 합성(L1228)
- [Source: src/yt_flow/pipeline/nodes/video.py:139-193, 690-715] — 7.3 by-construction 마진 계보(CHAR_MAX_W), _record_trace 버전 블록
- [Source: src/yt_flow/pipeline/nodes/sound_design.py:12-64] — MOOD_VALUES, 스팅어 원샷 t=0 재생 구조(trauma 동기 근거)
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:61-80] — CAMERA_PREFERENCES + 정정할 스테일 주석 2곳
- [Source: src/yt_flow/config.py:114-123, 151-163] — 플래그 군 패턴(camera_noise_enabled 배치처)
- [Source: _bmad-output/implementation-artifacts/11-2-camera-motion-archetype-wiring.md] — 직전 스토리: 레이어링 판정(video↛scenario_chain), 리뷰 MEDIUM/LOW, distinctness 가드
- [Source: _bmad-output/implementation-artifacts/sprint-status.yaml:186-192] — 착수 순서(8-16 병렬 주의, 11-5가 11-3에 의존)

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- **Task 5 라이브 ffmpeg 표현식 검증 (AC:8)** — 2026-08-01:
  - 입력: `ffmpeg -f lavfi -i testsrc2=size=1920x1080:rate=1 -frames:v 1 src.png`
  - 체인: `_camera_shake_filter("shake", 2.0, k=1, trauma=0.8)` 실출력(오버스캔 scale factor `1.18032` = `1+overscan_margin("shake", trauma=0.8)`, scale `eval=frame` → `rotate=a='fBm+trauma'` → `crop=1920:1080:x/y='clip(중심+fBm+trauma)'`)
  - 실행: `ffmpeg -y -loop 1 -framerate 30 -i src.png -vf <chain> -t 2 -pix_fmt yuv420p shake_trauma.mp4` → **rc=0**, 출력 1920×1080/60프레임/2.000s (ffprobe 확인)
  - 프레임별 t 평가 실증: 프레임 0/15/45 추출 md5 3종 모두 상이(b9eff42c…/10c9f0a8…/19d95a47…) — rotate/crop/scale 전부 per-frame 평가, eval=init NAN 함정 없음
- 전체 스위트: `PYTHONPATH=$PWD/src pytest tests/` → **1433 passed, 1 skipped**(YTFLOW_QWEN_TTS_SMOKE 게이트, 무관), 4m40s. 기준선 1374+1 대비 +59 신규.
- ruff: 변경 10개 파일 전부 clean.

### Completion Notes List

- **AC1**: `camera_path.py` 신설 — `fbm_expr`(해시 격자 + smoothstep 보간, persistence 0.5, 옥타브 합==amp 정규화), `CAMERA_NOISE_PROFILES`(다큐/locked/shake 3계층, 락스텝 assert), `noise_profile_for`(static→locked, None/자유텍스트→다큐 폴백), `max_excursion`/`overscan_margin`(분석적 by-construction 상한 + 짝수차원 슬랙 2px). st()/ld() 레지스터는 의도적 미사용 — ffmpeg eval 트리의 피연산자 평가순서 미보장이 이식성 함정이라 인라인 재계산 선택(`# ponytail:` 주석 기록).
- **AC2**: `_camera_shake_filter` — scale(eval=frame, micro-zoom 노이즈 가산)→rotate→crop(clip() 클램프) 체인, all-zero→"" 미부착. 삽입 4곳(fast 카드/bg-only, shot-clip 카드/bg-only) 완료, shake→post-fx→subtitles 순서 불변식 테스트로 고정. k 배선: fast=scene_index, multi-clip=scene_index*stride+local_i(L1228 값 재사용).
- **AC3**: trauma는 `_compose_scene`에서 첫 클립에만, `camera_noise_enabled and sound_design_enabled and include_stinger`일 때만 — 동기-by-construction 근거와 include_stinger=False 생략 근거를 docstring에 기록. 조건 4조합 파라미터라이즈 테스트.
- **AC4**: `_HINT_MAP` shake 주석 정정(베이스 푸시 유지), scenario_chain L66/L70-73 스테일 주석 정정(코드 무변경). `test_camera_preferences_first_alternate_renders_distinct`를 (EffectSpec, shake_filter) 튜플 비교로 확장 + `test_shake_and_push_in_render_distinct_chains` 신규.
- **AC5**: `MotionTerm.octaves` 필드 추가(0=레거시 사인), `_term_expr`가 camera_path.fbm_expr로 위임, tremble tremor 2옥타브 fBm(총 3.0px 유지, freq 단위 rad/s→steps/s 전환 docstring 명기). `MOTION_TABLE_VERSION` "1"→"2". `max_excursion()`==(18.0,16.5,1.075) 수치 불변 + CHAR_MAX_W/H 산식 회귀 테스트. sway/breath/pulse/glitch byte-for-byte 무변경(1.9c 레거시 테스트 무수정 통과).
- **AC6**: `camera_noise_enabled: bool = True`(config.py 플래그 군), video_node→`_compose_scene`→두 렌더 경로 스레딩. False→체인 pre-11.3 동일성 테스트(`test_render_fast_empty_shake_leaves_chain_unchanged`, args 완전 일치 비교).
- **AC7**: 전 노이즈가 (hint, k, trauma) 순수 함수, `random` 부재 테스트. 레거시 체크포인트(None/자유텍스트)→다큐 폴백. `_record_trace`에 `camera_path{version, enabled}` 블록(8.8 관용구).
- **AC8**: 위 Debug Log — 라이브 렌더 rc=0 + 프레임별 평가 실증, 전체 스위트 green, ruff clean.
- 설계 판정(스토리 Dev Notes 3건 그대로): 프로파일은 camera_path.py에 아키타입 키 배치(레이어링), per-frame float 주입의 등가물은 닫힌 형식 ffmpeg 표현식, 격자주파수 단위는 steps/s.

### File List

- `src/yt_flow/pipeline/nodes/camera_path.py` (NEW)
- `src/yt_flow/pipeline/nodes/video.py`
- `src/yt_flow/pipeline/nodes/character_motion.py`
- `src/yt_flow/pipeline/nodes/scenario_chain.py` (주석 2곳만)
- `src/yt_flow/config.py`
- `tests/pipeline/nodes/test_camera_path.py` (NEW)
- `tests/pipeline/nodes/test_video.py`
- `tests/pipeline/nodes/test_character_motion.py`
- `tests/pipeline/nodes/test_scenario_chain.py`
- `tests/pipeline/nodes/test_video_harmonization.py` (픽스처 필드 1줄)

## Senior Developer Review (AI)

**Reviewer:** Jay (자동 리뷰 세션) — 2026-08-01
**Outcome:** Approve — CRITICAL 0 / HIGH 0 / MEDIUM 0 / LOW 3, 자동수정 대상 없음

**검증 방법(주장 아닌 재현):**
- git vs File List: 완전 일치(불일치 0 — `_bmad-output` 자동화 파일 2건은 리뷰 제외 대상).
- AC 8건 전부 코드 실물 대조: fbm_expr/프로파일/락스텝 assert 2개(camera_path.py:84,96), 4개 렌더 분기 삽입(video.py:1012,1024,1061 + `_compose_shot_clip` 카드/bg-only), shake→post→subtitles 순서, trauma 첫-클립/조건 게이트(video.py `_compose_scene`), MOTION_TABLE_VERSION "2" + max_excursion (18.0,16.5,1.075) 불변, config 킬스위치, `_record_trace` camera_path 블록, 스테일 주석 3곳 정정 — 전부 확인.
- 전체 스위트 재실행: **1433 passed, 1 skipped** (Dev 기록과 일치). ruff 변경 10개 파일 clean.
- 라이브 ffmpeg **독립 재검증**: `_camera_shake_filter` 실출력으로 shake+trauma(-vf), push_in, locked+trauma 렌더 각 rc=0. 추가로 Dev가 안 했던 **filter_complex 임베드 형태**(`[cmp]{shake}[out]` — 카드 분기 실제 형상)도 rc=0 — 따옴표/콤마 이스케이프가 그래프 파서에서도 성립.
- 오버스캔 마진 수식 독립 검산: 회전 사각형 내부성 조건의 정확 하한은 M ≥ 1.78θ(코너 (960,540) 기준), 구현의 corner_r·θ/(h/2) = 2.04θ로 보수적 상회 + xy 변위·zoom trough·2px 슬랙 합산 — by construction 성립.

**LOW 3건 (기록만, 코드 무변경):**
1. `video_node` 예외 경로 `_record_trace`(video.py:1903)가 `camera_noise_enabled` 미전달 → 에러 트레이스의 camera_path 블록이 항상 `enabled: false`. `s = _settings()`가 try 내부라 except에서 참조 불가 — 기존 에러-경로 최소화 관용구(composite_harmonization_tier 등 전 피처 플래그 동일)와 일관되므로 이 플래그만 고치는 게 오히려 비일관. 수정 안 함.
2. `test_render_fast_empty_shake_leaves_chain_unchanged`는 신규 코드의 shake=""/미전달 두 호출을 자기-비교 — pre-11.3 리터럴 고정은 아님. 다만 기존 체인-고정 테스트 전부가 무수정 통과하는 것이 실질적 byte-identity 증거라 보강 불요.
3. AC1 자구("x_px, y_px, rot_rad, zoom")와 달리 `max_excursion`은 `(xy_frac_of_width, rot_rad, zoom)` 3-튜플 — x/y가 동일 진폭(프로파일 단위가 프레임폭 분율)이라 기능 등가, docstring/테스트에 단위 명기됨.

## Change Log

- 2026-08-01: Story 11.3 구현 완료 — 2대역 fBm 카메라 노이즈(camera_path.py 신설) + video.py 4분기 카메라 스테이지 + 스팅어 동기 trauma + shake 아키타입 실구현 + tremble fBm 교정(MOTION_TABLE_VERSION 2) + camera_noise_enabled 킬스위치 + 트레이스 메타데이터. 전체 스위트 1433 green, 라이브 ffmpeg 표현식 검증 rc=0. Status → review.
- 2026-08-01: 시니어 개발자 리뷰(AI) — Approve. CRITICAL/HIGH/MEDIUM 0, LOW 3 기록(에러-경로 트레이스 플래그, 자기-비교 테스트, AC1 시그니처 자구). 스위트 1433 green 재현 + 라이브 ffmpeg 독립 재검증(filter_complex 임베드 포함) + 오버스캔 마진 수식 검산. Status → done.
