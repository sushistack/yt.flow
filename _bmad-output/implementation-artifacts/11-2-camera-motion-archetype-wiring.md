---
baseline_commit: 3bd41aacb2e3749612e6db01a0fb71cc16085a76
---

# Story 11.2: 카메라 모션 아키타입 — 무드 주도 선택 + `camera_movement` 배선

Status: done

## Story

As a **yt.flow 운영자 (Jay)**,
I want **`camera_movement`가 하드코딩 `None`(scenario_chain.py:1079) 대신 닫힌 카메라 아키타입 enum으로 채워지고, 기본값은 무드→아키타입 결정론 매핑으로 산출되며, 연속 샷 동일 아키타입이 결정론적 validator로 금지**되도록,
so that **카메라 방향이 콘텐츠와 무관한 10개 인덱스 라운드로빈이 아니라 씬의 무드가 요구하는 모션 문법(push-in=dread, locked=clinical 등)을 따르고, "모든 샷이 같은 모션"이라는 조잡함의 대표 신호가 사라진다**.

## Acceptance Criteria

1. **닫힌 아키타입 enum**: `CAMERA_ARCHETYPES = ("push_in", "pull_back", "drift", "locked", "shake")` 상수를 `domain/state.py`에 신설(ShotData.camera_movement 필드 옆 — scenario_chain과 video가 순환 import 없이 공유하는 유일한 공통 하위 모듈). `ShotData.camera_movement` 타입은 `str | None` 유지(TypedDict — 레거시 체크포인트의 None/자유텍스트가 계속 유효해야 함), 필드 주석에 "one of CAMERA_ARCHETYPES (Story 11.2) | legacy free-text hint | None" 명시. LLM 자유 텍스트를 새로 만들어내는 경로는 없다.
2. **무드→아키타입 결정론 매핑**: `build_scenes`가 `camera_movement=None` 하드코딩 대신 매핑 테이블로 값을 채운다. 테이블 키는 **실제 무드 택소노미 `MOOD_VALUES = ("dread", "clinical", "escalation", "revelation")`** (sound_design.py:12 — epics 원문의 tension/isolation/panic 등 예시어는 리서치의 서술 어휘일 뿐 택소노미가 아님). `assert set(테이블) == set(MOOD_VALUES)` 락스텝 가드 필수(color_grade.py:26 / composite_harmonization.py:56과 동일한 7.2 KeyError 불변식 패턴). 매핑은 순수 결정론 — LLM 호출 없음, 같은 입력이면 항상 같은 출력.
3. **LLM 오버라이드 채널**: `prompts/scenario/visual_breakdown.md`에 선택적 `camera_movement` 필드를 추가(닫힌 어휘 = CAMERA_ARCHETYPES, "무드 기본값에서 벗어나야 할 비트에서만 지정, 그 외 생략" 지침 — `location_key`의 closed-vocabulary 서술 스타일 재사용). 파싱은 8.8 관용 패턴: 값이 유효하면 채택, 없거나 무효면 무드 매핑 적용 + 무효 시 warning 로그(resolve_mood 철학 — 어떤 위반도 스테이지를 실패시키지 않음). **프롬프트 변경은 PROMPT_POLICY 준수**: repo 파일이 원본, `migrate_prompts.py`로 시딩, production 승격 판단은 Jay 몫(8-12에서 eval_prompts.py에 AI 세션 차단 가드 추가됨 — dev 에이전트가 승격을 시도하지 않는다). 승격 전에도 기능은 완전 동작(매핑이 기본값을 채우므로 오버라이드 채널만 조용할 뿐).
4. **연속 샷 동일 아키타입 금지 validator**: `scenario_chain.py` 내부 순수 함수 — 한 씬 안에서 인접 샷 둘이 같은 `camera_movement` 값이면 뒤 샷을 해당 씬 무드의 대안 아키타입(선호 순서 테이블의 다음 항목 중 직전 값과 다른 첫 것)으로 즉시 재배정. LLM 재호출 없음(6-7/6-11/8.9 `_repair_movement` 결정론 repair 계보 — **8.18은 아직 backlog라 참조할 코드가 없음**, 패턴만 같음). LLM 오버라이드도 규칙을 어기면 동일하게 재배정된다(금지는 절대 규칙). epics 원문의 "아키타입+**방향**" 금지는 아키타입 수준 금지로 충족된다 — 방향 개념을 갖는 아키타입은 drift뿐이고 drift-drift 인접 자체가 금지되므로 "같은 아키타입+같은 방향" 조합이 성립할 수 없음(이 논증을 독스트링에 기록). 씬 경계는 검사하지 않는다 — 씬 사이는 5.16 dip-to-black 액트 브레이크로 시각 연속성이 끊기므로 씬 내부만으로 충분(이 근거를 독스트링에 기록).
5. **video.py `select_effect` 아키타입 1급 지원**: `push_in`/`pull_back`은 기존 `_HINT_MAP`에 이미 존재(무변경). 신규 3개만 추가 — `locked` → 기존 `"static"` 분기 재사용(1.0→1.005 마이크로 드리프트), `drift` → `_DIRECTION_POOL`의 pan-* 부분집합에서 인덱스 회전으로 방향 결정(기존 zoom 관용구 유지), `shake` → 11.2에서는 in-center 푸시 플레이스홀더 + `# ponytail:` 주석으로 11.3(fBm/trauma 셰이크)이 교체함을 명시. video.py diff는 `select_effect`/`_HINT_MAP` 주변으로 국소화(8-16이 video.py를 병렬 편집할 수 있음).
6. **폴백 강등 + 하위호환**: `_DIRECTION_POOL` 인덱스 라운드로빈과 기존 자유텍스트 `_HINT_MAP` 힌트는 삭제하지 않고 **폴백으로 유지** — `camera_movement`가 None(레거시 체크포인트 resume, 진행 중 run)이거나 미인식 값이면 기존 동작 그대로. `run_service.py:100`(SSE/API 직렬화)과 `character_service.py:1199`(`shot.get("camera_movement") or ""`)는 str 값을 그대로 수용하므로 무변경.
7. **회귀 가드**: 전체 스위트 green. 신규 테스트는 순수 함수 단위(매핑 전역성, validator 성질, 오버라이드 파싱, select_effect 스펙) — 렌더/픽셀 비교 없음. `camera_movement=None` 픽스처를 쓰는 기존 테스트 다수(test_video.py, test_shot_timing.py, test_tts.py, test_image.py 등)는 폴백 보존 덕에 무변경이어야 하며, 변경이 필요해지면 그 자체가 AC 6 위반 신호다.

