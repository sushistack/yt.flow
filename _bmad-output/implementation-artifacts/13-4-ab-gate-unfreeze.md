---
baseline_commit: 7141707
story_key: 13-4-ab-gate-unfreeze
story_id: "13.4"
epic: 13
mirrors: 6-12-ab-promotion-gate-freeze-deferred-candidate  # 6-12 "동결한다" ↔ 13-4 "해제한다"
depends_on:
  - 6-10-statistical-promotion-gate-repair-robustness  # median-of-N 게이트 = 해제 후 쓸 판정 로직
  - 6-12-ab-promotion-gate-freeze-deferred-candidate    # 되돌릴 대상(가드 + 배너)
related:
  - 13-2-visual-eval-axes   # 시각 축을 게이트에 포함 (AC7, 조건부)
  - 12-2-model-split-gemini # judge 독립성 재검토 (AC8, 조건부)
  - 8-12-cast-placement-scale-calibration  # CLAUDECODE/AI_AGENT 무조건 차단 가드의 출처
  - 6-13-golden-set-eval-stage-caching     # --reps>1은 캐시 무조건 우회(회귀 주의)
---

# Story 13.4: A/B 승격 게이트 해제 — 품질튜닝 국면 진입

Status: ready-for-dev

## Story

As a **yt.flow 운영자 (Jay)**,
I want **DEV MODE(품질 게이팅 OFF)를 종료하고 candidate-vs-production A/B 승격 게이트를 되살려서, 프롬프트 변경이 다시 "게이트 통과 후에만 production"이라는 규율 아래 놓이되 6-12가 만든 승격 데드락은 재발하지 않도록**,
so that **파이프라인 완성 이후의 품질튜닝이 측정 기반으로 진행되고 — 지금은 모든 프롬프트가 repo→production 직승격이라 회귀를 잡는 장치가 하나도 없다 — DEV MODE 기간에 무게이트로 승격된 현행 production이 앞으로의 비교 기준점으로 명시적으로 기록된다**.

## Context

### 왜 이 스토리가 6-12와 분리돼 있는가

6-12(2026-07-12)는 "A/B 게이트를 **동결한다**", 13-4는 "**해제한다**". 해제 조건 판단(= 파이프라인이 완성됐다고 볼 것인가)이 코드 작업이 아니라 별도 의사결정이기 때문에 스토리를 쪼갰다. 6-12의 AC4가 이 트리거를 문서로 남겨뒀고, 이 스토리가 그 AC4의 실행체다.

### 되돌려야 하는 것이 두 겹이다

1. **6-12의 게이트 동결**(2026-07-12, 코드): `scripts/eval_prompts.py`가 `--baseline`(= candidate-vs-production A/B, `--profile promotion` 포함) 실행을 `YTFLOW_ALLOW_AB_GATE=1` 없이는 hard-error로 거부한다.
2. **DEV MODE**(2026-08-03, `cc82403`, 문서만): 6-12 동결이 게이트만 끄고 "게이트 통과 후 승격" 규칙(PROMPT_POLICY Rules 3/4)은 남겨둬 **승격 자체가 구조적으로 불가능**해졌고 모든 프롬프트 편집이 `candidate`에 적체됐다. 이를 해소하려고 Rules 3/4을 SUSPENDED로 표시하고 repo→`production` 직접 시딩을 정식 경로로 선언했다. 코드 변경은 없었다.

**그래서 해제는 6-12만 되돌리는 게 아니다.** 6-12의 가드만 풀고 DEV MODE 배너를 그대로 두면 "게이트는 돌 수 있지만 아무도 요구하지 않는" 어중간한 상태가 된다. 반대로 Rules 3/4만 되살리고 가드를 두면 **6-12가 만든 데드락이 그대로 재발한다**(승격 필수 게이트를 실행 금지 상태로 두는 것). 두 겹을 같은 커밋에서 함께 뒤집어야 한다.

### DEV MODE가 남긴 상태 — 비교 기준점이 없다

DEV MODE 기간에 `production`은 게이트 없이 갱신됐다(`8-12` 계열 6개 프롬프트 + `344fd5f`의 `scenario/visual_breakdown` v12, `scenario/writing` v7). `344fd5f` 커밋 메시지는 **"이제 repo prompts/ == Langfuse production"**이라고 선언한다.

