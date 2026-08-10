# 10.4 Live Validation — image/narration semantic match (Jay findings 2·4·7·9·16)

Evidence for Story 10.4. Measured 2026-08-10 against run
`8a9a288b-800f-4c73-88a2-25ae6b5a4d7d` (SCP-049, 9 scenes, 66 shots — see the provenance
correction in §0 before reading "the run Jay watched" anywhere in this file),
judge `qwen-vl-plus` via DashScope, renders from the live ComfyUI at `http://127.0.0.1:8188`
(v0.12.3, ROCm, `AnimagineXL_v31.safetensors`).

> **Verdict: the prompt change LOST its pre-registered A/B and was NOT seeded. The
> repo prompt is reverted to `3869f95`; `scripts/migrate_prompts.py` was never run and
> Langfuse `scenario/visual_breakdown` is still version 14.**
>
> **And the baseline undercuts the story's premise.** Over all 66 frames the axis scores a
> **7.6 % failure rate** (5/66) against its own thresholds, with **0/66** below the legibility
> floor. The instrument does not reproduce finding 2 ("무슨 배경인지 모르겠다") *as a score* at
> all. What it does reproduce is finding 2 *as a fact*: the blind caller wrote
> `event: "unclear"` on **9/66 (13.6 %)** frames — it just still called those frames
> `legible: 4`. See §2.2; that mismatch between the rubric and the model's own numbers is
> the single most important thing this directory measured.

> **ITERATION 2 (same day, below §7).** §2.2's dead Likert was replaced with a boolean
> and the lever moved from prompt wording to the **1:1 sentence↔shot bijection**. §1–§7
> stand unchanged as the pre-change record. Headline: the boolean recovers **12/66**
> unreadable frames the Likert scored 0 (§8); the ordered cover ships and cuts renders
> 66 → 55 (§9, §10.1); and it **again lost its pre-registered rule** — paired Δ `match`
> **−0.152**, 95 % CI **[−0.394, +0.076]**, so nothing was seeded (§10.2). **AC3's
> prediction is falsified: 0 of the 4 worst rows were merged** (§10.3). A follow-up probe
> then performed those merges **by hand** and measured them (§12): merging bought
> **nothing** — M1 Δ **0.000** on 5 hand-merged sentences, M2 +0.200 against +0.182 on the
> untouched sentences of the same scenes. **The mapping hypothesis is dead as a `match`
> lever**, and the cover should be justified on render cost, not semantic match.

---


## 0. Provenance correction — 51 of the 66 baseline frames are NOT what Jay watched

Found 2026-08-10 while auditing `baseline_v2.json`, after the measurements below were taken.
Recorded rather than quietly fixed.

The scorer resolves a shot's frame from the checkpoint's `shot["image_path"]`. For this run
that field was **repointed to Story 10.1c's recompositions** (`recomposed/`, rendered
2026-08-09) by `recompose_service`, while the video Jay watched was rendered **2026-08-08**,
before the recompose. So the baseline is 51 recomposed frames + 15 original plates, not 66
frames from the screening.

| frame source | n | unreadable | blind reading = "corridor" | mean `match` |
|---|---:|---:|---:|---:|
| `recomposed/` (10.1c, post-screening) | 51 | 10 (20%) | 29 (57%) | 3.57 |
| `images/` (original plate) | 15 | 2 (13%) | 4 (27%) | 3.80 |

**What this does and does not invalidate.** The A/B legs (`ab2_old`, `ab2_new`) and the merge
probe rendered fresh plates, so every comparative result stands. What is wrong is the
*label*: the absolute baseline rates below describe the checkpoint's current frames, and the
recomposed subset scores worse on both measures (n=15 for the control, so the gap is a
direction, not a calibrated figure). `baseline.json` / `baseline_v2.json` are left
byte-identical; only this reading of them is corrected.

Re-derive:
```
python3 -c "import json;rows=json.load(open('baseline_v2.json'))['rows'];print(sum('/recomposed/' in r['frame'] for r in rows), len(rows))"
```


## 1. Re-derive everything with two commands

```
# PASS A — the baseline over the run's 66 frames (3 arms, ~8 min, ~230 VLM calls)
uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_baseline.py

# PASS B — old prompt vs new prompt on a fixed slate (needs ComfyUI up; ~45 min)
uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_ab.py
```

Both import and drive `scripts/score_shot_narration.py` — the axis is shipped code, not a
copy living in the harness. Every number below comes from a JSON file in this directory;
none was typed by hand. The axis alone, on any run:

```
uv run python scripts/score_shot_narration.py --run <run-id> --json out.json \
    [--frames images|shots] [--reps N] [--limit N]
```

**Provenance of every measurement here:** frames = `workspace/8a9a288b-…/images/*.png`
(PASS A) or this directory's `old/`+`new/` (PASS B); judge = `qwen-vl-plus`,
`temperature: 0`, DashScope international endpoint; the two judge prompts are stored
**verbatim** in every report JSON under `blind_prompt` / `match_prompt`; per-shot rows with
all raw samples are in `rows`; thresholds are in `thresholds`.

### 1.1 What the axis is

Two calls per shot, **in this order**:

1. **BLIND** — the frame alone. The narration sentence is *withheld*. Returns
   `{place, event, legible}`. This is the control: shown the sentence first, a VLM finds a
   way to agree with it, and the result is confirmation rather than measurement.
2. **MATCH** — the same frame *plus* its sentence. Returns `{match, evidence, missing}`.

Both prompts state that people are composited from separate cards and that an unpeopled
plate is correct — without that sentence every cast-bearing shot fails for the wrong reason
and the whole measurement is void.

Thresholds (module constants in `scripts/score_shot_narration.py`):
`MIN_LEGIBLE = 3`, `MIN_MATCH = 3`, and for scene 1's first shot (the hook)
`MIN_LEGIBLE_HOOK = 4`, `MIN_MATCH_HOOK = 4`.

### 1.2 The frames are prompt renders, not stock plates

Checked before anything else, because it decides whether `image_prompt` is even the lever:
all 66 frames' md5s were compared against the 43 approved plates in
`assets/locations/*/*.png` — **0 matches**. `stock_plate_substitution_enabled` is `false`
and is not pinned in `.env`. Every frame in this run was generated from its `image_prompt`.

```
python3 -c "import hashlib,glob;p={hashlib.md5(open(f,'rb').read()).hexdigest() for f in glob.glob('assets/locations/*/*.png')};print(sum(hashlib.md5(open(f,'rb').read()).hexdigest() in p for f in glob.glob('workspace/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d/images/scene_*[0-9].png')))"
```

---

## 2. PASS A — the baseline over all 66 frames

`baseline.json` — arm A1, `--frames images`, `--reps 1`, 66 rows, 0 skipped, 0 errored.

| metric | value |
|---|---:|
| shots scored | 66 |
| **failure rate** (below `MIN_LEGIBLE` or `MIN_MATCH`; hook at 4/4) | **7.6 %** (5/66) |
| mean `match` | 3.606 |
| mean `legible` | 4.303 |
| below `MIN_MATCH` (=3) | **4** |
| below `MIN_LEGIBLE` (=3) | **0** |
| illegible only (finding 2) / mismatch only (finding 4) / both | **0 / 4 / 0** |
| **hook `S00100`** | `legible` 4, `match` 3 → **fails** the hook bar (needs 4/4) |

### 2.1 Finding 2 and finding 4 are different defects, and only one of them scored

The AC requires these be kept apart, and keeping them apart is what exposes the result:

* **finding 4 ("나레이션과 안 맞는다")** — 4 shots scored below `MIN_MATCH` while remaining
  perfectly legible on their own: `S00105` (match 1), `S00303` (1), `S00708` (1), `S00503` (2).
  These are real, and they are exactly the "clear picture of the wrong thing" defect.
* **finding 2 ("무슨 배경인지 모르겠다")** — **zero** shots scored below `MIN_LEGIBLE`.
  Not one.