## Tasks / Subtasks

- [x] Task 1: 아키타입 enum + 매핑 테이블 (AC: 1, 2)
  - [x] `domain/state.py`에 `CAMERA_ARCHETYPES` 튜플 추가, `ShotData.camera_movement` 주석 갱신
  - [x] `scenario_chain.py`에 무드→선호순서 테이블 추가 — 시작점(라이브 튜닝 대상, `# ponytail:` 표기): `dread: (push_in, drift, locked)`, `clinical: (locked, drift, pull_back)`, `escalation: (shake, push_in, drift)`, `revelation: (push_in, pull_back, drift)` — 첫 항목이 기본값, 나머지가 validator 재배정 순서. 5개 아키타입 전부 어느 경로로든 도달 가능해야 함
  - [x] `assert set(테이블) == set(MOOD_VALUES)` 락스텝 가드(모듈 로드 시)
  - [x] 단위 테스트: 전역성(파라미터라이즈 `MOOD_VALUES`), 무드별 기본값, 값이 전부 CAMERA_ARCHETYPES 소속
- [x] Task 2: build_scenes 배선 + LLM 오버라이드 파싱 (AC: 2, 3)
  - [x] `build_scenes`의 `camera_movement=None`(scenario_chain.py:1079)을 "raw_shot의 유효 오버라이드 ?? 무드 매핑 기본값"으로 교체 — mood는 shots 루프 앞에서 이미 확정돼 있음(scenario_chain.py:1053)
  - [x] 오버라이드 파싱: `raw_shot.get("camera_movement")`를 CAMERA_ARCHETYPES 대조(strip/lower — `_normalize_enum` 관용구), 무효면 warning 로그 + 매핑 폴백. visual_breakdown parse(scenario_chain.py:794-818)는 shot dict를 통과시키므로 파서 수정 불필요
  - [x] 단위 테스트: 오버라이드 유효/무효/부재 3케이스, 무효 시 warning 로그 발생