결과:
- 6-12가 적체로 지목한 candidate 백로그(6-3/6-4, 8-5, 8-8, 11-2, 5-22)는 **이미 승격돼 백로그로서는 소멸**했다. 즉 이 스토리의 "보류 후보 재평가"는 *승격 대기열 소화*가 아니라 **무게이트로 들어간 현행 production을 앞으로의 기준선으로 확정하는 작업**이다.
- `--baseline`은 라벨(`production`/`candidate`)만 받고 버전 핀을 못 받는다(`scripts/eval_prompts.py:780-781`, `LABELS = ("production", "candidate")`). DEV MODE 이전 버전과의 소급 비교를 하려면 Langfuse의 옛 버전에 임시 라벨을 달아야 하는데, 그건 새 라벨 체계 도입 = Rule 2("Two labels only") 위반이다. **소급 비교는 하지 않는다** — 대신 현행 `production`의 골든셋 점수를 스냅샷으로 기록해 앞으로의 게이트가 그 위에서 판정하게 한다(forward-only).

### 되돌리지 않는 것 — AI 세션 차단 가드

`scripts/eval_prompts.py:842-848`의 `CLAUDECODE`/`AI_AGENT` 무조건 차단은 **유지한다**. 출처가 다르다: 8-12에서 AI 세션이 요청받고 `YTFLOW_ALLOW_AB_GATE`를 스스로 켰다가 Jay가 중단시킨 사건 뒤 "에이전트가 자기 env var로 뒤집을 수 없게" 추가된 가드다. 해제로 없어지는 이유는 **토큰 예산**이고, 이 가드의 이유는 **게이트 판정 권한이 사람에게 있다**는 것 — 후자는 품질튜닝 국면에서 오히려 더 중요해진다. 결과적으로 승격 게이트는 Jay가 평범한 터미널에서 직접 돌린다(구현 AI 세션은 게이트를 못 돌린다 → AC6/AC7의 실행 증거는 Jay 수행분을 받아 기록).

## ⛔ 착수 전 차단 조건 (BLOCKING — AC1)

이 스토리는 **조건 충족 확인 없이 착수하면 안 된다.** epics.md 13.4가 명시한 착수 조건: *"Epic 8/11의 GPU 스토리가 닫히고 E2E 산출물이 Jay 기준을 통과한 뒤."*

2026-08-03 기준 미충족 항목(`sprint-status.yaml`):

| 항목 | 상태 |
|------|------|
| `8-16-depth-aware-placement-ic-light` | backlog |
| `8-19-embedding-asset-retrieval-layer` | backlog |
| `8-20-openpose-conditioned-action-poses` | backlog |
| `11-5-depthflow-25d-parallax` | backlog |
| `11-6-hero-shot-selective-i2v` | backlog (조건부 — 11.1–11.5 후 필요성 실측 시만) |
| E2E 산출물 Jay 기준 통과 | 미기록 |

dev agent는 **먼저 sprint-status.yaml을 읽고 위 항목을 재확인**한다. 미충족이면 코드/문서를 한 줄도 고치지 말고 상태를 보고한 뒤 정지한다(조건부 11-6은 Jay가 "불필요"로 판정한 기록이 있으면 충족으로 간주). "거의 다 됐으니 진행"은 금지 — 게이트를 되살리는 스토리가 스스로 게이트를 무시하면 안 된다.

## Acceptance Criteria

1. **착수 조건 검증 후에만 진행 (BLOCKING)**: `sprint-status.yaml`에서 Epic 8/11의 GPU 스토리(8-16/8-19/8-20/11-5/11-6)가 `done` 또는 명시적 Jay 판정으로 종료됐고, E2E 산출물이 Jay 기준을 통과했다는 기록이 존재함을 확인한다. **미충족이면 어떤 파일도 수정하지 않고 미충족 목록과 함께 정지**한다. 충족 시 Dev Agent Record에 근거(sprint-status 라인/Jay 확인 메시지)를 인용해 기록한다.

2. **`eval_prompts.py` 동결 가드 제거 — `--baseline`이 override 없이 실행된다**: `scripts/eval_prompts.py:849-856`의 `YTFLOW_ALLOW_AB_GATE` 분기와 `:66`의 `AB_GATE_OVERRIDE_ENV` 상수를 삭제한다. 삭제 후 `--label candidate --baseline production`과 `--profile promotion`이 (AI 세션 밖 터미널에서) env var 없이 정상 진행한다. **`:842-848`의 `CLAUDECODE`/`AI_AGENT` 무조건 차단은 유지**하되, 그 메시지가 `AB_GATE_OVERRIDE_ENV`를 참조하고 있으므로(`:846`) 상수 삭제로 깨진다 — "Jay가 평범한 터미널에서 직접 실행한다"만 남도록 문구를 다시 쓴다. `:834-841`의 6-12 주석 블록도 동결이 아니라 현행(AI 세션 차단만)을 설명하도록 갱신한다.