### 2.2 …because `legible`, as scored by qwen-vl-plus, is a dead axis

| `legible` | 1 | 2 | 3 | 4 | 5 |
|---|---:|---:|---:|---:|---:|
| shots | 0 | 0 | **0** | 46 | 20 |

The score never left {4, 5} across 66 frames. Its own rubric says *"3 = the place reads, the
event does not"* — and the model wrote `event: "unclear"` on **9 frames** (`S00202`,
`S00204`, `S00300`, `S00304`, `S00305`, `S00400`, `S00707`, `S00805`, `S00900`) while
scoring **every one of them `legible: 4`**. The blind `event` field contradicts the blind
`legible` score, in the same reply.

**So the usable measurement of finding 2 is not the score — it is the blind caption's own
words: 9/66 = 13.6 % of frames depict no event the model can name.** That is a
free-text count, and it is reported as one; it is not a calibrated threshold.

`match` did spread (1: 3, 2: 1, 3: 27, 4: 23, 5: 12), so the failure this axis actually
measures is finding 4, not finding 2.

### 2.3 A confound found by accident: the plates are populated

28 of the 66 blind captions describe a **body inside the plate** — "two figures stand facing
each other", "a figure in a plague mask stands before the cell". `image_prompt` is
background-only and none of these prompts describe a person; this is Story 10.2's finding
5·12 (`background_person_guard_attempts` was 0 for this run), independently reproduced here
on 42 % of the run.

It matters for *this* story because those bodies can earn `match` credit the prompt never
asked for. Any future comparison on this axis should be run **after** 10.2's guard is on, or
it is scoring two variables at once.

### 2.4 Cross-check — does the verdict move on the composited frame?

Arms A2 (`worst_images.json`, same frames, `--reps 3`) and A3 (`worst_shots.json`,
`--frames shots`, `--reps 3`) run the 8 worst shots of A1 at identical reps, so the only
difference between them is the frame source. A2 exists precisely so a moved A3 verdict can
be told apart from the judge sampling differently on a second look.

| shot | A1 plate, reps 1 | A2 plate, reps 3 | A3 composited, reps 3 | verdict |
|---|---|---|---|---|
| `S00100` | 4 / 3 | 4 / 3 | 4 / 3 | unchanged |
| `S00105` | 4 / 1 | 4 / 1 | 5 / 1 | unchanged (`legible` +1) |
| `S00201` | 4 / 3 | 4 / 3 | 4 / 3 | unchanged |
| `S00204` | 4 / 3 | 4 / 3 | — no clip | n/a |
| `S00301` | 4 / 3 | 4 / 3 | 4 / 3 | unchanged |
| `S00303` | 4 / 1 | 4 / 1 | — no clip | n/a |
| `S00503` | 5 / 2 | 5 / 2 | — no clip | n/a |
| `S00708` | 5 / 1 | 5 / 1 | — no clip | n/a |

Two things fall out. **A2 reproduced A1 exactly on all 8 shots** — at `temperature: 0` this
judge is highly repeatable, which is why `--reps 3` bought so little. And on the 4 shots that
have a composited clip, **`match` did not move at all**: judging the plate is not measurably
different from judging what Jay saw. The 4 missing rows are a fact about the run, not the
axis — only 42 of 66 shots have a `shots/*.mp4` (per-shot cut assembly, Story 8.11, does not
emit one for every shot).

### 2.5 Per-shot baseline table

Full rows with every raw sample: `baseline.json`.

