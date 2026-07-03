---
baseline_commit: 8ad4e9bf648b03491ba18608a3660c5a51847aac
---

# Story 6.1: 프롬프트 정책 문서 + variant→label 배선

Status: review

## Story

As Jay,
I want a one-page prompt-management policy that AI sessions read, plus the missing code wiring that makes prompt A/B actually fetch different prompts,
so that every prompt change (human or AI) follows the same versioning/promotion protocol and A/B runs are real experiments.

## Context (2026-07-03 프롬프트 운영 논의)

정책 논의 중 배선 갭 발견: `prompt_service.get_prompt(name, label=...)`은 라벨을 지원하지만 scenario 체인이 `prompt_variant`를 fetch에 안 넘김 → **현재 A/B run은 Variant B도 production 프롬프트를 읽어 A=B 동일 프롬프트로 실행됨**. 정책과 배선을 한 스토리로 묶는다. Epic 5의 5-4/5-5(프롬프트를 만지는 스토리)보다 선행해야 함.

## Acceptance Criteria

### 정책 문서

1. **Given** `docs/PROMPT_POLICY.md` (1페이지), **Then** 다음 5개 규칙을 담는다:
   - **SoT는 repo**: 모든 런타임 프롬프트는 `prompts/<stage>/<name>.md` + 시드 스크립트로 관리. Langfuse는 서빙+라벨+메트릭.
   - **라벨 2개**: `production`(기본), `candidate`(A/B 도전자). production은 라벨 이동으로만 변경.
   - **변경 프로토콜**: repo 파일 수정 → 새 버전 시드+`candidate` 라벨 → 동일 SCP A/B run → Epic 4 평가+게이트 육안 → 승자 승격(라벨 이동), 커밋에 근거(변경 내용+평가 점수) 기록 → 패자 폐기.
   - **골든셋 회귀**: 승격 전 골든셋(Story 6.2) 평가 통과 필수.
   - **Langfuse UI에서 production 프롬프트 직접 편집 금지** (SoT 이탈 방지).
2. **Given** CLAUDE.md, **Then** 정책 문서를 참조하는 섹션이 추가된다 — AI가 매 세션 정책을 인지
3. **Given** Langfuse UI, **Then** `production` 라벨이 protected로 설정된다 (수동 설정 — 절차를 정책 문서에 기록)

### variant→label 배선

4. **Given** `prompt_variant="B"`인 run, **When** scenario 체인이 프롬프트를 fetch, **Then** `label="candidate"`로 조회한다
5. **Given** candidate 라벨이 없는 프롬프트(부분 실험 — 예: visual_breakdown만 candidate 시딩), **Then** production으로 폴백한다 — B run이 죽지 않고, 바뀐 프롬프트만 실험됨
6. **Given** `prompt_variant`가 None/"A", **Then** 현행과 동일하게 production 조회 (기존 테스트 무수정 통과)
7. 시드 스크립트가 `--label candidate` 옵션을 지원한다
8. 테스트: variant B→candidate 조회, candidate 부재 시 production 폴백, variant A 무변경

## Tasks / Subtasks

- [x] `docs/PROMPT_POLICY.md` 작성 + CLAUDE.md에 참조 섹션 추가 (AC: 1, 2)
- [x] `src/yt_flow/services/prompt_service.py`에 `get_prompt_with_fallback(name, *, label, fallback_label="production")` 추가 — `NotFoundError`만 캐치해 폴백, 그 외 예외는 기존 `get_prompt`처럼 `RuntimeError`로 래핑 (AC: 5)
- [x] `scenario_chain.py`의 `_call_stage`와 6개 `*_step` 함수(`research_step`/`structure_step`/`writing_step`/`visual_breakdown_step`/`review_step`/`critic_step`)에 키워드 전용 `label: str | None = None` 파라미터 추가 — `_call_stage`가 `label`이 있으면 `get_prompt_with_fallback`, 없으면 기존 `get_prompt` 호출 (AC: 4, 5, 6)
- [x] `scenario.py`: `scenario_node`가 `state.get("prompt_variant") == "B"`면 `label="candidate"`, 아니면 `None`을 계산해 `format_guide` fetch + 모든 `*_step`/`_write_and_review` 호출(최초+재시도 양쪽)에 전달 (AC: 4, 6)
- [x] `--label` CLI 옵션 존재 확인 및 정책 문서에 사용법 기록 — **코드 변경 불필요, 이미 구현됨** (AC: 7, 아래 Dev Notes 참조)
- [x] Langfuse UI에서 production protected 설정 + 절차 문서화 (AC: 3)
- [x] 테스트 3종 + 기존 테스트 무수정 통과 확인 (AC: 6, 8)