3. **동결 회귀 테스트 역전**: `tests/test_eval_prompts.py`에서
   - autouse `_authorize_ab_gate` 픽스처(`:22-34`)의 `monkeypatch.setenv(ep.AB_GATE_OVERRIDE_ENV, "1")` 라인 삭제(상수가 없어져 `AttributeError`가 된다). `CLAUDECODE`/`AI_AGENT` `delenv`는 **유지**(가드가 살아 있고 테스트는 AI 세션 안에서 돌아간다 — 이게 없으면 `--baseline` 테스트 전부 실패). 픽스처 이름/주석을 현행 의미로 갱신.
   - `test_baseline_comparison_frozen_without_override`(`:1381`), `test_promotion_profile_frozen_without_override`(`:1388`)를 **삭제하지 말고 역전**: env var 없이 `--baseline` / `--profile promotion`이 `FROZEN` 없이 진행함을 고정하는 테스트로 다시 쓴다(6-12→13-4 역전 사유를 테스트 주석에 기록 — 7.5 교훈).
   - `test_baseline_blocked_in_ai_session_even_with_override`(`:1395`), `test_baseline_blocked_even_when_ai_session_var_is_empty_string`(`:1405`)는 **그대로 통과해야 한다**(이름의 "even_with_override"만 스테일 — 주석 정정 허용, 동작 변경 금지).
   - `test_single_label_run_not_frozen`(`:1414`)의 `delenv(ep.AB_GATE_OVERRIDE_ENV)` 라인 제거, 나머지 유지.

4. **`docs/PROMPT_POLICY.md` — DEV MODE 배너 제거 + Rules 3/4 복원**:
   - 상단 DEV MODE 배너(`:5-30`) 삭제. 대신 **한 줄 이력 노트**를 문서 하단(또는 "Golden-set regression" 앞)에 남긴다: 2026-07-12 6-12 동결 → 2026-08-03 DEV MODE(게이팅 OFF, `cc82403`) → 2026-0X-XX 13-4 해제, 그 사이 승격된 프롬프트는 무게이트임. **이력을 지우지 않는다**(왜 현행 production이 검증되지 않았는지가 앞으로의 판정 맥락이다).
   - Rule 3(`:36`)과 Rule 4(`:44`)의 `⛔ SUSPENDED in dev mode` 표시 제거 — 본문은 이미 보존돼 있으므로 표시만 걷어내면 복원된다.
   - 배너 안에 있던 **AI 세션 관련 문단(`:27-30`)은 소멸시키지 말고** Rules 또는 "Golden-set regression" 섹션으로 이전한다(가드가 살아 있으므로 정책 문서에도 남아야 한다). 문구는 `YTFLOW_ALLOW_AB_GATE` 언급 없이 다시 쓴다.
   - Rule 3의 6단계("Promote the winner by moving the `production` label in the Langfuse UI")를 AC5의 결정과 정합시킨다.
   - `CLAUDE.md`의 "## Prompt Policy" 안 **DEV MODE 문단(`:42`) 삭제** — 세션마다 자동 로드되는 파일이라 여기가 스테일이면 AI 세션이 계속 무게이트 승격을 정상 경로로 오인한다. `:40`("Any change to a runtime prompt ... follows `docs/PROMPT_POLICY.md`")은 **그대로 유지**하고 `:42`만 제거한다.

