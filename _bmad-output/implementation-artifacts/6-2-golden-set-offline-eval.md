# Story 6.2: 골든셋 + 오프라인 프롬프트 회귀 평가 러너

Status: draft

## Story

As Jay,
I want a fixed golden set of SCP inputs and a cheap offline eval runner that scores a prompt version without running the full pipeline,
so that prompt promotions are gated on "no regression across known inputs", not on one lucky A/B run.

## Context

정책(6.1)의 "골든셋 회귀 통과 후 승격" 규칙을 실체화한다. **핵심 인식: 창작 파이프라인의 골든셋은 정답 출력 셋이 아니다** — 정답이 존재하지 않으므로, 업계 표준은 ①고정 입력 + ②평가 루브릭(LLM-as-judge) + ③버전별 점수 추이 비교. 우리는 셋 다 이미 부품이 있음: SCP 데이터, Epic 4 평가 서비스(judge 프롬프트+규칙 기반), Langfuse(Datasets + dataset run 기능이 정확히 이 용도).

비용 통제가 설계의 중심: full 파이프라인(이미지 45장+TTS+비디오)으로 회귀를 돌리면 회당 수십 분+GPU — **scenario 스테이지만** 돌리면 DeepSeek 12~20콜(~3분, 몇십 원)로 끝남. 프롬프트 변경의 품질 신호는 대부분 scenario 산출물에서 측정 가능.

## Acceptance Criteria

1. **Given** Langfuse Datasets, **Then** `golden-scps` 데이터셋에 고정 SCP 2~3개(예: SCP-096, SCP-173 — 이미 실전 검증된 입력)가 아이템으로 시딩된다
2. **Given** `scripts/eval_prompts.py --label candidate`, **When** 실행, **Then** 각 골든셋 아이템에 대해 **scenario 체인만** 실행한다 — 이미지/TTS/비디오 스테이지 없음, DB run 생성 없음, 게이트 없음
3. **Given** 체인 산출물(scenes/shots), **Then** Epic 4 평가 축(LLM-as-judge 루브릭 + 규칙 기반 지표 중 scenario에 적용 가능한 것)으로 점수화되고, Langfuse dataset run에 score로 기록된다 — 버전별 점수 추이를 Langfuse UI에서 비교 가능
4. **Given** `--label candidate --baseline production`, **Then** 두 라벨을 같은 골든셋에 대해 실행·채점하고 축별 점수 비교표를 출력한다 — 승격 판단의 근거 산출물
5. **Given** 체인 실패(스테이지 에러), **Then** 해당 아이템은 실패로 기록되고 나머지 아이템은 계속 진행 — 실패 자체가 회귀 신호
6. 러너는 순수 스크립트 — 파이프라인 코드(nodes/services)에 eval 전용 분기를 추가하지 않는다. scenario_node를 함수로 직접 호출
7. 문서화: 정책 문서(6.1)의 골든셋 절에 실행 커맨드와 승격 기준(예: 전 축 baseline 대비 하락 없음 + judge 총점 동등 이상) 기록

## Tasks / Subtasks

- [ ] 골든셋 선정 + Langfuse Dataset 시딩 스크립트/절차 (AC: 1)
- [ ] `scripts/eval_prompts.py`: 골든셋 로드 → scenario_node 직접 호출(label 주입은 6.1 배선 재사용) → 평가 → dataset run score 기록 (AC: 2, 3, 5, 6)
- [ ] scenario 적용 가능 평가 축 선별 — eval_service의 judge/규칙 기반 중 scenario 산출물로 계산 가능한 것 재사용, 신규 축 발명 금지 (AC: 3)
- [ ] `--baseline` 비교 모드 + 비교표 출력 (AC: 4)
- [ ] 정책 문서 골든셋 절 갱신 (AC: 7)
- [ ] 테스트: 카세트 기반으로 러너 조립 검증 (실 API 없이 — 기존 `_STAGE_CASSETTES` 재사용)

## Dev Notes

- 의존: Story 6.1 (label 배선, 정책 문서).
- 골든셋 확장(3개→N개)은 필요할 때 아이템 추가로 끝 — 러너 코드 불변.
- full-파이프라인 골든 런(이미지 정합성까지 회귀)은 의도적 범위 밖 — 그건 프롬프트가 아니라 워크플로우/모델 변경의 회귀 도구라 별개 문제이고, 비용 구조가 다름. 필요해지면 별도 발의.
- judge의 자기 편향(같은 계열 모델이 자기 출력 선호) 이슈는 Epic 4에서 이미 다룬 설계 그대로 따름 — 이 스토리에서 재설계하지 않음.
