---
title: 'Story 14.7: scenario 리뷰어를 recompose 이후 규칙에 맞춘다 — 생성기는 이미 옳고 리뷰어만 스테일이다'
type: 'bugfix'
created: '2026-08-22'
baseline_revision: '003045c'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: ['{project-root}/docs/PROMPT_POLICY.md']
warnings: [oversized]
---

<intent-contract>

## Intent

**Problem:** `prompts/scenario/review.md`의 두 줄(`:46`, `:61`)이 recompose 이전 아키텍처를 강제한다. 10.1e(recompose 기본값 ON)와 10.2(무인 배경) 하에서 `image_prompt`는 **배경 전용**이고 `negative_prompt`는 사람 배제 토큰을 **가져야** 하는데, 리뷰어는 그것을 `descriptor_violation` 결함으로 보고한다. run `4b35c0ed`의 게이트 경고 4건 중 2건(씬 8·9)이 이 오탐이었고, 오탐 1건은 게이트 배지 오염에 그치지 않고 **해당 씬의 pass-2 전면 재작성 1회를 실제로 지불**시킨다(`scenario.py:859` → `_retry_scope`). 결정적으로 생성기 프롬프트 `visual_breakdown.md:142-148/201/328`은 이미 정확히 반대를 지시하고 있다 — 두 프롬프트가 **정면으로 모순**한 채 라이브에서 돌고 있다.

**Approach:** 리뷰어의 두 스테일 규칙을 삭제하는 것으로 끝내지 않고 **역방향 규칙으로 교체**한다(모델은 `{{scp_visual_reference}}`로 frozen descriptor를 주입받으므로, 침묵은 규칙을 재도출할 여지를 남긴다). 즉 `image_prompt`에 개체·인물·SCP 지정자가 **있으면** `descriptor_violation`이고, `negative_prompt`의 사람 배제 토큰은 **계약이므로 절대 보고 대상이 아니다**. 살아 있는 지적(금지 일반어)은 유지하고, 리뷰어 목록이 생성기보다 5개 짧다는 두 번째 모순도 같은 편집에서 닫는다. 변경은 **렌더 전 텍스트 스크리닝**으로 검증한다(비-GPU) — run `4b35c0ed`의 실제 씬 6·8·9 입력에 구/신 프롬프트를 각 3회 돌려 오탐 2건 소멸·진성 2건 생존을 실측한다.

## Boundaries & Constraints

**Always:**
- 리포지토리 파일이 진실. 편집 후 `uv run python scripts/migrate_prompts.py --label production --source prompts`로 `production` 직승격(DEV MODE), 그리고 **런타임이 실제로 요청하는 이름**으로 확인: `get_prompt("scenario/review")` → `GET {langfuse_host}/api/public/v2/prompts/scenario/review?label=production`. 시더가 출력한 이름이 아니라 이 이름으로 검증한다.
- `descriptor_violation`은 `REVIEW_ISSUE_TYPES`(`domain/state.py:130-134`) 멤버이고 `review.md`에 **리터럴 토큰으로 남아야** 한다(`tests/pipeline/nodes/test_scenario_chain.py:6518`이 전 멤버를 부분문자열로 고정). `:118`의 `type:` 열거 줄은 바이트 단위로 그 상수와 일치해야 한다(`:5241`).
- 측정치는 재산출 스크립트·표본 밴드(thread_id·checkpoint_id·씬 번호·반복 수)와 함께 남긴다.
- 프롬프트 편집은 **텍스트 스크리닝 후** 판정한다. 셀당 n=1로 "고쳤다"를 선언하지 않는다(반복 3회).

**Block If:**
- Langfuse에 `scenario/review`를 시딩했으나 런타임 이름으로 `production` 라벨 조회가 실패/불일치한다 — 초록 출력과 미출하가 5주 방치된 전례가 있으므로 조용히 넘기지 않는다.
- 스크리닝이 신 프롬프트에서 오탐 2건 중 하나라도 살아남거나 진성 "dark" 지적이 사라진다고 나온다 — 프롬프트 문구를 한 번 고쳐 재측정하고, 두 번째도 실패하면 HALT.

**Never:**
- `src/yt_flow/config.py`, `src/yt_flow/pipeline/nodes/image.py`, `src/yt_flow/services/vision_check.py` 및 그 테스트 — **14.4가 동시 진행 중이며 이 파일들을 잡고 있다. 읽기만 하고 쓰지 않는다.**
- `prompts/scenario/visual_breakdown.md` 변경 — 생성기는 이미 옳다. 이 스토리는 리뷰어를 생성기에 맞추는 일이고 반대 방향이 아니다.
- 프로그램적(비-LLM) 금지어 스캐너 신설, `descriptor_violation` 타입 삭제·개명, `overall_pass` 차단화, 판정 축 신설·계측기 라운드 4 — 전부 이 스토리 범위 밖.
- `--baseline`·`YTFLOW_ALLOW_AB_GATE`·A/B·골든셋 게이트 실행(AI 세션 금지 + DEV MODE에서 무의미).
- 스크리닝을 위해 렌더(GPU) 한 장도 태우지 않는다.