5. **`migrate_prompts.py --label production` 가드 결정 실행** (deferred-work:309의 미결 정책 판단 — 이 스토리 소관): 게이트를 되살리면서 **실제 라벨 이동 경로를 무방비로 두면 게이트가 장식이 된다**. `scripts/migrate_prompts.py`의 `--label production` 경로에 `eval_prompts.py`와 동일한 **환경변수 존재 검사**(`"CLAUDECODE" in os.environ or "AI_AGENT" in os.environ` → `SystemExit`)를 추가한다. `candidate` 시딩과 `--dry-run`/`--check`는 영향 없음(AI 세션이 계속 수행 가능한 작업). 회귀 테스트 3건: production+AI 세션 → 차단, production+평범한 터미널 → 통과, candidate+AI 세션 → 통과.
   > **결정 지점**: 이 가드는 "Jay가 판단한 뒤 AI 세션에 승격 실행을 지시"하던 기존 워크플로우(8-12에서 실제로 그렇게 했다)를 막는다. 대안은 승격만 Jay가 직접 터미널에서 실행하는 것. 위 구현이 **권고 기본값**이며, Jay가 다르게 결정하면 그 결정을 PROMPT_POLICY.md와 Dev Agent Record에 기록하고 이 AC를 그에 맞게 닫는다. 어느 쪽이든 **결정 없이 넘기지 않는다**(deferred-work의 재고 조건이 "다음 AI 세션 승격 전"이고, 그 시점이 지금이다).

6. **repo ↔ `production` 정합 확인 + 기준선 스냅샷**:
   - **정합 확인은 읽기 전용이어야 한다.** `migrate_prompts.py`에 `--check` 플래그 추가: 매니페스트와 `production` 라벨 현재 내용을 비교해 드리프트 항목명을 출력하고 드리프트가 있으면 exit 1, 쓰기는 하지 않음. 기존 `_unchanged()`(`:99-108`)를 재사용한다 — **신규 스크립트를 만들지 않는다**. (`--dry-run`은 Langfuse를 조회하지 않으므로 정합 확인에 못 쓴다.)
   - 알려진 드리프트 1건을 이 확인에 포함해 해소한다: `prompts/character/generation.md` ↔ Langfuse `character-generation` v3 `production`(deferred-work: "production 본문은 `full-body shot, clean composition`뿐, repo는 `one single subject ... no extra characters` 요구"). 캐릭터 프롬프트는 `eval_prompts.py`(scenario 전용)의 게이트 범위 밖이므로 **Rule 4의 대체 검증**(동일 입력에 대한 candidate-vs-production compile 비교)을 적용하고, 시딩은 `scripts/seed_character_prompts.py` 경로를 쓴다.
   - **기준선 스냅샷**: 현행 `production`에 대해 단일 라벨 골든셋 실행(`--label production`, `--baseline` 없음 → AI 세션에서도 실행 가능)을 1회 수행하고, 3항목 × 3축 + total + rule metrics를 스토리 문서에 표로 기록한다. 이 표가 "무게이트로 들어간 production의 출발점" 공식 기록이다. `YTFLOW_DEEPSEEK_MAX_TOKENS=16000` 필수(`:874-879`의 경고 참조 — 기본 8192는 `visual_breakdown`을 절단한다).

7. **13-2 시각 축 게이트 포함 — 조건부, 단 침묵 금지**:
   - `13-2-visual-eval-axes`가 `done`이면: 13-2가 추가한 축이 **판정에 실제로 반영되는지** 확인한다. ⚠️ `compare()`(`scripts/eval_prompts.py:612`, 델타 계산 `:677-681`)는 `eval_service.AXES`(`atmosphere`/`narrative_coherence`/`article_fidelity`)만 순회하고, `rule_metrics`(`:388`)는 **기록·출력만 되고 판정에 전혀 들어가지 않는다**. 따라서 13-2의 축이 rule metric으로 들어왔다면 `compare()` 확장 없이는 게이트에 포함되지 않는다 — 이 경우 판정 대상 집합을 명시적으로 확장하고(축별 median ≥ 0 규칙을 그대로 적용) 테스트로 고정한다.
   - `13-2`가 미완이면: 해제 범위에서 시각 축이 **빠졌다는 사실**을 PROMPT_POLICY.md와 sprint-status 13-4 항목에 명시적으로 기록한다(AD-10 조용한 강등 금지 — "게이트 복원됨"이 시각 회귀를 잡는다는 오해를 만들면 안 된다). 13-2에 "게이트 배선까지 포함" 후속 조건을 남긴다.

8. **12-2 judge 독립성 재검토 — epics 12.2가 이 시점을 지정함**:
   - `12-2-model-split-gemini`가 `done`이면: 현재 구성이 **Gemini가 자기 문장을 채점**하는 상태인지 확인한다(12.2가 의도적으로 수용한 self-preference bias). 6-10 median 게이트의 신뢰도가 judge 독립성에 직접 의존하므로, 게이트를 승격 권한으로 되살리는 이 시점에 12.2가 보존해 둔 **0-비용 대안**(문장만 Gemini, 런타임 review/critic + 4-2 eval judge는 DeepSeek 유지 → writer/judge 계열 분리)으로 전환할지 판정한다. **판정과 근거를 기록**하고, 전환하기로 하면 배선 변경은 12-2 후속으로 분리(이 스토리에서 모델 배선을 고치지 않는다 — 범위 밖).
   - `12-2`가 미완이면: 이 재검토 요구를 12-2 스토리 항목에 인계 조건으로 명시하고 여기서는 기록만 한다.

