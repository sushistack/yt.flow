# Next Session Prompt — A/B 평가(evaluate_ab) 배선 + 계약 불일치 수정 (`bmad-quick-dev`)

Copy-paste this into a fresh session:

---

`bmad-quick-dev`로, Epic 4(A/B 평가) 파이프라인의 마지막 연결 고리를 고쳐줘. Journey 3 (`e2e/ab-comparison-accessibility.spec.ts`, A/B 비교 화면 Playwright 테스트)를 만들다가 발견한 문제로, **두 가지가 겹쳐 있음** — 트리거만 달면 안 되고 계약 불일치도 같이 고쳐야 실제로 동작함.

## 문제 1 (더 근본적): `evaluate_ab()`의 페어 검증이 실제 데이터 모양과 안 맞음

`src/yt_flow/services/eval_service.py:343` `_validate_pair(run_a_id, run_b_id)`:

```python
def _validate_pair(run_a_id: str, run_b_id: str) -> str:
    status_a, pair_a = _load_run_meta(run_a_id)
    status_b, pair_b = _load_run_meta(run_b_id)
    ...
    if not pair_a or pair_a != pair_b:
        raise ValueError(...)
    return pair_a
```

이건 **A run과 B run이 동일한 `ab_pair_id` 값을 각자 들고 있어야** 통과한다. 하지만 실제로 story 4.1이 구현한 데이터 모델(`src/yt_flow/services/run_service.py:334` `create_ab_run`, `_bmad-output/implementation-artifacts/4-1-ab-run-creation.md` AC1)은:

- **B run**: `ab_pair_id = source_run_id` (A run의 `id`를 그대로 가리킴)
- **A run**: `ab_pair_id`는 계속 `None`

즉 `pair_a`(=None)가 항상 falsy라서 `_validate_pair`는 **실제 프로덕션 A/B 페어에 대해 항상 `ValueError`를 던진다.** `tests/services/test_eval_service.py:192` `_seed_run()`이 A/B 양쪽에 동일한 합성 `ab_pair_id="pair-1"`을 심어서 테스트하기 때문에 이 불일치가 지금까지 안 드러났다 (유닛 테스트는 통과, 실제 데이터로는 항상 실패).

**할 일**: `_validate_pair`(및 필요하면 `_load_run_meta`, `evaluate_ab`의 페어 식별 방식 전체)를 실제 모델에 맞게 고쳐라 — "두 run이 서로를 가리키는 A/B 쌍인지" 판정 기준을 "동일한 `ab_pair_id` 보유"가 아니라 "B.`ab_pair_id` == A.`id`" 형태로. `tests/services/test_eval_service.py`의 관련 fixture(`_seed_run`, 페어 불일치 테스트 등)도 실제 모양(A: `ab_pair_id=None`, B: `ab_pair_id=<A의 id>`)으로 다시 써야 한다.

## 문제 2: `evaluate_ab()`를 호출하는 곳이 프로덕션 어디에도 없음

`grep -rn "evaluate_ab" src/yt_flow/`로 확인 — 유일한 호출부가 `tests/services/test_eval_service.py`뿐이다. 라우트도, run 완료 후 자동 트리거도 없다. 그래서 실제 앱을 써서 완료된 A/B 페어를 만들어도 `RunAbComparisonPage`는 **영원히 "평가 대기" 상태**에 머문다(문제 1이 고쳐져도 마찬가지 — 애초에 아무도 안 부르니까).

**권장 트리거 지점**: `src/yt_flow/services/run_service.py:271`, `_consume()`가 run을 `status="complete"`로 쓰는 바로 그 지점. 이 run 자체가 `prompt_variant == "B"`이고 `ab_pair_id`가 설정돼 있으면(= 방금 완료된 게 Variant B라면), 그 시점에 페어가 완성된 것이므로 평가를 걸 수 있다. `Run` row 조회는 근처 코드(`run_service.py:169-170`, `:348-349`)와 같은 `with Session(db._engine) as session: session.get(Run, run_id)` 패턴 재사용.

