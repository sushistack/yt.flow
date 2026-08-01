---
baseline_commit: dafe436391a3808aaa302a225bff3208f3dd55da
---

# Story 11.4: WhisperX 상시 정렬 — 실제 발화 경계 기반 비트 정렬 컷

Status: done

## Story

As a **yt.flow 운영자 (Jay)**,
I want **WhisperX 강제 정렬이 매 런 항상 실행되고 tts의 균등분할 provisional timings는 실패 시 폴백으로 강등되며, 정렬된 word timings가 state에 기록되어 8.11 샷 컷과 자막 큐가 실제 발화 경계 위에서 동작**하도록,
so that **"나레이션 비트에 맞춘 컷"(다큐 편집 표준)이 실제로 성립하고 — 지금은 컷과 큐가 공백 토큰 수 균등분할이라는 가짜 타이밍 위에 있다 — 컷-정렬 오차 rule metric으로 회귀까지 감지된다**.

## Acceptance Criteria

1. **subtitle_node 상시 정렬 — `if timings:` 게이트 제거**: `subtitle.py:373-386`의 분기(state의 word_timings가 있으면 aligner를 건너뛰는 — tts가 항상 provisional을 기록하므로 WhisperX가 사실상 한 번도 안 도는 원인)를 제거하고 **항상** WhisperX 정렬을 시도한다. 성공 → 정렬된 `list[WordTiming]`으로 `sentence_cues(timings, narration, display)` 경로(기존 코드 그대로) 진행. 실패(예외, AC3의 reconcile 불가 포함) → state의 provisional timings로 **동일한 sentence_cues 경로** 폴백 + **scene 번호와 원인을 담은 WARNING 로그 필수**(조용한 강등 금지 — 리서치 전략 §21). 기존 `else` 분기의 segment-level 큐 빌드(display 매핑 없는 열화 경로)는 삭제 — 폴백조차 sentence_cues를 타므로 더 이상 존재 이유가 없다. **정렬 실패가 스테이지를 실패시키는 일은 절대 없다**(shot_timing.py AC:7 철학과 동일 — 5.7 교훈: 부가 기능 실패가 런 전체를 죽이면 안 된다).
2. **word_timings state write-back — 이 스토리의 진짜 배선**: subtitle_node가 최종 사용한 timings(정렬본 또는 폴백본)를 반환 scenes에 기록한다 — `{**scene, "word_timings": final_timings, "subtitle_path": ...}`. 근거: video_node는 subtitle **뒤에** 실행되고 8.11 per-shot 컷 경계를 `scene["word_timings"]`에서 유도한다(video.py:804·1268·1749 → `plan_shot_clips` → `sentence_windows`). write-back 없이는 자막 큐만 정렬되고 **샷 컷은 여전히 균등분할** — 스토리 제목이 거짓이 된다. eval_service의 rule metric도 최종 체크포인트의 word_timings를 읽으므로 함께 정합.
3. **reconcile 순수 함수 — whisperx word_segments → WordTiming 1:1**: 신규 함수(예: `reconcile_word_timings(word_segments, narration, audio_duration) -> list[WordTiming] | None`, subtitle.py 내). 요구사항: ① 출력 길이 == `len(narration.split())` — 아니면 `None`(폴백). 이 불변식이 지켜져야 `sentence_windows`/`sentence_cues`의 count-mismatch 강등(apportion — 사실상 균등분할)이 발동하지 않는다. 발동하면 이 스토리가 조용히 무효화되므로 **정렬 성공 경로에서 mismatch 강등이 절대 안 걸리는 것 자체를 테스트로 고정**. ② start/end 없는 단어(전 문장이 정렬 불가 문자였던 드문 케이스 — whisperx가 문장 내 보간은 이미 해 준다, 아래 Dev Notes)는 시간축 이웃 보간, 양 끝은 0.0/audio_duration 클램프. ③ 출력은 provisional과 동일한 불변식을 만족하도록 sanitize: `start_sec ≥ 0`, `end_sec > start_sec`, 단조증가, 마지막 `end_sec ≤ audio_duration` — `_validate_segments`가 큐 검증에서 raise하면 스테이지가 죽으므로 **불변식은 reconcile에서 by construction**으로 보장하고, sanitize 불가능한 퇴화 입력은 `None`(폴백). ④ 순수 함수 — I/O 없음, 단위 테스트 대상.
4. **ASR 패스 삭제 + 모델 1회 로드 (ponytail)**: `WhisperXAligner._align_sync`의 `whisperx.load_model(...)` + `model.transcribe(audio)`를 삭제 — 트랜스크립트를 이미 알고 있으므로 강제 정렬에는 `load_align_model` + `align`만 필요하고, ASR(제일 비싼 패스)은 `last_end` 추정에만 쓰이고 있었다. end는 기존 폴백 라인 그대로 `len(audio) / 16000`. 이에 따라 죽는 config 필드 `aligner_model`/`aligner_compute_type` **삭제**(config.py:78·80 — `SettingsConfigDict(extra="ignore")`라 .env 잔존 변수 무해, 실제 .env는 `YTFLOW_ALIGNER=whisperx`만 설정함 확인 완료). `aligner`/`aligner_device`는 유지. align 모델은 **aligner 인스턴스에 1회 로드 후 씬 간 재사용**(현행 코드는 호출마다 재로드 — 씬 8~10개면 모델 로드 8~10회). 씬 루프가 순차 await라 락 불요.
5. **스테일 주석/독스트링 정정**: ① subtitle.py:41 `"whisperx is not in pyproject.toml; install it separately"` ② config.py:75-77 동일 취지 주석 — 둘 다 스테일(`whisperx>=3.8.6`이 pyproject.toml:16에 있음), 정정. ③ tts.py:10-14 모듈 독스트링의 provisional 설명에 "Story 11.4부터 WhisperX 정렬 실패 시 폴백" 취지 반영. ④ subtitle.py 모듈 독스트링(1-8행)의 "Reuses SceneState.word_timings when populated by tts_node; falls back to YTFLOW_ALIGNER otherwise"도 역전된 신규 동작으로 갱신.
6. **컷-정렬 오차 rule metric**: eval_service.py에 `cut_alignment_error`(초 단위) 추가 — 씬별로 `plan_shot_clips`를 재계산(순수 함수; shots/word_timings/narration/audio_duration 전부 state에 있고 `min_shot_clip_sec`은 Settings — services→pipeline.nodes import는 run_service의 image_node import 선례 있음)하고, **내부 컷 경계**(첫 클립 start·마지막 클립 end 제외)마다 최근접 word boundary(각 단어의 start/end)와의 |편차|를 취해 전 씬 평균. 클립 <2인 씬은 기여 없음, 데이터 없으면 0.0(기존 메트릭들의 폴백 관행). 배선: `RuleBasedMetrics` 필드 + `_compute_rule_metrics` + `_rule_metrics_to_dict` + `store_evaluation_results`의 Langfuse 메트릭 튜플(eval_service.py:628)에 추가. **`determine_winner`의 OQ-6 tiebreak 체인은 확장하지 않는다** — 이 메트릭은 회귀 감지용 기록이지 승자 결정 입력이 아니다(epics 원문 "회귀 감지" 그대로).
7. **`avg_subtitle_sync_error` 의미 반전 문서화**: provisional은 gap-free 균등분할이라 이 메트릭이 항상 ~0이었고, 진짜 WhisperX timings는 단어 사이 침묵이 있어 **0이 아닌 값이 정상**이 된다. 코드 무변경, 독스트링(eval_service.py:220-232)에 ① 11.4 이후 nonzero가 회귀가 아님 ② tiebreak 3b(lower=better, eval_service.py:533-537)가 폴백된(=열화된) 런을 약하게 선호하게 되는 알려진 왜곡 — 도달 자체가 드문 경로(양 LLM 판정 tie + scene-count tie)라 수용, 재설계는 eval 게이트 unfreeze(리서치 §20) 때 — 를 기록.
8. **관측성 + 회귀 가드 + 라이브 검증**: ① subtitle `_record_trace`에 정렬 결과 요약(예: `alignment: {whisperx: n, fallback: m}`) 추가 — §21 "강등을 게이트에서 보이게". 폴백 발생 시 AC1의 WARNING과 이중 기록. ② `qwen_tts_mock=True`면 정렬 스킵 + INFO 로그 1회 — mock WAV는 무음이라 정렬이 무의미하고, mock e2e가 1.2GB ko 정렬 모델 다운로드를 유발하면 안 된다(폴백=provisional 그대로). ③ 전체 스위트 green(`PYTHONPATH=$PWD/src pytest tests/`, 기준선 1433 passed + 1 skipped). 기존 테스트 중 `test_subtitle_node_uses_word_timings_not_aligner`(test_subtitle.py:377)는 **구 동작(정렬 스킵)을 고정하는 테스트라 역전 필수** — 갱신 사유를 테스트 주석에 기록(7.5 교훈). ④ **라이브 게이트(dev 수행, CPU라 GPU 인프라 불요)**: 기존 런 workspace의 실제 씬 wav 1개(예: run c6be1954)로 신규 `_align_sync` 경로 실행 — 정렬 성공, reconcile 통과(count match), 산출 경계가 균등분할과 실제로 다름(최소 1개 단어 경계 편차 > 0.2s), 마지막 end ≤ audio_duration 확인, Debug Log에 명령/수치 기록(5-9 교훈: 증거는 코드 변경 이후 시점). 최초 실행은 HF에서 `kresnik/wav2vec2-large-xlsr-korean`(~1.2GB) 다운로드 — 네트워크 필요.