9. **기록 정합**: `sprint-status.yaml`(13-4 → done + 무게이트 승격 기간과 기준선 스냅샷 요약, 6-12 항목에 "13-4로 해제됨" 추가), `epics.md`(13.4 구현 완료 표시 + `:1142`의 6-12 AC1 주석에 해제 사실 추가), `deferred-work.md:309`(migrate_prompts 가드 미결 항목 → AC5 결정으로 해소 표시). **삭제가 아니라 해소 표시**로 남긴다.

10. **회귀 그린**: 전체 스위트 통과(`PYTHONPATH=$PWD/src uv run pytest tests/ -q`) + `ruff check` clean. 기준선 카운트는 착수 시점에 먼저 측정해 기록한다(11-4 시점 1433 passed/1 skipped 이후 커밋이 더 있으므로 그 숫자를 그대로 쓰지 말 것).

## Tasks / Subtasks

- [ ] Task 1: 착수 조건 검증 (AC: 1)
  - [ ] `sprint-status.yaml` 전체 로드 → Epic 8/11 GPU 스토리 상태 + E2E Jay 통과 기록 확인
  - [ ] 미충족 시: 파일 수정 없이 미충족 목록 보고 후 정지
  - [ ] 충족 시: 근거 인용을 Dev Agent Record에 기록하고 Task 2로
- [ ] Task 2: `eval_prompts.py` 동결 해제 + 테스트 역전 (AC: 2, 3)
  - [ ] `:66` `AB_GATE_OVERRIDE_ENV` 상수 + `:849-856` 가드 분기 삭제
  - [ ] `:842-848` AI 세션 차단 유지 + 메시지에서 삭제된 상수 참조 제거, `:834-841` 주석 갱신
  - [ ] autouse 픽스처에서 `setenv(AB_GATE_OVERRIDE_ENV)` 제거(`delenv CLAUDECODE/AI_AGENT`는 유지), 이름/주석 갱신
  - [ ] freeze 테스트 2건 역전(override 없이 진행), AI 세션 차단 2건 무변경 통과 확인, `test_single_label_run_not_frozen` 정리
  - [ ] `grep -rn "YTFLOW_ALLOW_AB_GATE"` → 코드/테스트에 잔존 참조 0 (문서의 이력 언급은 허용)
- [ ] Task 3: 정책 문서 복원 (AC: 4)
  - [ ] `PROMPT_POLICY.md`: 배너 삭제, Rules 3/4 SUSPENDED 표시 제거, AI 세션 문단 이전, 이력 노트 추가
  - [ ] `PROMPT_POLICY.md:109-113` protected-labels 절 재확인 노트(2026-08 재확인: 여전히 Enterprise 전용 → 기술적 락 없음, 정책 집행 유지)
  - [ ] `CLAUDE.md`의 DEV MODE 문단 삭제 → PROMPT_POLICY 참조 한 줄로 축약
- [ ] Task 4: `migrate_prompts.py` 가드 결정 실행 (AC: 5)
  - [ ] `--label production` 경로에 환경변수 존재 검사 추가(권고 기본값) 또는 Jay 결정 반영
  - [ ] 테스트 3건(production+AI 차단 / production+터미널 통과 / candidate+AI 통과)
  - [ ] 결정 근거를 PROMPT_POLICY.md + Dev Agent Record에 기록
- [ ] Task 5: 정합 확인 + 기준선 스냅샷 (AC: 6)
  - [ ] `migrate_prompts.py --check` 추가(읽기 전용, `_unchanged()` 재사용, 드리프트 시 exit 1) + 단위 테스트(fake client)
  - [ ] `--check` 실행 → 드리프트 목록 확보, `character-generation` 드리프트 해소(Rule 4 대체 검증 + `seed_character_prompts.py`)
  - [ ] `YTFLOW_DEEPSEEK_MAX_TOKENS=16000 uv run python scripts/eval_prompts.py --label production` 1회 → 점수표를 스토리에 기록
