# Next Session Prompt — SYS-OPS-001 runbook + NFR assessment

Copy-paste this into a fresh session:

---

이전 세션에서 `/bmad-testarch-trace`로 yt.flow 시스템 레벨 트레이스를 완료했다 (게이트 PASS, P0 100%/P1 100%/전체 87.7% 코드 커버리지). 전체 기록은 `_bmad-output/test-artifacts/traceability-matrix.md`에 있음 — 시작하기 전에 이 파일의 "Post-Gate Follow-up" 섹션까지 읽어줘.

이번 세션에서 남은 작업 두 개를 **순서대로** 진행해줘 (순서 중요 — NFR이 이 런북의 결과를 증거로 요구함):

## 1. SYS-OPS-001 런북 실행 (trace overhead ≤10% 실측)

`_bmad-output/test-artifacts/test-design/test-design-qa.md`의 SYS-OPS-001 항목: "Trace-overhead measurement: traced vs. disabled run, record stage durations."

- `YTFLOW_LANGFUSE_ENABLED=true`(기본값)와 `false` 상태로 **동일한 SCP 입력**을 각각 한 번씩 실행해서 전체 wall-clock 시간과 스테이지별 시간을 비교.
- `src/yt_flow/observability.py`에 나온 대로 이 플래그는 **import 시점에 1회 바인딩**되므로, 반드시 별도 프로세스(subprocess)로 두 번 실행해야 함 — 같은 프로세스 안에서 env var만 바꿔서는 반영 안 됨.
- 먼저 환경을 확인해줘: 이 세션에 실제 DeepSeek/Qwen TTS/ComfyUI 접근 권한(API 키, 로컬 ComfyUI 인스턴스)이 있는지. 있으면 실제 전체 파이프라인(E2E, 최대 2시간)으로 측정. 없으면 **거짓 수치를 만들지 말고**, stub_profile 기반으로 측정 가능한 부분만(트레이싱 오버헤드 자체는 실제 API 호출 여부와 무관하게 관찰 가능할 수도 있음 — 판단해서 진행) 측정하고, 무엇을 못 쟀는지 명확히 기록.
- 결과를 `_bmad-output/test-artifacts/traceability-matrix.md`에 SYS-OPS-001 실행 기록으로 추가 (실행 시각, on/off 각각의 시간, overhead %, ≤10% 기준 충족 여부).

## 2. `bmad-testarch-nfr` 실행 (NFR 평가, 마지막)

1번이 끝난 뒌에 실행. 이제 두 축의 증거가 모두 준비됨:
- **Maintainability**: 코드 커버리지 87.7%(api 88.2%/pipeline 90.8%/services 84.3%, 모두 ≥80%) — 이전 세션에서 이미 측정, CI에도 게이트로 연결됨(`pyproject.toml`의 `fail_under=80`).
- **Performance**: 방금 1번에서 측정한 trace overhead 실측치.
- **Reliability**: Langfuse-down 시 파이프라인 정상 진행 + 로그 남김 — 이전 세션에서 테스트로 증명됨 (`tests/services/test_run_service_gate.py::test_trace_setup_failure_is_non_fatal_and_logged` 등).
- **Security**: `/files` 경로 탈출 방지 — 이전 세션에서 테스트로 증명됨 (`tests/api/test_workspace_files.py`).

`bmad-testarch-nfr` 스킬을 실행해서 이 4개 축에 대해 최종 PASS/CONCERNS/FAIL 판정을 받아줘.

---

**참고 — 이전 세션에서 있었던 일 (컨텍스트용):**
트레이스 도중 `pipeline/nodes/__init__.py`가 Story 1.4 스텁 함수를 scenario/image/tts/subtitle에 그대로 연결하고 있어서 (실제 구현은 1.5~1.8에서 이미 끝났는데도) 실제 파이프라인이 항상 실패하는 심각한 버그를 발견해서 고쳤음. 지금은 정상 동작함 — SYS-OPS-001 실측 시 이 부분 문제 없을 것으로 예상되지만, 혹시 이상 동작 보이면 이 히스토리 참고.