| shot | sentence | blind `place` | blind `event` | `legible` | `match` | `missing` (match call) |
|---|---|---|---|---:|---:|---|
| `S00100` **HOOK** | 손이 닿는 순간, 그는 죽었습니다. | a cracked stone corridor | debris and dust have fallen from the ce… | 4 | 3 | there is no visible sign of a person or their death in th… |
| `S00101` | 디 계급 인원이 격리실로 들어옵니다. | a metal cell | a stool is placed in front of a door | 4 | 5 |  |
| `S00102` | 가냘픈 실루엣, 바닥까지 닿는 검은 로브. | a dark, narrow corridor | a bright light has fallen from above | 4 | 5 |  |
| `S00103` | 길게 휜 부리의 도자기 가면이 그를 향하죠. | a dimly lit corridor with metal g… | two figures stand facing each other, on… | 5 | 5 |  |
| `S00104` | 맨손이 나와 악수를 청합니다. | a prison cell | two figures stand facing forward | 5 | 3 | There is no visible hand or gesture indicating an offer t… |
| `S00105` | 두 손이 맞닿자, 그는 그 자리에서 쓰러졌습니다. | a dilapidated wooden structure | two figures stand facing each other | 4 | 1 | The frame shows two people standing, but there is no indi… |
| `S00106` | '이것이 치료의 시작입니다.' | a damaged corridor | debris scattered on the floor | 4 | 4 | The specific details of what 'the start of treatment' ent… |
| `S00200` | 재단 격리 기록에는 이렇게 적혀 있습니다. | a desk with documents | papers are stacked and slightly disorga… | 4 | 4 | The specific content of what is written in the records is… |
| `S00201` | '에스씨피-공사구, 키 약 일점 구 미터, 인간형. | a metal-barred cell in a corridor | a figure in a plague mask stands before… | 4 | 3 | The height of approximately 1.5 meters is not visually ve… |
| `S00202` | 중세 흑사병 의사의 복장에, 얼굴에 융합된 창백한 도자기 가면.' 뗄 수가 없… | a stone-walled corridor | unclear | 4 | 5 |  |
| `S00203` | 그는 표준 인간형 격리 셀에서 지내며, 말을 합니다. | a barred cell or corridor | a figure stands in front of a barred do… | 4 | 4 | The sentence mentions the person speaking, but there is n… |
| `S00204` | 아주 협조적으로요. | a concrete corridor | unclear | 4 | 3 | There is no visible action or physical consequence that d… |
| `S00300` | 의사가 가면을 숙이며 말합니다. | a concrete corridor | unclear | 4 | 4 | The action of bowing their head while speaking is not exp… |
| `S00301` | '이 방에 병이 가득하오.' 창백한 손이 허공을 가리키고 있습니다. | a cracked concrete wall | cracks in the wall | 4 | 3 | There is no visible evidence of illness or anything that … |
| `S00302` | 당신 눈에는 그저 빈 콘크리트 벽. | a tiled floor with a wall | a circular hole in the floor with liqui… | 4 | 5 |  |
| `S00303` | 보입니까, 그 병이? | a dim corridor with a large window | a figure in a plague mask stands still | 4 | 1 | There is no visible evidence of a specific disease or ill… |
| `S00304` | 검은 눈구멍이 초점 없이 공중을 스캔합니다. | a concrete corridor | unclear | 4 | 3 | There is no visible evidence of black eye sockets or any … |
| `S00305` | 그는 진심으로 보고 있습니다. | a tiled examination room | unclear | 4 | 4 | The specific object or direction of the person's gaze is … |
| `S00306` | 당신만 못 볼 뿐, 그 병이 여기 있다는 겁니다. | a dimly lit corridor with a barre… | a figure in a hooded cloak stands in th… | 4 | 4 | The specific event of 'the disease being here' is not vis… |
| `S00400` | 지휘부의 재량 아래, 격리실 문이 열리고, 디계급이 들어섭니다. | a concrete corridor | unclear | 4 | 4 | The action of the door opening or the character being gui… |
| `S00401` | 에스씨피-049가 정중히 고개를 숙입니다. | a tiled examination room | medical instruments scattered on the fl… | 5 | 5 |  |
| `S00402` | '환자군요.' 검은 소매에서 창백한 맨손이 나옵니다. | a metallic corridor | smoke on the floor | 4 | 4 | The action of the hand being pulled out or any indication… |
| `S00403` | 가면의 어두운 눈구멍이 그를 끝까지 응시합니다. | a tiled examination room | a person is being observed by masked fi… | 5 | 5 |  |
| `S00500` | 악수를 청하던 손이, 이제 당신의 손을 감쌌습니다. | a dark, tiled room | a covered body lies on the floor | 4 | 3 | The frame does not show any hands or physical contact bet… |
| `S00501` | 피부가 닿는 순간, 체온이 사라졌습니다. | a dimly lit corridor | two figures stand facing each other | 5 | 3 | There is no visible indication of a change in temperature… |
| `S00502` | 가면의 부리가 시야를 가득 채웁니다. | a dimly lit, cracked concrete cor… | two figures stand in a corridor with bl… | 5 | 5 |  |
| `S00503` | 다리가 풀리고... | a futuristic circular corridor | two figures stand facing each other | 5 | 2 | There is no visible evidence of actual falling or collaps… |
| `S00504` | 바닥이 다가옵니다. | a cracked tiled floor under a tab… | a shoe has crushed the floor, causing i… | 4 | 5 |  |
| `S00505` | 수 초면, 죽음입니다. | a tiled examination room | a table has been smeared with a white s… | 4 | 3 | The sentence '수 초면, 죽음입니다.' (If it's a few seconds, it's … |
| `S00506` | '걱정 마세요. | a tiled examination room | bloodstains on the wall and floor | 4 | 3 | There is no direct evidence of what '걱정 마세요' (Don't worry… |
| `S00507` | 이제 시작입니다.' | a tiled examination room | a pool of red liquid on the floor | 4 | 3 | There is no visible consequence or physical evidence of a… |
| `S00600` | 수술 기록입니다. | a dim, tiled utility room | a rectangular panel lies askew on the f… | 4 | 3 | There is no visible evidence of a surgical record or docu… |
| `S00601` | 낡은 메스와 실이, 로브에서 나왔습니다. | a metallic examination table | a sheet of paper lies crumpled on the t… | 4 | 4 | The frame does not show a robe or any indication that the… |
| `S00602` | 시체를 반듯하게 눕혔습니다. | a tiled examination room | two figures stand in a medical-style ro… | 5 | 3 | There is no visible body on the bed, and no indication of… |
| `S00603` | 소중한 환자를 대하듯이. | a tiled examination room | two figures stand in a room with a bed | 5 | 3 | There is no visible evidence of a patient or any interact… |
| `S00604` | 절개가 시작됐습니다. | a high-tech containment unit | a swirling red anomaly is visible inside | 4 | 4 | The specific action of the fissure starting is not direct… |
| `S00605` | 천천히, 아주 천천히. | a sterile examination room | two figures stand facing each other, on… | 5 | 3 | There is no visible movement or action that directly corr… |
| `S00606` | 무언가를 더듬다가, 꿰맵니다. | a tiled examination room | a person is restrained on a table | 4 | 4 | The specific object being searched for or the act of inse… |
| `S00607` | 피부를 뚫는 소리. | a metallic corridor with a large … | two figures stand in front of a glowing… | 4 | 3 | There is no visible evidence of a piercing action or any … |
| `S00608` | 그게 격리실을 채웠습니다. | a tiled examination room | liquid has pooled and dripped from a do… | 5 | 4 | The action of filling the isolation room is not directly … |
| `S00609` | 관찰창 너머, 당신도 숨을 죽이고 있습니까? | a corridor with glass doors | two figures stand facing each other | 5 | 4 | The specific action of holding one's breath is not visual… |
| `S00610` | 자르는 게 무엇인지, 묻는 이가 없습니다. | a dimly lit cell | two figures stand in a cell with a bloo… | 4 | 3 | There is no visible evidence of someone being asked '자르는 … |
| `S00700` | 봉합이 끝났습니다. | a tiled examination room | a procedure has just been completed | 5 | 4 | There is no visible sign of a body or wound that would co… |
| `S00701` | 손가락이 움직입니다. | a dimly lit medical room | a figure stands in a spotlight with blo… | 4 | 3 | There is no physical evidence of a finger moving in the f… |
| `S00702` | 실이 조여드는 소리. | a tiled examination room | a wall has been violently breached | 5 | 4 | the actual sound of a string being tightened is not visua… |
| `S00703` | 몸이 부자연스러운 각도로 일어섭니다. | a futuristic corridor | distorted light streaks and damage on t… | 4 | 4 | There is no visible consequence of the body moving into t… |
| `S00704` | 비뚤어진 팔다리, 도드라진 봉합선. | a tiled examination room | a large cloth is draped and billowing | 4 | 4 | The frame does not show any explicit distortion in the li… |
| `S00705` | 눈이 떠졌지만, 그 안엔 아무것도 없습니다. | a dimly lit corridor with a large… | a dark circular stain is visible on the… | 4 | 3 | There is no visible evidence of an eye opening in this fr… |
| `S00706` | 에스씨피 공사구가 가면을 기울여 바라봅니다. | a sterile examination room | nothing has happened | 5 | 4 | The frame does not show the specific motion of tilting th… |
| `S00707` | 만족스러운 듯이요. | a corridor with barred doors | unclear | 4 | 3 | There is no visible action or consequence that directly i… |
| `S00708` | 이게 에스씨피 공사구-이입니다. | a tiled corridor | two figures stand in a pool of light | 5 | 1 | The sentence mentions '이게 에스씨피 공사구-이입니다.' (This is the SC… |
| `S00800` | "보십시오. | a sterile, industrial room | two figures stand in a room with signs … | 4 | 3 | There is no explicit event or action depicted in the fram… |
| `S00801` | 완치입니다. | a tiled examination room | a person stands in a dimly lit room wit… | 4 | 3 | There is no visible evidence of healing or recovery in th… |
| `S00802` | 이 환자는 이제 안전합니다." 창백한 손이, 되살아난 그것의 어깨를 두드립니다. | a concrete corridor | blood splatter on the floor | 5 | 4 | The specific action of a hand touching a shoulder is not … |
| `S00803` | 하지만 당신의 눈에는, 비뚤어진 팔다리와 잔뜩 꿰맨 봉합선뿐입니다. | a blood-splattered examination ro… | recent violence or surgery | 4 | 4 | The specific mention of 'crooked limbs' and 'stitched-up … |
| `S00804` | 빈 눈. | a metallic corridor with large wi… | a figure in torn scrubs stands still | 4 | 4 | There is no physical evidence of an event or consequence … |
| `S00805` | 그가 보는 병. | a dark, tiled corridor | unclear | 4 | 3 | There is no visible evidence of what 'he sees' or the spe… |
| `S00806` | 바로 그게 대역병의 정체입니다. | a circular stone chamber with a p… | two figures stand on the edge of a dark… | 5 | 4 | The specific identity or nature of the 'plague' is not vi… |
| `S00807` | 치료법은, 오직 그만이 이해합니다. | a dark, dripping doorway | a figure stands in a spotlight | 4 | 3 | The specific event of understanding a treatment method is… |
| `S00900` | 철제 문이 닫히는 금속음. | a concrete corridor | unclear | 4 | 3 | There is no visible evidence of a metal door closing or t… |
| `S00901` | 관찰창 하나만이 비춥니다. | a tiled examination room | a small window is ajar | 4 | 5 |  |
| `S00902` | 셀 중앙에 선 채, 그가 가면을 당신에게 돌립니다. | a tiled examination room | a figure in a plague mask stands in the… | 5 | 5 |  |
| `S00903` | 발견 기록도, 회수 기록도, 연대기도, 없던 개체. | a concrete corridor | papers hang askew on a wall | 4 | 5 |  |
| `S00904` | 그가 보는 대역병의 정체는, 끝내 알 수 없습니다. | a concrete corridor | a figure stands in a pool of light | 4 | 3 | There is no visible evidence of the consequences or after… |
| `S00905` | 그는 기다립니다. | a barred cell | a figure stands in the doorway | 4 | 4 | The specific action of 'waiting' is implied but not expli… |
| `S00906` | 환자를 살리고 있다고, 믿으며. | a cracked window in a concrete wa… | a circular object broke through the gla… | 5 | 3 | The frame does not show any person or creature that might… |

---

## 3. The prompt change under test

Four bounded edits to `prompts/scenario/visual_breakdown.md`, preserved verbatim as
`prompt_new.md` (the leg that lost) beside `prompt_old.md` (`3869f95`):

1. `:5` — "most powerful visual moment" qualified to be *of this sentence's event*, with an
   explicit statement that a beautiful frame carrying no trace of the event has failed.
2. Slot 3 rewritten from "Action, pose, or state" into **"This sentence's event, and what it
   left behind (REQUIRED)"** — 누가/무엇을/**결과**, the pure texture study named as a failure,
   and the spec's BAD/GOOD `S00100` transition inlined.
3. A new Scene-1 rule: scene 1's first shot must read on its own as *where this is* and
   *what just happened*; extreme close-ups and single-material abstractions forbidden for
   that one shot.
4. Three matching Pre-Output Self-Check bullets.

Untouched: the background-only rule, the negative-prompt contract, the forbidden-terms list,
every cast section. `diff prompt_old.md prompt_new.md` is 4 hunks, +15/−2 lines.

---

## 4. PASS B — the A/B, and the rule it was judged by

Slate: **scene 1 (7 shots, carries the hook) + scene 5 (8 shots, `escalation`)** = 15 slots,
30 renders. Held identical across legs: narration, sentences, `cast_by_sentence`, entity
context, the KSampler seed per slot (`image._shot_seed(run_id, scene_num, shot_id)` — the
seed each shot was originally rendered on), the workflow JSON (so 1344×768 / 30 steps / cfg
7.5 / `dpmpp_2m`+`karras` / `darkness_xl_v2` all come from production's own file), and the
`negative_prompt` (the checkpoint's, not each leg's own, so the pair differs in one thing).
Both legs scored by the same script, same model, `--reps 3`.

> **Pre-registered win rule (quoted from the spec's first AC, before its result):**
> *mean `match` over the slate does not decrease, the count of shots below `MIN_MATCH` does
> not increase, and the hook shot reaches `match ≥ 4` and `legible ≥ 4`.* The prompt is
> seeded to `production` **if and only if all three hold.**

| clause | OLD | NEW | held? |
|---|---:|---:|---|
| mean `match` does not decrease | **3.267** | **2.933** | ❌ **no** |
| count below `MIN_MATCH` does not increase | 2 | 1 | ✅ yes |
| hook reaches `match ≥ 4` **and** `legible ≥ 4` | 5 / 4 | **3** / 4 | ❌ **no** |

**Two of three clauses failed → `won: false` → the prompt was reverted and never seeded.**
`ab_result.json` records this; `run_ab.py` exits 1.

### 4.1 Per-shot

`old`/`new` columns are `legible` / **`match`**. Baseline is the checkpoint's current frame
(51/66 of which are 10.1c recompositions, not the 2026-08-08 render — see §0),
shown for scale only — it is a *different generation* of the same prompt version (see §4.2).

| shot | sentence | baseline `legible`/`match` | OLD leg | NEW leg | Δ match (new−old) |
|---|---|---|---|---|---:|
| `S00100` **HOOK** | 손이 닿는 순간, 그는 죽었습니다. | 4 / 3 | 4 / **5** | 4 / **3** | -2 |
| `S00101` | 디 계급 인원이 격리실로 들어옵니다. | 4 / 5 | 4 / **3** | 4 / **3** | +0 |
| `S00102` | 가냘픈 실루엣, 바닥까지 닿는 검은 로브. | 4 / 5 | 4 / **3** | 3 / **3** | +0 |
| `S00103` | 길게 휜 부리의 도자기 가면이 그를 향하죠. | 5 / 5 | 4 / **1** | 3 / **3** | +2 |
| `S00104` | 맨손이 나와 악수를 청합니다. | 5 / 3 | 4 / **1** | 4 / **3** | +2 |
| `S00105` | 두 손이 맞닿자, 그는 그 자리에서 쓰러졌습니다. | 4 / 1 | 5 / **4** | 4 / **3** | -1 |
| `S00106` | '이것이 치료의 시작입니다.' | 4 / 4 | 4 / **3** | 4 / **3** | +0 |
| `S00500` | 악수를 청하던 손이, 이제 당신의 손을 감쌌습니다. | 4 / 3 | 4 / **5** | 4 / **3** | -2 |
| `S00501` | 피부가 닿는 순간, 체온이 사라졌습니다. | 5 / 3 | 3 / **3** | 4 / **3** | +0 |
| `S00502` | 가면의 부리가 시야를 가득 채웁니다. | 5 / 5 | 4 / **4** | 3 / **1** | -3 |
| `S00503` | 다리가 풀리고... | 5 / 2 | 4 / **3** | 4 / **3** | +0 |
| `S00504` | 바닥이 다가옵니다. | 4 / 5 | 3 / **4** | 4 / **4** | +0 |
| `S00505` | 수 초면, 죽음입니다. | 4 / 3 | 4 / **4** | 4 / **3** | -1 |
| `S00506` | '걱정 마세요. | 4 / 3 | 4 / **3** | 4 / **3** | +0 |
| `S00507` | 이제 시작입니다.' | 4 / 3 | 3 / **3** | 5 / **3** | +0 |

Pairs (same seed, same negative, different `image_prompt`):
`pairs/<base>_pair.jpg`, labelled OLD | NEW.

### 4.2 The result that matters more than the verdict: this experiment is underpowered

The baseline frames and the OLD leg were written by **the same prompt version** — the only
difference is that DeepSeek wrote them on different days. So the baseline→OLD delta is a
pure same-prompt control, and it is the noise floor any A/B on this slate has to clear:

| comparison | mean Δ `match` | mean \|Δ\| | sd | max \|Δ\| |
|---|---:|---:|---:|---:|
| **same-prompt control** (baseline frames → OLD leg) | **−0.267** | 1.47 | 1.87 | 4 |
| **the A/B effect** (OLD leg → NEW leg) | **−0.333** | 0.87 | 1.35 | 3 |

The effect the rule rejected (−0.333) is **the same size as the drift between two runs of the
identical prompt** (−0.267), on n = 15 with a per-shot sd of ~1.4. The hook clause fails on a
single shot whose control leg swung 3 → 5 between two generations of the same prompt text.

**The honest reading is "no measurable effect", not "the new prompt is worse."** The rule was
pre-registered and it did not hold, so the prompt is not seeded — that is the rule working as
intended. But nothing here licenses the claim that the edit hurt quality.

### 4.3 One measured mechanism, offered as a hypothesis and not a conclusion

The new prompt made `image_prompt` **44 % longer**, and the extra length is the event clause
it asked for:

| leg | shots | mean words | max words |
|---|---:|---:|---:|
| baseline (all 66, same prompt version as OLD) | 66 | 86 | — |
| OLD | 15 | **84** | 112 |
| NEW | 15 | **121** | 137 |

A longer prompt is not free at the renderer: SDXL's text encoder chunks at 77 tokens and
weights dilute across the whole string, so clauses added at the end compete with the shot
type, the tactile detail and the lighting that were already there. `pairs/scene_001_S00100_pair.jpg`
is the visible case — the NEW leg's prompt describes a wide containment cell with an impact
hollow in the dust and an instrument tray knocked open; the render is a green-lit brick pit
with none of that in it.

**This is a hypothesis with one supporting measurement (the word counts) and one
illustration (that pair). It was not tested** — testing it means a third leg with the event
requirement expressed in the same word budget, which is out of this story's scope. It is
recorded because it is the most actionable thing to try next: *require the event, but require
it to replace words rather than add them.*

### 4.4 Reconstruction caveats specific to pass B

`location` / `color_palette` / `atmosphere` are `writing_step` fields and were never
persisted for this run (the checkpoint keeps `scenes`, not the writing artifact), so
`visual_breakdown_step` fell back to its module defaults *for both legs*. `scene_role` was
rebuilt from the checkpoint's own `mood`/`title`/`kicker` — those three ARE this run's
structure output; the act/beat/synopsis *wording* is not. `frozen_descriptor` /
`entity_sheet` / `story_logline` come from one live `research_step` call made once, before
either leg ran, and shared by both (`ab_context.json`). All of this is constant across legs,
so it cannot explain the delta — but it does mean the legs are not byte-identical
reproductions of the original production call.

---

## 5. What this sample does NOT say

- **qwen-vl-plus is the instrument, and it was not human-audited.** No verdict in this
  directory was checked against a human's reading of the frame beyond the pair JPEGs
  reproduced here. §2.2 shows the instrument contradicting its own rubric; §2.3 shows it
  reading bodies into plates. Treat `legible` as unusable and `match` as a coarse
  1–5 with roughly ±1.5 of per-shot noise.
- **n = 66 for the baseline and n = 15 per leg for the A/B, one run, one SCP (049), one
  Korean script.** Nothing here generalises to another entity, another script length, or
  another checkpoint.
- **It does not say the old prompt is good.** It says that on this instrument, at these
  thresholds, only 4 of 66 frames scored as mismatched. Jay's own review of the same video
  was far harsher. Either the thresholds are wrong, the judge is too generous (§2.2 says it
  is), or the defect he perceived is not the one this axis measures — e.g. it is
  *cumulative* ("many backgrounds I can't place"), and a per-frame score cannot see a
  run-level sameness.
- **It does not say the prompt edit fails.** §4.2: the A/B is inside its own noise floor.
- **It does not establish a root cause for findings 2·4·7·9·16.** The only causal claim this
  directory supports is negative: the frames were prompt renders, not stock plates (§1.2), so
  whatever the cause is, it is upstream of plate substitution.
- **The A3 cross-check covers 4 shots.** "Plate ≈ composited frame" is supported on those
  four and unmeasured on the other 62.
- **No runtime behaviour changed.** No prompt was seeded, no config knob moved,
  `src/yt_flow/` is byte-identical to `3869f95`.

---

## 6. Judgment — should this axis go into Story 13.2?

**Recommendation: yes for `match` and the blind `event` caption; no for `legible`; and not
until Story 10.2's guard is on.** Reasoning, in the order the evidence supports it:

1. **`match` is the only scored field with signal.** It spread across all five values and it
   ranked the four shots (`S00105`, `S00303`, `S00708`, `S00503`) that a human reading the
   narration next to the frame would also call wrong. That is a usable axis.
2. **`legible` must not be shipped as scored.** 0 variance below 4 over 66 frames (§2.2). If
   13.2 wants finding 2, it should take the **blind `event` string** and count `"unclear"` —
   which produced 13.6 %, an order of magnitude more signal than the score did — or replace
   the 1–5 scale with a forced binary ("can you name what happened here: yes/no").
3. **The blind-first call shape should be kept whatever the fields become.** It cost one
   extra call per shot and it is the only reason §2.2 was visible at all: the model's
   unanchored testimony disagreed with its own anchored score.
4. **It must run after 10.2's guard, not before.** 42 % of these plates contain a body
   (§2.3). An axis scored on populated plates measures the guard and the prompt at once.
5. **Cost is real but bounded**: 2 calls/shot ≈ 132 calls for a 66-shot run, ~8 minutes
   wall-clock, no new dependency. `--reps 3` is not worth it — A2 reproduced A1 exactly on
   8/8 shots at `temperature: 0` (§2.4).
6. **It stays out of `eval_service.AXES` / `determine_winner` / the Langfuse judge rubric**
   until 6.12's A/B promotion freeze lifts (Story 13.4). Ship it as a reporting axis first.

**Re-open condition for the prompt edit itself:** re-run pass B with ≥ 40 slots and both legs
generated ≥ 3 times (median per slot), after 10.2's guard is on, and with the event
requirement written to a **word budget** rather than as an addition (§4.3). Until the design
clears its own control (§4.2), a 15-slot single-generation A/B cannot decide this question in
either direction.

---

## 7. Explicitly not done

- **The prompt was not seeded.** `scripts/migrate_prompts.py` was not run; there is no
  `migrate_prompts.txt` in this directory, deliberately — Langfuse `scenario/visual_breakdown`
  is still version 14, identical to `3869f95`'s repo file.
- **No negative-prompt string gained a term** anywhere (`gotcha_negative-prompt-overstuffing`).
- **No runtime regeneration guard on a low semantic score**, per the spec's Never tier — and
  §4.2 is now a second, independent reason not to build one: the score's per-shot noise
  (sd ≈ 1.4) is larger than any threshold such a guard could use.
- **Nothing under `workspace/8a9a288b-…/` was written.** PASS A reads frames and extracts
  mid-frames into a temp dir.
- **`src/yt_flow/` is unchanged** — `git diff 3869f95 --stat -- src/yt_flow` is empty.

## Layout

| Path | What it is |
|---|---|
| `run_baseline.py` | PASS A — 3 arms over the 66 baseline frames; drives the shipped axis |
| `baseline.json` | A1: all 66 shots, plates, reps 1 — rows, both judge prompts, summary |
| `worst_images.json` | A2: the 8 worst shots re-scored on the same plates at reps 3 (control) |
| `worst_shots.json` | A3: the same 8 on the composited clip's mid-frame at reps 3 |
| `worst_delta.json` | A1/A2/A3 side by side per shot — the §2.4 table's source |
| `run_ab.py` | PASS B — writes both legs, renders both, scores both, evaluates the rule |
| `prompt_old.md` / `prompt_new.md` | The two runtime prompt texts actually compiled |
| `ab_context.json` | The entity/scene context built once and given to both legs |
| `ab_old_shots.json` / `ab_new_shots.json` | Each leg's raw `visual_breakdown_step` output |
| `ab_slate.json` | The 15 slots: both prompts, the shared seed, the shared negative |
| `old/*.png` / `new/*.png` | The 30 renders |
| `pairs/*_pair.jpg` | OLD \| NEW, labelled — the adjudication artifacts |
| `ab_old.json` / `ab_new.json` | The axis's full report per leg |
| `ab_result.json` | The pre-registered rule, its three clauses, and `won: false` |

---

# Iteration 2 — the lever changes: bijection → ordered cover

Everything above is iteration 1 and stands as the **pre-change record**. It is not
revised here; it is the thing iteration 2 was built on top of. Two things changed,
both because the data above said so, and Jay's answer to the three blocking questions
settled the third:

> **"한 대본 문장에 여러 이미지가 있을 수 있고, 한 이미지에 여러 대본 문장셋이 매핑될 수 있다"**

## 8. The instrument: `legible` 1–5 → `readable` boolean

§2.2 measured a dead axis: 66 frames produced `legible` ∈ {4:46, 5:20}, **nothing below
4**, while **9 of those same replies** wrote `event: "unclear"`. The score refused to
express what the reply already knew. So the question changed to the discrete value the
model was volunteering anyway — `readable: true|false`, true only if a viewer could say
*both* where this is *and* what happened, from the frame alone.

Re-derive (no frame is re-rendered — the identical preserved PNG set, a different
question; `baseline.json` is never rewritten):

```
uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_baseline.py --rescore
#   -> baseline_v2.json, instrument_v1_vs_v2.json
```

| on the same 66 preserved frames | Likert `legible` (iteration 1) | boolean `readable` (iteration 2) |
|---|---:|---:|
| frames the readability axis fails | **0 / 66** | **12 / 66 (18.2 %)** |
| distribution | `{4: 46, 5: 20}` | `{true: 54, false: 12}` |
| blind reply wrote `event: "unclear"` | 9 / 66 | 12 / 66 |
| of the failing frames, how many the Likert had scored 4–5 | — | **12 / 12** |

**Every one of the 12 frames the boolean calls unreadable had been scored `legible: 4`
by the Likert, and every one of them has `event: "unclear"` in the same reply.** The
axis was not missing the defect; it had no way to report it. `mean_match` is unchanged
by the instrument swap (3.621 vs iteration 1's 3.606 — inside the judge's own noise),
which is what makes this a change of question and not a change of judge.

The two defects stay orthogonal, and that is the point of keeping them apart: 6 of the
12 unreadable frames score `match >= 3` (`S00202` scores **5**). A frame can carry its
sentence's event and still be undecodable on its own.

The 12: `S00201 S00202 S00204 S00300 S00303 S00304 S00305 S00400 S00707 S00804 S00805
S00900` — rows in `baseline_v2.json`, cross-tab in `instrument_v1_vs_v2.json`.

`MIN_LEGIBLE`/`MIN_LEGIBLE_HOOK` are gone: a boolean *is* its threshold, so "the hook
must be readable" and "every shot must be readable" became one clause.

## 9. The cover contract

`visual_breakdown_step.parse` enforced a bijection — one shot per sentence, no more, no
fewer. The YAML output contract has carried `sentence_end` all along; the parser simply
ignored it. Iteration 2 activates the field that already existed. **No field was added
to `ShotData`/`SceneState`** — `sentence_indices` is already a `list[int]`.

What the parser now enforces (`scenario_chain.visual_breakdown_step.parse`), each
violation raising with the offending indices named so the stage's one corrective retry
can act on it:

1. every sentence `1..N` is covered by at least one shot — a gap names the missing
   indices and is a parse failure, never a warning (subtitles and cuts are derived
   from this cover);
2. `sentence_start <= sentence_end`, both inside `1..N`;
3. ranges never move backwards — shot *n+1* starts and ends no earlier than shot *n*;
4. **at most N shots.** The stated bound. An ordered cover with no ceiling lets one
   scene mint 40 renders; here a split has to be paid for by a merge, so image cost can
   only fall.

A shot spanning several sentences takes the **union** of their cast, deduped by
`card_key`, first occurrence's `position`/`depth` kept — a merge never drops whoever
was in frame. A shot that omits `sentence_end` covers exactly its start sentence, so a
pre-cover reply and every pre-cover checkpoint stay valid.

`shot_timing.plan_shot_clips` already handled many-sentences→one-shot. What broke was
one-sentence→many-shots: identical windows, so the gap loop set the earlier clip's end
to the later's start (duration 0) and `_merge_short_clips` deleted it — a rendered
frame that silently never reached the video. The fix is the **start** and only the
start:

```python
share_n   = how many shots start on this same sentence   # 1 in every pre-cover run
share_idx = how many of them came earlier
start     = w0 + (w1 - w0) * share_idx / share_n         # == w0 when share_n == 1
```

`share_n == 1` reproduces the shipped arithmetic exactly, which is why
`test_plan_shot_clips_pre_cover_checkpoint_is_byte_identical` — pinning `[(0.0, 3.0),
(3.0, 6.0), (6.0, 9.0)]`, the values `test_plan_shot_clips_normal_three_shots` asserted
at `3869f95` — is the real check on this change. An old run still renders.

## Layout — iteration 2 additions

| Path | What it is |
|---|---|
| `run_baseline.py --rescore` | Re-scores the preserved 66 frames with the boolean instrument |
| `baseline_v2.json` | The 66 preserved frames under `readable` (+ sentence-paired rows) |
| `instrument_v1_vs_v2.json` | The Likert↔boolean cross-tab of §8, joined on `shot_id` |
| `run_ab2.py` | PASS B iteration 2 — bijection vs cover, all 9 scenes, paired by sentence |
| `prompt_cover.md` | The cover prompt text this run used, preserved after the repo file was reverted; `run_ab2.py` reads the new leg from it |
| `ab2_context.json` | The entity/scene context built once and given to both legs |
| `ab2_old_shots.json` / `ab2_new_shots.json` | Each leg's raw `visual_breakdown_step` output |
| `ab2_old_scenes.json` / `ab2_new_scenes.json` | Each leg after `build_scenes` — the cover as assembled, with seed + negative per shot |
| `ab2_old/*.png` / `ab2_new/*.png` | The renders (separate dirs from iteration 1's `old/`+`new/`) |
| `ab2_old.json` / `ab2_new.json` | The axis's full report per leg, incl. `sentence_rows` |
| `ab2_result.json` | The rule, its three clauses, the bootstrap CI, the cover shape, the AC3 table |

Re-derive iteration 2 with two commands (ComfyUI up, `~2 h` for the second):

```
uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_baseline.py --rescore
uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_ab2.py
```

Both are resumable: every stage reuses its output file if it already exists, so a
killed run costs only the work in flight. `run_ab2.py` takes the old leg's **parser**
as well as its prompt from `git show 3869f95:` — running the old prompt through the new
permissive parser would measure only half the change.

## 10. PASS B — bijection vs cover, all 9 scenes, paired by sentence

Both legs written by the shipped `visual_breakdown_step` on live DeepSeek and assembled
by the shipped `build_scenes`. The **old** leg takes its prompt *and its parser* from
`git show 3869f95:` — running the old prompt through the new permissive parser would
have measured only half the change. Held identical: narration, `cast_by_sentence`,
scene role/entity context (built once), the per-starting-sentence seed, and the
checkpoint's `negative_prompt`.

### 10.1 What the cover actually did

| scene | sentences | old shots | new shots | merges |
|---:|---:|---:|---:|---:|
| 1 | 7 | 7 | 7 | 0 |
| 2 | 5 | 5 | 4 | 1 |
| 3 | 7 | 7 | 6 | 1 |
| 4 | 4 | 4 | 3 | 1 |
| 5 | 8 | 8 | 8 | 0 |
| 6 | 11 | 11 | 9 | 2 |
| 7 | 9 | 9 | 7 | 2 |
| 8 | 8 | 8 | 6 | 2 |
| 9 | 7 | 7 | 5 | 2 |
| **total** | **66** | **66** | **55** | **11** |

**The old leg reproduces the bijection exactly** (66 shots, one per sentence, 0 merges
in all 9 scenes) — the git-sourced baseline parser behaved as the baseline.

**The cover is real but small and one-sided: 11 merges, 0 splits, −16.7 % renders.**
Not one shot in either leg was inverted, moved backwards, or left a sentence uncovered
— AC2 verified from the emitted `cover_shape` block in `ab2_result.json`, not asserted.

Every merge is an **adjacent pair**, and they cluster at scene openings:

```
scene 2: S00203 [3,4]              scene 7: S00701 [1,2]  S00705 [6,7]
scene 3: S00301 [1,2]              scene 8: S00800 [0,1]  S00804 [5,6]
scene 4: S00401 [1,2]              scene 9: S00902 [2,3]  S00904 [5,6]
scene 6: S00600 [0,1]  S00601 [2,3]
```

Never a 3-sentence span, never a split, and in the two scenes with the most sentences
(5 and 1) no merge at all. That pattern reads as a *positional* habit — "fold one
neighbouring pair near the top, then one in the middle" — rather than the content
judgment the prompt asked for ("merge the sentence that has nothing of its own to
show"). It is the first thing §10.3 has to be read against.

### 10.2 The pre-registered rule, and the result

> **The rule, fixed before the run** (spec AC1): *the paired mean Δ `match` over the 66
> sentences is positive and its bootstrap 95% CI excludes 0; the count of unreadable
> frames does not increase; and the hook shot is `readable` with `match >= 4`.*

| clause | old (bijection) | new (cover) | held |
|---|---:|---:|:--:|
| paired mean Δ `match` > 0, bootstrap 95 % CI excludes 0 | — | **−0.152**, CI **[−0.394, +0.076]**, n=66 | ✗ |
| count of unreadable frames does not increase | 16 of 66 | 15 of 55 | ✓ |
| hook is `readable` with `match >= 4` | `true` / 3 | `true` / 3 | ✗ |

**`won: false`. The prompt was NOT seeded.** `prompts/scenario/visual_breakdown.md` is
byte-identical to `3869f95` again, Langfuse `scenario/visual_breakdown` is still v14,
and `migrate_prompts.txt` is deliberately absent. The cover text this run used is
preserved at `prompt_cover.md`, and `run_ab2.py` reads the new leg from there once the
repo file is back at baseline — so the run stays re-derivable.

**The honest reading is "no effect", not "the cover is worse".** The CI spans zero. Per
sentence: **10 improved, 19 got worse, 37 unchanged**, mean |Δ| 0.61, sd 0.98. Mean
`match` 3.288 → 3.136.

Two clauses need reading carefully rather than at face value:

- **The unreadable clause held on a technicality.** 16 → 15 is a smaller *count*, but the
  cover renders 11 fewer frames: the **rate** goes **24.2 % → 27.3 %**, i.e. slightly
  worse. The clause was pre-registered as a count and is scored as a count, but nobody
  should read it as an improvement.
- **The hook clause failed identically in both legs** (`readable: true`, `match: 3`).
  It is not discriminating between the legs here; it is telling us the opening frame
  fails the hook bar under the bijection *and* under the cover.

### 10.3 AC3 — the falsifiable prediction, and its falsification

The root-cause claim said the four worst baseline rows are sentences with nothing to
render, so an ordered cover would fold them into a neighbour "by construction". That is
a prediction, and it is **wrong**:

| baseline shot | sentence | predicted | what the cover did | old `match` | new `match` |
|---|---|---|---|---:|---:|
| `S00105` | scene 1, sentence 6 | merged or split | **LEFT ALONE** | 4 | 3 |
| `S00303` | scene 3, sentence 4 | merged or split | **LEFT ALONE** | 3 | 3 |
| `S00708` | scene 7, sentence 9 | merged or split | **LEFT ALONE** | 3 | 3 |
| `S00503` | scene 5, sentence 4 | merged or split | **LEFT ALONE** | 4 | 3 |

**0 of 4.** Every one kept its own frame, and two of them scored *lower* than under the
bijection. `S00708` is the sharpest refutation available: its sentence is
"이게 에스씨피 재단입니다", which the cover prompt **quotes verbatim as its first merge
example**, and the model still gave it a dedicated frame.

**And the merges that did happen bought nothing.** Splitting the 66 paired deltas by
whether the sentence ended up inside a merged shot:

| | n | mean Δ `match` |
|---|---:|---:|
| sentences the cover MERGED | 22 | **−0.136** |
| sentences the cover left alone | 44 | **−0.159** |

The two groups are indistinguishable. Merging did not help the merged sentences, so the
null result is not "the cover helped some and hurt others" — the mechanism simply did
not move this score at all.

Per-scene mean Δ, for completeness (`ab2_result.json` → `pairs`):

```
scene 1  −0.429    scene 4  +0.250    scene 7  −0.444
scene 2   0.000    scene 5  +0.625    scene 8  −0.625
scene 3  −0.143    scene 6  −0.455    scene 9  +0.286
```

Scene 5 is the largest positive and it had **0 merges** — its delta is prompt wording
and sampler noise, not the cover.

### 10.4 What this run does and does not establish

**Established.**
- The bijection was a real constraint and removing it works mechanically: the parser,
  `build_scenes`, and `plan_shot_clips` carry an N:M cover, every sentence stayed
  covered in 18 of 18 scene-legs, and image cost fell 16.7 % (66 → 55 renders).
- Given the freedom, the model merges **conservatively and positionally** — 11 adjacent
  pairs, 0 splits, clustered at scene openings — not by the content rule it was given.
- On this axis, that redistribution is worth **nothing measurable**: Δ −0.152, CI
  [−0.394, +0.076].

**Not established, and not to be claimed.**
- *That sentence/shot mapping is not the defect.* This run tested one prompt's ability
  to persuade one model to merge well, not the value of good merging. The cover the
  model produced barely overlaps the cover the root-cause claim imagined — the four
  named sentences were never merged, so **the hypothesis was never actually put to the
  test**. It is untested, not refuted.
- *That the cover is safe to ship.* It is not seeded, and the unreadable *rate* moved
  the wrong way.

**Confounds that survive from iteration 1** and still apply to every `match` number
here: 11/66 baseline rows docked a frame for an absent composited person (the score is
partly measuring card absence), and 28/66 blind captions read a body inside a plate
that should be unpeopled. Sample: one run, one SCP, one judge model, `--reps 1`.

**Provenance notes.** Both legs scored 66/66 and 55/55 with **0 skipped and 0 errored**.
One line of `visual_breakdown_step.parse` was changed *after* this run started — an
explicit YAML `null` for `sentence_end` now reads as "omitted" instead of raising. It
cannot have affected these numbers: **0 of the 121 emitted shots wrote a null
`sentence_end`**, so the branch was never taken. The running process had already
imported the pre-edit module in any case.

## 11. Judgment for Story 13.2 (updated)

- **`match`**: still the recommended axis. It is the only one of the three that has ever
  moved with anything.
- **`readable` (boolean) replaces `legible` (1–5) — now with evidence.** The Likert
  reported 0/66 failures on frames where the boolean reports 12/66, every one of them
  previously scored `legible: 4`. Wire the boolean.
- **Strip the card-absence confound before `match` becomes a gate.** Unchanged from
  iteration 1 and still the largest known threat to this axis.
- **Do not build a cover-quality gate from this run.** What is worth measuring next is
  whether a *good* merge helps, and this run could not answer that because the model
  did not produce good merges. The cheapest next experiment is not another prompt: it is
  a hand-authored cover over one scene, compared against its bijection — if a
  human-chosen merge does not move `match` either, the mapping hypothesis is dead and
  the lever is elsewhere.

## 12. The decisive probe — does merging help *when it actually happens*?

§10.3 showed the mapping hypothesis was never tested: the model merged 11 adjacent pairs
positionally and left all four AC3 sentences alone. So the question "is a *good* merge
worth anything on `match`?" is still open. This section answers it with a hand-authored
cover on scenes 3 and 7 — the two scenes carrying `S00303` and `S00708`.

### 12.1 The selection rule, fixed before any score was read

> **A sentence is a merge candidate if and only if, read on its own, it introduces no new
> renderable visual referent** — it names **none** of: (a) a place or setting, (b) a
> physical object, body part or surface, (c) a physical change, motion or state
> transition. A sentence that only labels what we are already looking at, only reports a
> perception, judgement or interior state, or only qualifies the sentence before it,
> is a candidate.
>
> A candidate merges into the shot of the **immediately preceding** sentence — the frame
> the viewer is already on while those words are spoken. Consecutive candidates join the
> same span. A candidate at position 0 would merge forward instead (none occurred).

This rule was written down, applied to the 16 sentences below, and the resulting merge
list frozen **before** any M1 or M2 call was made and before the control scores for
these sentences were looked up. It is a content rule, not a positional one, and it is
the rule the cover prompt was *asking* the model to apply.

### 12.2 The 16 sentences, and what the rule selects

**Scene 3** (7 sentences):

| # | sentence | renderable referent? | merge |
|---:|---|---|---|
| 0 | 의사가 가면을 숙이며 말합니다. | 가면 (object) + 숙임 (motion) | keep |
| 1 | '이 방에 병이 가득하오.' 창백한 손이 허공을 가리키고 있습니다. | 방 (place), 손 (body part), 가리킴 (motion) | keep |
| 2 | 당신 눈에는 그저 빈 콘크리트 벽. | 콘크리트 벽 (surface) | keep |
| 3 | **보입니까, 그 병이?** | none — a perception question; 병 is a disease, not a renderable object | **→ 2** |
| 4 | 검은 눈구멍이 초점 없이 공중을 스캔합니다. | 눈구멍 (body part) + 스캔 (motion) | keep |
| 5 | **그는 진심으로 보고 있습니다.** | none — interior state | **→ 4** |
| 6 | **당신만 못 볼 뿐, 그 병이 여기 있다는 겁니다.** | none — assertion/restatement; 여기 is deictic | **→ 4** |

Cover: `[0,0] [1,1] [2,3] [4,6]` — **7 shots → 5**.

**Scene 7** (9 sentences):

| # | sentence | renderable referent? | merge |
|---:|---|---|---|
| 0 | 봉합이 끝났습니다. | 봉합 (object) + 끝남 (state change) | keep |
| 1 | 손가락이 움직입니다. | 손가락 (body part) + 움직임 (motion) | keep |
| 2 | 실이 조여드는 소리. | 실 (object) + 조여듦 (physical change) | keep |
| 3 | 몸이 부자연스러운 각도로 일어섭니다. | 몸 (body) + 일어섬 (motion) | keep |
| 4 | 비뚤어진 팔다리, 도드라진 봉합선. | 팔다리, 봉합선 (objects) | keep |
| 5 | 눈이 떠졌지만, 그 안엔 아무것도 없습니다. | 눈 (body part) + 떠짐 (state change) | keep |
| 6 | 에스씨피 공사구가 가면을 기울여 바라봅니다. | 가면 (object) + 기울임 (motion) | keep |
| 7 | **만족스러운 듯이요.** | none — interior state | **→ 6** |
| 8 | **이게 에스씨피 공사구-이입니다.** | none — a naming line | **→ 6** |

Cover: `[0,0] … [5,5] [6,8]` — **9 shots → 7**.

**5 sentences merge in total** (3, 5, 6 of scene 3; 7, 8 of scene 7), and the set contains
both AC3 failures the probe was aimed at: `S00303` = scene 3 sentence 3, `S00708` = scene
7 sentence 8. The rule selects them without being told to.

### 12.3 The two arms

- **M1 (0 renders).** For each span, the control's frame for its *first* sentence is
  re-scored against the **joined** text of the whole span. This asks precisely: *is the
  neighbour's existing frame, now asked to carry both sentences, better than the
  fabricated frame the merged sentence got on its own?* Control = the already-scored
  `ab2_old` leg. No frame is re-rendered.
- **M2 (12 renders).** `visual_breakdown_step` is re-run on both scenes with the cover
  **dictated** — the exact ranges are given as fixed input, so the model authors an
  `image_prompt` *for the merged span* instead of choosing whether to merge. Rendered on
  the same seeds and the same checkpoint negatives as every other leg, then scored.

### 12.4 Result — per sentence, against the `ab2_old` control

Both scenes obeyed the dictated cover exactly (`[(0,0),(1,1),(2,3),(4,6)]` and
`[(0,0)…(5,5),(6,8)]`), so M2 measures a prompt written *for a merged span*, not a
model's willingness to merge. `probe_result.json` carries every row.

| scene | # | control | M1 | ΔM1 | M2 | ΔM2 | |
|---:|---:|---:|---:|---:|---:|---:|---|
| 3 | 0 | 3 | 3 | 0 | 3 | 0 | |
| 3 | 1 | 3 | 3 | 0 | 4 | +1 | |
| 3 | 2 | **5** | 3 | **−2** | 4 | −1 | host of span [2,3] |
| 3 | 3 | 3 | 3 | 0 | 4 | +1 | **MERGED** (`S00303`) |
| 3 | 4 | 3 | 3 | 0 | 3 | 0 | host of span [4,6] |
| 3 | 5 | 3 | 3 | 0 | 3 | 0 | **MERGED** |
| 3 | 6 | 3 | 3 | 0 | 3 | 0 | **MERGED** |
| 7 | 0 | 4 | 4 | 0 | 3 | −1 | |
| 7 | 1 | 1 | 1 | 0 | 3 | **+2** | |
| 7 | 2 | 4 | 4 | 0 | 4 | 0 | |
| 7 | 3 | 3 | 3 | 0 | 3 | 0 | |
| 7 | 4 | 3 | 3 | 0 | 3 | 0 | |
| 7 | 5 | 4 | 4 | 0 | 5 | +1 | |
| 7 | 6 | 3 | 3 | 0 | 3 | 0 | host of span [6,8] |
| 7 | 7 | 3 | 3 | 0 | 3 | 0 | **MERGED** |
| 7 | 8 | 3 | 3 | 0 | 3 | 0 | **MERGED** (`S00708`) |

| arm | merged sentences (n=5) | untouched sentences (n=11) |
|---|---:|---:|
| **M1** (control frames, joined text) | **0.000** (+0 / −0 / =5) | −0.182 |
| **M2** (dictated cover, re-authored, rendered) | **+0.200** (+1 / −0 / =4) | **+0.182** |

**An internal validity check falls out of M1 for free.** The 8 singleton spans feed the
judge an identical frame and identical text to the control, and all 8 reproduced their
control score exactly. The instrument is stable at `temperature: 0`, so a Δ of 0 on the
merged sentences means "no change registered", not "the judge was noisy".

### 12.5 Verdict — merging does not help, even when it actually happens

**M1: exactly zero.** Handing the merged sentence to its neighbour's existing frame
moved **none** of the five, and it **cost the host 2 points** — scene 3 sentence 2 was a
`match: 5` on its own and becomes a 3 once the same frame has to carry sentence 3 as
well. A merge is not free: it trades a frame that fitted one sentence for a frame that
fits two less well.

**M2: a lift that is not a merge effect.** The merged sentences gained +0.200 — and the
untouched sentences of the very same scenes gained **+0.182**. The two are
indistinguishable, so what M2 measured is a **whole-scene re-authoring / re-roll effect**,
not merging. The largest single move in the probe (+2, scene 7 sentence 1) is an
*unmerged* sentence. `S00708` — "이게 에스씨피 공사구-이입니다", the naming line this
entire story treated as the archetypal merge candidate — scored **3 → 3 → 3**: it did not
move in either arm.

**The mapping hypothesis is dead as a `match`-score lever.** Not "untested" any more, as
§10.4 had to say: the merges the hypothesis wanted were performed by hand, obeyed
exactly, rendered, and scored, and they bought nothing. Whatever is wrong with these
frames, giving a contentless sentence to its neighbour does not fix it.

**Limits of this probe, stated plainly.** n=5 merged sentences over 2 scenes and one
judge model at `--reps 1`; +0.200 on n=5 is far inside PASS B's own per-sentence spread
(sd 0.98). This probe can support "no detectable benefit" and it can support "the cost
to the host is real and was measured once (−2)". It cannot support "merging is harmful
in general". And `match` clusters hard at 3 — 11 of 16 M2 rows and 15 of 16 M1 rows are
unchanged — so the axis has limited resolution in exactly the band these sentences live
in; a real but small benefit could hide under it.

**What this leaves.** The cover code stays (it is correct, it cuts renders 16.7 %, and
every sentence stays covered) but it should be justified on **cost and cut rhythm**, not
on semantic match. The remaining candidate levers for findings 2·4·7·9·16 are the ones
this story never touched: the **12/66 unreadable rate** the new boolean exposed (§8), and
the card-absence confound that is polluting `match` itself (11/66). Story 13.2 should
wire `readable` and fix the confound before anyone spends another run on the mapping.

### 12.6 Layout — probe additions

| Path | What it is |
|---|---|
| `run_merge_probe.py` | The probe — M1 (0 renders) and M2 (11 renders), both against the `ab2_old` control |
| `probe_m1.json` | M1: control frames re-scored against the joined spans |
| `probe_m2_shots.json` | M2's `visual_breakdown` output under the dictated cover |
| `probe_m2/*.png` | M2's 11 renders (same seeds, same checkpoint negatives) |
| `probe_m2.json` | M2's axis report |
| `probe_result.json` | Both arms' per-sentence deltas, split by merged/untouched |

```
uv run python _bmad-output/implementation-artifacts/10-4-live-validation/run_merge_probe.py
#   --m1-only  skips the rendered arm (M1 costs no renders at all)
```

The hand cover lives in `run_merge_probe.py` as `HAND_COVER`, with the rule that
produced it in §12.1 and its sentence-by-sentence application in §12.2.