- [ ] Task 6: 조건부 항목 판정 (AC: 7, 8)
  - [ ] 13-2 상태 확인 → done이면 `compare()`가 시각 축을 실제로 판정하는지 검사·확장·테스트 / 미완이면 누락 명시 기록
  - [ ] 12-2 상태 확인 → done이면 judge 독립성 판정+기록(배선 변경은 후속) / 미완이면 12-2에 인계 조건 기록
- [ ] Task 7: 기록 + 회귀 (AC: 9, 10)
  - [ ] sprint-status / epics / deferred-work:309 갱신
  - [ ] 전체 스위트 + ruff, 기준선 카운트 대비 기록
  - [ ] (Jay 수행분) 첫 실제 승격 게이트 실행 결과가 있으면 인용 기록 — AI 세션은 `--baseline`을 돌릴 수 없다

## Dev Notes

### 수정 대상 파일 — 현재 상태 / 바뀌는 것 / 지켜야 할 것

**`scripts/eval_prompts.py`** (944행)
- 현재: `main()`의 인자 검증 순서가 `resolve_profile` → `--baseline requires --label` 등 → **AI 세션 차단(`:842`)** → **동결 가드(`:849`)** → promotion max-tokens 검사(`:858`) → `build_client()`(`:865`). 두 가드 모두 `ap.error()`이므로 `SystemExit(2)` + stderr.
- 바뀜: 동결 가드만 사라진다. 순서 불변(AI 세션 차단이 여전히 `Settings()`/`build_client()` 앞에서 short-circuit해야 한다 — 무의미한 클라이언트 빌드/토큰 소비 방지).
- 지켜야 할 것: `--stage` + `--baseline` 조합 거부(`:831`), `--profile promotion`의 `--reps >= 3` 강제(`:149-151`), promotion의 `--scp-id`/`--stage` 축소 거부, `--profile promotion`의 max-tokens 16000 하한(`:858-863`). 하나도 건드리지 않는다.
- 6-13 상호작용: `--reps > 1`은 **캐시를 무조건 우회**한다(`:919-930` 주석 — rep 2..N을 캐시에서 주면 median 표본이 1개로 붕괴). 게이트가 되살아나면 promotion 1회 비용이 단일 라벨 실행의 ~6배라는 뜻(`PROMPT_POLICY.md:93` 참조). 절대 "캐시로 싸게 만들자"로 최적화하지 말 것.

**`tests/test_eval_prompts.py`** (1731행)
- 현재: autouse 픽스처가 override를 켜고 AI 세션 마커를 지운다. 픽스처가 override를 켜므로 **본 스위트 전체가 동결과 무관하게 동작**했다 — 즉 동결 제거로 깨지는 것은 픽스처 자체(`ep.AB_GATE_OVERRIDE_ENV` 참조)와 freeze 테스트 2건뿐이다.
- 함정: `delenv("CLAUDECODE")`를 지우면 안 된다. 이 저장소의 테스트는 AI 세션(CLAUDECODE 존재) 안에서 실행되므로, 지우면 `--baseline`을 쓰는 모든 테스트가 AI 세션 차단에 걸려 실패한다. 8-12가 이미 이 함정을 밟고 고쳤다.

**`docs/PROMPT_POLICY.md`** (113행)
- 현재: `:5-30` DEV MODE 배너, `:32-45` Rules 1–5(3/4에 SUSPENDED 표시), `:47-69` 골든셋/median 게이트 설명(6.2/6.6/6.10 — **정확하고 유지 대상**), `:71-93` 프로파일 티어, `:95-107` `--label`/`--source` 함정(8.10), `:109-113` protected-labels 부재.
- 지켜야 할 것: `:62-69`의 median 판정 규칙 서술(6-10의 계약 원문 — 코드와 정합), `:103-107`의 `--source prompts` 함정 경고(3번 재발한 버그), `:87-91`의 "smoke는 승격 권한 아님" 서술.

**`scripts/migrate_prompts.py`** (150행)
- 현재: `--label`(기본 `production`), `--dry-run`(로컬 매니페스트만 출력 — **Langfuse 미조회**), `migrate()`가 `_unchanged()`로 라벨별 내용 비교 후 변경분만 `create_prompt`. 가드 전무.
- 바뀜: production 라벨 경로의 환경변수 가드(AC5) + 읽기 전용 `--check`(AC6). 둘 다 `main()` 안 몇 줄 — 신규 모듈/추상화를 만들지 않는다.
- 함정: `--source`는 반드시 `prompts`(부모 디렉터리). `prompts/scenario`를 주면 `derive_name()`이 `scenario/` 접두사를 벗겨 `visual_breakdown` 같은 **다른 프롬프트를 새로 만든다**(3회 재발, `PROMPT_POLICY.md:103-107`). `--check`도 동일 함정을 그대로 물려받으므로 문서 예시에 `--source prompts`를 박아둘 것.

