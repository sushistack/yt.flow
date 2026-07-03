# Story 5.4: TTS 한국어 자연화 — 낭독용 텍스트 정규화 스테이지

Status: draft

## Story

As Jay,
I want narration text to be normalized for Korean speech synthesis before TTS,
so that ambiguous readings (e.g. "한 연구원" → "한연구원"으로 붙여 읽힘) and awkward phrasing are avoided.

## Context (2026-07-03 라이브 리뷰 피드백 #5)

Qwen TTS가 띄어읽기·수식 관계를 오독하는 사례 발견. 텍스트 쪽에서 오독 유발 표현을 제거하는 것은 표준 기법으로 확실히 완화 가능. 억양 자체는 모델 한계일 수 있어 이 스토리 범위 밖 (부족하면 voice/모델 파라미터 A/B를 별도 발의).

## Acceptance Criteria

1. **Given** scenario 체인의 review/critic 통과 산출물, **When** 새 `tts_normalize` 스테이지 실행, **Then** 각 씬 narration이 낭독 친화적으로 재작성된다 — 규칙: ①오독 유발 표현 교체(관형사 "한"+직함류 → "한 명의 X" 등), ②장문 분절·쉼표로 띄어읽기 유도, ③숫자/단위/영문 약어를 한글 발음 표기로, ④의미·사실 관계는 불변
2. **Given** 정규화된 narration, **Then** 자막(SRT)과 TTS가 **같은 텍스트**를 사용한다 — 낭독용/표시용 이원화 금지 (WordTiming 정합성 유지, 이원화는 YAGNI)
3. **Given** 정규화 결과 문장 수, **Then** 원본과 동일하다 — shot 1:1 매핑(visual_breakdown의 sentence↔shot 계약)이 깨지지 않음. 문장 수가 달라지면 해당 씬은 원본 유지 + 경고 로그 (전체 실패 아님)
4. **Given** Langfuse Prompt Hub, **Then** `scenario/tts_normalize` 프롬프트가 production 라벨로 시드되고 `prompts/scenario/tts_normalize.md` 인리포 사본이 존재
5. **Given** DeepSeek 호출 실패, **Then** 기존 체인 규약대로 `PipelineState.error`로 표면화 (53abd54 에러 라우팅 계약: 성공 반환에 `"error": None` 포함)
6. 기존 체인 테스트 규약 준수: `tests/fixtures/cassettes/deepseek_tts_normalize.json` 카세트 + `_STAGE_CASSETTES` 등록, 문장 수 불일치 폴백 테스트 포함

## Tasks / Subtasks

- [ ] `prompts/scenario/tts_normalize.md` 작성 — JSON 계약: 입력 `{scenes: [{scene_num, narration}]}` → 출력 동일 구조, 위 4개 규칙 명시 (AC: 1, 4)
- [ ] Langfuse 시드 (AC: 4)
- [ ] `scenario_chain.py`에 `tts_normalize_step` 추가 — `_call_stage` 재사용, 문장 수 검증(`split_sentences`) + 씬 단위 폴백 (AC: 1, 3, 5)
- [ ] `scenario.py` 오케스트레이터에서 critic 통과 후 호출 (재시도 루프 밖 — 정규화는 1회) (AC: 1)
- [ ] 카세트 + 테스트: 정상 정규화, 문장 수 불일치 폴백, 스테이지 실패 표면화 (AC: 3, 5, 6)
- [ ] 라이브 검증: 실전 런에서 "한 연구원"류 표현이 포함된 씬으로 before/after 청취 비교

## Dev Notes

- 위치가 scenario 체인 끝인 이유: tts_node에 넣으면 자막(subtitle_node)이 보는 narration과 갈라져 AC2 위반. 체인 끝이면 하류 전체가 정규화본을 봄.
- 비용: 씬 배치 1콜 추가 (체인 12–20콜 → +1).
- 억양/운율 자체 개선(voice 선택, 파라미터)은 완화 불충분 시 Epic 4 A/B 인프라로 별도 실험.