## I/O & Edge-Case Matrix

리뷰어는 LLM이므로 아래는 **스크리닝으로 관측할 셀**이다(각 3회 반복, 판정은 다수결).

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 무인 플레이트 + 사람배제 negative (씬 8) | `entity_visible=true`, `S00800.image_prompt`="…an empty steel autopsy table…"(개체 없음), `negative_prompt`에 `person, human figure, character, silhouette of a person` | `descriptor_violation` **0건** — 이것이 계약 준수 상태다 | 진성 "dark"(`"soft dark blur"`) 지적은 그대로 보고 |
| 같은 상태 + negative 제거 요구 (씬 9) | `S00900` 동일 패턴, 4b35c0ed에서 리뷰어가 "remove 'person, human figure…' from negative_prompt" 교정을 요구했다 | 그 교정·그 지적 **모두 부재** | — |
| `image_prompt`에 개체가 들어간 역방향 결함 | `image_prompt`에 `"SCP-049"` 지정자 또는 인물 신체·얼굴·포즈·의복 서술 | `descriptor_violation` 1건 + 배경 전용으로의 교정 | 인용 없이 단정하지 않는다 |
| 나레이션이 frozen descriptor와 모순 | 나레이션 본문이 Visual Identity Profile과 충돌하는 물리 서술 | `descriptor_violation` 여전히 발화(§4는 나레이션 소관으로 살아 있다) | 근거 인용 규칙 유지 |
| 금지 일반어 (씬 6) | `image_prompt`에 `"dark red-black fluid"` 등 3건 | 금지어 지적 보고 — 진성 결함 | 목록은 생성기와 동일한 11개 |
| 생성기에만 있던 5개 어휘 | `image_prompt`에 `"ominous"`/`"sinister"` 등 | 이제 리뷰어도 보고 | — |

</intent-contract>

## Code Map

- `prompts/scenario/review.md:45-48` -- §4 Visual Identity Consistency. `:46`이 "Every scene where the entity appears must use the Frozen Descriptor" — **적용 대상이 무기재**라 리뷰어가 `image_prompt`까지 끌어간다. 나레이션·`visual_description` 인물 서술로 명시 범위화할 지점.
- `prompts/scenario/review.md:60` -- 금지 일반어 6개. **살려둘 규칙**(진성 지적 2건의 유일한 탐지 기구). 생성기 11개와의 격차를 닫을 지점.
- `prompts/scenario/review.md:61` -- `"When entity_visible is true, the SCP frozen descriptor from Visual Identity Profile is present"`. **주 삭제·역전 지점.**
- `prompts/scenario/review.md:118` -- 출력 스키마의 `type:` 열거 줄. `domain/state.py`의 `REVIEW_ISSUE_TYPES`와 바이트 일치 필수(`test_scenario_chain.py:5241`).
- `prompts/scenario/visual_breakdown.md:136`(금지어 11개), `:142-148`(배경 전용 규칙), `:201`(negative_prompt 사람배제 의무), `:327-328`(셀프체크) -- **읽기 전용 정본.** 리뷰어 문구는 여기서 파생한다.
- `prompts/scenario/writing.md:219,236-238` -- `entity_visible`의 정의처: **씬 단위**이고 "SCP가 이 씬의 나레이션에서 언급/등장하는가"이다. "배경 플레이트에 개체를 그려라"가 아니다 — 리뷰어가 오독한 지점.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:3025` -- `get_prompt("scenario/review")`. 시딩 검증이 맞춰야 할 유일한 이름.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:2894-2944` -- `review_step`/`_aggregate_review`. 씬당 1콜 병렬, `visual_descriptions`는 씬별 JSON 덤프로 주입.
- `src/yt_flow/pipeline/nodes/scenario.py:216-252`, `:859` -- `_retry_scope`. 오탐 1건 = 그 씬 pass-2 재작성 1회. 오탐의 실제 비용 근거.
- `src/yt_flow/pipeline/nodes/scenario.py:522`, `:538-606` -- `review_issues`(최대 20, 600자 클립)와 `warning.categories`(멤버십 필터). 게이트 오염 경로.
- `src/yt_flow/domain/state.py:130-134` -- `REVIEW_ISSUE_TYPES`. **변경 금지**, 고정 대상.
- `tests/pipeline/nodes/test_scenario_chain.py:935`(`_prompt_text`), `:5241`, `:6487-6518`(`_UNLOOSENED`) -- 프롬프트 텍스트 고정 테스트의 기존 선례·확장 지점.
- `yt_flow.db` `checkpoints`, `thread_id=4b35c0ed-8a1e-4448-8594-11bd9997376d`, checkpoint `1f19a3de-374f-68db-800f-3033ac398867` -- ormsgpack blob. 스크리닝 입력(`channel_values.scenes`, `.scenario_quality`)의 출처.
- `_bmad-output/implementation-artifacts/14-0-angle-conflict/measure_angle_agreement.py` -- 같은 체크포인트를 읽는 선례 스크립트. 역직렬화·thread 접두사 해석 코드를 재사용한다.

