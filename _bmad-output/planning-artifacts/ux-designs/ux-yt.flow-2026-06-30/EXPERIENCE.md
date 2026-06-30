---
name: yt.flow
status: final
created: 2026-06-30
updated: 2026-06-30
mockups:
  - mockups/dashboard.html
  - mockups/run-detail.html
sources:
  - _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md
---

# yt.flow — Experience Spine

## Foundation

Desktop web, single surface, local deployment (`localhost:8000`). React SPA — shadcn/ui + Tailwind — served by FastAPI as a static build under `/app`. Single operator; no auth; no multi-user state. SSE (`/runs/{id}/progress`) for real-time stage and gate events. DESIGN.md (Zinc System direction) is the visual identity reference; this spine is the behavior.

Form factor: desktop browser, wide viewport (≥ 1024px minimum design target). No mobile layout required.

## Information Architecture

| Surface | URL pattern | Reached from | Purpose |
|---------|------------|-------------|---------|
| Dashboard | `/` | App root, nav wordmark | Run list; new-run entry point |
| Run Detail | `/runs/{id}` | Dashboard row click | Stage progress, artifact review, gate controls, retry |
| A/B Comparison | `/runs/{id}/ab` | Run Detail → A/B tab | Side-by-side variant scoring |

No persistent sidebar nav. Top nav is the only persistent chrome (wordmark + "새 실행" CTA). Modal stack: one level deep maximum — SCP Picker Dialog lives on Dashboard; inline confirmations (Retry) live in Run Detail; no Dialog-on-Dialog.

→ Key-screen mockups: [mockups/dashboard.html](mockups/dashboard.html) (run list + SCP picker), [mockups/run-detail.html](mockups/run-detail.html) (image stage awaiting approval). Spine wins on conflict.

## Voice and Tone

Operator microcopy. Short, active, specific. No apologies, no explanations of what the system is doing when the label says it.

| Do | Don't |
|----|-------|
| "승인 대기" | "파이프라인이 사용자의 확인을 기다리고 있습니다" |
| "재시도" | "이 스테이지를 다시 실행하시겠습니까?" |
| "실행 중 — scenario" | "현재 시나리오 생성 단계가 진행 중입니다" |
| "TTS 오류" | "요청하신 작업을 완료하지 못했습니다" |
| "열기" | "상세 보기로 이동하기" |

Korean UI strings throughout. Stage tokens (`scenario`, `image`, `tts`, `subtitle`, `video`) displayed in English monospace — they are technical identifiers, not prose labels.

## Component Patterns

Behavioral. Visual specs in DESIGN.md.Components.

| Component | Use | Behavioral rules |
|-----------|-----|-----------------|
| **Run Row** | Dashboard list | Full-row click → Run Detail. Status badge + stage token visible at glance. Awaiting rows (purple) sort to top. No per-cell actions; "열기" link is redundant affordance only. |
| **SCP Picker** | "새 실행" dialog | shadcn Dialog. List loaded from `GET /scps` (or client-side from pre-fetched facts). **Default sort: rating descending.** Search `<input>` debounced 200ms — matches against: (1) numeric ID part (`"096"` → SCP-096), (2) full ID string (`"SCP-096"`), (3) English nickname derived from `facts.json` tags (hyphen-normalized: `"shy guy"` matches tag `shy-guy`; `"plague doctor"` matches `plague-doctor`). Meta/admin tags excluded from nickname derivation (`_licensebox`, `scp`, `_cc`, `featured`, `illustrated`, `rewrite`, `co-authored`, `audio`, `_licensebox`). Row shows: SCP ID (mono), English nickname (first descriptive tag), `object_class`, rating (right-aligned, tabular-nums). Keyboard: ↑↓ + Enter to select. On confirm → `POST /runs`; dialog closes; new row at list top with "실행 중" badge. |
| **Stage Sidebar** | Run Detail, 240px left | Ordered list of 5 stages: scenario → image → tts → subtitle → video. Each item: stage token (mono) + state icon + gate indicator. Click → navigate to that stage's artifact panel. Stages not yet reached: muted, not clickable. Active item: primary-blue left border. Awaiting item: purple left border (strongest signal; means "act here"). |
| **Artifact Panel** | Run Detail, flex-1 right | Content by selected stage (see State Patterns). Header: stage name + edit or retry button as applicable. Footer: gate controls when `gate_state === 'pending'`. |
| **Gate Controls** | Artifact panel footer, awaiting only | "승인" (primary button) + "반려" (outline destructive). Visible only when `gate_state === 'pending'`. On click: button disabled + spinner during request. On success: buttons replaced by state label; SSE confirms. |
| **Retry Button** | Artifact panel header, approved, rejected, or failed | Outline button "재시도". On click: inline confirmation text appears below button ("이 스테이지를 다시 실행합니까?") with "확인" + "취소" inline — no modal. "확인" → `POST /runs/{id}/stages/{stage}/retry`; panel state resets to "실행 중". |
| **Inline Text Editor** | scenario and subtitle panels only | "편집" button in panel header toggles to edit mode: textarea replaces read view. "저장" → `PATCH` to artifact endpoint; reverts to read mode with updated text. "취소" reverts without saving. Saving does not advance the pipeline; "승인" is still required. |
| **SSE Progress** | Run Detail, persistent | Hidden `EventSource` on `/runs/{id}/progress`. On `stage_entry`/`stage_exit`: update sidebar item state. On `gate_pending`: update gate badge in sidebar (purple border). No toast or push notification — state encoded in sidebar only. |
| **Image Lightbox** | image stage panel | Click any scene image → lightbox overlay (shadcn Dialog full-screen). ← → keys navigate scenes. Esc closes. |

