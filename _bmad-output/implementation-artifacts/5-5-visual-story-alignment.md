# Story 5.5: 비주얼 정합성 — visual_breakdown 컨텍스트 강화 + SCP 참조 이미지

Status: draft

## Story

As Jay,
I want generated images to actually depict what the narration describes,
so that viewers see the story, not generic horror imagery.

## Context (2026-07-03 라이브 리뷰 피드백 #4)

실전 런(SCP-096)에서 이미지가 스토리와 안 맞음. 유력 원인: visual_breakdown이 문장 단위로 프롬프트를 만들면서 씬 전체 맥락·등장 개체의 시각적 정체성을 잃음 — "SCP-096"이 프롬프트에 있어도 SD 모델은 그게 뭔지 모름.

**보류된 대안** (deferred-work.md 참조): DuckDuckGo 검색 이미지 + LoRA img2img 변형 — 저작권/수익화 리스크, 스타일 비일관성, 검색 품질 통제 불가로 보류. 축소판(SCP 위키 공식 이미지만 참조)은 본 스토리 Phase 2에 포함.

## Acceptance Criteria

### Phase 1 — 프롬프트 컨텍스트 강화

1. **Given** visual_breakdown 스테이지, **When** 각 씬 처리, **Then** 프롬프트에 다음이 주입된다: ①스토리 전체 로그라인(research/structure 산출물), ②해당 씬의 서사적 역할, ③**개체 시각 정의서**(entity sheet) — 대상 SCP의 외형을 한 번 정의하고 모든 shot 프롬프트에 동일 토큰으로 반복
2. **Given** 개체 시각 정의서, **Then** research 단계 산출물에서 생성된다 (SCP 원문 묘사 기반, 예: SCP-096 = "tall pale emaciated humanoid, elongated arms, hollow eyes") — 모든 shot에서 동일 문구 사용으로 shot 간 개체 일관성 확보
3. **Given** shot 프롬프트, **Then** 구도 지시(shot type: wide/close-up/POV 등)가 명시적으로 포함된다 — 현행 프롬프트의 자유 서술 대신 구조화
4. 기존 계약 불변: sentence↔shot 1:1, 빈 image_prompt 병합 로직, 카세트 테스트 규약

### Phase 2 — SCP 위키 공식 이미지 참조 (IPAdapter)

5. **Given** 대상 SCP의 위키 공식 이미지(CC BY-SA — 합법, 출처 표기 필요), **When** ComfyUI 워크플로우에 IPAdapter 참조로 주입, **Then** 생성 이미지가 공식 이미지의 개체 외형을 따른다
6. **Given** 공식 이미지가 없거나 다운로드 실패, **Then** Phase 1 프롬프트만으로 폴백 — 런이 죽지 않음
7. **Given** CC BY-SA 의무, **Then** 참조 이미지를 쓴 런의 메타데이터에 출처 URL이 기록된다 (영상 설명란 표기용)

### 검증 — Epic 4 A/B

8. **Given** Phase 1 구현 완료, **When** 동일 SCP로 A(현행)/B(강화) A/B 런 실행, **Then** 평가 서비스 + 육안 게이트 리뷰로 정합성 개선을 확인 — 이것이 본 스토리의 완료 판정
9. Phase 2는 Phase 1 결과가 불충분할 때만 진행 (A/B 결과로 판단)

## Tasks / Subtasks

- [ ] research 프롬프트에 entity sheet 산출 추가 (`prompts/scenario/research.md` + Langfuse 재시드) (AC: 2)
- [ ] visual_breakdown 프롬프트 재작성: 로그라인/씬 역할/entity sheet 주입 + 구도 필드 구조화 (AC: 1, 3)
- [ ] `scenario_chain.py` `visual_breakdown_step` 변수 배선 (research 산출물 전달) (AC: 1)
- [ ] 카세트 갱신 + 기존 테스트 통과 확인 (AC: 4)
- [ ] A/B 런 실행·평가 (AC: 8)
- [ ] (조건부) Phase 2: SCP 위키 이미지 fetcher + IPAdapter 워크플로우 변형 + 출처 메타데이터 (AC: 5-7)

## Dev Notes

- **visual_breakdown max_tokens 잘림 이슈 선결**: 컨텍스트 주입으로 프롬프트가 길어지면 기존 deferral(8192 토큰 잘림, run 7218aab2에서 실제 발생)이 더 자주 터짐. 이 스토리 첫 커밋에서 `YTFLOW_DEEPSEEK_MAX_TOKENS` 상향 또는 출력 축약을 함께 처리할 것.
- Phase 2는 Story 5.2의 워크플로우 작업과 겹침(둘 다 ComfyUI 워크플로우 변형) — 5.2 완료 후 착수가 순서상 자연스러움.
- Epic 1의 캐릭터 참조 검색 인프라(1.11 reference search)가 이미 존재 — Phase 2 fetcher는 신규 작성 전에 재사용 가능성 확인.
