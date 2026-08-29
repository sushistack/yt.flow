from typing import Literal, NamedTuple

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Story 10.2 — hard ceiling on the background-person guard's regeneration ladder.
# It bounds the config field below AND fixes the ladder's length: image_node derives
# the same number of candidate seeds regardless of the run's current knob value, so
# lowering the knob (or losing the vision key) never invalidates a shot that was
# already accepted on a bumped seed. ponytail: a module constant, not a second knob.
# RESUME CONTRACT: this number may only GROW, never shrink. It is the length of the
# seed ladder `_existing_complete_shot` accepts; shrinking it orphans every shot a
# previous run accepted on a now-missing rung, which regenerates them forever.
BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS = 4

# Story 10.2 — after this many consecutive undecidable verdicts (no key, HTTP error,
# unparseable reply) the guard switches itself off for the rest of the run: a dead
# detector would otherwise spend a 120s timeout on every remaining shot.
BACKGROUND_PERSON_GUARD_BREAKER_STREAK = 3

# Story 10.2 — same breaker, total rather than consecutive: an intermittently failing
# detector (fail, ok, fail, ok…) resets the streak every other call and never trips it,
# so the 120s-per-call cost the breaker exists to bound comes back. Set above the
# streak so a hard-dead detector still trips on the streak first.
BACKGROUND_PERSON_GUARD_BREAKER_TOTAL = 6


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YTFLOW_",
        env_file=".env",
        extra="ignore",
    )

    langfuse_host: str
    langfuse_public_key: str
    langfuse_secret_key: str
    # B-3: when false, @observe/get_client no-op (see observability.py). Does NOT
    # disable Prompt Hub fetching. env YTFLOW_LANGFUSE_ENABLED.
    langfuse_enabled: bool = True

    # Single SQLite file shared by LangGraph checkpoints and future SQLModel tables. [AD-7]
    db_path: str = "yt_flow.db"

    # DeepSeek (OpenAI-compatible) — model names are config-pinned, never hardcoded in nodes.
    # ponytail: api_key defaults to "" so Settings() stays constructible in tests/tooling;
    # nodes guard for a missing key at call time and fail with a readable error.
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    # Measured 2026-08-05 over 6 live run attempts (SCP-999, SCP-049): 8192 was the
    # shipped default while .env already carried 16384, and 16384 truncates
    # scenario/structure 4/4 (finish_reason=length). 32768 passes structure cleanly.
    # 65536 stops truncation everywhere, but the all-scenes scenario/writing call was
    # still outstanding after 29 minutes with zero artifacts — so the fix for writing
    # was batching it one scene per call (scenario_chain.writing_step), not more
    # budget. This value is sized for the largest single call that remains,
    # structure, with headroom over its measured 16384 failure / 32768 pass.
    deepseek_max_tokens: int = 32768
    # ROOT CAUSE of the 2026-08-05/06 truncation class (finish_reason=length,
    # content=="", the whole budget spent inside discarded reasoning_content).
    # Batching stages per scene treated the symptom — live run 4c85f66d had
    # writing already at one call PER SCENE and still burned all 32768 tokens on
    # 67k–77k characters of reasoning for a single scene, re-roll included.
    # Probed directly against api.deepseek.com (deepseek-v4-flash), measuring
    # completion_tokens_details.reasoning_tokens:
    #   baseline (no field)             -> 26
    #   "reasoning_effort": "low"       -> 16
    #   "thinking": {"type":"disabled"} -> 0
    # So reasoning depth is the real lever. Mapped to a request field in
    # REASONING_BODY (below): low/medium/high -> reasoning_effort,
    # "disabled" -> thinking (the only mechanism that reached 0), "default" ->
    # send neither field. Literal so an unknown value fails at config load.
    deepseek_reasoning: Literal["low", "medium", "high", "disabled", "default"] = "low"
    # A/B evaluation judge (Story 4.2). Same OpenAI-compatible endpoint; the model is
    # config-pinned so the judge can be swapped independently of the content generator.
    # Kept after the Story 12.2 split moved judging to Gemini: it is the zero-new-provider
    # fallback if Gemini-writes-and-judges self-preference bias makes results suspect.
    deepseek_judge_model: str = "deepseek-v4-flash"

    # Gemini (Story 12.2 model split). Owns every prose-producing/prose-judging call:
    # scenario writing + scene repair, the runtime review/critic judges, and the Epic 4
    # axis/pairwise judges. DeepSeek keeps research/structure/cast/visual/tts_normalize.
    # ponytail: same empty-key default as DeepSeek above so Settings() stays constructible
    # in tests/tooling; the call sites fail fast with a provider-specific error.
    gemini_api_key: str = ""
    # Google's OpenAI-compatibility endpoint. Callers append `/chat/completions`, exactly
    # like deepseek_base_url — so no new transport, just a second base URL + key.
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    # Exact stable IDs only, never a `-latest`/preview alias: `latest` can be hot-swapped
    # under a running pipeline, which would silently change output quality and destroy
    # quality attribution between runs.
    # SCOPE, because the names undersell it: the *writing* pair below serves every
    # scenario-chain stage Gemini owns — writing, scene repair AND the runtime
    # review/critic judges — because they all share one injected seam
    # (scenario._call_gemini). The *judge* pair serves the Epic 4 A/B judge only
    # (eval_service). Deliberate: Story 12.2 Task 2 suggested putting runtime
    # review/critic on the judge budget, but the 2026-08-06 live probe measured
    # ~2-5k thinking tokens per Gemini call, and review/critic are the two stages
    # that already truncated live at 16k (run 370666ba) — capping them at 8192 would
    # buy nothing and re-introduce a known failure. Per-stage model plumbing is the
    # thing to add if a *different* runtime judge model is ever actually wanted.
    gemini_writing_model: str = "gemini-3.6-flash"
    gemini_judge_model: str = "gemini-3.6-flash"
    # Writing is batched one scene per call (scenario_chain.writing_step), so it needs
    # far less than deepseek_max_tokens' whole-outline budget. Independently pinned so
    # an A/B-judge budget change can't perturb generation.
    gemini_writing_max_tokens: int = 16384
    gemini_judge_max_tokens: int = 8192

    # ComfyUI image generation (Story 1.6). Reachability is checked lazily before
    # the first ComfyUI submission in image_node (Story 5.14), not app startup —
    # a fully-resumed retry never touches HTTP. Mock mode never instantiates the
    # HTTP client.
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_workflow_path: str = "data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json"
    comfyui_mock: bool = False

    # Sustained-load crash mitigation (Story 5.23): two independent runs crashed
    # ComfyUI (hipErrorIllegalAddress, ROCm RX 9060 XT) near shot ~40 under load.
    # A periodic re-check catches a crash before submit_and_fetch itself would;
    # the bounded wait-and-recheck window covers a manual restart-and-retry.
    comfyui_health_poll_every_n_shots: int = Field(20, ge=1)
    comfyui_crash_recovery_poll_sec: float = Field(15.0, gt=0)
    comfyui_crash_recovery_timeout_sec: float = Field(300.0, gt=0)

    # Read timeout for the /system_stats health probe. ComfyUI's server is
    # single-threaded on the GPU: while it executes a prompt it does not answer
    # /system_stats at all. Measured 2026-08-06 (run fdd69699): 28/28 prompts
    # succeeded at ~20s each, yet the old 5s probe timeout misread the
    # healthy-but-busy server as crashed and stalled the image stage after
    # 1/68 shots. So this must tolerate at least one full generation. Crash
    # detection does NOT depend on it — a dead server fails at connect
    # (5s, see comfyui_client.HEALTH_CONNECT_TIMEOUT), not at read.
    comfyui_health_read_timeout_sec: float = Field(120.0, gt=0)

    # Per-generation poll budget for submit_and_fetch*. Measured 2026-08-04 on
    # RX 9060 XT / ROCm: a cold character card (SDXL + LoRA + IPAdapter +
    # CLIPVision + InspyrenetRembg) completes at ~400s. The old hardcoded 180s
    # budget timed out mid-generation, the caller retried, and each retry
    # enqueued another prompt — queue 3 -> 6 pending with 0 completed history.
    comfyui_generation_timeout_sec: float = Field(900.0, gt=0)
    comfyui_poll_interval_sec: float = Field(1.0, gt=0)

    # Runtime artifact root; stage nodes write under workspace/{run_id}/. [AD-10]
    workspace_path: str = "./workspace"

    # Reusable asset library root (character cards, location plates, look-dev
    # anchors) — distinct from workspace_path so run cleanup can never touch
    # library assets (Story 8.6). [AD-10]
    assets_path: str = "./assets"
    # Current style-anchor generation; AssetService's manifest is the persisted
    # source of truth once it exists — this is only the bootstrap seed.
    style_epoch: int = 1

    # Qwen TTS via Alibaba DashScope (international). Model/voice are config-pinned,
    # never hardcoded in nodes. ponytail: api_key defaults to "" so Settings() stays
    # constructible in tests/tooling; tts_node guards for a missing key at call time.
    qwen_tts_api_key: str = ""
    qwen_tts_endpoint: str = "https://dashscope-intl.aliyuncs.com"
    qwen_tts_model: str = "qwen3-tts-flash"
    qwen_tts_voice: str = "Cherry"
    qwen_tts_clone_enabled: bool = True  # 2026-08-15 Jay 라이브 판정으로 확정 (v4)
    qwen_tts_clone_model: str = "qwen3-tts-vc-2026-01-22"
    qwen_tts_clone_voice_path: str = "data/voices/sutak.mp3"
    qwen_tts_clone_voice_id: str = ""
    # 1.1 since 2026-08-17 on Jay's viewing verdict of run 4b35c0ed (SCP-049, 3:20):
    # "말이 아직 너무 빠른것 같음. 지금이 1.2라면 1.1 정도로 줄이도록". 1.2 was itself a
    # tuning value, never a measured one. The 1.2 -> 1.1 change originally moved the code
    # default AND a `.env` pin together, because a stale pin wins
    # (gotcha_env-file-beats-code-default). Story 14.4 removed that pin instead: a
    # decision-bearing value belongs HERE and nowhere else, so there is no second copy to
    # keep in step. Do not re-add it — see CLAUDE.md "Decision-bearing settings".
    qwen_tts_speed: float = Field(1.1, ge=0.5, le=2.0)
    qwen_tts_mock: bool = False

    # Forced alignment for subtitles + shot cuts (Story 1.8; always-on Story 11.4).
    # Strategy is config-driven; swap the aligner name without touching
    # subtitle_node. whisperx>=3.8.6 ships in pyproject.toml. Align-only (no ASR
    # pass), so no model/compute_type knobs — just the device.
    aligner: str = "whisperx"
    aligner_device: str = "cpu"

    # Image search provider (Story 1.11). DuckDuckGo is the default; no API key needed.
    image_search_provider: str = "duckduckgo"

    # Character image generation (Story 1.12). Provider-specific character image
    # generation for multi-angle character portraits.
    character_image_provider: str = "comfyui"  # "comfyui" or "qwen"
    character_comfyui_workflow_path: str = "data/workflows/comfyui_character_multi_angle_api.json"
    character_qwen_model: str = "qwen-image-max"
    character_qwen_api_key: str = ""
    character_image_width: int = 832
    character_image_height: int = 1216
    special_pose_max_per_run: int = 3
    # Story 10.5: route special-pose cards through the ControlNet Union guide graph so
    # the requested action state is drawn instead of ignored. Live isolation at a shared
    # seed triple: 3/3 supine with the guide, 0/3 without it and 0/3 with the IPAdapter
    # anchor removed (`10-5-live-validation/README.md`).
    #
    # 2026-08-14: flipped ON by Jay's promotion decision, together with retiring the
    # defective pose-hint cards. The two go together — this flag reaches only cards that
    # do not exist yet (`_ensure_special_pose_cards` skips any hint with an *approved*
    # row), so turning it on without retiring would have changed nothing on screen.
    #
    # Known cost, accepted rather than discovered later: one of the three guided seeds
    # drew two figures in one sprite. That defect appears with and without the guide, so
    # it is not caused here, but it now ships. A figure-count check on the generated
    # sprite is the thing that would retire this caveat.
    pose_guide_conditioning_enabled: bool = True

    # Derived-entity on-demand cards (Story 8.13): a cast_decision `<scp_id>-<n>`
    # duplicate/offshoot gets a full card generated the first time it's referenced.
    derived_entity_max_per_run: int = 2

    # Vision LLM descriptor enrichment (Story 5.13). DashScope Qwen-VL — the DeepSeek
    # account has no vision-capable model at all (text-only), so this is a distinct
    # provider from deepseek_*, not just a different model on the same account.
    # ponytail: api_key defaults to "" so Settings() stays constructible in tests/tooling;
    # enrich_descriptor_from_references guards for a missing key at call time.
    character_vision_model: str = "qwen-vl-plus"
    character_vision_api_key: str = ""
    # Own knob, not deepseek_max_tokens: qwen-vl-plus rejects max_tokens > 8192 with a
    # 400, so borrowing the text model's budget silently killed every enrichment call
    # once YTFLOW_DEEPSEEK_MAX_TOKENS went to 16384. An enriched descriptor is a
    # paragraph, so 2000 is already generous.
    character_vision_max_tokens: int = Field(2000, gt=0, le=8192)

    # Chapter-card transitions (Story 5.1). Cards insert between scenes when true;
    # video_node clamps duration to the accepted 1.5-2.0s range.
    chapter_cards: bool = True
    chapter_card_duration_sec: float = 1.75

    # Sound design (Story 7.1): mood-driven BGM/ambient/stinger, ducked under
    # narration. Opt out if the data/audio asset library isn't populated yet.
    sound_design_enabled: bool = True

    # Post-processing filters (Story 7.2): mood-driven color grade + constant
    # vignette/film-grain on every scene and chapter card.
    post_fx_enabled: bool = True

    # Character parallax (Story 7.3): couple the near-plane character's zoom/pan to
    # the background's EffectSpec, amplified by CHAR_DEPTH_FACTOR, for a real
    # multiplane depth cue. When false, character reverts to fixed-size sway/bob only.
    parallax_enabled: bool = False  # 2026-08-15 Jay 라이브 판정으로 확정 (v4)

    # Camera noise (Story 11.3): fBm handheld camera stage (sway/tremor/rot/
    # micro-zoom + stinger-synced trauma shake) on every composited shot.
    # When false, no stage is attached — the pre-11.3 filter chain, byte-identical.
    camera_noise_enabled: bool = False  # 2026-08-15 Jay 라이브 판정으로 확정 (v4)

    # Character idle motion (Story 1.9c/8.8): the per-card breath/sway/tremble/pulse
    # sine and the 8.9 entrance offsets. Separate system from `camera_noise_enabled`
    # — that one moves the *camera*, this one moves the *cards* — and until now only
    # the camera had a switch. Live run e5ed4b3a made the gap visible: with the
    # handheld camera off, 37 of 40 cast placements still carried an active
    # `motion_style` (breath 25, sway 5, pulse 5, tremble 2) and the render still read
    # as shaking. When false, every card is frozen through the same seam
    # `_render_fusion_still` documents (`motion_style="hold"` + `movement_mode="anchored"`),
    # because those terms are non-zero at t=0 and a partial freeze bakes a fraction of
    # a frame's animation in.
    character_idle_motion_enabled: bool = False  # 2026-08-15 Jay 라이브 판정으로 확정 (v4)

    # Background camera archetype (Story 11.2/11.5): push_in / pull_back / drift are
    # what actually move the plate, through both the zoompan chain and the 11.5 depth
    # trajectory. `camera_noise_enabled` only removes the fBm tremor riding on top and
    # `character_idle_motion_enabled` only freezes the cards — measured on live run
    # e5ed4b3a, background clips still moved 2.3-3.8 mean inter-frame delta with both
    # of those off, while the one shot already on the `locked` archetype sat at 0.15.
    # When false every shot renders on `_FUSION_STILL_SPEC` with a `locked` hint, so
    # the plate holds still and 2.5D depth is kept (unlike disabling depth outright).
    background_camera_motion_enabled: bool = False  # 2026-08-15 Jay 라이브 판정으로 확정 (v4)

    # Content language (Story 9.1): single seam for a future language pivot. The
    # pipeline is Korean-only today — changing this to anything else makes
    # scenario_node fail fast rather than silently mixing languages. Touchpoints
    # that would need real work before this value does anything: the WhisperX
    # aligner language (subtitle.py, already wired), SUBTITLE_FONT_FAMILY +
    # line-wrap constants tuned for Hangul density (subtitle.py), CARD_FONT_PATH
    # (video.py), and the scenario-chain prompt templates in prompts/scenario/
    # (research/structure/visual_breakdown/tts_normalize here, plus
    # writing/review/critic_agent/format_guide which live only in Langfuse's
    # production label / the sibling yt.pipe repo). `qwen_tts_voice` is also
    # coupled to language — swapping this without picking a matching voice
    # would silently mis-synthesize; no mapping exists yet.
    content_language: str = "ko"

    # CC BY-SA attribution (Story 5.20): ending credit card + description.txt for
    # every monetized SCP video. Off for dry-runs/non-SCP content where the license
    # doesn't apply — skips both outputs entirely, no HTTP calls, no file writes.
    cc_attribution: bool = True

    # Stock location plates (Story 8.5): IPAdapter style-anchor weight for the
    # seed script's bulk plate generation. Tunable without a code change if the
    # anchor bleeds content (lower) or the style doesn't hold (raise).
    location_ipadapter_weight: float = Field(0.4, ge=0.0, le=1.0)
    location_plate_workflow_path: str = "data/workflows/comfyui_location_plate_api.json"
    location_anchor_dir: str = "data/anchors/locations"
    # Curated structure references (Story 8.17): one real photo per
    # (location_key, variant), written by scripts/fetch_location_refs.py and read
    # back by the seed script as the ControlNet hint. Same shape as the anchor dir
    # above so tests and operators can redirect it with one env var.
    location_refs_dir: str = "data/refs/locations"
    # Gate for the Story 8.17 STOCK plate substitution in image_node. OFF: the
    # substitution discards the shot's image_prompt entirely and is keyed on
    # scene_num, so every shot of a scene gets ONE identical background —
    # measured run-wide collapse from 155 distinct backgrounds to 41 (85% of
    # shots; scene 5's containment chamber went 21 shots -> 1 image). Stays off
    # until a plate-vs-prompt reconciliation story makes plate reuse per-shot and
    # prompt-aware. ON reproduces 8.17 behaviour exactly.
    #
    # 2026-08-25, STORY 14.1: THE FRAMING HALF OF THE BLOCKER IS GONE, THE FLAG
    # STAYS `False`. This comment named two blockers — scene keying AND the
    # discarded image_prompt. `image._select_plate` retired the FIRST one only:
    # assignment is per shot, keyed on the shot's own `camera_angle` matched
    # against each plate's MEASURED viewpoint, and a shot with no fitting plate
    # falls back to generation with `stock_plate_unfit` rather than taking a wrong
    # one. The SECOND is untouched — the selector reads `camera_angle`, `cast` and
    # `location_key` and nothing else, so `image_prompt` is still discarded whole
    # and semantic match (does this plate show what the prompt describes?) remains
    # unsolved. A `location_key` is a room, not a scene: two shots asking for very
    # different things inside one room are indistinguishable to the selector. ON
    # therefore no longer reproduces 8.17's framing collapse, but it does still
    # ship a background chosen without reading the prompt. (`epics.md`'s Story 14.1
    # line says assignment is decided by "`image_prompt`/`location_key`와의 정합" —
    # half of that is aspiration, not code.) Two conditions remain to turn this on,
    # and they are AND, not OR:
    #   (a) measured coverage clears the pre-registered bar
    #       (`14-1-approved-plate-sets/PREREGISTRATION.md` §5, C1/C2/C3) — as
    #       measured on 2026-08-25 it does NOT; see that story's report.md for the
    #       shortfall enumerated per (location_key, viewpoint) cell.
    #   (b) Jay's viewing verdict on an E2E iteration run with substitution ON.
    #       Precedent is unanimous (10.1c, 10.5, 10.1e, 14.2): a visual default
    #       does not flip before a human has watched frames.
    # No `.env` / `.env.example` pin, and NO `DECISIONS` row — there is still no
    # dated *promotion* verdict, only a dated statement of what promotion requires
    # (see the "NO DATE, so no row" note further down; it stands).
    stock_plate_substitution_enabled: bool = False
    # Story 10.2 — extra renders image_node may spend when Qwen-VL says the generated
    # background already contains a person (a card composited onto it would make two
    # figures). 0 disables the guard entirely; the detector is never called.
    #
    # ON AT 2 SINCE STORY 14.4, 2026-08-22. The previous rationale for 0 ("off by
    # default like every other new path in this epic") is WITHDRAWN, not appended to:
    # it shipped a working guard that never ran once in 15 days, and the run that
    # finally needed it only got it through a `.env` pin — which is
    # `gotcha_a-decision-that-only-reaches-env-never-ships` verbatim, since a fresh
    # checkout reverts a judged decision silently.
    #
    # WHY 2 AND NOT 1, from the only two live samples that exist. They disagree, and
    # the disagreement is the reason for the value:
    #   - 10.2's single hit (`10-2-live-validation/`) needed rung **2** — rung 1 came
    #     back populated too, so a budget of 1 would have shipped a populated frame.
    #   - run 4b35c0ed (43 shots, guard pinned at 2) hit on **5** shots — S00103,
    #     S00202, S00203, S00301, S00400 — and all five cleared on rung **1**;
    #     38 shots were accepted on rung 0 and **0** exhausted the ladder.
    #     Those 5 are DETECTOR hits, not confirmed contaminations: 3 are the plates
    #     Jay's ⑤ named, S00202 was never eyeballed, and S00103 is contradicted by
    #     `14-0-angle-conflict/report.md` §8-5 (no person visible in either render),
    #     i.e. probably a false positive that cost a real render. A false positive is
    #     a permanent tax, so if a later run keeps hitting on frames nobody can see a
    #     person in, the threshold is the thing to look at, not the budget.
    # So the observed modal need is 1 and the observed worst case is 2. `2` is the
    # worst case seen, not a round number someone liked, and MAX_ATTEMPTS stays 4
    # because nothing has ever needed a third rung.
    #
    # MEASURED COST, both halves. Per accepted shot: one vision call — 7 timed calls
    # in `14-4-live-validation/` gave min 1.46s / mean 3.17s / max 10.11s, a ~7x spread
    # on identical input because it is a hosted service (the first 4-call burst looked
    # like a ~2s constant and was too narrow a sample —
    # `gotcha_measure-densely-before-declaring-a-fix`). Per HIT only: one extra ~17s
    # render. On this run's shape that is 43 vision calls (~2.3 min at the mean) and 5
    # extra renders (~1.4 min), not 43 extra renders.
    # THE WORST CASE IS BOUNDED BY CONSTRUCTION, not by a threshold: 2 extra renders
    # per shot, i.e. at most 3x the image stage's render time, reached only if every
    # shot hits twice. Nothing warns on the aggregate — `guard_counts["regenerated"]`
    # goes to the Langfuse span only — so a checkpoint change that moves the hit rate
    # from 12% to 60% would show up as a slow run rather than as a warning. Deferred
    # deliberately: the threshold that would warn has no data behind it yet
    # (`deferred-work.md`).
    #
    # FREE ON RESUME. `_seed_ladder` is fixed-length (MAX_ATTEMPTS + 1) and
    # `_existing_complete_shot` compares the accepted seed against the WHOLE ladder,
    # so raising or lowering this knob cannot invalidate a cached shot, and rung 0
    # still hashes the pre-10.2 string byte-identically. Only newly-generated shots
    # change.
    #
    # An undecidable verdict (no key, HTTP error, unparseable reply) accepts the
    # frame and consumes NO rung — re-rendering on no information spends ~17s to
    # learn nothing — but Story 14.4 makes it visible per shot
    # (`background_guard_unscreened` / `detector_undecidable_shot`).
    background_person_guard_attempts: int = Field(2, ge=0, le=BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS)

    # ── Story 14.2: plate affordance gate ─────────────────────────────────────
    # OFF BY CODE DEFAULT, 2026-08-24 (review loop 1 lowered it from ON). The second
    # pixel predicate on the accepted render: "can a whole body stand in this plate at
    # all?" — asked once per cast-bearing shot, and a `false` verdict empties that
    # shot's `cast` so the card is never composited onto a frame with nowhere to put it.
    #
    # MEASURED, run 4b35c0ed, 33 cast-bearing shots
    # (`_bmad-output/implementation-artifacts/14-2-affordance-calibration/`), on the
    # SHIPPED envelope — `[image, text]` + `temperature: 0`:
    #   * recall 5/7, false positives 1/25 (4%). Text-first is 3/7 · 0/25 on the same 33
    #     plates with zero flips across repeated passes, which is why the envelope is
    #     pinned in `vision_check` rather than left to the caller.
    #   * base rate 7/33 (21%) — plates with no readable ground for a whole body. The
    #     failure modes are the plate being re-framed away entirely, a floor being
    #     INVENTED, and the card entering as a floating bust or a knee-cropped figure.
    #   * the one false positive is `S00901`, a narrow real floor the card did land on.
    #     The pre-registration forbade shipping "delete the cast" as the terminal action
    #     above 3/25, and 1/25 clears that bar.
    # WHY OFF ANYWAY. The pre-registered bar `recall >= 6/7` is UNREACHABLE BY
    # CONSTRUCTION, so the FAIL is a property of the bar and not of the detector
    # (`gotcha_a-screening-gate-can-fail-on-its-own-threshold`): of the two misses,
    # `S00601` is a permanent `data_inspection_failed` refusal (reproduced; the 10.2
    # guard is `None` on the same plate) and so can never be recalled by THIS gate —
    # it is this gate's own class, not Story 14.3's — and `S00105` was a LABEL error
    # where the detector was right. The corrected denominator is 5 and a new bar has to
    # be RE-PRE-REGISTERED after Jay's 33-pair adjudication (AC1) and confirmed on a
    # fresh sample; writing a bar after seeing the result is not a pre-registration.
    # Until that human viewing verdict exists this stays off, the same posture 10.1c /
    # 10.5 / 10.1e all shipped in: no default deletes what a person has not yet judged.
    # An undecidable verdict keeps BOTH the frame and the cast: this endpoint refuses
    # corpse/medical plates deterministically (`data_inspection_failed`, reproduced),
    # and reading that as "no standing room" would delete the cast of a whole class of
    # SCP shot forever. On costs one vision call (~3.2s) per cast-bearing shot,
    # ~1.8 min on this run's 33.
    plate_affordance_gate_enabled: bool = False
    # Story 10.1c — regenerate each shot from plate + cards + a placement instruction
    # instead of compositing cards onto the plate. The overlay path stays intact behind it.
    # VERDICT (10.1c close-out): stays OFF, despite the live run passing. For: 51 passes /
    # 0 errors, Jay's motion verdict on the 3:06 render PASS (findings 3·11 gone), 0
    # composition collapses across the 42-plate sweep. Against, and decisive for the
    # *default*: (a) MEASURED AND PASSED by Story 10.1e — see below; the original
    # numbers are WITHDRAWN; (b) CLOSED by Story 10.1d — the
    # path needs ComfyUI started with specific flags and free system RAM, and that is now
    # declared once in `recompose_service.REQUIRED_FLAGS` and read off the RUNNING server's
    # argv at recompose entry: a miss bails the whole run out to the overlay with a
    # `recompose_preflight_failed` run_warning, instead of swap-deadlocking for ~12 minutes
    # while the try/except fallback never fires. The one prerequisite that guard cannot see
    # is the fp8 text encoder: it is pinned in the workflow JSON's `clip` node rather than
    # in argv, and a missing file fails fast at that node with ComfyUI's own error naming
    # it, so it is out of the preflight's reach by design and not an unchecked gap;
    # (c) MEASURED by Story 10.1e at 1.2h and STILL over the pre-registered 1.0h
    # line — this is now the ONLY reason the default is False.
    #
    # ── items (a) and (c), REWRITTEN by Story 10.1e, 2026-08-17 ───────────────
    # (a) IS NOW MEASURED, AND IT PASSED. Legibility is neutral-or-better under
    # recompose. What kept this False is (c), the time budget — measured, not
    # inherited. Read `10-1e-live-validation/README.md`; every number re-derives
    # with `run_pairs.py report`.
    #
    # (a)'s OLD NUMBERS ARE WITHDRAWN — do not cite them again. "unreadable 20%
    # vs 13%, misread-as-corridor 57% vs 27%" was never a treatment measurement.
    # `screening.json` re-reads the same committed `baseline_v2.json` those
    # figures came from: its 51 `recomposed/` rows and its 15 `images/` rows are
    # DISJOINT shot sets (0 shot_id overlap), and splitting the same 66 rows by
    # CAST-PRESENCE instead of by arm selects byte-identical sets and reproduces
    # every count (unreadable 10/2, corridor 29/4). Arm and cast-presence are
    # 100% collinear there — all 15 plate rows are shots with `cast == []` — so
    # the figures cannot separate "recompose hurt legibility" from "shots that
    # contain characters read as corridors". Free to establish: no GPU, no
    # network, from data already in the repo.
    #
    # THE PAIRED MEASUREMENT (2026-08-17, run e5ed4b3a, n=33 shots / 40 passes):
    # the same shots, same plates, one cast-card resolution shared by both arms,
    # rendered once through the overlay (`video.render_composite_still`, the
    # production `_build_card_chain`) and once through `recompose_run_shots`,
    # then scored by 13-2's instrument with the blind axis first. The decision
    # rule was committed in 82de77e BEFORE any score existed
    # (`PREREGISTRATION.md`), and `report` applies it mechanically:
    #   deciding axis, blind `readable`, paired:  b=2, c=1, b-c=1 <= slack 1  -> FLIP
    #   veto, >=5 of 40 passes failed:            0 failed                    -> not triggered
    #   cost line, >1.0 h added to a 43-shot run: 107.9 s/pass x 40 = 1.2 h    -> BLOCKS
    # => "(a) closed PASS, (c) still blocks", which is the pre-registered wording
    # for exactly this outcome, so this stays False.
    #   OFF  unreadable 3/33 (9.1%)   corridor 27.3%   mean DSG 0.4443
    #   ON   unreadable 4/33 (12.1%)  corridor 30.3%   mean DSG 0.4615
    # 28 of 33 shots readable in BOTH arms, 2 in NEITHER, 3 discordant. All three
    # discordant shots split on `event: unclear`, never on an unreadable `place` —
    # the same axis as 10.4b's surviving `visible_event` defect. (Do NOT say the arms
    # name the place "correctly": on S00501 they name DIFFERENT rooms, OFF "a sterile
    # laboratory" vs ON "a tiled examination room", and no artifact holds a ground
    # truth to score that against.)
    #
    # HOW THIN THIS IS, stated because the rule was fixed in advance and cannot
    # be re-chosen now: b-c=1 is the rule's exact boundary. One shot the other
    # way would have read STAY OFF. Three discordant pairs carry no statistical
    # power. The honest claim is "no evidence recompose is worse on legibility",
    # NOT "recompose is better".
    #
    # (c) IS NOW MEASURED TOO, and it is SMALLER than the recorded 1.3-1.7 h:
    # 107.9 s/pass (mtime deltas over 32 shots / 39 passes) x 40 passes = 1.2 h.
    # Two things made that possible and both are now shipped:
    #   - Story 10.1d's preflight passed live for the first time (ram_free 19.35
    #     GiB at entry, steady ~17 GiB through the run, 0 failed passes).
    #   - `--disable-smart-memory` was REMOVED from `REQUIRED_FLAGS`. It was
    #     required on 10.1c's older-ComfyUI observation, does not reproduce over
    #     the 40 passes of the 2026-08-17 sweep on 0.12.3, and was the whole cost problem: the graph's weights total
    #     22.6 GB against 16 GB VRAM, so `--lowvram` streams them from system RAM
    #     and that flag then unloaded them after every prompt. With it: 385.66 ->
    #     677 -> 609 s/pass, ram_free 19.35 -> 5.46 GiB, swap 8185/8191 MiB — CONFOUNDED,
    #     a concurrent session ran four SDXL prompts between pass 1 and passes 2-3
    #     (`render_on_blocked.json:other_session.ATTRIBUTION_CAVEAT`). Unconfounded:
    #     107.9 s/pass over 40 passes without the flag. See
    #     `recompose_service.REQUIRED_FLAGS`.
    # BEWARE ONE NUMBER: `on.json`'s `seconds_per_pass_mean` is wall-clock over
    # passes PUBLISHED, and recompose output is content-addressed, so a re-run
    # publishes 40 having rendered 3 and reports 7.8 s/pass. That value produced a
    # FLIP verdict for one report run before it was caught. The cost figure must
    # come from `per_shot_from_mtime`; `run_pairs.py report` now enforces that.
    #
    # FLIPPED 2026-08-17 ON JAY'S VIEWING VERDICT: "recompose 무조건 해야하고"
    # ("recompose is a must"). This is a HUMAN OVERRIDE of the pre-registered cost
    # line, not a measurement result, and the epic's closure standard is what
    # authorises it: "a viewing verdict overrides a favorable measurement" — and
    # symmetrically an unfavorable one. Recording the shape honestly so nobody
    # later reads this as the numbers having said yes:
    #   - the deciding legibility axis said FLIP, but weakly. `verdict.json` now
    #     carries the numbers that say so, computed by `report`, not asserted here:
    #     `exact_mcnemar_p_two_sided` 1.0, `unreadable_difference_pp` +3.0,
    #     `unreadable_difference_ci95_pp` [-7.2, +13.3] — a CI that CONTAINS the
    #     incumbent's own 7 pp claim, so this run does not refute the figures it
    #     withdrew; the collinearity arithmetic does. n=33 rules out a catastrophe
    #     and nothing finer.
    #   - the pre-registered cost line said BLOCK at 1.2 h vs 1.0 h. Jay accepted
    #     the 1.2 h. THAT IS THE PRICE NOW PAID ON EVERY RUN.
    #   - what actually decided it is the axis the score never read: on the paired
    #     motion clips (`10-1e-live-validation/viewing/`) the ON arm puts figures on
    #     the floor with a contact shadow in the room's own palette, while the OFF
    #     arm's card is cut at the waist by foreground furniture (S00600) or stands
    #     on top of a lab bench (S00501). That is the "floating" complaint recompose
    #     was built for.
    #   - CAVEAT ON THAT EVIDENCE, found in review AFTER the verdict: the clip build
    #     Jay watched hardcoded `composite_harmonization_tier=0`, which switches off
    #     `build_sprite_tint` AND `build_contact_shadow` (video.py:1577/:1650, both
    #     gated on tier >= 1) — i.e. it handicapped the incumbent on two of the three
    #     things just cited, while the SCORED OFF arm used production tier 1. The
    #     harness now reads the setting and the clips were re-rendered at tier 1;
    #     the override stands until Jay says otherwise. 11.5 parallax is still
    #     excluded from both arms, which understates the incumbent on motion.
    #     Full list: `10-1e-live-validation/VERDICT_OVERRIDE.md`.
    #   - b=2 does NOT survive looking at the frames: both b shots are better
    #     composited in the ON arm and scored worse, and at reps=1 that is
    #     indistinguishable from judge noise at the margin. See
    #     `viewing.json:read_once_observations`.
    # ALSO SHIPPED, and previously unstated: recompose pops `depth_map_path`
    # (`recompose_service.py`), so Story 11.5's 2.5D parallax degrades to NO_DEPTH for
    # every recomposed shot — 33 of 43 on run e5ed4b3a — while `parallax_25d_enabled`
    # is still True. Card idle motion (1.9c) likewise cannot apply to a shot with no
    # cards. Both are intended consequences of recreation-over-overlay, not bugs, but
    # they are now the shipped behaviour rather than a hypothetical.
    #
    # KNOWN DEFECT SHIPPED WITH THIS FLIP, raised by Jay on the same viewing:
    # `depth: "near"` figures are drawn oversized for the room. `_DEPTH_PHRASE["near"]`
    # asks for "in the foreground close to camera, his whole body from head to feet
    # visible in frame" — two clauses that fight, since a 1.9 m figure truly close to
    # camera cannot be head-to-feet in a 16:9 frame, so the model satisfies both by
    # oversizing the figure against the room's own scale cues. Recorded in
    # `deferred-work.md`; NOT fixed here, because changing that phrase invalidates
    # the 43-plate sweep and the slate this path was verified on.
    # RETIREMENT IS NOW OWED (10.1e AC7). While this was False the overlay-only
    # machinery (ground placement, _GROUND_Y_MAX, occlusion, contact shadow, 11.5
    # parallax, 1.9c idle motion) is a FOLLOW-UP story, NEVER the flip commit —
    # see `deferred-work.md`, "Deferred from Story 10.1e". `render_composite_still`
    # must survive any such deletion: it is the only way to re-measure the
    # decision that retired the overlay.
    #   CORRECTED IN REVIEW: an earlier version of this note argued the overlay stays
    #   live because 10 of 43 shots are ineligible. It does not. All 10 are ineligible
    #   for having an EMPTY CAST (`pairs.json.dropped`, 10/10 — none for a missing
    #   CARD_LOOKS key), and `_build_card_chain` is only entered for a non-empty card
    #   list (video.py:1508/:1563). So under this flip **0 of 43 shots exercise the
    #   card-compositing machinery** — ground placement, _GROUND_Y_MAX, occlusion,
    #   contact shadow, 11.5 parallax and 1.9c idle motion are dead on this run's
    #   shape, not merely demoted. The retirement story is therefore MORE owed than
    #   the earlier wording implied. What still keeps that code from being deletable
    #   is a shot with cast whose card_key is outside CARD_LOOKS (5 keys, hand-written
    #   prose) — reachable, and unreached on this run.
    shot_recompose_enabled: bool = True
    shot_recompose_workflow_path: str = "data/workflows/comfyui_shot_recompose_qwen_api.json"
    # Story 10.1d — the free-system-RAM floor the recompose preflight enforces. NOT a
    # model-footprint calculation: it is the floor that catches the known-fatal state
    # (2026-08-15, run e5ed4b3a: 0 free / 4 GB swap on a 31 GB box was ALREADY thrashing a
    # path lighter than this one), rounded up so the Q4_K_M unet's ~12 GB can load without
    # swapping. A number that ends a 90-minute misdiagnosis, not a sizing model. GiB
    # (2**30), which is how /system_stats and `free` both report memory — the preflight
    # divides the same way it prints. CALIBRATED AGAINST THE FAILURE ONLY: no free-RAM
    # reading from a HEALTHY run at video_node entry was ever recorded, and
    # `--disable-smart-memory` parks weights in system RAM precisely so a working box may
    # sit lower than intuition suggests, so a false-bail rate is possible and unmeasured —
    # 10.1e's paired recompose-on/off scoring is where it would show up.
    # 10.1e, 2026-08-17: first live readings, and the false-bail rate is now measured at
    # ZERO across a full 33-shot / 40-pass run — entry 19.35 GiB, steady ~17 GiB, 0 bails.
    # The floor is vindicated at 12.0; leave it. What the run DID expose is that the floor
    # is an ENTRY check on a value a run can itself destroy: under the then-required
    # `--disable-smart-memory` the same box went 19.35 -> 5.46 GiB free with swap
    # 8185/8191 MiB and 385s -> 677s -> 609s per pass, i.e. below the floor its own
    # preflight had just cleared. That flag is gone from `REQUIRED_FLAGS` (see
    # `recompose_service`) and RAM has been flat since, so the entry-check gap is no longer
    # reachable by any shipped configuration — but it is a property of the mechanism, not of
    # the number. Do not raise 12.0 to "fix" it and do not lower it to get past a bail.
    # (`10-1e-live-validation/render_on_blocked.json` + `README.md`.)
    recompose_preflight_min_free_ram_gb: float = Field(12.0, gt=0)

    # Composite harmonization (Story 8.7): tiered collage-look resolution ladder.
    # 0=off (byte-for-byte pre-8.7 output), 1=mood tint+contact shadow,
    # 2=+light wrap, 3=+IC-Light re-lighting. Default 1 since Story 11.1: the
    # 2026-08-01 quality research (§Phase 1 quick-win 3) identified tier 0 as a
    # confirmed "cheap collage" cause; tier 1 stays the fallback once 8-16's
    # IC-Light (tier 3) lands.
    composite_harmonization_tier: int = Field(1, ge=0, le=3)
    iclight_comfyui_workflow_path: str = "data/workflows/comfyui_iclight_relight_api.json"

    # Depth-aware card placement (Story 8.16): stand a card's feet on a ground
    # plane estimated from the plate's monocular depth map instead of frame
    # centre, with the contact shadow derived from the same value, and mask the
    # card where the plate is nearer than it.
    #
    # ON after live verification (2026-08-03): rendered a real control-room plate
    # with a real card through real ffmpeg and measured the composited feet row
    # against the plate's own floor on every frame of a 1.15x push-in — 3.9px max
    # error tracking, versus 57.2px for a static anchor by the last frame. Ground
    # lines measured across all 41 readable library plates: strictly ordered
    # far<=mid<=near on 41/41. With no depth map (ComfyUI down, mock mode) the
    # resolver hands back the measured fallback ground and the run completes.
    depth_placement_enabled: bool = True
    depth_comfyui_workflow_path: str = "data/workflows/comfyui_depth_anything_v2_api.json"

    # Depth estimator identity (Story 11.5 AC3). Pinned HERE, not inside the
    # workflow JSON, because the depth cache key and provenance sidecar have to
    # record what actually produced a map — a checkpoint swapped inside the JSON
    # used to serve every previously cached map unchanged.
    # Depth-Anything-V2 *Small* is Apache-2.0; Base/Large/Giant weights are
    # CC-BY-NC-4.0 and are refused below on a potentially monetized output path.
    # Story 8.16 shipped `depth_anything_v2_vitl.pth` (Large, non-commercial);
    # this default is the AC3 correction.
    depth_model_ckpt: str = "depth_anything_v2_vits.pth"
    depth_model_resolution: int = Field(1024, gt=0)
    # Explicit, logged opt-in for a non-commercial checkpoint (research renders
    # only). Off means depth estimation refuses to run one at all — AC3's "not
    # *silently* used" needs a real gate, not a warning nobody reads.
    depth_allow_noncommercial_model: bool = False

    # ── 2.5D parallax (Story 11.5) ──────────────────────────────────────────
    # Kill switch (AC9): off → no depth/parallax renderer is called at all and
    # the Story 7.3/11.3 zoompan behaviour is preserved byte-for-byte.
    parallax_25d_enabled: bool = True
    # Visible plate displacement as a fraction of frame WIDTH. AC6 bounds this
    # to the 1-3% band single-image displacement can hide disocclusion inside;
    # the Field bounds make an out-of-band env var a startup error, not a
    # rubber-edged render nobody traces back to config.
    parallax_displacement_frac: float = Field(0.02, ge=0.01, le=0.03)
    # DepthFlow (AGPL-3.0) is an EXTERNAL runtime in its own virtualenv, never a
    # yt.flow dependency — see docs/PARALLAX_RUNTIME.md for the compliance
    # decision and install steps. Off until spiked on the target host (AC11);
    # the depth-warp renderer below it in the ladder needs no extra runtime.
    depthflow_enabled: bool = False
    depthflow_python: str = ""  # interpreter of the isolated DepthFlow venv
    depthflow_timeout_sec: float = Field(180.0, gt=0)

    # Per-shot cut assembly (Story 8.11): a shot's clip window shorter than this
    # merges into the previous shot's clip (first shot merges forward). 0.0
    # disables merging entirely.
    min_shot_clip_sec: float = Field(2.0, ge=0.0)


