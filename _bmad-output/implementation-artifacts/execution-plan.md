# yt.flow — Execution Plan

Parallel tracks and code review batches derived from epic dependency graph.

---

## Dependency Graph

```
1.1 ──[BLOCKER]──────────────────────────────────────────────────────────┐
1.2 ──────────────────────────────────────────────────┐                  │
                                                       ▼                  ▼
                                                  1.4 ────────────────> 1.3
                                                   │
                                                   ▼
                                                  1.5
                                                 /    \
                                              1.6      1.7
                                           (image)    (tts)
                                                        │
                                                       1.8 (subtitle)
                                                        │
                                                       1.9 (video)
                                                        │
                                                       1.10 (resume/restart)
```

> 1.6과 1.7은 유일한 에픽 내 병렬 실행 지점.

---

## Parallel Execution Tracks

아래 트랙들은 동시에 진행 가능. 단, 트랙 내부 순서는 지켜야 함.

### Track A — Pipeline Core
```
1.1 → 1.3 → 1.4 → 1.5 → 1.7 → 1.8 → 1.9 → 1.10
```
메인 블로킹 경로. 다른 모든 트랙의 기반.

### Track B — Scaffold (Track A와 동시 시작)
```
1.2
```
1.4 시작 전에만 완료되면 됨. 독립 실행 가능.

### Track C — Frontend Foundation (즉시 시작 가능)
```
3.1 → 3.2
```
백엔드 의존성 없음. 프로젝트 시작과 동시에 진행 가능.

### Track D — Pipeline Node Parallelism (1.5 완료 후)
```
1.5 완료 시점: 1.6 || 1.7 동시 실행 가능
```
1.6(image_node)과 1.7(tts_node)은 둘 다 1.5에만 의존.
단, 1.8은 1.7 완료 후 시작.

### Track E — API Layer (1.4 완료 후 시작 가능)
```
2.1 → 2.2 → [2.3 || 2.4 || 2.5]
```
2.1은 stub graph가 있는 1.4 완료 시점부터 병렬 진행 가능.
2.3, 2.4, 2.5는 2.2 완료 후 병렬 처리 가능.

### Track F — Frontend Screens (2.x + 3.2 완료 후)
```
3.3 → 3.4 → 3.5
```
각 화면은 해당 API 엔드포인트 완료에 의존.

### Track G — A/B Evaluation (1.10 + 2.1 완료 후)
```
4.1 → 4.2 → 4.3 → 3.6
```
완전한 파이프라인 실행 결과(run)가 있어야 평가 가능.

---

## Earliest Parallel Start Points

| 시점 | 동시 실행 가능 스토리 |
|------|----------------------|
| Day 0 (즉시) | **1.1** + **1.2** + **3.1** |
| 1.1 완료 후 | **1.3** 추가 |
| 1.2 + 1.3 완료 후 | **1.4** 시작 (합류점) |
| 1.4 완료 후 | **1.5** + **2.1** + **3.2** |
| 1.5 완료 후 | **1.6** + **1.7** (유일한 노드 레벨 병렬) |
| 2.1 완료 후 | **2.2** + **4.1** |
| 2.2 완료 후 | **2.3** + **2.4** + **2.5** |

---

## Code Review Batches

리뷰어가 동일한 레이어·패턴을 한 컨텍스트에서 볼 수 있도록 묶음.
24개 스토리 → 8개 배치.

### Batch 1 — 환경 · 스캐폴드
`1.1` + `1.2`

- 공통점: 비즈니스 로직 없음. 설정, 타입 정의, 디렉터리 구조.
- 리뷰 포인트: YTFLOW_ prefix 규칙, Pydantic 모델 필드, uv 의존성 충돌 여부.

### Batch 2 — Langfuse 연결 · LangGraph 토폴로지
`1.3` + `1.4`

- 공통점: 외부 서비스(Langfuse Prompt Hub) 연동 + 그래프 기반 구조 설정.
- 리뷰 포인트: Prompt Hub 키 명명 일관성, AsyncSqliteSaver 설정, 10개 노드 토폴로지 정확성.

### Batch 3 — LLM 파이프라인 노드 (동일 패턴)
`1.5` + `1.6` + `1.7`

- 공통점: `@observe` 스팬, `PipelineState` 변이, 오류 시 `state.error` 세팅. 세 노드 모두 동일한 뼈대.
- 리뷰 포인트: @observe span 이름 일관성, 토큰/레이턴시 캡처 누락 여부, 에러 핸들링 패턴 통일.

### Batch 4 — 미디어 처리 · 재개 로직
`1.8` + `1.9` + `1.10`

- 공통점: LLM 미사용. subprocess(FFmpeg), forced alignment, checkpoint 재개.
- 리뷰 포인트: YTFLOW_ALIGNER 전략 패턴, FFmpeg 종료코드 처리, trace_id 연속성(FR-12).

### Batch 5 — FastAPI 앱 · SSE 인프라
`2.1` + `2.2`

- 공통점: API 레이어 기반. lifespan, SQLModel 테이블, 이벤트 스트림 구조.
- 리뷰 포인트: AD-4(서비스 레이어 순수 함수), asyncio.Queue 등록/해제, SSE 4개 이벤트 타입 스펙.

### Batch 6 — Gate · Stage Control · Data Access API
`2.3` + `2.4` + `2.5`

- 공통점: 파이프라인 상태 조작 엔드포인트. 게이트 상태머신, 재시도, artifact 읽기.
- 리뷰 포인트: AD-3(interrupt/resume 흐름), PATCH 유효 대상(scenario·subtitle만), LangGraph state 직접 읽기(AD-7).

### Batch 7 — React 디자인 시스템 · 공통 컴포넌트
`3.1` + `3.2`

- 공통점: 비즈니스 로직 없음. CSS 토큰, shadcn 설정, 세 가지 재사용 컴포넌트.
- 리뷰 포인트: UX-DR1~6 토큰 값 정확성, aria-current, pointer-events:none 미구현 스테이지.

### Batch 8 — UI 화면 전체
`3.3` + `3.4` + `3.5` + `3.6`

- 공통점: 실제 화면. API 연동, SSE 클라이언트, 게이트 컨트롤, A/B 뷰.
- 리뷰 포인트: SSE 상태 반영, window.confirm 언세이브 경고, role="alert" 재시도 확인, A/B 사이드바이사이드 레이아웃.
- 규모가 크므로 3.3+3.4 / 3.5+3.6 으로 반씩 나눠도 무방.

### Batch 9 — A/B 평가 백엔드
`4.1` + `4.2` + `4.3`

- 공통점: A/B 기능 전체. 런 생성 → 평가 → 결과 저장.
- 리뷰 포인트: AD-6(그래프 레벨 분기 없음 확인), OQ-6 pairwise bias 처리, quality floor 조건, Langfuse trace 연결.

---

## Summary

| 항목 | 수량 |
|------|------|
| 병렬 실행 가능 최대 동시 스토리 | 3개 (Day 0: 1.1 + 1.2 + 3.1) |
| 노드 레벨 병렬 지점 | 1개 (1.6 ∥ 1.7) |
| API 레벨 병렬 지점 | 1개 (2.3 ∥ 2.4 ∥ 2.5) |
| 리뷰 배치 수 | 9개 (스토리 24개 → 64% 감소) |
| 가장 긴 크리티컬 패스 | 1.1 → 1.3 → 1.4 → 1.5 → 1.7 → 1.8 → 1.9 → 1.10 (8 스토리) |