- [x] Task 3: 연속 샷 금지 validator (AC: 4)
  - [x] 순수 함수(예: `_enforce_camera_variety(shots, mood)`) — build_scenes의 씬별 shots 조립 완료 직후 호출. 인접 동일 값 → 뒤 샷을 선호 순서에서 직전 값과 다른 첫 항목으로 재배정, 재배정 로그(info 수준 — 위반이 아니라 정상 동작)
  - [x] 독스트링에 씬-경계 미검사 근거(5.16 dip-to-black) + 8.9 `_repair_movement` 계보 기록
  - [x] 단위 테스트: 재배정 후 인접 중복 부재(성질 검사), 결정론(같은 입력 2회 → 동일 출력), LLM 오버라이드도 재배정됨, 단일 샷 씬 무해
- [x] Task 4: select_effect 아키타입 지원 (AC: 5, 6)
  - [x] `locked`을 `"static"` 분기에 합류, `drift` pan-부분집합 회전, `shake` 플레이스홀더(+`# ponytail:` 11.3 교체 예정) — `push_in`/`pull_back`은 `_HINT_MAP`에 이미 있음을 테스트로 고정
  - [x] 폴백(라운드로빈/자유텍스트/`static`) 경로 무변경 확인 — 기존 select_effect 테스트(test_video.py:209-247 구획) 전부 그대로 통과해야 함
  - [x] 신규 테스트: 아키타입 5종 각각의 EffectSpec(방향/줌 방향), None → 라운드로빈 유지, 미인식 문자열 → 라운드로빈 유지
- [x] Task 5: visual_breakdown 프롬프트 확장 (AC: 3)
  - [x] `prompts/scenario/visual_breakdown.md`에 `### camera_movement (Optional)` 절 추가 — 닫힌 어휘 5종, 무드 기본값 존재 명시, "비트가 요구할 때만 지정" 지침, YAML 예시 1곳에 필드 시연
  - [x] `migrate_prompts.py`로 시딩(라벨은 PROMPT_POLICY 현행 절차 준수), production 승격은 **하지 않고** 스토리 노트에 Jay 판단 항목으로 기록
- [x] Task 6: 전체 검증 (AC: 6, 7)
  - [x] `PYTHONPATH=$PWD/src pytest tests/` 전체 green (워크트리 작업 시 PYTHONPATH 필수 — 글로벌 editable install이 메인 트리 src를 가림)
  - [x] `camera_movement=None` 기존 픽스처 테스트들이 무변경으로 통과함을 확인(AC 6의 하위호환 증거)
  - [x] build_scenes 기존 테스트 중 ShotData 전체-dict 동등 비교가 있으면 새 필드 값에 맞게 갱신(갱신 사유를 테스트 주석에 기록 — 7.5 교훈: 체크박스 아닌 실코드 검증)

## Dev Notes

### 이 스토리가 존재하는 이유 (리서치 근거)

2026-08-01 품질 리서치 `research/technical-yt-flow-quality-strategy-research-2026-08-01.md` §4.4·§5.1: "모션-무드 문법"(slow push-in=dread/tension/revelation, pull-back=isolation/aftermath, lateral drift=calm exposition, locked=clinical/oppressive, shake=panic/breach)은 다큐/호러 업계 관행 수렴이고, **"모든 샷이 같은 모션"이 조잡한 슬라이드쇼의 대표 신호**. 현재 코드는 LLM의 카메라 의도가 video에 도달할 통로 자체가 없음(§5.1 "hardcoded None — the LLM's camera intent never reaches video"). 이 스토리는 통로(배선) + 결정론 기본값 + 다양성 강제를 만든다. **후속 결합**: 11.3이 무드별 노이즈 프로파일(진폭/주파수)을 이 스토리의 아키타입 테이블에 병합할 예정 — 지금 스캐폴딩하지 말 것(YAGNI), 테이블을 찾기 쉬운 모듈 상수로만 유지하면 충분.