## Dev Notes

### AC7은 이미 구현되어 있음 — 코드 변경 없음

`scripts/migrate_prompts.py`가 이미 `--label` 옵션을 지원한다 (`ap.add_argument("--label", default="production")`, [scripts/migrate_prompts.py:129](scripts/migrate_prompts.py#L129)). `uv run python scripts/migrate_prompts.py --label candidate --source ...`로 즉시 candidate 시딩 가능. `scripts/seed_eval_prompts.py`도 동일 옵션 보유하지만 evaluation/character 프롬프트는 variant 배선 대상이 아니므로 무관. **이 AC의 작업은 확인 + PROMPT_POLICY.md에 사용법을 적는 것뿐** — 새 CLI 옵션을 만들면 중복 구현.

### variant→label 배선 — 정확한 호출 체인과 시그니처

배선 갭의 정확한 위치: [src/yt_flow/pipeline/nodes/scenario.py:124](src/yt_flow/pipeline/nodes/scenario.py#L124) `scenario_node`가 `state["prompt_variant"]`를 전혀 읽지 않음 → 모든 하위 `*_step` 호출과 `get_prompt("scenario/format_guide")` (line 133)가 라벨 없이 production을 조회.

**호출 체인 (수정 대상, 상위→하위):**
```
scenario_node (scenario.py)
  ├─ get_prompt("scenario/format_guide")          # line 133 — label 없음
  ├─ research_step(...)                            # → _call_stage("scenario/research", ...)
  ├─ structure_step(...)                            # → _call_stage("scenario/structure", ...)
  └─ _write_and_review(...) ×2 (최초 + 1회 재시도)
        ├─ writing_step(...)                        # → _call_stage("scenario/writing", ...)
        ├─ visual_breakdown_step(...) ×N (씬별 병렬) # → _call_stage("scenario/visual_breakdown", ...)
        ├─ review_step(...)                         # → _call_stage("scenario/review", ...)
        └─ critic_step(...)                         # → _call_stage("scenario/critic_agent", ...)
```
`_call_stage`([scenario_chain.py:38](src/yt_flow/pipeline/nodes/scenario_chain.py#L38))가 유일한 프롬프트 fetch 지점 — 여기 하나에 `label` 파라미터를 추가하면 모든 `*_step`이 자동으로 배선된다. `format_guide` fetch(scenario.py:133)는 `_call_stage`를 안 거치므로 별도 처리 필요.

**시그니처 변경 (키워드 전용 `label=None` 추가 — 위치 인자 순서는 절대 바꾸지 말 것):**
```python
# scenario_chain.py
async def _call_stage(prompt_name: str, variables: dict, s, call_deepseek, *, label: str | None = None) -> str:
    prompt = prompt_service.get_prompt_with_fallback(prompt_name, label=label) if label else prompt_service.get_prompt(prompt_name)
    rendered = prompt.compile(**variables)
    ...  # 나머지 동일

async def research_step(scp_id, scp_text, format_guide, s, call_deepseek, *, label=None) -> dict:
    raw = await _call_stage("scenario/research", {...}, s, call_deepseek, label=label)
    ...
# structure_step / writing_step / visual_breakdown_step / review_step / critic_step 동일 패턴
```
`_write_and_review`도 `*, label=None` 추가해 4개 스텝 호출에 그대로 전달.

**왜 `label=None`일 때 반드시 `prompt_service.get_prompt`를 그대로 호출해야 하는가 (AC6 "기존 테스트 무수정" 필수 조건):**
`tests/pipeline/nodes/test_scenario_chain.py`의 모든 테스트가 `monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())`로 **`prompt_service.get_prompt`를 직접 패치**한다. `_call_stage`가 label=None일 때 `get_prompt_with_fallback`을 (설령 내부에서 get_prompt로 위임하더라도) 거치면 몽키패치 경로가 달라질 위험이 있다 — `label`이 falsy면 무조건 `prompt_service.get_prompt(prompt_name)`을 직접 호출하는 조건 분기를 유지할 것. 마찬가지로 `tests/pipeline/nodes/test_scenario.py`의 `_isolate` fixture는 `monkeypatch.setattr(sc, "get_prompt", ...)`로 **scenario.py에 바인딩된 이름**을 패치한다 — `state["prompt_variant"]`가 None인 기존 테스트들이 계속 통과하려면 `scenario_node`도 label이 None일 때 반드시 (import된) `get_prompt("scenario/format_guide")`를 그대로 호출해야 한다. `get_prompt_with_fallback`은 scenario.py에 새로 import해서 label이 truthy("candidate")할 때만 쓴다.

**`get_prompt_with_fallback` 설계 (`prompt_service.py`에 추가):**
```python
from langfuse.api import NotFoundError  # 공개 재export, langfuse==4.x 확인됨

def get_prompt_with_fallback(name: str, *, label: str, fallback_label: str = "production"):
    """label로 조회, 없으면(NotFoundError) fallback_label로 폴백 (Story 6.1 AC5:
    프롬프트 일부만 candidate로 시딩해도 B run이 죽지 않게 함)."""
    client = build_client()
    try:
        return client.get_prompt(name, label=label)
    except NotFoundError:
        return get_prompt(name, label=fallback_label)
    except Exception as exc:
        raise RuntimeError(f"Langfuse prompt fetch failed: name={name!r} label={label!r}") from exc
```
`NotFoundError`는 `from langfuse.api import NotFoundError`로 가져온다 (`langfuse.api.__all__`에 공개 재export됨, 확인됨: `langfuse.api.commons.errors.not_found_error.NotFoundError`, `ApiError`의 서브클래스). 기존 `get_prompt`의 범용 `except Exception`은 건드리지 않는다 — `get_prompt_with_fallback`만 별도로 `NotFoundError`를 먼저 잡는다.

**`scenario_node`에서 label 계산 (한 곳):**
```python
from yt_flow.services.prompt_service import get_prompt, get_prompt_with_fallback

label = "candidate" if state.get("prompt_variant") == "B" else None
format_guide = (get_prompt_with_fallback("scenario/format_guide", label=label) if label else get_prompt("scenario/format_guide")).compile()
...
research = await research_step(state["scp_id"], state["scp_text"], format_guide, s, _call_deepseek, label=label)
structure = await structure_step(state["scp_id"], research, format_guide, s, _call_deepseek, label=label)
writing, visual_by_scene, review, critic = await _write_and_review(..., s, stages, label=label)  # 최초 호출
# 재시도 호출(line ~150)도 동일하게 label=label 추가
```
`PipelineState.prompt_variant`의 타입은 `Literal["A", "B"] | None` ([domain/state.py:15,104](src/yt_flow/domain/state.py#L15)) — `"A"`와 `None`을 동일하게 취급(둘 다 label=None)하면 AC6을 만족한다.

### 배선 범위 밖

- `evaluation`/`character` 프롬프트: 파이프라인 산출물이 아니므로 variant 배선 대상 아님 (production 고정, `seed_eval_prompts.py`는 그대로 둠).
- image/tts/subtitle/video 노드: 현재 Langfuse 프롬프트를 안 씀 — scenario 체인만 배선.

### 정책 문서 작성 시 참고

- `Settings` 클래스([src/yt_flow/config.py](src/yt_flow/config.py))에 이미 `langfuse_host`/`langfuse_public_key`/`langfuse_secret_key`/`langfuse_enabled` 필드 존재 — 정책 문서에서 이 설정을 언급할 필요는 없음(운영 문서가 아니라 프롬프트 버저닝 프로토콜 문서).
- AD-6(아키텍처 스파인): A/B는 `POST /runs/{id}/ab`가 `prompt_variant="B"`로 완전히 독립된 두 번째 run을 만드는 구조 — 그래프 분기 없음. 이 스토리는 그 기존 인프라의 "B가 실제로 다른 프롬프트를 읽게" 만드는 마지막 배선.
- Langfuse `production` 라벨 protected 설정은 Langfuse UI에서 Prompt → Labels 메뉴의 수동 클릭 작업 (self-hosted, host는 기존 메모리 참조: `langfuse.eli.kr`) — 코드 작업 아님, 문서에 스크린샷 없이 절차 텍스트로 기록.

### 테스트 전략 (AC8)

- `tests/test_prompt_service.py`에 `get_prompt_with_fallback` 테스트 추가: ① candidate 존재 시 그대로 반환 ② candidate 없을 때(`NotFoundError`) production 폴백 ③ 기타 예외는 `RuntimeError`. `FakeClient.get_prompt`를 label별로 다른 결과/예외를 내도록 확장 필요 (현재는 dict 조회 후 없으면 `LookupError` — `NotFoundError`로 교체하거나 label별 분기 추가).
- `tests/pipeline/nodes/test_scenario_chain.py`: 기존 테스트 전부 `label` 인자를 안 넘기므로 무수정 통과해야 함 (그대로 두고 실행해서 확인). 신규: `label="candidate"`를 넘겼을 때 `prompt_service.get_prompt_with_fallback`이 그 label로 호출되는지 검증하는 테스트 1~2개 추가.
- `tests/pipeline/nodes/test_scenario.py`: `_state()`가 이미 `"prompt_variant": None` 필드를 갖고 있음 — `prompt_variant="B"`로 오버라이드하는 신규 테스트를 추가해 `sc.get_prompt_with_fallback`(신규 monkeypatch 대상)이 `label="candidate"`로 호출됨을 검증. 기존 `_isolate` fixture는 수정하지 말 것(다른 테스트가 깨짐) — 신규 테스트에서만 추가로 `monkeypatch.setattr(sc, "get_prompt_with_fallback", ...)`.

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- `uv run pytest -q` → 495 passed, 1 skipped, 0 failed (full regression, no changes to prior test files besides additive tests for this story).

### Completion Notes List

- `prompt_service.get_prompt_with_fallback` added; catches `langfuse.api.NotFoundError` only and falls back to `fallback_label="production"`, other exceptions wrap in `RuntimeError` same as `get_prompt`.
- `_call_stage` (scenario_chain.py) is the single fetch point — added keyword-only `label=None`; `label` falsy still calls `prompt_service.get_prompt` directly (unchanged monkeypatch seam for `test_scenario_chain.py`). All six `*_step` functions and `_write_and_review` thread `label` through unchanged otherwise.
- `scenario_node` computes `label = "candidate" if state.get("prompt_variant") == "B" else None` once, uses it for the `format_guide` fetch (via `get_prompt_with_fallback` only when label is truthy — keeps `test_scenario.py`'s `sc.get_prompt` monkeypatch seam intact for variant A/None) and passes it into both `_write_and_review` calls (initial + retry).
- `docs/PROMPT_POLICY.md` written (5 rules + `--label` usage + manual protected-label procedure) and referenced from `CLAUDE.md`.
- AC7: confirmed `scripts/migrate_prompts.py --label` already exists — no code change, only documented usage in the policy doc.
- AC3 (Langfuse `production` label → protected): **verified with Jay in-session (2026-07-04) that this is not available** — Project Settings on the self-hosted instance (`langfuse.eli.kr`, v3.201.1 OSS) has no "Prompts" tab at all; Langfuse's Protected Labels feature requires an Enterprise license this OSS build doesn't have. `docs/PROMPT_POLICY.md` updated to record this and fall back to policy-only enforcement (CLAUDE.md → PROMPT_POLICY.md rule 5) since the project is single-operator. AC3 is satisfied to the extent technically possible; the literal "라벨이 protected로 설정된다" outcome cannot be achieved on this Langfuse edition.
- Tests added: `test_prompt_service.py` (candidate hit / fallback / other-exception wrap), `test_scenario_chain.py` (`_call_stage` label=None → `get_prompt`, label set → `get_prompt_with_fallback`), `test_scenario.py` (variant B → `candidate` label reaches `research_step`; variant A/None → unchanged `get_prompt` call with no label). Full suite green, no existing test modified.

### File List

- `docs/PROMPT_POLICY.md` (new)
- `CLAUDE.md` (modified — Prompt Policy reference section)
- `src/yt_flow/services/prompt_service.py` (modified — `get_prompt_with_fallback`)
- `src/yt_flow/pipeline/nodes/scenario_chain.py` (modified — `label` param on `_call_stage` + 6 `*_step` functions)
- `src/yt_flow/pipeline/nodes/scenario.py` (modified — `scenario_node` variant→label wiring, `_write_and_review` label param)
- `tests/test_prompt_service.py` (modified — `get_prompt_with_fallback` tests)
- `tests/pipeline/nodes/test_scenario_chain.py` (modified — `_call_stage` label tests)
- `tests/pipeline/nodes/test_scenario.py` (modified — variant B/A/None label wiring tests)

## Change Log

- 2026-07-04: Implemented variant→label wiring (AC4-8) and prompt policy doc (AC1-3, 7); full regression green.
- 2026-07-04: Confirmed Langfuse Protected Labels unavailable on this OSS self-host instance (Enterprise-only feature); updated `docs/PROMPT_POLICY.md` AC3 section to policy-only enforcement.
- 2026-07-04: Code review fix — `get_prompt_with_fallback` now logs a WARNING on each fallback so a candidate-absent A/B run (partial or total fallback) is no longer silent.