class Decision(NamedTuple):
    """One recorded product judgement about a setting above (Story 13.6 AC1).

    ``decided`` is what the verdict said the value should be; the *code default*
    is read separately from ``Settings.model_fields`` so the two can be compared.
    ``citation`` quotes the comment this row was harvested FROM — this table is
    an index into the prose, never a second place a decision is made. If the two
    ever disagree, the comment is right and this row is stale.
    """

    story: str
    date: str
    decided: object
    citation: str


# field name -> Decision. Seeded ONLY from verdicts already dated in the comments
# above (Story 13.6 Task 1: "Harvest those rather than re-deciding"), which is why
# it is short: a decision-bearing flag with no dated verdict gets NO row, because
# inventing a date here would make this table the deciding authority instead of an
# index. The absences are recorded here so the gap reads as a decision rather than
# an oversight — every one of them is a candidate 13.6 Task 1 named:
#   - NO DATE, so no row: `stock_plate_substitution_enabled` (False, story 8.17, a
#     measured rationale but undated), `post_fx_enabled` (True, story 7.2),
#     `qwen_tts_voice` ("Cherry", coupled to `content_language`). These want a dated
#     verdict from whoever owns them next — 14.1 for the plate flag.
#   - DATED but outside Story 14.4's seed set: `depth_placement_enabled` ("ON after
#     live verification (2026-08-03)", story 8.16) and `composite_harmonization_tier`
#     ("Default 1 since Story 11.1", research dated 2026-08-01). Both look eligible;
#     14.4's spec fixed the seed set to the verdicts it had read, and growing this
#     table is a separate, cheap, deliberate act rather than a side effect.
# Six of the rows below share one byte-identical stamp — `# 2026-08-15 Jay 라이브
# 판정으로 확정 (v4)` — which is a v4-rebuild viewing session, not a story, so that
# is what `story` says for them. `scripts/report_decision_drift.py` is the reader.
DECISIONS: dict[str, Decision] = {
    "qwen_tts_clone_enabled": Decision(
        "Jay 라이브 판정 (v4)", "2026-08-15", True,
        "qwen_tts_clone_enabled: `# 2026-08-15 Jay 라이브 판정으로 확정 (v4)`",
    ),
    "qwen_tts_speed": Decision(
        "Jay 시청 판정 (run 4b35c0ed)", "2026-08-17", 1.1,
        "qwen_tts_speed: \"말이 아직 너무 빠른것 같음. 지금이 1.2라면 1.1 정도로 줄이도록\"",
    ),
    "pose_guide_conditioning_enabled": Decision(
        "10.5", "2026-08-14", True,
        "pose_guide_conditioning_enabled: `flipped ON by Jay's promotion decision`",
    ),
    "parallax_enabled": Decision(
        "Jay 라이브 판정 (v4)", "2026-08-15", False,
        "parallax_enabled: `# 2026-08-15 Jay 라이브 판정으로 확정 (v4)`",
    ),
    "camera_noise_enabled": Decision(
        "Jay 라이브 판정 (v4)", "2026-08-15", False,
        "camera_noise_enabled: `# 2026-08-15 Jay 라이브 판정으로 확정 (v4)`",
    ),
    "character_idle_motion_enabled": Decision(
        "Jay 라이브 판정 (v4)", "2026-08-15", False,
        "character_idle_motion_enabled: `# 2026-08-15 Jay 라이브 판정으로 확정 (v4)`",
    ),
    "background_camera_motion_enabled": Decision(
        "Jay 라이브 판정 (v4)", "2026-08-15", False,
        "background_camera_motion_enabled: `# 2026-08-15 Jay 라이브 판정으로 확정 (v4)`",
    ),
    "shot_recompose_enabled": Decision(
        "10.1e", "2026-08-17", True,
        "shot_recompose_enabled: `FLIPPED 2026-08-17 ON JAY'S VIEWING VERDICT`",
    ),
    "background_person_guard_attempts": Decision(
        "14.4", "2026-08-22", 2,
        "background_person_guard_attempts: `ON AT 2 SINCE STORY 14.4, 2026-08-22`",
    ),
    "plate_affordance_gate_enabled": Decision(
        "14.2", "2026-08-24", False,
        "plate_affordance_gate_enabled: `OFF BY CODE DEFAULT, 2026-08-24 ... recall 5/7, "
        "false positives 1/25 (4%) ... the pre-registered bar `recall >= 6/7` is "
        "UNREACHABLE BY CONSTRUCTION ... has to be RE-PRE-REGISTERED after Jay's 33-pair "
        "adjudication (AC1)`",
    ),
    # Not a flag and not a Jay verdict — a MEASURED value, which is the other shape a
    # product judgement takes. Added in 14.4's review pass after a full sweep of every
    # `.env.example` assignment found it pinned at the measured-failing 16384: the row
    # exists so the report can see that class of revert, not just the flags.
    "deepseek_max_tokens": Decision(
        "6.9 truncation measurement", "2026-08-05", 32768,
        "deepseek_max_tokens: `Measured 2026-08-05 ... 16384 truncates scenario/structure 4/4`",
    ),
}


# One mechanism per value, never both fields: reasoning_effort for a depth,
# `thinking` only for off (the only form that probed reasoning_tokens=0), and
# nothing at all for "default" so that value keeps the pre-2026-08-06 request
# byte-identical. See `deepseek_reasoning` above for the probe numbers.
#
# Lives here rather than in pipeline/nodes/scenario.py (Story 10.8): services
# must not import from pipeline/, and character_service needs the same mapping —
# `_select_entity_angles` was the one call site that never got the 2026-08-05
# fix and truncated on every run because of it.
REASONING_BODY: dict[str, dict] = {
    "low": {"reasoning_effort": "low"},
    "medium": {"reasoning_effort": "medium"},
    "high": {"reasoning_effort": "high"},
    "disabled": {"thinking": {"type": "disabled"}},
    "default": {},
}