## 지켜야 할 제약

- **AD-10 (Langfuse/평가 실패는 non-fatal)**: `evaluate_ab()`는 `YTFLOW_DEEPSEEK_API_KEY` 미설정 시 `RuntimeError`를 던진다(`eval_service.py:383-384`) — E2E stub 서버(`scripts/run_e2e_stub_server.py`)나 API 키 없는 로컬 환경에서 즉시 발생함. 트리거는 반드시 `_trace_cm`(run_service.py:276) 같은 try/except로 감싸서 실패해도 파이프라인 run 자체(`status="complete"`)에는 영향 없어야 한다. 로그만 남기고 조용히 넘어갈 것.
- **Fire-and-forget**: story 4.2 AC5에 따르면 `evaluate_ab()`는 최대 5분 걸릴 수 있다(3축×3회×2 variant LLM 호출). `_consume()` 안에서 `await`하면 안 되고 `asyncio.create_task(...)`로 던지고 바로 리턴해야 한다(`start_run`이 백그라운드 태스크를 띄우는 기존 패턴과 동일 — `create_ab_run`도 이미 이 패턴).
- **AD-1 (레이어 규율)**: `run_service.py`가 `eval_service.py`를 import하는 건 둘 다 `services/`라서 문제없음.
- 새 프로덕션 스텁 플래그 추가 금지(B-2, 기존 관례) — 이번 건 스텁이 아니라 진짜 기능 배선이라 해당 없지만, "완료 감지"를 위해 또 다른 `if os.getenv(...)` 분기를 넣는 식으로 우회하지 말 것.

## 해야 할 일

1. `_validate_pair`(+ 관련 헬퍼/테스트)를 실제 A/B 데이터 모양에 맞게 수정 (문제 1).
2. `run_service._consume()`에 완료 시점 트리거 추가 (문제 2) — non-fatal, fire-and-forget.
3. `uv run pytest` 전체 회귀 확인 — 특히 일반 run(비-A/B)이 이 새 분기 때문에 영향받지 않는지 (`ab_pair_id`가 없으면 트리거 자체가 스킵되어야 함).
4. E2E stub 서버로 실제 A/B 플로우 한 번 수동 확인: Run A 생성→5게이트 승인→`POST /runs/{id}/ab`→Run B 5게이트 승인. `YTFLOW_DEEPSEEK_API_KEY` 없는 상태이므로 트리거는 걸리되 `evaluate_ab()`가 `RuntimeError`로 실패하는 것까지가 정상 — 이 경우 `ab_result`는 계속 null이어야 하고(로그에 에러만 남고) run 자체는 `complete` 상태를 유지해야 함. **판단해서 진행**: stub 환경에서 실제 "평가 완료" 상태까지 재현하고 싶으면 `tests/stubs/fakes.py`가 이미 다른 스테이지에서 하듯 DeepSeek 판정 호출도 fake로 대체하는 걸 검토 — 다만 이건 범위 확장이니 먼저 필요성부터 판단.
5. `e2e/ab-comparison-accessibility.spec.ts`(Journey 3, 이번에 만든 파일)로 돌아가서: 이 배선이 들어간 뒤에도 실제 플로우 테스트는 여전히 "평가 대기"를 검증해야 하는지(트리거가 걸려도 API 키가 없어 실패하면 결과는 동일), 아니면 4번에서 stub 판정을 추가했다면 실제 승자/점수 상태로 테스트를 갱신할지 결정하고 반영.

## 완료 기준

- `_validate_pair`가 story 4.1이 실제로 쓰는 데이터(A: `ab_pair_id=None`, B: `ab_pair_id=<A id>`)로 성공적으로 페어를 인식한다 — 유닛 테스트로 증명.
- Variant B run이 완료되면 (API 키가 있는 실제 환경에서) 자동으로 `ab_result`가 채워진다 — 수동 호출 없이.
- API 키가 없거나 평가가 실패해도 run의 `status`/게이트 흐름은 전혀 영향받지 않는다.
- `uv run pytest`, `npm test` 전체 그린.