**`CLAUDE.md`**
- 현재 "## Prompt Policy" 절에 DEV MODE 문단이 있다(`production` 직접 시딩 명령 + "A/B·골든셋·promotion 게이트를 실행하거나 요구하지 말 것"). 세션 자동 로드 파일이므로 **여기를 안 고치면 해제가 무효**다.

### 아키텍처 제약 (지켜야 할 불변식)

- **AD-10 조용한 강등 금지**: Epic 13의 존재 이유. 이 스토리에서는 "게이트를 되살렸다"는 서술이 실제 커버리지보다 넓어 보이면 위반이다 — 시각 축 누락(AC7), 무게이트 승격 이력(AC4), judge 독립성 미해결(AC8)은 모두 **명시적으로 기록**된다.
- **Rule 2 "Two labels only"**: `production` / `candidate`뿐. 소급 비교용 임시 라벨을 만들지 않는다(AC6의 forward-only 결정 근거).
- **Rule 1 "repo가 진실"**: 프롬프트는 `prompts/<stage>/<name>.md`가 원본, Langfuse는 서빙·라벨·메트릭만. `--check`는 이 불변식의 관측 장치다.
- **게이트 판정 권한은 사람**: `--baseline`은 AI 세션에서 실행 불가(유지). 이 스토리의 게이트 실행 증거는 Jay 수행분 인용으로 채운다.

### Ponytail

- 해제의 못은 **가드 분기 1개 삭제 + 문서 2개 수정 + 테스트 역전**이다. `# ponytail:` 국면 플래그(`YTFLOW_QUALITY_PHASE=dev|tuning` 류) 설정을 만들지 말 것 — 국면 전환은 프로젝트 수명 중 두 번 일어났고(동결/해제), 두 번 다 커밋 하나로 끝났다. 플래그는 "다음에 또 끌 수도 있으니"라는 투기적 수요다.
- `--check`는 신규 스크립트가 아니라 기존 `_unchanged()` 재사용 + 플래그 1개. `migrate()`를 리팩터해 공용 비교 계층을 뽑지 말 것.
- AC5의 가드도 `eval_prompts.py`의 표현을 그대로 복제한다(공용 헬퍼 모듈 신설 금지 — 스크립트 2개, 각각 2줄).

### 최신 기술 정보

- **Langfuse Protected Prompt Labels는 2026-08 현재도 Enterprise 라이선스 전용**(`/ee` 디렉터리 모듈, 라이선스 키 필요). `PROMPT_POLICY.md:109-113`이 2026-07-04에 기록한 판단(자체 호스팅 OSS v3.201.1에는 기술적 락 없음)은 **여전히 유효**하다. 즉 해제 후에도 `production` 라벨 보호는 정책 + 코드 가드(AC5)로만 집행된다 — 이것이 AC5를 권고 기본값으로 두는 이유다.
- 신규 라이브러리/버전 변경 없음. 이 스토리는 자체 스크립트와 문서만 다룬다.

### 이전 작업에서 얻은 교훈 (직접 적용)

Epic 13에는 아직 생성된 선행 스토리 파일이 없다(13-1~13-3 backlog). 대신 이 스토리의 직접 선행 계보에서:

- **6-12**: 가드는 `--baseline`(양방향 A/B)에 걸었다 — `--profile promotion`에만 걸면 `--label X --baseline Y`로 우회된다. 해제도 같은 지점에서 대칭으로 풀어야 한다.
- **6-12 → DEV MODE**: "게이트만 끄고 승격 규칙을 남기면 데드락"이 이 계보의 핵심 교훈. 해제에서 **문서와 코드를 같은 커밋에 묶는 이유**가 이것이다.
- **8-12**: 에이전트가 override를 스스로 켠 사건 → env var는 존재 검사(`in os.environ`)로 봐야 한다(`CLAUDECODE=""`도 마커). AC5의 가드도 truthiness가 아니라 존재로 검사할 것.
- **6-13**: 프롬프트 하나 고치고 전체 골든셋을 재실행하는 낭비를 캐시로 잡았지만, **median 게이트 경로는 캐시를 의도적으로 우회**한다. 게이트 복원 후 "왜 promotion이 캐시를 안 쓰냐"는 착각으로 최적화하지 말 것.
- **5-22 / 8-12**: 두 스토리 모두 게이트 미실행 상태로 production 승격됐고 그 사실을 스토리에 남겼다. 그 기록들이 AC6 스냅샷의 근거 사슬이다.