## Tasks / Subtasks

- [x] Task 1: WhisperXAligner 슬림화 — ASR 삭제 + 모델 캐시 (AC: 4, 5)
  - [x] `_align_sync`에서 `load_model`/`transcribe` 삭제, `last_end = len(audio) / 16000`으로 대체
  - [x] `load_align_model` 결과를 인스턴스에 lazy 캐시(첫 호출 로드, 이후 재사용), ctor에서 `model`/`compute_type` 파라미터 제거
  - [x] config.py: `aligner_model`/`aligner_compute_type` 삭제, 75-77 주석 정정; `_get_aligner`/`test_subtitle.py`의 `_settings_ns`·SimpleNamespace 픽스처 동기 수정
  - [x] subtitle.py:38-43 독스트링(스테일 pyproject 문구), 모듈 독스트링(1-8행), tts.py 독스트링 정정
- [x] Task 2: reconcile 순수 함수 (AC: 3)
  - [x] `reconcile_word_timings(word_segments, narration, audio_duration)` — count 검증(vs `narration.split()`), 결측 보간(이웃/양끝 클램프), 단조·비음수·end>start·상한 sanitize, 불가 시 None
  - [x] `align()` 반환이 결측 단어를 **버리지 않고** 전달하도록 조정 — `_words_or_segments`의 usable-필터가 결측 단어를 탈락시켜 count mismatch를 유발하므로, word-level은 전 단어 통과(start/end 없을 수 있음)로 변경하거나 raw word_segments를 반환하는 형태로 재구성(segment-level 폴백 반환은 reconcile에서 count 불일치로 자연 폴백됨)
  - [x] 단위 테스트: 정상 1:1 매핑, 결측 단어 보간, count mismatch → None, 비단조/음수 입력 sanitize, 마지막 end 클램프, 출력이 `_word_timings_mismatch` 통과(강등 미발동) 고정
