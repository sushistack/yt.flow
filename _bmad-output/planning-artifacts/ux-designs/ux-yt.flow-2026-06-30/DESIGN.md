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
colors:
  # Dark (primary mode)
  background: '#1C1C1E'
  card: '#2C2C2E'
  card-hover: '#323234'
  border: 'rgba(255,255,255,0.07)'
  foreground: '#F2F2F7'
  muted-foreground: '#8E8E93'
  subtle-foreground: '#48484A'
  primary: '#0A84FF'
  primary-foreground: '#FFFFFF'
  # Light mode (system-preference swap)
  background-light: '#F2F2F7'
  card-light: '#FFFFFF'
  border-light: 'rgba(0,0,0,0.09)'
  foreground-light: '#1C1C1E'
  muted-foreground-light: '#6C6C70'
  primary-light: '#007AFF'
  # Semantic status — separate tier, never used as accent
  status-running: '#FF9F0A'
  status-running-bg: 'rgba(255,159,10,0.18)'
  status-awaiting: '#BF5AF2'
  status-awaiting-bg: 'rgba(191,90,242,0.18)'
  status-approved: '#30D158'
  status-approved-bg: 'rgba(48,209,88,0.18)'
  status-failed: '#FF453A'
  status-failed-bg: 'rgba(255,69,58,0.18)'
typography:
  body:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: 13px
    fontWeight: '400'
    lineHeight: '1.4'
    letterSpacing: '-0.01em'
  label:
    fontSize: 11px
    fontWeight: '500'
    letterSpacing: '0'
  mono:
    fontFamily: "'Courier New', Consolas, Menlo, monospace"
    fontSize: 12px
    fontWeight: '700'
rounded:
  badge: 6px
  sm: 6px
  md: 10px
  lg: 12px
  cta: 10px
spacing:
  # Tailwind defaults inherited; no overrides
components:
  status-badge:
    padding: '3px 8px'
    radius: '{rounded.badge}'
    fontSize: 11px
    fontWeight: '500'
  card-row:
    background: '{colors.card}'
    hover: '{colors.card-hover}'
    padding: '13px 16px'
    borderBottom: '1px solid {colors.border}'
  stage-sidebar-item:
    padding: '10px 14px'
    radius: '{rounded.sm}'
    activeLeftBorder: '2px solid {colors.primary}'
    awaitingLeftBorder: '2px solid {colors.status-awaiting}'
  cta-primary:
    background: '{colors.primary}'
    foreground: '{colors.primary-foreground}'
    radius: '{rounded.cta}'
---

## Brand & Style

yt.flow is a local single-operator pipeline control workbench for SCP Foundation YouTube content. It is not a product — it is a tool. The visual identity follows that distinction: iOS-native zinc dark as the ground, system blue for primary actions, semantic color for pipeline state. Restraint is the brand. No gradients, no decorative chrome, no marketing copy. Every element encodes information or enables an action.

Inherits shadcn/ui defaults throughout. This file specifies only the brand-layer delta. Components not listed here ship from shadcn unchanged (Dialog, Sheet, Skeleton, Separator, Toast, etc.).

Dark-first: the operator monitors pipelines over long sessions. Light mode is supported for system-preference compliance.

## Colors

Two-tier palette: zinc neutrals (ground) + system blue (action). Status color is a third, independent tier encoding pipeline state — it must never bleed into accent usage.

**Dark (primary)**

| Token | Hex | Role |
|-------|-----|------|
| `background` | `#1C1C1E` | iOS zinc-900. Ground. Chosen over pure black for long-session eye comfort. |
| `card` | `#2C2C2E` | zinc-800. Card and list-row surface. |
| `card-hover` | `#323234` | Hover state on interactive rows. |
| `border` | `rgba(255,255,255,0.07)` | Ghost hairline. Separates without adding visual weight. |
| `foreground` | `#F2F2F7` | iOS standard light text on dark. |
| `muted-foreground` | `#8E8E93` | Timestamps, subtitles, helper text. |
| `subtle-foreground` | `#48484A` | Stage tokens in run rows, tertiary labels. |
| `primary` | `#0A84FF` | iOS system blue (dark). The only blue on screen; not used for status. |

**Status (semantic)**

| Token | Hex | Meaning |
|-------|-----|---------|
| `status-running` | `#FF9F0A` | Active motion. |
| `status-awaiting` | `#BF5AF2` | Holding, needs operator attention. |
| `status-approved` | `#30D158` | Gate cleared. |
| `status-failed` | `#FF453A` | Error state. |

Light-mode swaps: background `#F2F2F7`, card `#FFFFFF`, primary `#007AFF`. Status hues remain semantically identical.

## Typography

Single family: system-ui / -apple-system. The native stack renders at maximum quality on macOS/Windows without a font load — correct for a local tool. No display face; no heading font distinct from body. Labels are body weight with letter-spacing only.

Monospace (`'Courier New', Consolas, Menlo`) reserved for SCP IDs (`SCP-096`) and pipeline stage tokens (`scenario`, `tts`). These are technical identifiers, not prose.

**Scale**

| Use | Size | Weight | Notes |
|-----|------|--------|-------|
| Wordmark | 15px | 600 | Wordmark only |
| Body / card title | 13px | 400–600 | Primary content |
| SCP ID | 12px | 700 | Monospace |
| Badge / secondary label | 11px | 500 | |
| Timestamp / muted | 11px | 400 | `muted-foreground` |

## Layout & Spacing

Tailwind spacing scale inherited. Two layout contexts:

1. **Dashboard** — top nav (52px) + scrollable card list. Items full-width.
2. **Run Detail** — top nav + two-column: `240px` fixed sidebar (stage list) + `flex-1` main panel (artifact display). Sidebar scrolls independently on long stage lists.

## Shapes

Rounded token usage:
- Card list group container: `{rounded.lg}` (12px)
- CTA button: `{rounded.cta}` (10px)
- Status badge: `{rounded.badge}` (6px)
- Stage sidebar active border: 2px left border only, no radius override

## Components

Behavioral rules in EXPERIENCE.md. Visual specs here.

| Component | Visual spec |
|-----------|------------|
| `status-badge` | Foreground from `status-*`; background from `status-*-bg`; 11px/500; `rounded.badge` |
| `card-row` | `{colors.card}` bg; `{colors.card-hover}` on hover; `{colors.border}` hairline bottom |
| `stage-sidebar-item` | Active: 2px `{colors.primary}` left border, `{colors.card}` bg. Awaiting: 2px `{colors.status-awaiting}` left border. Inactive: transparent bg. |
| `cta-primary` | `{colors.primary}` bg; `{colors.primary-foreground}` text; `{rounded.cta}` |
| SCP ID display | `{typography.mono}`; `{colors.foreground}` |
| Stage token display | `{typography.mono}` 11px/400; `{colors.subtle-foreground}` |

## Do's and Don'ts

**Do**
- Use `status-awaiting` (purple) as the strongest visual signal — it means "you need to act."
- Monospace for SCP IDs and stage tokens everywhere they appear.
- System blue exclusively for interactive actions (buttons, links). Never for status.

**Don't**
- Use status colors as decorative accent (e.g., purple for section headings).
- Add border-radius to table/list separators — hairline borders only.
- Display marketing or explanatory copy inside the tool UI.