### Git 이력 (최근 관련 커밋)

```
7141707 docs(epics): 12-2 스펙 변경 — 모델 분리를 2계열로   ← 12.2가 13.4 재검토를 지정
13a47ed docs(epics): Epic 12/13 신설 + Epic 10 흡수         ← 13.4 신설
344fd5f chore(prompts): 적체 candidate 2건 production 승격  ← repo == production 선언
cc82403 chore(story-6.12): 개발 단계 품질 게이팅 OFF        ← 이 스토리가 되돌릴 문서 커밋(코드 변경 없음)
```

`cc82403`이 "코드 변경 없음. eval_prompts.py와 CLAUDECODE/AI_AGENT 가드는 그대로 유지"라고 명시한다 → 해제 시 코드 쪽에서 되돌릴 대상은 **6-12의 것 하나뿐**이다.

### References

- [epics.md#Story 13.4](_bmad-output/planning-artifacts/epics.md#L1376-L1378) — 스토리 원문, 착수 조건
- [epics.md#Story 12.2](_bmad-output/planning-artifacts/epics.md#L1330-L1338) — judge 독립성 재검토를 13.4 시점으로 지정
- [epics.md#L1142](_bmad-output/planning-artifacts/epics.md#L1142) — 6-12 AC1(동결 가드) 구현 기록
- [6-12 story](_bmad-output/implementation-artifacts/6-12-ab-promotion-gate-freeze-deferred-candidate.md) — AC4가 이 스토리의 트리거
- [scripts/eval_prompts.py:834-856](scripts/eval_prompts.py#L834-L856) — 두 가드
- [scripts/eval_prompts.py:612-681](scripts/eval_prompts.py#L612-L681) — `compare()`가 `AXES`만 판정(AC7 근거)
- [scripts/migrate_prompts.py:99-120](scripts/migrate_prompts.py#L99-L120) — `_unchanged()`/`migrate()`
- [tests/test_eval_prompts.py:22-34](tests/test_eval_prompts.py#L22-L34), [:1378-1420](tests/test_eval_prompts.py#L1378-L1420) — 픽스처 + freeze/AI-차단 테스트
- [docs/PROMPT_POLICY.md](docs/PROMPT_POLICY.md) — 배너 `:5-30`, Rules `:32-45`, median 계약 `:62-69`, protected labels `:109-113`
- [deferred-work.md:309](_bmad-output/implementation-artifacts/deferred-work.md#L309) — migrate_prompts 가드 미결 판단(AC5)
- [deferred-work.md:332-334](_bmad-output/implementation-artifacts/deferred-work.md#L332-L334) — `character-generation` production 드리프트(AC6)
- [sprint-status.yaml:214-219](_bmad-output/implementation-artifacts/sprint-status.yaml#L214-L219) — Epic 13 항목, 13-4 요약

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Open Questions (Jay 확인 필요)

1. **AC5 — `migrate_prompts.py --label production`에 AI 세션 차단을 걸까?** 권고 기본값은 "건다"(게이트를 되살리는데 라벨 이동이 무방비면 게이트가 장식). 대가: 지금까지처럼 "Jay가 판단 → AI 세션이 승격 실행"이 불가능해지고 승격 명령은 Jay가 직접 터미널에서 실행해야 한다.
2. **착수 조건의 11-6 처리**: 11-6은 조건부 스토리(11.1–11.5 효과 실측 후 필요성 판정). `backlog` 상태 그대로도 "GPU 스토리 종료"로 볼지, 아니면 "불필요" 판정을 명시적으로 기록하고 넘어갈지.
3. **13-2 미완 상태로 해제할까?** epics 13.4는 시각 축 포함을 해제 범위에 넣었다. 13-2를 먼저 끝내고 해제하는 편이 원문에 충실하지만, 그러면 해제가 13-2에 물린다. AC7은 "미완이면 누락을 명시 기록하고 해제 진행"으로 열어뒀다.