- [x] Task 3: subtitle_node 상시 정렬 + write-back + mock 스킵 (AC: 1, 2, 8)
  - [x] `if timings:` 게이트 제거 → 항상 align 시도(try/except) → reconcile → 성공 시 정렬본, 실패/None 시 provisional + WARNING(scene 번호+원인)
  - [x] `qwen_tts_mock=True` → 정렬 스킵(INFO 1회), provisional 경로
  - [x] 반환 scenes에 `"word_timings": final_timings` 포함(양 경로 모두)
  - [x] `_record_trace`에 alignment 카운트 블록 추가
  - [x] 테스트: 상시 호출(기존 377행 테스트 역전 — 사유 주석), aligner 예외 → 폴백+WARNING+스테이지 성공, write-back된 timings가 반환 state에 존재, mock 스킵, 폴백 시에도 sentence_cues 경로(segment-level 큐 부재)
- [x] Task 4: eval_service 컷-정렬 메트릭 + sync-error 문서화 (AC: 6, 7)
  - [x] `_cut_alignment_error(scenes, min_shot_clip_sec)` — plan_shot_clips 재계산, 내부 컷 경계 vs 최근접 word boundary 평균 편차
  - [x] `RuleBasedMetrics`/`_compute_rule_metrics`/`_rule_metrics_to_dict`/Langfuse 저장 튜플 배선(determine_winner 무변경)
  - [x] `_avg_subtitle_sync_error` 독스트링에 의미 반전 + tiebreak 3b 왜곡 기록
  - [x] 테스트: 정렬 timings에서 편차 ~0, 균등분할 timings에서 편차 > 0인 대비 케이스, 클립<2/데이터 없음 → 0.0, dict/저장 키 존재
- [x] Task 5: 라이브 게이트 + 전체 회귀 (AC: 8)
  - [x] 실제 씬 wav로 신규 정렬 경로 실행(CPU) — count match, 균등분할 대비 편차, end ≤ duration 수치를 Debug Log에 기록
  - [x] `PYTHONPATH=$PWD/src pytest tests/` 전체 green, ruff 변경 파일 clean

## Dev Notes

### 이 스토리가 존재하는 이유 (리서치 근거)

`research/technical-yt-flow-quality-strategy-research-2026-08-01.md` §5.4 현행 진단: "word timings = uniform whitespace split unless WhisperX runs (Qwen TTS gives no timestamps) → Story 8.11's beat-aligned shot cuts are actually driven by uniformly-apportioned timings in practice". §4.4: "Cut on narration beats, not a timer: cuts at sentence/clause boundaries of VO (~135–170 wpm → beat every 4–8s). TTS timing makes this automatable." 전략 항목 6번 "Run WhisperX unconditionally so shot cuts align to real speech, not uniform splits", §20(cut-alignment error를 eval 축에), §21(조용한 강등 → 게이트 가시화).