### 핵심 발견: epics 원문과 실제 택소노미의 불일치

epics.md Story 11.2 원문은 `push_in(dread/tension/revelation)` 식으로 6+개 무드 어휘를 나열하지만, **실제 Epic 7 택소노미는 4값뿐**: `MOOD_VALUES = ("dread", "clinical", "escalation", "revelation")` (sound_design.py:12, 7.1이 소유). tension/isolation/aftermath/exposition/calm/oppressive/panic/breach는 리서치 §4.4의 서술 어휘로, 매핑 테이블의 키가 될 수 없다. **매핑은 4키 → 아키타입 선호순서**로 구현하고, 5개 아키타입 도달성은 선호순서의 대안 항목 + LLM 오버라이드로 확보한다. 무드는 씬 단위(SceneState.mood)이고 카메라는 샷 단위 — 같은 씬의 샷들은 같은 기본값에서 출발하되 validator가 인접 중복을 대안으로 흩뜨린다(이것이 의도된 다양성 메커니즘).

### 수정 대상 파일 현황

**`src/yt_flow/pipeline/nodes/scenario_chain.py`** (UPDATE — 주 작업장):
- L1079: `camera_movement=None,  # yt.pipe's visual_breakdown has no equivalent field` — 교체 지점. `build_scenes(writing, visual_by_scene, structure)`는 순수 함수, mood는 L1048-1053에서 `resolve_mood`로 확정(structure 씬에서만 취득, MOOD_VALUES 밖이면 warning + DEFAULT_MOOD).
- 재사용할 기존 관용구: `_normalize_enum(raw, valid, fallback)`(L80-84), `_parse_motion_field`의 "absent stays absent / present-but-invalid normalizes" 철학(L87-96, 8.8), `_repair_movement` 결정론 repair 테이블(L99-138, 8.9 — 이 스토리 validator의 직계 선례).
- **네임스페이스 주의**: `_repair_movement`의 `"drift"`는 **캐스트 movement_mode** 값(8.9)이고 이 스토리의 `"drift"`는 **카메라 아키타입** — 이름이 겹칠 뿐 무관한 도메인. validator/매핑 코드가 `_VALID_MOVEMENT_MODES` 계열과 섞이지 않게 명명 구분(예: `CAMERA_` 접두).
- visual_breakdown parse(L794-818)는 필수 필드만 검증하고 shot dict를 통과시킴 — LLM이 `camera_movement` 키를 내면 build_scenes의 `raw_shot`에 그대로 도착. 파서 수정 불필요.
- import: `MOOD_VALUES, resolve_mood`는 이미 import돼 있음(L37). `CAMERA_ARCHETYPES`는 domain.state에서 추가 import(이미 ShotData 등을 import 중이라 순환 없음).

**`src/yt_flow/domain/state.py`** (UPDATE — 상수 1개 + 주석):
- L86-90: `ShotData.camera_movement: str | None`. 타입 변경 금지(Literal화 금지) — 레거시 체크포인트의 None/자유텍스트("zoom in" 등, tests/services/test_character_angle_selector.py:536이 실사용 증거)가 계속 유효해야 함. `tests/domain/test_state_imports.py:17`이 키 목록을 고정하므로 필드 추가/삭제 없음 확인.
- `CAMERA_ARCHETYPES`를 여기 두는 근거: scenario_chain과 video 둘 다 이미 domain.state를 import하고, 서로는 import하지 않음(scenario_chain은 LLM 스택을 끌고 들어와 video가 import하기엔 무거움). MOOD_VALUES가 sound_design(leaf)에 사는 것과 같은 배치 논리.

