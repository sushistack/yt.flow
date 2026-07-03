# Story 6.1: 프롬프트 정책 문서 + variant→label 배선

Status: draft

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

- [ ] `docs/PROMPT_POLICY.md` 작성 + CLAUDE.md 참조 추가 (AC: 1, 2)
- [ ] `_call_stage`(scenario_chain.py)에 label 파라미터 추가 — state의 `prompt_variant`에서 도출, orchestrator(scenario.py)가 전달 (AC: 4, 6)
- [ ] candidate 부재 폴백: `get_prompt` 호출부에서 not-found 시 production 재조회 (AC: 5)
- [ ] 시드 스크립트 `--label` 옵션 (AC: 7)
- [ ] Langfuse UI에서 production protected 설정 + 절차 문서화 (AC: 3)
- [ ] 테스트 3종 (AC: 8)

## Dev Notes

- 폴백(AC5)이 이 스토리의 핵심 설계 판단: 이것 덕분에 "프롬프트 하나만 바꿔서 A/B"가 가능해짐 — 전체 7개를 매번 candidate로 재시딩할 필요 없음.
- evaluation/character 프롬프트는 파이프라인 산출물이 아니므로 variant 배선 대상 아님 (production 고정).
- 다른 스테이지 노드(image/tts 등)는 현재 Langfuse 프롬프트를 안 씀 — scenario 체인만 배선하면 됨.