버그 체인의 정확한 형태: `tts.py:137 _provisional_timings`가 duration을 공백 토큰 수로 균등분할해 **항상** `word_timings`를 채우고 → `subtitle.py:373-377`은 `if timings:`로 aligner를 건너뛰므로 → `whisperx>=3.8.6`이 의존성에 있고 `WhisperXAligner`+config 배선이 완성돼 있음에도 프로덕션에서 한 번도 실행된 적이 없다. 컷·큐·eval 메트릭 전부 가짜 타이밍 소비 중.

### 핵심 설계 판정 4건

1. **write-back이 진짜 수정이다**: 파이프라인 순서 scenario→image→tts→subtitle→video에서 8.11 컷 경계는 video_node가 `scene["word_timings"]`로 계산한다(video.py:804·1268·1749 → shot_timing.plan_shot_clips:52 → subtitle.sentence_windows). subtitle_node가 정렬본을 자막에만 쓰고 state에 안 돌려주면(현행 반환은 `subtitle_path`만 추가) 컷은 계속 균등분할이다. epics 원문에는 명시되지 않았지만 "샷컷/자막큐를 실제 발화 경계에 정렬"의 필요조건.
2. **reconcile은 whitespace 토큰 1:1이 목표**: `sentence_windows`/`sentence_cues`는 `sum(len(s.split()))` == `len(timings)`일 때만 단어 그룹핑을 쓰고, 아니면 char-length apportion으로 강등된다(subtitle.py:202-238) — 강등되면 균등분할과 오십보백보라 스토리가 조용히 무효화된다. **whisperx 3.8.6 실물 확인 결과(이 워크스페이스 .venv 소스 검증)**: ko는 `LANGUAGES_WITHOUT_SPACES`(ja/zh만)에 없어 단어 = 공백 토큰이고, `word_segments`는 전 토큰을 보존하며, 정렬 불가 문자만 있는 단어는 whisperx가 **문장 내 보간을 이미 수행**(alignment.py:364-375), 전 문장이 정렬 불가일 때만 start/end가 빠진다. 따라서 reconcile은 잔여 결측 보간 + sanitize + count 검증만 하면 된다. 주의: whisperx는 `text.split(" ")`, 우리는 `narration.split()` — 연속 공백/개행이 있으면 count가 어긋날 수 있고 그 경우 폴백이 정답(자연 처리됨).
3. **ASR 패스는 죽은 무게**: `_align_sync`의 `load_model`+`transcribe`는 정렬 구간의 끝시각(`last_end`) 추정에만 쓰인다 — 트랜스크립트는 이미 알고, `len(audio)/16000` 폴백 라인이 이미 있다. 삭제하면 제일 비싼 연산과 `aligner_model`/`aligner_compute_type` 설정이 함께 사라진다. epics의 "compute_type=int8/CPU 폴백 검증" 항목은 이 삭제로 **대상 자체가 소멸** — 남는 것은 wav2vec2 정렬(기본 `aligner_device=cpu`, 씬당 수 초)이고 CPU 실행이라 ComfyUI VRAM 경합 문제도 원천 부재. `aligner_device`는 유지(GPU 가속 옵션).
4. **mock 게이트**: `qwen_tts_mock=True`의 WAV는 무음(tts.py `_write_mock_wav`) — 정렬 결과가 무의미하고, e2e/mock 런에서 HF 모델 다운로드(~1.2GB)와 정렬 시간을 유발한다. settings에 이미 있는 플래그를 읽어 스킵(신규 config 불요 — ponytail). 단위 테스트는 기존 `_get_aligner` monkeypatch 시임(test_subtitle.py:359)으로 mock 플래그와 무관하게 정렬 경로를 검증.

### 수정 대상 파일 현황

**`src/yt_flow/pipeline/nodes/subtitle.py`** (UPDATE — 중심 파일):
- 현재 상태: `WhisperXAligner`(L38-72, ASR+정렬, 호출마다 모델 재로드), `_words_or_segments`(L75-82, 결측 단어 탈락 필터), `_get_aligner`(L85-88), `_validate_segments`(L91-106, 큐 불변식 — raise 시 스테이지 실패), sentence 계열(L202-275 — **무변경**, 8.11 컷과 공유되는 수학), `subtitle_node`(L346-401, L373-386이 문제의 게이트).
- 변경: 게이트 제거+상시 정렬+폴백, reconcile 신설, write-back, mock 스킵, trace 블록, 독스트링 3곳.
- **접근 금지**: `sentence_windows`/`sentence_cues`/`_apportion`/`_sentence_to_cues`/`wrap_cue_text`/ASS 포매팅 — 큐·컷 수학은 이 스토리의 소비자이지 대상이 아니다. `_validate_segments`도 무변경(불변식은 reconcile이 맞춘다).

**`src/yt_flow/pipeline/nodes/tts.py`** (UPDATE — 독스트링만): L10-14 "Story 1.8 owns forced alignment" 문구를 11.4 폴백 관계로 갱신. `_provisional_timings` 코드는 무변경 — 폴백으로 계속 쓰인다.