## Tasks & Acceptance

**Execution:**
- [x] `prompts/scenario/review.md` -- §4의 `:46`을 **적용 범위 명시**로 교체(frozen descriptor 준수는 나레이션과 `visual_description`의 인물/캐스트 서술에만 적용되고 `image_prompt`에는 적용되지 않는다). §6의 `:61`을 **역방향 규칙**으로 교체: `image_prompt`는 배경 전용이므로 개체·인물의 신체·얼굴·포즈·의복 서술이나 SCP 지정자 토큰이 **있으면** `descriptor_violation`이고, 없는 것은 정상이다. 그리고 §6에 **"보고하지 말 것" 명시 절**을 신설 — (a) `entity_visible=true`인데 `image_prompt`에 frozen descriptor가 없는 것, (b) `negative_prompt`에 `person`/`human figure`/`character`/`silhouette of a person` 등 사람 배제 토큰이 있는 것. 둘 다 recompose(10.1e)+무인 배경(10.2) 아키텍처가 **요구하는** 상태이며 인물은 비디오 단계가 합성하는 승인 카드에서 온다는 한 줄 근거를 붙인다. `entity_visible`이 씬 단위 나레이션 필드라는 정의도 한 줄. -- 삭제만 하면 `{{scp_visual_reference}}`로 주입된 frozen descriptor를 근거로 모델이 같은 규칙을 재도출한다. 오탐 1건의 비용은 배지 오염이 아니라 씬 1개의 pass-2 재작성이다.
- [x] `prompts/scenario/review.md:60` -- 금지 일반어 목록을 생성기와 동일한 11개(`ominous`, `sinister`, `menacing`, `foreboding`, `unsettling` 추가)로 맞춘다 -- 판정 런의 진성 지적 2건을 만든 유일한 기구인데 리뷰어 목록이 5개 짧아 생성기가 금지한 어휘를 조용히 통과시킨다. 스테일 리뷰어라는 **같은 결함 부류의 두 번째 사례**이므로 같은 편집에서 닫는다.
- [x] `_bmad-output/implementation-artifacts/14-7-prompt-screening/screen_review_prompt.py` -- 신규. run id를 인자로 받아 `yt_flow.db` 체크포인트에서 `scenes`를 읽고, 씬 6·8·9에 대해 `review.md`의 **구 버전(git show)과 신 버전(작업트리)** 을 동일 변수로 렌더해 실제 리뷰 LLM에 각 3회 호출한다. 셀별로 `issues[].type`+`description` 요약과 (i) `entity_visible`/frozen-descriptor 오탐, (ii) `negative_prompt` 오탐, (iii) 금지어 지적의 발생 횟수를 표로 출력한다. 헤더에 thread_id·checkpoint_id·반복 수를 찍고, 역직렬화 실패는 삼키지 않고 stderr로 알린다. GPU 0. -- 재산출 없는 측정치는 무효이고, 셀당 n=1은 "고쳤다" 선언의 근거가 못 된다.
- [x] `_bmad-output/implementation-artifacts/14-7-prompt-screening/report.md` -- 신규. 표본 밴드(런 id·thread·checkpoint·씬 3개·반복 3회·모델), 구/신 대조표, 4b35c0ed 원본 경고 4건의 원문과 각각의 신 프롬프트 하 판정, 그리고 **비용 근거**(오탐 1건 = pass-2 씬 재작성 1회, `scenario.py:859`). 반대 결과·판정불가 셀도 지우지 않고 남긴다.
- [x] `tests/pipeline/nodes/test_scenario_chain.py` -- 두 테스트 추가. (1) `review.md`에 배경 전용 규칙·negative_prompt 면제·`descriptor_violation` 토큰이 **존재하고** 스테일 문구(`"the SCP frozen descriptor from Visual Identity Profile is present"`)가 **부재**함을 단정(`_UNLOOSENED` 선례를 따르되 역방향 고정 1건 포함). (2) `review.md`와 `visual_breakdown.md`의 금지어 목록을 각 파일에서 파싱해 **집합 동일성**을 단정(파일 부재 시 skip) -- 손으로 베낀 리터럴 두 벌은 자기검증일 뿐이고, 이번 격차가 바로 그 실패 사례다.
- [x] `uv run python scripts/migrate_prompts.py --label production --source prompts` 실행 후 `GET {langfuse_host}/api/public/v2/prompts/scenario/review?label=production`으로 본문에 신 규칙이 있는지 확인 -- DEV MODE 직승격 경로이고, 시더 출력 이름이 아니라 런타임 요청 이름으로 확인해야 한다.
- [x] `_bmad-output/planning-artifacts/epics.md` Story 14.7 항목 -- `(draft)` → 종결 기록으로 갱신: 무엇이 스테일이었고(2줄), 생성기는 이미 옳았다는 사실, 스크리닝 실측치, 금지어 11개 정렬. **14.4가 이 파일의 다른 섹션을 동시에 수정 중이므로 14.7 항목만 국소 편집한다.**
- [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` -- 14-7 행만 done으로 갱신(같은 동시성 주의).

**Acceptance Criteria:**
- Given run `4b35c0ed`의 씬 8·9 실제 `visual_descriptions`, when 신 `review.md`로 3회 리뷰하면, then `entity_visible`/frozen-descriptor 오탐과 `negative_prompt` 사람배제 토큰 삭제 요구가 **9셀 중 0건**이다(3회×2오탐 유형 각 씬 다수결 기준 0).
- Given 같은 런의 씬 6, when 신 `review.md`로 3회 리뷰하면, then `"dark"` 금지어 지적이 **다수결로 생존**한다 — 스테일 규칙 제거가 살아 있는 규칙을 함께 죽이지 않았다.
- Given `image_prompt`에 `"SCP-049"` 지정자나 인물 신체 서술이 들어간 합성 입력, when 신 `review.md`로 리뷰하면, then `descriptor_violation` 1건이 보고된다 — 규칙이 침묵으로 사라진 것이 아니라 방향이 뒤집혀 살아 있다.
- Given `uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/test_prompt_migration.py -q`, when 실행하면, then 신규 2건 포함 전부 통과하고 `test_review_issue_vocabulary_matches_the_prompt_enum`·`test_the_judging_prompts_were_not_loosened`·`test_prompt_seeding_covers_runtime_names`가 초록이다.
- Given 시딩 완료 후, when `scenario/review`를 `label=production`으로 조회하면, then 응답 본문에 배경 전용 규칙 문구가 존재하고 스테일 문구가 부재하다 — 시더 출력만으로는 출하를 단정하지 않는다.
- Given `git diff --stat`, when 확인하면, then `src/yt_flow/config.py`·`pipeline/nodes/image.py`·`services/vision_check.py`와 그 테스트가 이 스토리의 변경에 **포함되지 않는다**(14.4 동시 진행).
- Given `prompts/scenario/visual_breakdown.md`, when `git diff`를 보면, then 비어 있다 — 생성기는 정본이고 이 스토리는 리뷰어만 움직인다.

## Spec Change Log

## Review Triage Log

### 2026-08-22 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 24: (high 6, medium 15, low 3)
- defer: 4: (high 0, medium 3, low 1)
- reject: 5: (high 0, medium 1, low 4)
- addressed_findings:
  - `[high]` `[patch]` §4의 나머지 두 불릿(`:47-48`)이 무범위로 남아 제거한 규칙을 되살릴 경로였다 — "visual descriptions"는 문자 그대로 샷 JSON의 변수명이다. §4 전체를 나레이션 + 샷 `cast`로 범위화하고 `image_prompt`/`negative_prompt` 배제를 명시.
  - `[high]` `[patch]` 새 역방향 규칙에 **묘사된/무생물 인물 예외가 없어** 새 오탐 부류를 만들 상태였다(사진·포스터·회화·해부도·마네킹·조각상, 소품 의복, 그리고 생성기가 가르치는 카메라 어휘 `over-the-shoulder`/`POV`). `gotcha_person-token-regex-is-unusable-on-image-prompt` + 14.4의 2026-08-22 결정과 정면으로 어긋났다 — 예외 절 신설.
  - `[high]` `[patch]` **(a) 절의 주어인 `entity_visible`이 스크리닝 입력에 아예 없었다.** 체크포인트 `SceneState` 키에 없고(실측 확인) 라이브는 미영속 `writing` 딕트로 받는다 → 구 프롬프트의 오탐은 `cast` 배열에서 발화한 것이었고 (a)의 문자적 트리거는 미검증이었다. `--entity-visible`로 주입하고 세 번째 재구성으로 명기.
  - `[high]` `[patch]` **비용 주장이 그 런의 기록으로 반증됐다** — `review_overall_pass: true`, `critic_verdict: retry`(실측). pass-2를 산 것은 크리틱이고 warning 등급 리뷰 이슈는 `scenario.py:859`를 단독으로 켤 수 없다. 오탐이 실제로 한 일은 **이미 발화한 repair의 범위를 넓힌 것**: `_retry_scope`가 리뷰 이슈의 `scene_num`을 크리틱 노트와 합집합하므로 {1,4,6,7} ∪ {6,8,9} = {1,4,6,7,8,9} — 오탐 2건이 **씬 8·9를 추가**했다. "재작성 패스 2회"도 단위가 틀렸다(`writing_scene_repair_step`은 인덱스 집합 전체에 대한 단일 호출). report §6 + epics + sprint-status 세 곳 정정 — 14.0 회고와 같은 형태(거짓 전제가 여러 문서에 번짐)를 그 자리에서 끊었다.
  - `[high]` `[patch]` "규칙이 뒤집혔나 침묵했나"를 가리는 **유일한 판별 게이트가 그것이 배제하려는 결함으로 충족될 수 있었다** — `buckets()`가 `NEGATIVE_FP` 부여 후 `elif` 체인을 흘려 한 이슈가 `negative_fp`와 `entity_in_prompt` 양쪽에 들어갔다(리뷰어가 모듈을 실행해 실증). 상호배타 정밀도 체인 + `--selftest` 14케이스로 고정.
  - `[high]` `[patch]` 이 스토리가 커밋되는 순간 `old`(=`HEAD`)가 `new`와 같아져 문서화된 재산출 명령이 프롬프트를 자기 자신과 비교하게 됐다. `--old-ref` 기본값을 `003045c`로 고정하고 두 텍스트가 같으면 판정불가로 거부.
  - `[medium]` `[patch]` §4의 새 범위가 **존재하지 않는 필드**를 지목했다(`visual_description`의 인물 산문). 실제 샷 키는 `camera_angle, camera_movement, cast, image_path, image_prompt, location_key, negative_prompt, sentence_indices, shot_id` → `cast` 배열로 정정.
  - `[medium]` `[patch]` (b) 절이 예외를 닫힌 목록으로 열거해 미열거 토큰을 다음 오탐에 넘겨줬다 → "예시이지 경계가 아니다" + 생성기가 의무화한 해부 접두사도 결함이 아님을 명시.
  - `[medium]` `[patch]` 새 규칙의 교정을 **출력 스키마가 담을 수 없었다** — `corrections[].field`에 `image_prompt` 채널이 없다(열거 변경은 금지). 이슈 자신의 `correction`에 인라인으로 싣고 `corrections[]`를 내지 않도록 지시.
  - `[medium]` `[patch]` `narration`이 **TTS 정규화 후** 텍스트였다(씬 8: `에스씨피 공사구` vs `display_narration`의 `SCP-049`). `tts_normalize_step`은 리뷰 뒤에 돈다 → `display_narration` 우선 + 같은 씬을 두 표기로 두 번 보내던 것 제거.
  - `[medium]` `[patch]` `variables()` docstring의 "byte-for-byte" 주장과 report §1의 "재구성은 둘뿐"이 모두 거짓 → 7항목 divergence 표로 교체(래퍼 형태·`parse_error` 주입·필드 트리밍·`_call_stage_with_retry`/`_make_parse` 우회로 tally가 pre-filter라는 것까지).
  - `[medium]` `[patch]` 광고된 자기검증이 **코드에 없었다**(`fp_survivors`가 `("new",)`만 순회) → 구 프롬프트가 오탐 (i)을 다수결로 재현하지 못하면 판정불가로 종료. 실제로 발화했다(씬 6·8만 돌린 진단이 정확히 이 조건으로 3을 반환).
  - `[medium]` `[patch]` 분류기 사각 2종: 부정형 존재("contains no", "free of" 등)를 준수 진술이 아니라 위반으로 셀 수 있었고, `corrections[]`/`grounded_contradictions[]`를 안 봤다 — 이 런의 씬 9 오탐은 `negative_prompt` 요구를 **`correction`에만** 담았다.
  - `[medium]` `[patch]` 합성 통제가 교란돼 있었다 — `del shots[1:]`가 다문장 나레이션에 샷 1개만 남겨 §6의 샷수/문장수 규칙을 독립적으로 위반하고 나머지 `sentence_indices`를 고아로 만들었다. 전 샷 유지 + 샷 1에만 주입.
  - `[medium]` `[patch]` tally를 정당화할 **전사 기록이 저장되지 않았다** → 호출당 1줄 JSONL(원문·파싱 결과·배정 버킷) 저장 + 경로 출력.
  - `[medium]` `[patch]` 체크포인트가 **repair 이후** 텍스트다(`final_pass_index: 2`) → 헤더에 pass/scope/verdict 출력 + report §1에 caveat 명기.
  - `[medium]` `[patch]` **금지어 게이트 기준 자체가 틀렸다.** 셀별 다수결 멤버십의 집합차를 쓰는데, 실제 발생률 ~10~25%인 셀은 작은 `reps`에서 50% 선을 무작위로 넘는다 — reps 3에서 씬 6이 구 2/3 vs 신 1/3으로 FALSIFIED, reps 9에서는 구 1/9 vs 신 2/9(방향 반대). PROMPT_POLICY 6.10이 이미 "단일 시행 무관용 게이트는 노이즈만으로 통과 불가"로 결론낸 것과 같은 형태. 게이트 단위를 **런 단위 총합 회귀 + 다수결→0 kill**로 교체.
  - `[medium]` `[patch]` report의 R1/R2/R3 집계가 **분류기 두 버전을 섞고** 자기 caveat이 6/9라고 적은 셀을 헤드라인에 5/9로 남겨뒀다 → 단일 분류기 단일 실행을 헤드라인으로, 이전 3회는 "폐기됨"으로 사실만 보존(수치 미반입).
  - `[medium]` `[patch]` 금지어 드리프트 가드가 `"([a-z][a-z ]*)"`만 매칭해 하이픈·대문자·비ASCII 용어를 못 봤고, `len(...) == 11` 하드코딩이 정당한 12번째 용어 추가를 드리프트로 오보고했다 → 인용 패턴 일반화 + 집합 동일성 + 하한.
  - `[medium]` `[patch]` 스테일 규칙 부재 핀이 정확문자열이라 패러프레이즈로 조용히 복귀 가능했다 → `entity_visible`±120자 창의 frozen/descriptor 요구 문형 부재를 형태로 단정.
  - `[medium]` `[patch]` 가드가 **한 방향뿐**이었다 — 생성기(`visual_breakdown.md`)가 배경 전용 규칙과 사람배제 의무를 계속 갖고 있는지는 아무것도 고정하지 않았다. 생성기 측 핀 2건 추가(같은 divergence 부류를 반대 방향에서 막는다).
  - `[low]` `[patch]` 하네스 견고성 일괄: 동시성 세마포어(8), `gather(return_exceptions=True)` + `compile()`을 per-call try 안으로(한 렌더 오류가 완료된 전 호출을 버리던 것), `reps_ok == 0` 셀을 판정불가로(미측정이 clean으로 읽혔다), 짝수 reps 동수 규칙 명시, 중복/비정수 `scene_num` 거부, 빈 `scp_id`로 `LIKE '%'`가 되던 것 차단, `git show`/파일 읽기 예외 포착, `Settings().db_path` 사용, sqlite `close()`, 합성 통제 셀 이름 출력(`args.scenes[-1]`이라 `--scenes` 순서가 조용히 통제를 바꿨다), `__doc__` Optional.
  - `[low]` `[patch]` report에 §"이 스토리가 검증하지 않은 것" 신설 — 이 런의 미스크리닝 6개 씬에서의 새 규칙 오탐율, 예외 절 자체(합성 입력 미검증), (a)는 주입된 `entity_visible`에서만 검증, pass-1 이슈 목록은 미기록.
  - `[low]` `[patch]` 크로스파일 가드가 `pytest.skip`으로 사라질 수 있었고(파일명 변경 시 초록) 모듈의 `_prompt_text` 헬퍼 대신 경로를 손으로 재도출했다 → 헬퍼 사용, 부재는 실패.

## Design Notes

**왜 삭제가 아니라 역전인가.** 리뷰어에게는 `{{scp_visual_reference}}`로 frozen descriptor 전문이 주입되고 `{{visual_descriptions}}`로 `image_prompt`·`negative_prompt`가 함께 주입된다. `:61`만 지우면 모델은 "개체가 등장하는 씬인데 프롬프트에 개체가 없다"를 §4나 상식에서 다시 도출한다 — 실제로 4b35c0ed의 씬 9 지적은 `:61`의 문구를 넘어 `negative_prompt` 교정까지 요구했고, 그 요구는 리뷰어 프롬프트 어디에도 적혀 있지 않았다. 즉 이 오탐은 **규칙의 존재가 아니라 아키텍처 정보의 부재**에서 나온다. 그래서 처방은 "보고하지 말 것"을 이유와 함께 명시하고, 같은 축의 진짜 결함(개체가 `image_prompt`에 들어간 경우)을 반대 방향으로 세우는 것이다.

**`entity_visible`은 씬 단위 나레이션 필드다.** 정의처는 `writing.md:219`("SCP 개체가 이 씬에서 언급되거나 등장하는 경우")이고 `visual_breakdown.md`에는 **아예 등장하지 않는다**. 4b35c0ed의 `S00800`/`S00900` 샷 dict에도 그런 키가 없다. 리뷰어는 씬 단위 나레이션 사실을 샷 단위 렌더 지시로 오독했다.

**금지어 목록을 손으로 두 벌 유지하지 않는다.** 같은 어휘가 두 프롬프트에 리터럴로 박혀 있고 이번에 실제로 갈라졌다. 프로그램적 스캐너를 만드는 것(범위 밖)과 아무것도 하지 않는 것 사이의 laziest 지점은 **두 파일을 파싱해 집합 동일성을 단정하는 테스트 하나**다 — 14.0이 `_CAMERA_ANGLES`에 쓴 것과 같은 패턴.

```markdown
# 형태 예시 (구현이 이 형태를 따를 필요는 없다)
- `image_prompt` is background-only: the plate is rendered people-free and cast
  members are composited from approved cards. Report `descriptor_violation` when an
  `image_prompt` DOES name the entity/a person's body, face, pose, clothing, or a bare
  SCP designator. Do NOT report a missing frozen descriptor, and do NOT report
  person-exclusion terms in `negative_prompt` — both are required by the architecture.
```

## Verification

**Commands:**
- `uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/test_prompt_migration.py -q` -- expected: 신규 2건 포함 전부 통과
- `uv run python _bmad-output/implementation-artifacts/14-7-prompt-screening/screen_review_prompt.py 4b35c0ed` -- expected: 씬 8·9 오탐 0/9, 씬 6 금지어 지적 다수결 생존, report.md 수치와 동일
- `uv run python scripts/migrate_prompts.py --label production --source prompts` -- expected: `scenario/review` created/updated, 실패 0
- `curl -s -u "$YTFLOW_LANGFUSE_PUBLIC_KEY:$YTFLOW_LANGFUSE_SECRET_KEY" "$YTFLOW_LANGFUSE_HOST/api/public/v2/prompts/scenario/review?label=production" | grep -c "background-only"` -- expected: `1` 이상 (런타임 요청 이름으로의 확인 — `.env`의 키 이름은 전부 `YTFLOW_` 접두사이고 리뷰 LLM 키는 `YTFLOW_GEMINI_API_KEY`)
- `git diff --stat -- src/yt_flow/config.py src/yt_flow/pipeline/nodes/image.py src/yt_flow/services/vision_check.py prompts/scenario/visual_breakdown.md` -- expected: 빈 출력

**Manual checks (if no CLI):**
- `prompts/scenario/review.md`와 `prompts/scenario/visual_breakdown.md`를 나란히 읽어 배경 전용 규칙·negative_prompt 계약·금지어 목록이 서로 모순하지 않는지 확인.

## Auto Run Result

Status: done — **스테일은 리뷰어 한쪽뿐이었고, 생성기는 이미 옳았다.**

### 구현 요약

`prompts/scenario/review.md`가 `prompts/scenario/visual_breakdown.md`와 **정면으로 모순한 채 라이브에서 돌고 있었다.** 생성기는 `image_prompt`가 배경 전용이고 `negative_prompt`에 사람 배제 토큰이 의무라고 지시하는데(`:142-148`, `:201`, `:328`), 리뷰어는 바로 그 상태를 `descriptor_violation`으로 보고했다. run `4b35c0ed`의 게이트 경고 4건 중 2건이 그것이다.

처방은 삭제가 아니라 **역전**이다. 리뷰어는 `{{scp_visual_reference}}`로 frozen descriptor를 주입받으므로 침묵은 규칙을 재도출할 여지를 남긴다 — 실제로 이 런의 씬 9 지적은 프롬프트 어디에도 없던 `negative_prompt` 교정까지 요구했다. 그래서 (1) §4 전체를 나레이션 + 샷 `cast`로 범위화하고, (2) `image_prompt`에 개체가 **있으면** 결함으로 세우고, (3) 보고 금지 2건을 아키텍처 근거와 함께 명시했다. 리뷰에서 **묘사된/무생물 인물·미착용 의복·카메라 어휘 면제 절**이 추가됐다 — 없으면 이 스토리가 오탐 2건을 없애고 새 오탐 부류를 하나 만들 상태였다. 금지 일반어는 6→11개로 생성기와 정렬했다(리뷰어가 5개를 조용히 통과시키고 있었다).

### 파일

- `prompts/scenario/review.md` — §4 전체 범위화, §6에 배경 전용 역방향 규칙 + 면제 절 + 보고 금지 2건 + 교정 채널 지시, 금지어 11개 정렬. `type:` 열거 줄과 `REVIEW_ISSUE_TYPES`는 불변.
- `tests/pipeline/nodes/test_scenario_chain.py` — 가드 5건: 배경 전용 6핀 / 스테일 문장 부재 / 스테일 규칙 **형태** 핀(패러프레이즈 복귀 차단) / 생성기측 2핀(반대 방향 divergence) / 두 프롬프트 금지어 목록 집합 동일성.
- `_bmad-output/implementation-artifacts/14-7-prompt-screening/screen_review_prompt.py` — 렌더 전 텍스트 스크리닝 하네스. 런타임 경로 재사용(`TextPromptClient.compile` → `_call_gemini` → `_parse_yaml`), 자기검증(구가 오탐을 재현 못 하면 판정불가), 상호배타 분류기 + `--selftest` 14케이스, JSONL 전사, 판정 코드 4종.
- `_bmad-output/implementation-artifacts/14-7-prompt-screening/report.md` + `headline-run-*.txt` + `transcript-*.jsonl` — 표본 밴드, 7항목 fidelity divergence, 구/신 대조, 반대 결과 4건, 비용 메커니즘, 미검증 항목.
- `_bmad-output/planning-artifacts/epics.md` / `sprint-status.yaml` — Story 14.7 종결 기록(14.4가 동시 소유한 다른 섹션은 미접촉).
- `_bmad-output/implementation-artifacts/deferred-work.md` — 선행 결함 4건 등재.

### 리뷰 결과

patch 24건 적용(high 6 / medium 15 / low 3), defer 4건, reject 5건, intent_gap·bad_spec 0건. 상세는 위 Review Triage Log. high 6건의 성격: §4의 남은 불릿이 제거한 규칙을 되살릴 경로였고, 새 규칙에 세트드레싱 면제가 없었고, **(a) 절의 주어인 `entity_visible`이 스크리닝 입력에 아예 없었고**, 비용 주장이 그 런의 기록으로 반증됐고, 판별 게이트가 그것이 배제할 결함으로 충족될 수 있었고, 커밋 직후 재산출 명령이 프롬프트를 자기 자신과 비교하게 됐다.

reject 중 하나만 기록해 둘 값이 있다: "`negative_prompt`에 사람 배제 토큰이 **빠진** 경우를 검사할 규칙이 없어 플레이트에 사람이 그려진다"는 지적의 결론이 거짓이다 — `image.py`가 `BG_NEGATIVE_SUFFIX`를 코드로 주입하므로 프롬프트 측 누락은 무해하다.

### 검증

- `uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/test_prompt_migration.py -q` → **997 passed**. `test_review_issue_vocabulary_matches_the_prompt_enum` / `test_the_judging_prompts_were_not_loosened` / `test_prompt_seeding_covers_runtime_names` 초록.
- `ruff check` → clean. `--selftest` → 14 케이스 OK.
- 헤드라인 스크리닝(`--reps 5`, 40 텍스트 콜, GPU 0, 실패 0, **exit 0**): 오탐(i) 구 6/15 → **신 0/15**, 오탐(ii) 구 1/15 → 신 0/15, 금지어 **구 6 → 신 6 불변**(씬 8 구·신 5/5), 역방향 통제 **구 0/5 → 신 5/5**, §4 나레이션 진성 모순 구·신 5/5. 자기검증 통과(구가 씬 9에서 5/5 다수결 재현).
- Langfuse: `production` 직승격 후 **런타임이 요청하는 이름으로** 확인 — `prompt_service.get_prompt("scenario/review")` → v11, labels `[production, latest]`, 면제 절 존재, 스테일 문장 부재, `rstrip("\n")` 후 리포 파일과 동일.
- 금지 파일 무접촉 확인: `config.py`·`image.py`·`vision_check.py`·`domain/state.py`·`visual_breakdown.md` diff 공백.

### 잔여 리스크

1. **새 역방향 규칙의 오탐율은 미측정이다.** 이 런의 9개 씬 중 3개만 스크리닝했고, 면제 절(사진·마네킹·조각상·소품 의복·카메라 어휘) 자체는 합성 입력으로 검증하지 않았다 — 기록된 gotcha와 14.4의 결정에 근거한 예방적 조항이다. 다음 런의 게이트 경고가 첫 실측이 된다.
2. **`descriptor_violation`이 세 축을 겸한다**(금지어 / 개체 누출 / 나레이션 모순). 게이트의 `warning.categories`는 이 셋을 구분하지 못하고, 이 스토리의 스크리닝조차 전용 분류기가 필요했다. deferred 등재.
3. **`issues[]`에는 증거 검증이 코드에 없다.** 새 규칙의 "인용 없이 단정 금지"는 프롬프트 산문뿐이고, 그 규칙의 오탐 비용은 repair 범위에 씬 하나가 추가되는 것이다. deferred 등재.
4. **pass-1 리뷰 산출물은 영속되지 않는다.** 실제로 `_retry_scope`를 먹인 지적 목록은 기록에 없으므로, 오탐이 그 런에서 정확히 씬 8·9를 추가했다는 것은 pass-2 산출물로부터의 추론이다.
5. 이 스토리는 **텍스트 층만** 바꿨다. 라이브 런에서의 게이트 경고 감소는 다음 E2E에서 확인된다.