**`src/yt_flow/pipeline/nodes/video.py`** (UPDATE — select_effect 구획만, 국소화 필수):
- `_HINT_MAP`(L211-228): `"push_in" → "in-center"`, `"pull_back" → "out-center"` **이미 존재** — 두 아키타입은 코드 무변경으로 동작. 이 우연의 정합을 테스트로 고정할 것.
- `select_effect`(L232-252): `hint == "static"` 분기(L240-242)에 `locked` 합류. `drift`는 pan-* 부분집합(예: `[d for d in _DIRECTION_POOL if d.startswith("pan-")]`)에서 `scene_index % len(부분집합)` 회전 — 8.11 경로는 scene_index 자리에 `scene_index * _EFFECT_INDEX_STRIDE + local_i`(L1218, 소수 97)를 넘기므로 샷마다 다른 인덱스가 이미 공급됨. `shake`는 in-center 푸시 플레이스홀더(신규 줌 상수 발명 금지 — 기존 ZOOM_IN_MAX 재사용, 11.3이 fBm/trauma로 교체).
- 폴백 라운드로빈(L246-247)과 EffectSpec 산출(L249-252)은 무변경.
- **동시 편집 경고**: 8-16(compositing_service 신설 + video.py 편집 가능성)과 병렬 진행될 수 있음 — 11-1이 그랬듯 video.py diff를 한 구획으로 국소화. sprint-status.yaml 동시편집 충돌 전례 다수(부분 스테이징으로 대응).

**`prompts/scenario/visual_breakdown.md`** (UPDATE — 프롬프트):
- 현재 camera 관련은 `camera_type`뿐(L213-224: 7값 닫힌 어휘 + "Vary between consecutive shots" 지침). `camera_movement` 절은 `location_key`(L204-211)의 closed-vocabulary 서술 스타일을 따를 것: 닫힌 어휘 명시, "미지정 시 무드 기본값 적용" 안내, 무효 값은 버려짐 경고.
- **PROMPT_POLICY(docs/PROMPT_POLICY.md)**: repo 파일이 원본(rule 1), 라벨은 production/candidate 2종뿐, UI 직접 편집 금지. 시딩은 `uv run python scripts/migrate_prompts.py --label candidate --source prompts`. production 승격은 Jay 판단(5-17 선례: 프롬프트 승격 Jay에게 이관 / 8-12: AI 세션의 eval_prompts.py 실행 차단 가드 존재). **승격 전에도 이 스토리의 가치는 온전** — production 프롬프트가 camera_movement를 안 내면 모든 샷이 무드 매핑 기본값 + validator 산포로 동작.

**무변경 확인 대상 (건드리지 말 것)**:
- `run_service.py:100` — SSE 페이로드에 `sh["camera_movement"]` 직렬화: str 아키타입 값 그대로 통과.
- `character_service.py:1199` — `shot.get("camera_movement") or ""`: 동일.
- `_zoompan_filter`/`_compose_shot_clip`/`_build_card_chain` — EffectSpec 소비부는 스펙 형태가 불변이므로 무관. 11-1이 방금 `CARD_EDGE_FEATHER`를 넣은 구획이니 접근 금지.

### 시스템 무결성 (명시 AC 밖이지만 깨지면 안 되는 것)

- **resume 하위호환**: 진행 중/과거 run의 체크포인트에는 `camera_movement=None`이 저장돼 있고, video_node retry 시 그 값으로 `select_effect`가 다시 불린다 — 폴백 라운드로빈이 반드시 살아 있어야 함(AC 6). 이 스토리는 image_node 사이드카(11-1) 같은 캐시 무효화가 **없다** — camera_movement는 렌더 시점 소비라 기존 이미지 자산과 무관.
- **AD-4(입력 state 비변형)**: build_scenes는 신규 ShotData를 생성하는 쪽이라 해당 없음. validator는 자기가 만든 shots 리스트를 조작하므로 안전 — 단 외부에서 받은 dict를 제자리 수정하는 형태로 구현하지 말 것.
- **AD-1 레이어 규칙**: 전부 pipeline/nodes + domain 내부 — services/api 경계를 넘는 코드 없음.
- **결정론**: 매핑·validator·drift 방향 회전 모두 (mood, 샷 위치)의 순수 함수 — `random` 금지(11-1의 sha256-not-hash 교훈과 같은 계열: resume된 런은 다른 프로세스).
- **scenario 골든셋/eval**: eval judge는 나레이션 텍스트만 채점(리서치 §5.1) — camera_movement 추가가 골든셋 점수에 영향 없음. 단 visual_breakdown 프롬프트 변경은 6.2 골든셋 캐시(6-13)와 무관함을 전제로 하되, 프롬프트 시딩 후 스모크로 scenario 스테이지가 정상 파싱되는지 확인.

