# Next Session Prompt 3/3 — Generate E2E tests per journey (`bmad-qa-generate-e2e-tests`)

Copy-paste this into a fresh session, **after** 파일 1(framework)과 파일 2(stub-server-mode)가 끝난 뒤. 이 세션은 Playwright 프레임워크 + stub 서버가 이미 동작하는 상태를 전제로 함.

---

`bmad-qa-generate-e2e-tests` 스킬로 이미 구현된 4개 에픽의 핵심 사용자 여정을 커버해줘. **한 번에 다 하지 말고, 아래 여정 하나씩 순서대로 `bmad-qa-generate-e2e-tests` 스킬을 반복 실행**해줘 (스킬 자체가 "create qa automated tests for [feature]" 형태로 기능 단위 호출을 기대함).

각 여정 실행 전에 관련 스토리 파일(`_bmad-output/implementation-artifacts/`)을 참고해서 실제 acceptance criteria를 반영해줘 — 여기 적힌 건 스코프 힌트일 뿐, 정확한 화면 요소/셀렉터는 실제 프론트엔드 코드(`frontend/src/`)를 봐야 함.

## 여정 1 (P0) — 대시보드 → Run 생성 → Gate 승인 → 완료

test-design-qa.md의 SYS-E2E-002가 정의한 baseline 그대로:
> dashboard → create run → approve gate → artifact panel per stage type

관련 스토리: 3-3(Dashboard+SCP Picker), 3-4(Run Detail+Artifact Panel), 3-5(Gate Controls+Retry+SSE).

시나리오: 대시보드 로드 → SCP 검색/선택 → Run 생성 → SSE로 상태 실시간 업데이트 확인 → 5개 스테이지 게이트 각각 승인 → 스테이지별 아티팩트 패널(이미지/오디오/자막/비디오) 렌더 확인 → 최종 완료 상태 확인.

## 여정 2 (P1) — Gate 거부/재시도/편집 흐름

관련 스토리: 3-5(Gate Controls+Retry+SSE), 2-4(백엔드 retry/edit — 이미 API 레벨은 커버됨, 이번엔 UI 레벨).

시나리오: 게이트 거부 → 재시도 트리거 → 아티팩트 인라인 편집(scenario/subtitle) → 편집 후 재승인 → 하위 스테이지 재실행 확인. B-1 concurrency guard(진행 중일 때 버튼 비활성화 등 UI 반영) 확인 포함.

## 여정 3 (P1) — A/B 비교

관련 스토리: 3-6(AB Comparison+Accessibility), 4-1(AB Run Creation), 4-3(Results+Winner).

시나리오: 완료된 Run에서 A/B 생성 → 두 번째 variant 완료까지 대기(또는 stub이라 빠르게 완료됨) → 비교 화면에서 axis scores/winner 표시 확인 → 접근성(키보드 네비게이션 등) 기본 확인.

## 여정 4 (P2) — 캐릭터 관리

관련 스토리: 3-7(Character Management UI), 1-11(Character Domain Reference Search), 1-12(Multi-Angle Character Generation).

시나리오: 캐릭터 목록 → 신규 캐릭터 생성 → 참조 이미지 검색 → 앵글 생성 → 갤러리에서 결과 확인.

## 우선순위/스코프 조정

- 시간이 부족하면 **여정 1만이라도 확실하게** — 이게 test-design이 원래 요구했던 최소 SYS-E2E-002 스코프임.
- 여정 2~4는 상황 봐서 이후 세션으로 나눠도 됨 — 한 세션에 몰아넣지 말 것 (각 여정마다 셀렉터 디버깅 시간이 꽤 들 수 있음).

## CI 배치

test-design-qa.md의 Execution Strategy에 따라 **nightly job, PR 블로킹 아님**으로. 파일 1에서 CI wiring을 이미 했으면 job 트리거만 확인, 안 했으면 이번에 `.github/workflows/test.yml`에 스케줄 job 하나 추가.

## 완료 기준

- 각 여정별로 최소 1개 이상의 Playwright 테스트가 stub 서버 대상으로 로컬에서 그린.
- `_bmad-output/test-artifacts/traceability-matrix.md`의 SYS-E2E-002 항목을 "optional, 미구축"에서 "구축됨"으로 업데이트.
