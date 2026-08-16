# Story 12.7 — Langfuse seeding (DEV MODE, straight to `production`)

`CLAUDE.md` / `docs/PROMPT_POLICY.md`의 DEV-MODE 배너대로 프롬프트 편집은 A/B도 승격 게이트도 없이 `production`으로 직행합니다. 라이브 재측정이 **시딩된 프롬프트**를 읽으므로 시딩이 재측정보다 먼저입니다.

## 사전 확인 — 무엇이 바뀌는가

`--dry-run`은 이름과 변수만 나열할 뿐 Langfuse와 대조하지 않습니다. 그래서 변경 집합은 스크립트 자신의 `build_manifest` + `client.get_prompt`로 직접 계산했습니다(2026-08-16, `langfuse.eli.kr`):

```
CHANGED:
   scenario/writing
   scenario/writing_scene_repair
MISSING:
unchanged: 18
```

이 스토리가 편집한 두 프롬프트뿐입니다. 무관한 드리프트 동반 승격 없음.

`--dry-run`은 두 프롬프트의 변수 집합이 **그대로**임도 확인해 줍니다 — 배정은 새 변수가 아니라 기존 `scene_structure`(자유 텍스트)를 타고 갑니다:

```
scenario/writing: vars=['format_guide', 'glossary_section', 'parse_error',
  'quality_feedback', 'scene_structure', 'scp_id', 'scp_visual_reference']
scenario/writing_scene_repair: vars=['format_guide', 'glossary_section',
  'original_scenes', 'parse_error', 'scene_feedback', 'scene_structure', 'scp_id',
  'scp_visual_reference']
```

## 시딩

```
uv run python scripts/migrate_prompts.py --label production --source prompts
```

```
created: scenario/writing
created: scenario/writing_scene_repair
skipped: (나머지 18개)
```

Exit 0.

## 재시딩 두 번 (리뷰 지적 반영)

리뷰가 프롬프트 가드절 6개를 요구했고(`after.md` pass 2), 이어 연결 문장의 접지를 좁혔습니다(pass 3). **매 편집마다 다시 시딩하고 다시 측정했습니다** — 재지 않은 프롬프트를 출하하지 않기 위해서입니다.

```
2회차: created: scenario/writing, scenario/writing_scene_repair   (변경 집합 재확인: 이 둘뿐)
3회차: created: scenario/writing                                   (연결 규칙 한 항목)
```

커밋된 `prompts/scenario/*.md`와 Langfuse `production`은 3회차 이후 동일합니다. 코드 쪽에도 `_require_seeded_device_allocation`(`scenario_chain.py`)이 붙어, 시딩되지 않은 `scenario/writing`으로 런이 도는 것을 `writing_step` 진입에서 막습니다 — 배정이 새 `{{변수}}`가 아니라 자유 텍스트를 타고 가므로, 옛 프롬프트는 렌더에 실패하지 않고 **조용히 옛 할당량으로 되돌아가기** 때문입니다.