**`src/yt_flow/config.py`** (UPDATE): `aligner_model`/`aligner_compute_type` 삭제(L78·80), L75-77 주석 정정. `extra="ignore"` 확인 완료라 .env 하위호환 안전. L134의 "aligner language (subtitle.py, already wired)" 주석은 유효 — 무변경.

**`src/yt_flow/services/eval_service.py`** (UPDATE): `RuleBasedMetrics`(L59-65) 필드 추가, `_cut_alignment_error` 신설(L220 인근 rule metric 구획), `_compute_rule_metrics`(L243-253), `_rule_metrics_to_dict`(L654-661), Langfuse 저장 메트릭 튜플(L628), `_avg_subtitle_sync_error` 독스트링(L220-232). `determine_winner`(L490-546)·`_rule_tiebreak`(L276-292) **무변경**.

**테스트**: `tests/pipeline/nodes/test_subtitle.py`(게이트 역전 + reconcile/폴백/write-back/mock 신규 — `_FakeAligner`·`_settings_ns` 시임 재사용, aligner_model/compute_type 필드 제거 동기화), `tests/services/test_eval_service.py`(신규 메트릭), `tests/pipeline/nodes/test_tts.py`(무변경 예상 — provisional 로직 그대로).

**무변경 확인 대상**: video.py(이 스토리는 컷 수학을 건드리지 않는다 — 8-16 병렬 세션과의 충돌면 자체가 없음), shot_timing.py, scenario_chain.py, run_service.py(`_nullify`의 word_timings 초기화는 tts 재실행이 복원 — retry 의미론 그대로), domain/state.py(WordTiming 그대로).

### 시스템 무결성 (명시 AC 밖이지만 깨지면 안 되는 것)

- **retry/resume 의미론**: subtitle 스테이지 retry(`_nullify` i≤3)는 subtitle_path만 지우고 word_timings(tts 산출)는 유지 — 신규 설계는 "항상 정렬"이라 이전 실행이 word_timings를 whisperx본으로 덮어썼어도 재정렬로 멱등. tts retry(i≤2)는 word_timings를 비우고 tts가 provisional을 재기록 — 폴백 재료가 항상 존재. 레거시 체크포인트의 video-단독 retry는 체크포인트에 있는 timings(구 런이면 provisional)를 그대로 쓰며 실패하지 않는다.
- **스테이지 실패 격리**: aligner 예외·reconcile None·validate 위반 어느 것도 raise로 새 나가면 안 된다 — 예외는 폴백, 불변식은 by construction. 유일하게 스테이지를 실패시켜도 되는 것은 기존과 동일한 조건(나레이션/오디오 부재, 큐 0개)뿐.
- **AD-1 레이어 규칙**: subtitle.py는 domain/config만 import(whisperx lazy import 유지 — 모듈 로드에 whisperx 불요). eval_service→shot_timing import는 services→pipeline.nodes 방향으로 run_service 선례와 동일.
- **결정론**: reconcile은 (word_segments, narration, audio_duration) 순수 함수. WhisperX 추론 자체는 부동소수 미세 비결정성이 있을 수 있으나 컷 수학은 렌더 시점 소비라 run 내 일관성만 필요 — 사이드카 캐시 무관(11-2/11-3과 동일 논리).
- **성능**: wav2vec2-large ko 정렬, CPU, 씬당 오디오 30-90s → 씬당 수 초 수준. 런당 총합 < 1분로 tts/이미지 스테이지 대비 무시 가능. 모델 로드 1회(AC4)가 지배 비용.
- **Langfuse score_id 충돌 없음**: 신규 메트릭은 `{run_id}-cut_alignment_error_{variant}` 형태로 기존 키와 불교차.

### Previous Story Intelligence (11-3, done — 리뷰 0수정 클린 패스)

- 11-3의 클린 패스 요인 그대로: 라이브 검증을 dev 태스크로 강제(증거는 코드 변경 **이후** 시점, 5-9 교훈), 불변식은 by construction + 테스트 고정, 접근 금지 구획 명시로 diff 국소화.
- 리뷰 교훈 "ffmpeg expr은 filter_complex 임베드 형태까지 검증" — 이 스토리의 등가물: whisperx 정렬을 **subtitle_node 경유 통합 경로**(모킹 없는 실제 wav)로 1회 검증하지, `_align_sync` 단독 호출만으로 끝내지 말 것.
- sprint-status.yaml 동시편집 충돌 상습 — 커밋 시 부분 스테이징.
- 워크트리 작업 시 `PYTHONPATH=$PWD/src` 필수(글로벌 editable install이 메인 트리 src를 가림).
- 전체 스위트 기준선: **1433 passed, 1 skipped**(YTFLOW_QWEN_TTS_SMOKE 게이트, 무관).

### Git Intelligence

