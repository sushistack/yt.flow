# Story 12.8 — Langfuse seeding (DEV MODE, straight to `production`)

`CLAUDE.md` / `docs/PROMPT_POLICY.md`의 DEV-MODE 배너대로 A/B도 승격 게이트도 없이
`production` 직행입니다. 런타임 체인은 프롬프트를 Langfuse에서 읽으므로 **시딩이 라이브
측정보다 먼저**입니다 — 시딩 전에 돌리면 옛 프롬프트를 잰 셈이 됩니다.

## 사전 확인 — 무엇이 바뀌는가

`--dry-run`은 매니페스트(이름 + 변수)만 출력할 뿐 Langfuse와 대조하지 않습니다. 그래서
변경 집합은 12-6/12-7 시딩 기록과 같은 방식으로 `build_manifest` + `client.get_prompt`
직접 비교로 계산했습니다 (2026-08-16, `langfuse.eli.kr`):

```
CHANGED:
   scenario/structure
MISSING:
unchanged: 19
```

이 스토리가 편집한 프롬프트 하나뿐입니다. 알려진 드리프트(`character/*`) 동반 승격 없음.

`--dry-run`은 `scp_source_text`가 실제로 템플릿 변수로 잡혔는지도 확인해 줍니다 —
이 스토리는 12.7과 달리 **새 `{{변수}}`를 추가**하므로 여기 없으면 아웃라인은 원문을
영영 못 봅니다:

```
scenario/structure: vars=['archetype_guide', 'format_guide', 'glossary_section',
  'max_closing_word_pct', 'max_opening_word_pct', 'min_budget_spread', 'parse_error',
  'research_packet', 'scene_word_budget_max', 'scene_word_budget_min', 'scp_id',
  'scp_source_text', 'scp_visual_reference', 'story_archetype', 'target_duration',
  'total_word_budget_max', 'total_word_budget_min']
```

## 시딩

```
uv run python scripts/migrate_prompts.py --label production --source prompts
```

```
created: scenario/structure
skipped: (나머지 19개)
```

Exit 0.

## 코드 쪽 가드

`_require_seeded_budget_variables`(`scenario_chain.py`)가 12.6의 예산 변수에 더해
`{{scp_source_text}}` 부재를 `structure_step` 진입에서 잡습니다. 12.7의 가드와 이유가
다릅니다: 여기서는 옛 프롬프트가 **조용히 되돌아가지 않고** 매 씬 `fact_references_invalid`로
두 번 다 죽습니다 — 실패는 하는데 원인으로 **모델을 지목**합니다. 그래서 메시지가 둘로
갈립니다(12.6 예산 밴드 / 12.8 원문 블록). 두 번째 메시지가 재시딩 명령을 그대로 답니다.
