# Epic 6 Context: Prompt Ops — 프롬프트 버저닝·평가 정책

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

앞으로의 품질 개선을 프롬프트 반복 작업으로 안전하게 운영할 수 있도록, 프롬프트 변경을 버전·라벨·평가 게이트를 거친 승격 프로토콜로 정착시킨다. Langfuse의 프롬프트 버전, 라벨, Dataset, trace 연결 기능을 활용해 별도 관리 인프라 없이 변경 이력과 품질 근거를 남기며, 실제 A/B 변형 배선부터 비용 관측, 구조화 출력 복원력, 통계적으로 유효한 승격 판정까지 하나의 운영 체계로 묶는다.

## Stories

- Story 6.1: 프롬프트 정책 문서 + variant→label 배선
- Story 6.2: 골든셋 + 오프라인 프롬프트 회귀 평가 러너
- Story 6.3: DeepSeek 프롬프트 캐시-히트 최적화 + 토큰/비용 관측성
- Story 6.4: 시나리오 체인 YAML 출력 전환 + 스테이지 단위 bounded 재시도
- Story 6.5: 재시도 신 단위 부분 수정
- Story 6.6: 계층형 프롬프트 평가 게이트
- Story 6.7: YAML 문법 전용 경량 repair 경로 분리
- Story 6.8: judge 채점 bounded retry — 단일 malformed 응답이 항목 전체를 죽이는 문제 해소
- Story 6.9: writing_scene_repair truncation 근본원인 + SCP-173/096 축 회귀 조사·수정
- Story 6.10: 통계적 promotion 게이트 + SCP-049 scoped-repair 견고성 (6-3/6-4 언블록)

## Requirements & Constraints

- 저장소의 프롬프트 파일이 원본이며 Langfuse Prompt Hub에는 버전으로 게시한다. 파이프라인은 실행 시 프롬프트를 가져와야 하고, 프롬프트 변경은 코드 변경이나 서비스 재시작 없이 다음 실행부터 적용되어야 한다. 운영 UI에서의 직접 편집은 금지한다.
- `production`과 `candidate` 라벨을 변경 프로토콜의 핵심으로 사용한다. 실행의 prompt variant는 실제 라벨 선택에 연결되어야 하며, candidate가 없는 프롬프트는 production으로 폴백해 부분 실험을 허용한다.
- 승격 근거는 정답 문자열이 아닌 고정 SCP 입력, 동일 루브릭, 점수 추이로 구성된 골든셋 평가다. 빠른 단일 canary `smoke`는 개발 피드백 전용이고 승격 권한이 없으며, `promotion`만 전체 골든셋의 candidate 대 production 비교를 수행한다.
- 평가 축은 atmosphere, narrative coherence, article fidelity이며 각 축은 1–5점이다. 개별 judge 응답은 반복 샘플링하고, malformed 응답은 해당 호출에만 bounded retry를 적용한다. 일부 샘플 실패는 성공 표본으로 집계하되 과반 실패는 해당 항목 실패로 명시해야 한다.
- 생성 결과의 실행 간 편차 때문에 단일 음수 델타를 전체 실패로 처리하지 않는다. promotion은 각 골든 항목을 최소 3회 생성하고 중앙값 델타로 판정한다. 일부 실행의 하드 실패는 기록·격리하며, 특정 항목에서 과반 실행이 실패하면 그 항목은 FAIL이다. 품질 하락이 확인되면 production 승격을 강행하지 않는다.
- 시나리오 체인의 자유 텍스트 구조화 출력은 YAML block literal을 사용한다. 파싱 실패와 스키마/내용 검증 실패를 구분해 각각 문법 전용 repair와 전체 스테이지 재생성으로 라우팅하며, 모든 복구는 1회로 제한하고 재실패는 기존 오류 표면화 계약을 유지한다.
- 재작성은 가능한 한 문제가 있는 신만 대상으로 하고 정상 신은 재사용한다. scoped repair는 반환 순서가 달라도 요청한 신 집합의 커버리지를 검증할 수 있어야 하며, truncation이나 복구 가능한 coverage 오류는 제한된 fallback으로 처리한다.
- 모든 LLM 호출은 렌더링된 프롬프트, 원시 응답, 지연, 토큰 수를 추적한다. DeepSeek 사용량에는 prompt/completion 및 cache hit/miss 토큰을 스테이지 메타데이터로 남겨 비용 개선을 실측할 수 있어야 한다. 관측성 장애는 파이프라인 실패를 유발하지 않는다.

## Technical Decisions

- Langfuse의 네이티브 labels, protected labels, Datasets, trace-to-version 연결을 사용하고 자체 프롬프트 관리 인프라는 만들지 않는다. 프롬프트 버전 이력과 변경 감사는 Langfuse에서 유지한다.
- A/B는 그래프 내부 분기가 아니라 같은 SCP 입력으로 실행되는 독립 run 두 개이며 `ab_pair_id`로 연결한다. `prompt_variant`는 PipelineState와 run 메타데이터에 유지되고 실제 프롬프트 라벨 선택까지 전달되어야 한다.
- DeepSeek는 OpenAI 호환 클라이언트로 호출하며 모델 식별자는 설정에 고정한다. 캐시 최적화는 호출 단계 재병합이 아니라 템플릿에서 불변 접두사를 가변 입력보다 앞에 배치하는 방식으로 수행한다. 프롬프트 지시 의미를 바꾸는 변경은 별도 품질 검증 대상이다.
- YAML 파서는 모델이 붙인 코드 펜스를 방어적으로 제거해야 한다. YAML 문법 오류는 원문과 오류 위치를 넣은 작은 syntax-repair 프롬프트로 고치고, 스키마 위반은 직전 오류를 포함해 동일 스테이지만 재생성한다.
- 평가 결과와 비교 점수는 Langfuse trace에 연결한다. 판정 리포트에는 성공 점수뿐 아니라 재시도, 결측, 하드 실패의 횟수와 사유도 남겨야 한다.

## Cross-Story Dependencies

- Story 6.1은 실제 A/B 실행을 가능하게 하는 필수 배선이며 프롬프트를 변경하는 후속 품질 작업보다 선행한다. Story 6.2의 골든셋 러너는 이후 모든 candidate 승격 근거가 된다.
- Story 6.3과 6.4는 같은 시나리오 프롬프트 템플릿들을 수정하므로 병렬 편집하지 말고 먼저 완료된 변경 위에 다음 작업을 적용한다.
- Story 6.6–6.10은 6.3/6.4 candidate의 promotion 과정에서 드러난 타임아웃, YAML, judge, truncation, 생성 편차 문제를 순차적으로 해소한다. 최종 production 승격은 통계 게이트와 scoped-repair 복원력이 검증된 뒤에만 가능하다.
- 자동 라벨 승격은 의도적으로 범위 밖이다. 현재는 평가 통과 후 Langfuse에서 수동 승격하며, 빈도가 운영 부담이 될 때만 자동화를 별도로 발의한다.