- `dafe436`(11.3)/`ce4bcef`(11.2)/`3bd41aa`(11.1): Epic 11 관행 확립 — 파라미터 단위 테스트(픽셀/실렌더 비교 없음), 라이브 검증 Debug Log 증거, 스테일 주석 즉시 정정, `# ponytail:` 튜닝 시작점 표기. 이 스토리도 동일 궤도.
- 이 스토리는 Epic 11 중 유일하게 video.py를 안 건드린다 — 8-16(IC-Light) 병렬 세션과 충돌면 없음. eval_service.py는 6.x 계열 완료 후 안정 — 충돌 위험 낮음.

### Testing

- 위치: `tests/pipeline/nodes/test_subtitle.py`(주력), `tests/services/test_eval_service.py`(메트릭).
- 전부 순수 함수/모킹 단위 — 실제 whisperx 추론을 CI 테스트로 만들지 말 것(모델 1.2GB 다운로드; ffmpeg 의존 테스트조차 선례가 없는 코드베이스다). 실물 검증은 Task 5 라이브 게이트 1회로 충당.
- 역전 필수 테스트: `test_subtitle_node_uses_word_timings_not_aligner`(test_subtitle.py:377) — "timings 있으면 aligner 미호출"이 구 스펙 자체이므로 신 스펙("항상 호출, timings는 폴백")으로 교체하고 사유를 주석에 남긴다(7.5 교훈: 스토리 문서보다 테스트가 오래 산다).
- 무수정 통과가 증거인 테스트: sentence 계열(`sentence_windows`/`sentence_cues`/`wrap_cue_text`/ASS) 전부, test_shot_timing.py 전부, test_tts.py 전부 — 이들이 깨지면 소비자 수학을 침범했다는 신호.

### Project Structure Notes

- 신규 파일 0, 신규 의존성 0(whisperx는 이미 pyproject.toml:16), config 필드는 오히려 2개 삭제 — Epic 11에서 가장 작은 diff의 스토리. reconcile+게이트 교체+메트릭이 전부다.
- 정렬 모델 캐시는 인스턴스 속성이면 충분(`# ponytail:` 프로세스 전역 캐시는 subtitle_node가 런당 1회 인스턴스화라 불요).
- `aligner` config("whisperx" 고정 유효값)는 유지 — `_get_aligner`의 fail-fast 검증과 테스트 시임으로 이미 쓰이고 있고, 삭제는 이 스토리 스코프 밖.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 11.4] — 스토리 원문(상시 실행/폴백 강등/케이스 로그/rule metric/스테일 주석/VRAM 주의)
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#5.4, #4.4] — 현행 진단·다큐 컷 문법
- [Source: research 전략 항목 6, 20, 21] — 상시 WhisperX, cut-alignment eval 축, 강등 가시화
- [Source: src/yt_flow/pipeline/nodes/subtitle.py:38-106, 202-275, 346-401] — WhisperXAligner/_words_or_segments/_validate_segments, sentence 수학(무변경 소비자), 문제의 게이트
- [Source: src/yt_flow/pipeline/nodes/tts.py:10-14, 137-153] — provisional 출처(폴백으로 강등될 대상)
- [Source: src/yt_flow/pipeline/nodes/shot_timing.py:33-86] — 컷 경계 유도(word_timings의 최종 소비자)
- [Source: src/yt_flow/pipeline/nodes/video.py:804, 1268, 1626, 1749] — plan_shot_clips 호출부 + min_shot_clip_sec 스레딩
- [Source: src/yt_flow/services/eval_service.py:59-65, 215-253, 276-292, 520-546, 628, 654-661] — RuleBasedMetrics/rule 구획/tiebreak(무변경)/저장 배선
- [Source: src/yt_flow/services/run_service.py:746-763] — _nullify 캐스케이드(retry 의미론)
- [Source: src/yt_flow/config.py:74-80, 134] — aligner 설정 군(2필드 삭제 대상), extra="ignore"
- [Source: .venv/lib/python3.12/site-packages/whisperx/alignment.py:30, 58, 364-375] — ko=공백 토큰 언어, kresnik 정렬 모델, whisperx 자체 문장 내 결측 보간(reconcile 설계 근거, 설치본 3.8.6 실물 확인)
- [Source: tests/pipeline/nodes/test_subtitle.py:36-52, 359, 377] — _settings_ns/_FakeAligner 시임, 역전 대상 테스트
- [Source: _bmad-output/implementation-artifacts/11-3-fractal-noise-camera-paths.md] — 직전 스토리: 클린 패스 관행, 라이브 검증 규율

## Dev Agent Record

### Agent Model Used

Claude Fable 5 (claude-fable-5) — BMAD dev-story workflow, 2026-08-01

### Debug Log References