## State Patterns

### Dashboard

| State | Treatment |
|-------|-----------|
| Empty | Center: "실행 없음. 새 실행을 시작하세요." + primary CTA |
| Loading | shadcn Skeleton rows (4) at row height |
| List | Sorted `started_at` desc; awaiting-approval rows float to top |
| Error (API down) | Top banner: "서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요." |

### Run Detail — artifact panel by stage

| Stage | Panel content | Editable |
|-------|--------------|----------|
| `scenario` | Scrollable Korean prose, `~65ch` line width, 1.6 line-height | Yes — inline textarea |
| `image` | Scene-indexed image grid (2 col). Click → lightbox. Image count label. | No — Retry only |
| `tts` | Per-scene `<audio controls>`. Scene index + duration. Sorted by scene number. | No — Retry only |
| `subtitle` | SRT text in monospace textarea-like scroll area. Subtitle count label. | Yes — inline textarea |
| `video` | Single `<video controls>` player, full panel width. Download link below. | No — Retry only |
| Not yet reached | Muted "아직 실행되지 않은 스테이지입니다." | — |
| Running | Spinner + "실행 중…" placeholder. SSE will update when done. | — |

### Gate states

| Gate state | Sidebar indicator | Panel footer |
|-----------|------------------|--------------|
| `pending` | Purple left border + "⏸" icon | "승인" + "반려" buttons |
| `approved` | Green left border + "✓" | State label only |
| `rejected` | Red left border + "✗" | "재시도" button |
| `n/a` (not reached) | No border, muted text | — |

### Run-level states (dashboard badge)

| State | Badge |
|-------|-------|
| `running` | amber "● 실행 중" |
| `awaiting_approval` | purple "⏸ 승인 대기" |
| `complete` | green "✓ 완료" |
| `failed` | red "✗ 실패" |

## Interaction Primitives

- **Row tap target**: entire dashboard row is the interactive target. `cursor: pointer`. No nested buttons — "열기" is a visual affordance only, not an additional click target.
- **SCP search**: debounce 200ms. Filter-as-you-type, no submit button. Empty query shows full list (2000 items virtualized). ↑↓ + Enter for keyboard selection.
- **Stage navigation**: clicking a sidebar item scrolls the main panel to top and loads that stage's artifact. Browser history is not pushed per stage (only per run).
- **Inline edit lifecycle**: "편집" → textarea active. "저장" → `PATCH` → read mode. "취소" → read mode, no save. Navigating away from a stage with unsaved edits: show `window.confirm("저장하지 않은 변경사항이 있습니다. 계속하시겠습니까?")`.
- **Gate action lifecycle**: button click → disabled + spinner → API call → SSE event confirms → UI updates. If API fails: button re-enabled, error inline below buttons.
- **Retry confirmation**: inline below the retry button (not a Dialog). "확인" fires request; "취소" dismisses. Confirmation disappears after 5 seconds of no action.
- **Back to Dashboard**: wordmark click. Browser back also works — no special handling needed.

## Accessibility Floor

Behavioral. Visual contrast in DESIGN.md.

- Semantic structure: `<nav>`, `<main>`, `<aside>` in Run Detail two-column layout. `<ul>` + `<li>` for stage sidebar and SCP picker results.
- Focus visible: shadcn default ring on all interactive elements.
- Color not sole indicator: every status encoded as badge text + color (never color alone). Gate state: left border + text label + icon.
- Audio controls: native `<audio controls>` — keyboard accessible without JS.
- SCP Picker: `role="listbox"` + `aria-activedescendant` for keyboard navigation of results. `aria-label="SCP 검색"` on the input.
- Stage sidebar items: `aria-current="true"` on the active stage.
- Retry confirmation: `role="alert"` on the inline confirmation so screen readers announce it.

## Key Flows

### Jay starts a new SCP run

Jay opens `localhost:8000`. The dashboard shows three runs — SCP-173 is purple ("승인 대기", image stage). He'll handle that after.

He clicks "+ 새 실행". A Dialog opens. Search input is focused. He types "096". The list filters to SCP-096 "수줍음쟁이" (Euclid, rating 8800). He clicks it. The dialog closes. A new row appears at the top: "SCP-096 — 실행 중 — scenario". He leaves the tab open and does other work.

### Jay reviews images and re-runs a stage

Jay returns to the dashboard. SCP-096 shows "승인 대기" (purple) — image stage finished while he was away. SCP-173 is still purple too; two runs need attention.

He clicks SCP-096. Run Detail opens. Stage sidebar shows "image" with a purple border. The artifact panel shows 8 scene images in a 2-col grid. Scene 3 looks tonally wrong — too bright for SCP-096's horror register. He clicks "재시도". Inline: "이 스테이지를 다시 실행합니까? 확인 / 취소". He clicks "확인". Panel shows "실행 중…". Sidebar item turns amber.

Three minutes later, SSE fires. Purple border returns. He reviews the new images. Scene 3 is better. He clicks "승인" in the panel footer. Footer clears. Sidebar turns green. Pipeline advances to TTS automatically.

### Jay edits the scenario text before approving

The scenario stage for SCP-173 completed and is awaiting approval. Jay reads the generated Korean prose. The opening line is too mild — doesn't capture SCP-173's clinical containment menace. He clicks "편집" in the panel header. A textarea replaces the read view. He rewrites the first two sentences. Clicks "저장". Read mode returns with his edited text. He clicks "승인". Pipeline advances.
