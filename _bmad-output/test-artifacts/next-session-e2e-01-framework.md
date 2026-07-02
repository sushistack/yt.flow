# Next Session Prompt 1/3 — Playwright framework setup (`bmad-testarch-framework`)

Copy-paste this into a fresh session. This is step 1 of 3 — do NOT proceed to stub-server-mode or test generation in this same session; each is its own session by design.

---

yt.flow는 지금까지 백엔드 pytest(468개) + 프론트엔드 Vitest 컴포넌트 테스트(94개)만 있고, **브라우저 레벨 E2E는 전무**하다. `_bmad-output/test-artifacts/test-design/test-design-qa.md`의 SYS-E2E-002 항목("UI smoke on stub backend: dashboard → create run → approve gate → artifact panel per stage type")이 이걸 위해 이미 계획돼 있었지만 "optional — build only if UI regressions recur"로 미뤄져 있었다. 이제 만들기로 함.

## 이번 세션에서 할 일

`bmad-testarch-framework` 스킬을 실행해서 Playwright 테스트 프레임워크를 스캐폴딩해줘.

**참고할 컨텍스트:**
- `test-design-qa.md`의 "Dependencies & Test Blockers" 섹션에 이미 `@seontechnologies/playwright-utils`를 쓴 예제 코드가 있음:
  ```typescript
  import { test } from '@seontechnologies/playwright-utils/api-request/fixtures';
  import { expect } from '@playwright/test';

  test('@P0 @API stub run reaches first gate', async ({ apiRequest }) => {
    const { status, body } = await apiRequest({
      method: 'POST',
      path: '/runs',
      body: { scp_id: 'SCP-096', scp_text: 'stub text' },
    });
    expect(status).toBe(201);
    ...
  });
  ```
  이 컨벤션(`playwright-utils` 사용)을 따라가는 걸 우선 검토해줘. `_bmad/tea/config.yaml`의 `tea_use_playwright_utils: true` 설정도 이미 그렇게 돼 있음.
- 프론트엔드는 `frontend/` 아래 Vite + React + Tailwind + shadcn, 이미 `frontend/vitest.config.ts`가 컴포넌트 테스트용으로 분리돼 있음(Vite 8 관련 esbuild jsx automatic 이슈로 분리됨 — 참고: story 3.2 메모). Playwright 설정은 이거랑 별개로 최상위 또는 `frontend/e2e/`에 둘지 판단해서 진행.
- 백엔드는 FastAPI, `src/yt_flow/api/main.py`가 앱 엔트리포인트. 프론트는 빌드된 정적 파일을 FastAPI가 `/app`에서 서빙하는 구조(story 3.1 참고) — 로컬 dev 서버(vite dev)와 별개로 "FastAPI가 서빙하는 빌드 결과물"을 대상으로 테스트할지, dev 서버 대상으로 할지도 결정해서 진행.

## 이번 세션 스코프 (하지 마)

- **서버를 stub 모드로 띄우는 방법은 아직 만들지 마** — 그건 다음 세션(파일 2)에서 별도로 설계한다. 이번엔 Playwright 자체의 설정/컨벤션/디렉토리 구조/CI 스캐폴딩만.
- **실제 테스트 케이스는 쓰지 마** — 그것도 다음-다음 세션(파일 3, `bmad-qa-generate-e2e-tests`)에서 기능별로 진행한다. 이번엔 프레임워크가 정상 동작하는지 확인하는 최소 smoke(예: 빈 페이지 로드 확인 정도)만 있으면 충분.
- CI에는 **nightly job**으로 넣을 계획(PR 블로킹 아님) — test-design의 Execution Strategy 참고. 이번 세션에서 CI wiring까지 할지, 다음 세션으로 미룰지는 판단해서 진행.

## 완료 기준

- `npx playwright test` (또는 프로젝트 컨벤션에 맞는 명령)이 최소 1개 smoke 테스트로 로컬에서 그린.
- 디렉토리 구조/설정 파일이 커밋 가능한 상태.
- 다음 세션(파일 2)이 참고할 수 있게, 이번 세션에서 결정한 것들(디렉토리 위치, base URL 설정 방식, dev-server vs FastAPI-served 선택)을 짧게 요약해서 남겨줘.