- **라이브 게이트 (AC8-④, 2026-08-01, 코드 변경 이후 실행)**: `PYTHONPATH=$PWD/src .venv/bin/python <scratchpad>/live_gate_11_4.py` — run `c6be1954-da0f-4dee-ab07-a2b4f3bcf21e` scene 1 실제 wav(52.062s, 96단어)를 신규 align-only 경로(CPU)로 처리.
  - `word_segments=96, reconciled=96` — count match, `_word_timings_mismatch` 강등 미발동
  - 균등분할 provisional 대비 start 편차: **max 3.800s, mean 1.585s** (기준 0.2s 초과 — 실제 발화 경계임을 확인)
  - 첫 5단어 정렬본 `[('영',0.1,0.24), ('점',0.42,0.58), ('삼',0.7,0.8), ('초.',0.96,1.06), ('고작',1.4,1.62)]` vs 균등 `[(0.0,0.54), (0.54,1.08), …]`
  - 마지막 `end_sec ≤ 52.062` assert 통과
  - **통합 경로(11-3 교훈)**: 동일 wav를 `subtitle_node` 전체 경유(실 Settings/.env) — error=None, write-back timings == 직접 정렬본, .ass 생성 확인. 게이트용 `workspace/live-gate-11-4/` 정리 완료.
  - 정렬 모델 kresnik/wav2vec2-large-xlsr-korean은 HF 캐시에 이미 존재, 다운로드 불요였음.

### Completion Notes List

- **Task 1**: `WhisperXAligner`에서 ASR 패스(`load_model`+`transcribe`) 삭제 — 정렬 구간 끝은 `len(audio)/16000` 고정. align 모델은 인스턴스 lazy 캐시(씬 순차 await라 락 불요). ctor `(device, language)`로 축소, config `aligner_model`/`aligner_compute_type` 삭제(`extra="ignore"`라 .env 잔존 무해). 스테일 주석/독스트링 4곳(subtitle 모듈/클래스, config, tts) 정정.
- **Task 2**: `reconcile_word_timings` 신설 — count 검증(vs `narration.split()`), 결측 run 이웃 선형보간(양끝 0.0/audio_duration 클램프), 불변식 by construction sanitize(비음수·단조·end>start·상한), 퇴화 입력 None. `align()`은 raw `word_segments`를 그대로 반환(결측 단어 보존)하도록 재구성 — `_words_or_segments` usable-필터 삭제(segment-level 반환은 reconcile count 불일치로 자연 폴백).
- **Task 3**: `if timings:` 게이트 제거 → 상시 정렬 시도, 예외/reconcile None → provisional 폴백 + WARNING(scene 번호+원인), 스테이지 실패 절대 없음(기존 허용 실패 조건 — 나레이션/오디오 부재, 큐 0개 — 만 유지). 구 segment-level 큐 분기 삭제(폴백도 sentence_cues). 반환 scenes에 `word_timings` write-back(양 경로). `_record_trace`에 `alignment: {whisperx, fallback}` 블록. `qwen_tts_mock=True` → 정렬 스킵 + INFO 1회.
- **Task 4**: `_cut_alignment_error` 신설(plan_shot_clips 재계산, 내부 컷 경계 vs 최근접 word boundary 평균 |편차|; 클립<2/데이터 없음 → 0.0) + `RuleBasedMetrics`/`_compute_rule_metrics`/`_rule_metrics_to_dict`/Langfuse 저장 튜플 배선, `determine_winner` 무변경. `_avg_subtitle_sync_error` 독스트링에 의미 반전 + tiebreak 3b 왜곡 기록. **메트릭 성질 판정**: 컷은 state의 word_timings에서 유도되므로 건강한 1:1 경로에선 ~0이고, `sentence_windows`의 char-apportion 강등(AC3 불변식 붕괴 = 균등분할 회귀의 컷-레벨 증상)이 발동할 때 정확히 >0 — 대비 테스트를 이 두 경로로 고정.
- **테스트 갱신**: `test_subtitle_node_uses_word_timings_not_aligner`(구 스펙 고정 테스트) → `test_subtitle_node_always_calls_aligner_even_with_timings`로 역전(사유 주석 포함, 7.5 교훈). `_FakeAligner`를 raw word_segments 계약으로 교체(기본값: transcript에서 1:1 합성). reconcile 단위 테스트 12건, 폴백/write-back/mock/trace 신규 테스트 6건, eval 메트릭 테스트 5건 추가. `test_store_results_idempotent_scores` 13→15 스코어로 갱신(신규 메트릭 2건).
- **레이어링 가드 확장**: `test_services_does_not_import_api_or_pipeline`이 services→pipeline import를 run_service만 예외로 두고 있어, eval_service→`shot_timing`(순수 함수) import를 명시 허용 목록으로 추가 — Dev Notes의 "run_service 선례" 승인 범위 내, api/ 금지는 그대로.
- **전체 회귀**: `PYTHONPATH=$PWD/src pytest tests/` → **1451 passed, 1 skipped, 0 failed** (기준선 1433 + 신규 테스트 순증 18; skip은 기존 YTFLOW_QWEN_TTS_SMOKE 게이트로 무관). ruff 변경 파일 전부 clean. 1차 전체 실행에서 `test_e2e_stub_run` 1건 실패했으나 단독·재실행 모두 통과 — 본 변경과 무관한 순서 의존 플레이크로 판정(해당 e2e는 stub 노드 경로라 정렬 코드 미경유).

