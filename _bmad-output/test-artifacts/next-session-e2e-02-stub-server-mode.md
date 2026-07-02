# Next Session Prompt 2/3 — E2E stub-server mode (chore, `bmad-quick-dev`)

Copy-paste this into a fresh session, **after** 파일 1(`next-session-e2e-01-framework.md`)이 끝난 뒤. Playwright 프레임워크가 스캐폴딩된 상태를 전제로 함.

---

## 문제

지금까지 만든 `tests/conftest.py`의 `stub_profile` 픽스처(DeepSeek/Qwen/ComfyUI/ffmpeg/Langfuse-Prompt-Hub 5개 시드)는 **pytest monkeypatch**라서 같은 프로세스 안에서만 동작한다. Playwright는 브라우저가 **실제로 떠 있는 서버 프로세스**를 때리기 때문에 in-process monkeypatch가 안 먹힌다. 이 상태로 Playwright E2E를 돌리면 실제 DeepSeek/ComfyUI를 호출하게 되어 (a) 느리고 (b) API 키/로컬 ComfyUI가 없으면 다 실패한다.

## 지켜야 할 제약 (읽어봐)

`_bmad-output/implementation-artifacts/spec-b1-b3-dev-dependencies.md`의 B-2 부분에 이런 제약이 명시돼 있다:

> **Ask First:** Adding any NEW production stub/mock flag (B-2 forbids it — the existing `comfyui_mock`/`qwen_tts_mock` are not to be extended for this).

즉 `src/yt_flow/`쪽 프로덕션 코드에 `if os.getenv("YTFLOW_E2E_STUB")`같은 새 스텁 분기를 넣는 건 이전에 이미 금지된 패턴이다. **프로덕션 코드는 건드리지 않는 방향으로 설계해줘.**

## 권장 접근 (검토해서 진행)

프로덕션 코드를 안 건드리고, `tests/stubs/fakes.py`의 기존 fake들을 재사용하는 **독립 실행 스크립트**를 만드는 방법을 우선 검토해줘:

- 예: `scripts/run_e2e_stub_server.py` — uvicorn을 프로그래매틱하게(`uvicorn.run(...)` 또는 `Server`/`Config` API) 띄우기 **전에**, `tests/stubs/fakes.py`를 import해서 `tests/conftest.py::stub_profile`이 하는 것과 똑같이 5개 모듈 속성을 monkeypatch(또는 그냥 직접 속성 재할당 — pytest monkeypatch 픽스처 없이도 `module.attr = fake_fn` 형태로 동일하게 가능)한 다음 서버를 시작.
- 이렇게 하면:
  - 프로덕션 `src/yt_flow/` 코드는 한 줄도 안 바뀜 (B-2 제약 준수)
  - B-2 fakes를 그대로 재사용 (중복 없음)
  - Playwright는 그냥 평범한 FastAPI 서버를 때리는 것처럼 동작 — 서버 쪽이 stub인지 모름

`tests/`를 프로덕션 스크립트에서 import하는 게 어색하면, 공유 fake 코드를 `tests/stubs/fakes.py`에서 별도 위치(예: `scripts/_e2e_fakes.py` 또는 패키지화)로 옮기고 양쪽(`tests/conftest.py`와 이 스크립트)에서 같은 곳을 가리키게 하는 것도 고려— 다만 이건 기존 B-2 구조를 건드리는 거라 신중하게, 최소 변경으로.

## 해야 할 일

1. 위 접근(또는 검토 후 더 나은 대안)으로 "stub 모드로 뜨는 서버 실행 방법"을 하나 만들기.
2. 실제로 이 서버를 띄우고, `curl`이나 간단한 스크립트로 `POST /runs` → 5회 gate approve → `complete` 상태까지 실제 HTTP로 확인 (SYS-E2E-001의 pytest 버전이 통과하는 것과 동일한 시나리오를, 이번엔 진짜 뜬 서버로).
3. 프론트엔드도 이 서버를 보게 설정 (파일 1에서 정한 base URL 방식에 맞춰서).
4. 짧은 문서화: `scripts/README.md` 또는 스크립트 자체 docstring에 "이건 E2E 전용, 프로덕션에 절대 쓰지 말 것" 명시.
5. 회귀 확인: 기존 `uv run pytest`, `npm test`가 전부 그린인지 재확인 (이 변경이 기존 스위트에 영향 없어야 함).

## 완료 기준

- `python scripts/run_e2e_stub_server.py` (또는 최종적으로 정한 명령)로 서버가 뜨고, 실제 브라우저나 curl로 전체 파이프라인(5개 게이트)을 승인해서 완료 상태까지 갈 수 있음 — 진짜 네트워크/서브프로세스 호출 없이.
- 프로덕션 `src/yt_flow/` diff가 0줄이거나, 있다면 왜 불가피했는지 명확히 설명.
