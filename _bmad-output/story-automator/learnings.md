## Run 2026-08-01 — Epic 11/8 무인 구간 (11.1→11.4, 8.18)

**Stats:** 5/5 stories done, 5 review cycles (each passed cycle 1), 1 dev retry (11.3 monitor timeout mid-work), 0 user escalations.

**What worked:**
- 리서치 문서(2026-08-01 quality strategy)를 extra_instruction으로 create/dev 세션에 주입 → 4/5 스토리가 자발적으로 References에 인용. 8.18만 누락되어 오케스트레이터가 한 줄 보강.
- monitor-session 타임아웃(max_polls_exceeded)이 잦았으나 소스 오브 트루스(스토리 Status/체크박스/sprint-status) 검증으로 전부 복구 — v1.9.0 규칙이 실제로 유효.

**Gotchas:**
- 첫 tmux 세션은 Claude CLI 신뢰/bypass 다이얼로그에 걸림 — tmux send-keys로 수동 승인 필요했음. Down과 Enter를 한 번에 보내면 키가 뭉개져 "No, exit" 선택됨 → 키는 분리 전송(sleep 2 간격).
- 모니터 타임아웃 시 세션이 아직 작업 중일 수 있음(11.3 attempt 1) — kill 전에 sprint-status/스토리 파일 먼저 확인할 것.

## Run: 2026-08-08

**Epic:** 대본·나레이션 품질 — 리텐션 구조 + 모델 분리 + 접지 게이트
**Stories:** 12.1, 12.2, 12.3, 12.4, 12.5

### Patterns Observed
- 결정론적 계약과 좁은 fallback은 효과적이었지만, 실제 결함은 transport·checkpoint/gate·stdout/filesystem·실 ffmpeg 같은 경계에서 반복됐다.
- Claude TUI가 작업 완료 후 프롬프트에 머무는 경우가 잦아 monitor timeout만으로 실패 판정하면 안 됐다. story/sprint 상태와 산출물 검증이 복구 기준이었다.
- 테스트 수와 과거 상태 설명이 여러 스토리에서 드리프트했다. 최종 수치는 명령 결과로 생성해야 한다.
- Story 12.5의 사람 게이트는 한 번의 정당한 escalation이었다. 사용자의 종합 선호는 기록하되 제공되지 않은 축별 점수는 추론하지 않았다.

### Code Review Insights
- Common issues: provider response variants, rejected rationale leakage, scene-boundary aggregation, fallback observability, blind-package identity leakage, error-type contract bypass.
- Average cycles to clean: 1.0 (5 stories, 5 review cycles).

### Timing Estimates
- create-story: existing files verified; no generation sessions required.
- dev-story: approximately 30–40 minutes for implementation-heavy stories; Story 12.5 additionally required a human listening pause.
- code-review: approximately 12–26 minutes per cycle, plus full-suite runtime.

### Recommendations for Future Runs
- 실제 경계 E2E와 mutation checks를 개발 단계부터 포함한다.
- 최종 verification summary와 sprint-status 설명을 command-derived로 만든다.
- judge-provider independence를 Story 13.4 promotion 권한 복구 전에 결정한다.
- Qwen clone 운영 전환은 별도 승인으로 처리하고 약 34% 속도 차이의 전체 에피소드 페이싱 영향을 먼저 측정한다.