### Testing

- 프레임워크: pytest + pytest-asyncio(기존 그대로). 위치: `tests/pipeline/nodes/test_scenario_chain.py`(매핑/validator/오버라이드), `tests/pipeline/nodes/test_video.py`(select_effect — L209-247의 기존 `test_select_effect_*` 패턴 그대로 확장), `tests/domain/test_state_imports.py`(키 목록 불변 확인).
- 신규 테스트는 전부 순수 함수 단위 — LLM 호출/렌더 없음. `MOOD_VALUES` 파라미터라이즈는 test_color_grade.py:9 패턴 재사용.
- 기존 `camera_movement=None` 픽스처(test_video.py:83, test_shot_timing.py:20, test_tts.py:47, test_image.py:54, test_stub_profile_smoke.py:92, test_run_service_gate.py:150, test_composite_harmonization.py:254)는 **무변경 통과가 AC 6의 증거** — 이들이 깨지면 폴백 강등이 잘못된 것.
- 라이브 검증(선택): 스텁 아닌 실제 scenario 1회 돌려 shots의 camera_movement 분포 확인은 비용이 커서 필수 아님 — 순수 함수 테스트로 충분(11-1 AC7과 같은 "파라미터 단위 검증" 방침).

### Project Structure Notes

- 신규 파일 없음, 신규 의존성 없음. Ponytail 래더 4-5단: 기존 enum/repair 관용구 재사용 + 상수 테이블 + 분기 몇 줄. 매핑 테이블은 튜닝 시작점이므로 `# ponytail:` 표기(ZOOM_IN_MAX 1.08→1.15 이력과 같은 라이브 반복 스타일).
- validator를 서비스로 분리하지 않는다(8-18 스프린트 노트의 "scenario_chain.py 내부 순수 함수(서비스 분리 안 함)" 방침 공유).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 11.2] — 스토리 원문 ①–④
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#4.4] — 모션-무드 문법, "never two consecutive shots with same archetype+direction", 아키타입 4–6개 로테이션
- [Source: research §5.1] — "camera_movement hardcoded None — the LLM's camera intent never reaches video"
- [Source: src/yt_flow/pipeline/nodes/sound_design.py:12-38] — MOOD_VALUES 4값 + resolve_mood(택소노미 소유자 = 7.1)
- [Source: src/yt_flow/pipeline/nodes/color_grade.py:24-26, composite_harmonization.py:54-56] — 무드-키 dict 락스텝 assert 불변식(7.2)
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:80-138] — `_normalize_enum`/`_parse_motion_field`(8.8)/`_repair_movement`(8.9) 결정론 repair 선례
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:1037-1108] — build_scenes 현행(mood 확정 L1053, 교체 지점 L1079)
- [Source: src/yt_flow/pipeline/nodes/video.py:98-110, 211-252, 1211-1219] — _DIRECTION_POOL, _HINT_MAP(push_in/pull_back 기존재), select_effect, _EFFECT_INDEX_STRIDE 인덱스 합성
- [Source: docs/PROMPT_POLICY.md] — repo 원본, candidate 시딩, production 승격 절차(Jay)
- [Source: _bmad-output/implementation-artifacts/sprint-status.yaml:186-193] — 착수 순서(11-2는 8-16과 병렬 가능, video.py 동시편집 주의), 11-3이 아키타입 테이블에 노이즈 프로파일 병합 예정
- [Source: _bmad-output/implementation-artifacts/11-1-image-gen-param-hardening.md#Dev Notes] — 직전 스토리: video.py diff 국소화 관행, PYTHONPATH 워크트리 함정, 파라미터-단위 검증 방침

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- TDD red→green 각 태스크 확인: Task1 ImportError → 12 passed; Task2 4 failed → green; Task3 7 failed → green; Task4 3 failed → green (shake 테스트는 index 0에서 라운드로빈 폴백과 우연 일치해 통과했음을 발견, scene_index=1로 강화해 진짜 RED 확보 후 구현)
- 전체 스위트: `PYTHONPATH=$PWD/src pytest tests/` → **1374 passed, 1 skipped** (skip은 기존 YTFLOW_QWEN_TTS_SMOKE 게이트, 무관). ruff 변경 파일 전부 clean
- 프롬프트 시딩: `uv run python scripts/migrate_prompts.py --label candidate --source prompts` → `scenario/visual_breakdown` created. 부수 관찰: `scenario/writing`도 created — 5-22에서 커밋된 repo 파일 대비 candidate 라벨이 스테일했던 것을 스크립트가 동기화(repo-원본 정책상 정상)

### Completion Notes List

- **AC1**: `CAMERA_ARCHETYPES` 5값 튜플을 `domain/state.py`에 신설, `ShotData.camera_movement` 주석에 "one of CAMERA_ARCHETYPES (Story 11.2) | legacy free-text hint | None" 명시. 타입은 `str | None` 유지 — `test_state_imports.py` 키 목록 무변경 통과.
- **AC2**: `CAMERA_PREFERENCES` 4무드→선호순서 테이블(`# ponytail:` 튜닝 시작점 표기) + 모듈 로드 시 락스텝 assert 2개(키==MOOD_VALUES, 값 도달성==CAMERA_ARCHETYPES 전체). 순수 결정론.
- **AC3**: `_resolve_camera_movement(raw, mood)` — 유효 오버라이드 채택(strip/lower), 부재 시 무경고 폴백, 존재-무효 시 warning + 폴백(8.8/resolve_mood 철학). 프롬프트에 `### camera_movement (Optional)` 절 추가(location_key 서술 스타일), candidate 시딩 완료. **production 승격은 Jay 판단 대기** — 승격 전에도 무드 매핑이 기본값을 채우므로 기능 온전.
- **AC4**: `_enforce_camera_variety(shots, mood)` — build_scenes 씬별 shots 조립 직후 호출, 인접 중복 시 뒤 샷을 선호순서의 첫 비중복 항목으로 재배정 + info 로그. 독스트링에 아키타입-수준 금지로 "아키타입+방향" 금지가 충족되는 논증(drift 유일 방향성 + drift-drift 자체 금지)과 씬-경계 미검사 근거(5.16 dip-to-black) 기록. 순차 스캔이라 재배정 전파도 인접 중복을 남기지 않음(성질 테스트로 고정).
- **AC5**: video.py 변경은 `_HINT_MAP`/`select_effect` 구획에 국소화. `shake` → `_HINT_MAP` 1줄(in-center 플레이스홀더, `# ponytail:` 11.3 교체 명시), `locked` → 기존 static 분기 합류, `drift` → `_PAN_POOL`(pan-* 부분집합) 인덱스 회전. `push_in`/`pull_back` 기존재를 테스트로 고정.
- **AC6**: None/미인식 값 → 라운드로빈 폴백 무변경(기존 test_select_effect_* 전부 무수정 통과). run_service/character_service 무변경.
- **AC7**: 전체 스위트 1374 passed. `camera_movement=None` 픽스처 테스트들(test_video/test_shot_timing/test_tts/test_image 등) 전부 무수정 통과 — AC6 하위호환 증거. build_scenes의 ShotData 전체-dict 동등 비교 테스트는 존재하지 않아 갱신 불필요.
- 신규 테스트 함수 23개: test_scenario_chain.py 17개(매핑 전역성/기본값/도달성 6, 오버라이드 파싱 4, validator 성질/결정론/오버라이드 재배정/단일샷 7), test_video.py 6개(select_effect 아키타입).

### File List

- src/yt_flow/domain/state.py (CAMERA_ARCHETYPES 상수 + camera_movement 주석)
- src/yt_flow/pipeline/nodes/scenario_chain.py (CAMERA_PREFERENCES + _resolve_camera_movement + _enforce_camera_variety + build_scenes 배선)
- src/yt_flow/pipeline/nodes/video.py (_HINT_MAP shake, _PAN_POOL, select_effect locked/drift 분기)
- prompts/scenario/visual_breakdown.md (camera_movement 절 + YAML 예시 필드)
- tests/pipeline/nodes/test_scenario_chain.py (신규 테스트 17개)
- tests/pipeline/nodes/test_video.py (신규 테스트 6개)
- _bmad-output/implementation-artifacts/11-2-camera-motion-archetype-wiring.md (본 스토리 파일)
- _bmad-output/implementation-artifacts/sprint-status.yaml (11-2 상태 전이)

## Senior Developer Review (AI)

**Reviewer:** claude-fable-5 자동 리뷰 (story-automator, 2026-08-01) · **판정: Approve** (CRITICAL 0 / HIGH 0 / MEDIUM 1 수정 / LOW 1 기록)

**검증 완료 항목**: File List ↔ git 변경분 일치(불일치 0). AC 1–7 전부 구현 확인 — 락스텝 assert 2개, 오버라이드 파싱(strip/lower + warning), validator 순차 스캔 성질, select_effect 아키타입 분기, 폴백 라운드로빈 무변경, `camera_movement=None` 기존 픽스처 무수정 통과. 전체 스위트 1374 passed 재현. ruff clean. image_node 사이드카 캐시 키(image_prompt/negative_prompt/seed)에 camera_movement 미포함 확인 — resume 캐시 무효화 없음(스토리 무결성 주장 검증됨). 프롬프트는 candidate 시딩만, production 승격 안 함(PROMPT_POLICY 준수).

**MEDIUM (수정됨) — escalation 씬 시각적 단조**: `CAMERA_PREFERENCES["escalation"] = (shake, push_in, drift)`에서 validator의 첫 대안이 push_in인데, 11.2의 shake 플레이스홀더가 `_HINT_MAP`에서 push_in과 동일한 in-center 푸시로 렌더됨 → escalation 씬 기본 시퀀스 `[shake, push_in, shake, …]`가 **전 샷 동일 EffectSpec**으로 렌더(라이브 재현으로 확정). 이 스토리가 제거하려는 "모든 샷이 같은 모션" 결함이 escalation 무드에서 그대로 재생산되는 것. **수정**: 선호순서를 `(shake, drift, push_in)`로 재배열(테이블은 명시적 튜닝 시작점, 도달성/락스텝 assert 무영향) + 회귀 가드 `test_camera_preferences_first_alternate_renders_distinct`(전 무드 파라미터라이즈: prefs[0] vs prefs[1]의 EffectSpec이 반드시 상이) 추가. 수정 후 escalation 기본 시퀀스는 push/pan 교대로 렌더.

**LOW (기록만, 11.3 스코프)**: shake 플레이스홀더가 push_in과 렌더 수준에서 충돌하는 것 자체는 잔존 — LLM이 인접 샷에 shake/push_in을 명시 오버라이드하면 여전히 동일 렌더 인접이 가능(validator는 아키타입 수준만 검사). 11.3의 fBm/trauma 셰이크가 플레이스홀더를 교체하면 자연 해소되며, 신규 회귀 가드가 그 시점의 정합도 계속 검증한다.

## Change Log

- 2026-08-01: 자동 코드리뷰(Approve) — escalation 선호순서 재배열(shake/push_in 렌더 충돌로 인한 씬 단조 수정) + 전 무드 "기본값 vs 첫 대안 렌더 상이" 회귀 가드 추가. 전체 스위트 재검증 green. Status: review → done.
- 2026-08-01: Story 11.2 구현 — camera_movement 하드코딩 None 제거, 닫힌 아키타입 enum + 무드→아키타입 결정론 매핑 + 연속샷 동일 아키타입 금지 validator + select_effect 아키타입 1급 지원(라운드로빈은 폴백 강등). visual_breakdown 프롬프트에 선택적 camera_movement 오버라이드 채널 추가, candidate 시딩(production 승격은 Jay 판단). 전체 스위트 1374 passed.