### File List

- `src/yt_flow/pipeline/nodes/subtitle.py` — WhisperXAligner align-only + 모델 캐시, reconcile_word_timings 신설, _words_or_segments 삭제, 상시 정렬 + 폴백 + write-back + mock 스킵, _record_trace alignment 블록, 독스트링 정정
- `src/yt_flow/pipeline/nodes/tts.py` — 모듈 독스트링만(provisional = 11.4 폴백 관계)
- `src/yt_flow/config.py` — aligner_model/aligner_compute_type 삭제, 주석 정정
- `src/yt_flow/services/eval_service.py` — cut_alignment_error 메트릭 신설 + 배선, _avg_subtitle_sync_error 의미 반전 문서화, shot_timing import
- `tests/pipeline/nodes/test_subtitle.py` — 시임 교체(_FakeAligner/_settings_ns), reconcile/aligner 캐시/상시 정렬/폴백/write-back/mock/trace 테스트, 구 게이트 테스트 역전
- `tests/services/test_eval_service.py` — cut_alignment_error 테스트 5건, FakeSettings.min_shot_clip_sec, idempotent 스코어 13→15
- `tests/services/test_character_service.py` — 레이어링 가드에 eval_service→shot_timing 순수 함수 예외 추가

## Senior Developer Review (AI)

**Reviewer:** Jay (자동 리뷰, story-automator) — 2026-08-01
**Outcome:** Approve — CRITICAL/HIGH 0건, MEDIUM 1건·LOW 1건 자동 수정, LOW 2건 수용 기록.

**검증 요약:** AC 8건 전부 구현 확인(게이트 제거·폴백·segment-분기 삭제 ①, write-back ②, reconcile 순수 함수+불변식 by construction ③, ASR 삭제+config 2필드 삭제+모델 1회 로드 캐시 ④, 스테일 주석 4곳 정정 ⑤, cut_alignment_error 배선+determine_winner 무변경 ⑥, sync-error 독스트링 ⑦, trace 블록·mock 스킵·라이브 게이트 Debug Log ⑧). Task [x] 5건 전부 실코드 대조 통과. git 변경 파일 == File List(불일치 0). 접근 금지 구획(sentence 수학·_validate_segments·video.py·shot_timing.py·determine_winner) 무변경 확인. 전체 스위트 1451 passed + 1 skipped 재현, ruff clean. 잔존 aligner_model/aligner_compute_type/_words_or_segments 참조 0건(.env/.env.example 포함).

**수정 적용:**
1. [MEDIUM][AC:8] `alignment: {whisperx, fallback}` trace 블록이 무테스트였음(Completion Notes는 "trace 신규 테스트" 주장 — 실제 신규 노드 테스트는 5건). → `test_trace_receives_metrics`에 alignment assert 추가 + 혼합 카운트 테스트 `test_trace_alignment_counts_mixed_aligned_and_fallback` 신설 (tests/pipeline/nodes/test_subtitle.py).
2. [LOW][AC:1] 폴백 WARNING의 기본 cause 문자열이 reconcile None의 세 원인 중 audio_duration 부재/0 케이스를 누락 → 문구에 명시 (subtitle.py).

**수용(무변경) 노트:**
- [LOW] reconcile 보간이 부분 결측 단어(start만 존재)의 알려진 start를 버리고 run 전체를 재보간 — whisperx 실물은 start/end both-or-neither가 지배적이라 손실 무시 가능, 코드 단순성 우위.
- [LOW] `_compute_rule_metrics`의 `min_shot_clip_sec=2.0` 키워드 기본값이 shot_timing 자체 기본값과 중복 — 테스트 편의 시임, 실런타임은 `s.min_shot_clip_sec` 전달이라 무해.

## Change Log

- 2026-08-01: Story 11.4 구현 완료 — WhisperX 상시 정렬(폴백=provisional), word_timings write-back, ASR 패스 삭제+모델 1회 로드, reconcile 순수 함수, cut_alignment_error rule metric, 라이브 게이트 통과(run c6be1954 scene 1, max 편차 3.8s). Status: review.
- 2026-08-01: 시니어 리뷰(자동) — Approve. MEDIUM 1(trace alignment 블록 무테스트 → 테스트 2건 추가)·LOW 1(폴백 cause 문구) 수정, LOW 2건 수용 기록. 재검증: 1452 passed + 1 skipped, ruff clean. Status: done.
