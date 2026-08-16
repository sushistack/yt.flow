# Writing-stage prompt ablation — device allocation (A) and prose relaxation (B)

Jay listened to the 12.6 after-run script and reported two defects. This is a
two-arm ablation on the same SCP (SCP-049), against the same production prompts, with
**nothing seeded to Langfuse and nothing changed under `prompts/` or `src/`** — the
substitutions live in `run_ablation.py` and are applied to the compiled prompt text in
memory. It is an experiment; no shipped behaviour changed.

Control is the existing after-run ([`after.md`](./after.md), `after_scenes.json`) and
was not re-run.

## Commands

```
uv run python .../run_ablation.py --arm A --out .../armA_scenes.json
uv run python .../run_ablation.py --arm B --out .../armB_scenes.json

uv run python .../run_after_tts.py --scenes .../armA_scenes.json \
    --out .../armA_durations.json --run-id 12-6-armA          # 그리고 armB 동일

uv run python scripts/measure_script.py --run 12-6-armA \
    --scenes-json .../armA_scenes.json --durations-json .../armA_durations.json \
    --coverage > .../armA.json                                 # control/B 동일

uv run python .../count_devices.py control=after_scenes.json A=armA_scenes.json \
    B=armB_scenes.json > .../devices.json

uv run python .../make_listening_copy.py --scenes armA_scenes.json \
    --durations armA_durations.json --title "…" --out 12-6-armA-narration
```

Real DeepSeek (research/structure) + Gemini (writing/review/critic) + Qwen TTS
(클론 음성 `qwen3-tts-vc-2026-01-22`, `speed=1.2` — the same voice and speed the control
used, printed by each TTS run and recorded in `arm*_durations.json`).

`ablation_control.json` re-measures the control **in this session**, so the source
exhaustion numbers of the three arms come from three calls of the same judge rather
than from a report written a day earlier. The deterministic half is identical to the
committed `after.json`.

## What each arm changed

Both arms replace the same block of `scenario/writing`; arm B adds two more
substitutions. Every substitution asserts its anchor exists before a single LLM call is
spent (`_replace` raises unless the anchor appears exactly once), and the fully rendered
prompt of each arm is committed as `arm{A,B}_prompt_writing.txt` — the receipt that the
arm was not silently identical to control.

### Arm A — device allocation

1. **`### 필수 몰입 기법 (전부 사용)` → `### 몰입 기법 — 이 씬에 배정된 것만 사용`**, whose
   body reads *"아래 배정된 기법만 쓰고, 배정되지 않은 기법은 쓰지 마세요"* and points each
   technique at the scene's own `assigned_devices` field. 감각 묘사 is explicitly left
   free in every scene ("이건 기법이 아니라 질감입니다").
2. **The ending-form rhythm rule.** `- 씬 전체에서 최소 다음 형태를 섞어 쓰세요 … 2. 의문형`
   became *"의문형 — 이 씬에 `dramatic_question`이 배정된 경우에만"*. See the finding below:
   this was a **second, independent** requirement that every scene contain a question,
   and the framing that motivated this ablation named only the first one.
3. **`여전히 전부 필수지만` → `배정된 기법은 여전히 필수지만`** in the fact-grounding
   section, which otherwise contradicts substitution 1 four screens later.
4. One line added to `scenario/writing_scene_repair` (*"배정되지 않은 기법을 수리하면서
   새로 추가하지 마세요"*). The repair pass rewrites flagged scenes through a different
   prompt and it fired in all three runs, so without this the arm leaks at the repair.

**No fact-grounding rule was touched** — `fact_references` obligations, the ban on
asserting outside them, and the 허용되는 각색 three categories are byte-identical to
production in both arms.

### The allocation itself

`_writing_scene_brief` builds its payload as `{**structure[idx], …}`, so the driver
writes `assigned_devices` onto the outline after `structure_step` returns and the field
arrives in the brief with no `src/` change. Every rule reads a field the retention
validator already constrains to a closed vocabulary, so it survives a different
archetype naming its acts differently:

| device | rule | control outline would give | A gave | B gave |
|---|---|---|---|---|
| 극적 질문 | the hook scene + the scene that closes the **last** loop | 1, 8 | 1, 7 | 1, 8 |
| 2인칭 / 상황 가정 | the scenes whose `pattern_interrupt` is `direct_address` | 2, 6 | 7, 8 | 1, 5 |
| 리액션 삽입 | the scenes whose `pattern_interrupt` is `tone_shift` / `pov_shift` | 5, 7 | 3 | 2, 6 |
| 감각 묘사 | unallocated — free in every scene | — | — | — |

The 2인칭 rule is the one worth arguing for: `structure.md:160` already tells Stage 2 to
plan at least one viewer-immersion scene, and `pattern_interrupt: direct_address` is
where it records that decision. The control prompt then asked *every* scene to address
the viewer, overriding the outline's own plan in seven of the eight scenes that were not
chosen for it.

Arm A's outline produced only one `tone_shift`/`pov_shift` scene, so 리액션 was allocated
1 scene there and 2 in B — inside the 1–2 the brief asked for. Arm A's final scene (9)
drew no device at all: the last loop closes in scene 7, so the dramatic question landed
there rather than on the closer. That is the rule behaving as written, and it is a
candidate defect — see the read.

### Arm B — A plus prose relaxation

5. **문장 길이.** `- 문장 길이: 15~25자 (TTS 최적화용 — 짧고 펀치있게)` became:

   > 문장 길이: 기본 15~25자로 짧고 펀치있게. **단, 인과·대조를 나타내는 연결 구문**
   > (때문에 / 그래서 / ~하자 / ~인데도 / ~지만 / ~할수록 / ~기 위해)이 필요한 문장은
   > **40자까지 허용**합니다. 그 논리를 잘라 두 문장으로 나누면 왜 그렇게 됐는지·그런데도
   > 무엇이 이상한지가 사라지고 단언만 남습니다 — 사실을 나열하지 말고 이어 붙이세요.
   > 40자급 문장은 한 씬에 두세 개까지, 나머지는 짧게.

6. **Opening sentence.** A bullet added beside the connective rule:

   > **이 씬의 첫 문장은 앞 씬과의 연결을 세우고 시작하세요.** `previous_scene_context`가
   > 남긴 상태·결과를 한 번 짚은 다음 이 씬의 사실로 들어갑니다 — 맨 사실 문장으로 열지
   > 마세요. (Scene 1 은 예외입니다. 그 자리는 훅이고, 연결할 앞 씬이 없습니다.)

## 1. Device counts — the direct test

Re-derivable: `count_devices.py` (rules documented in its docstring; raw output in
`devices.json`). Per scene, all three arms:

```
2인칭 (당신/여러분 출현 횟수)
  control   1  1  2  1  1  0  0  1        합계 7   씬당 0.88   사용 씬 6/8
  A         0  0  0  0  0  0  1  1  0     합계 2   씬당 0.22   사용 씬 2/9
  B         1  0  0  0  1  0  0  0        합계 2   씬당 0.25   사용 씬 2/8

질문 (물음표 개수)
  control   1  1  1  1  1  1  1  2        합계 9   씬당 1.12   사용 씬 8/8
  A         1  0  0  0  0  0  1  0  0     합계 2   씬당 0.22   사용 씬 2/9
  B         1  0  0  0  0  0  0  1        합계 2   씬당 0.25   사용 씬 2/8

리액션 (나레이터 반응·자극 형용사 어휘 출현 횟수)
  control   3  1  1  0  1  2  0  1        합계 9   씬당 1.12   사용 씬 6/8
  A         1  1  1  0  2  0  1  0  0     합계 6   씬당 0.67   사용 씬 5/9
  B         0  2  1  1  0  2  1  0        합계 7   씬당 0.88   사용 씬 5/8

가정 (가정 표지를 담은 문장 수)
  control   0  1  0  1  0  2  0  1        합계 5   씬당 0.62   사용 씬 4/8
  A         0  0  0  0  0  0  0  0  0     합계 0   씬당 0.00   사용 씬 0/9
  B         1  0  0  0  1  0  0  0        합계 2   씬당 0.25   사용 씬 2/8
```

And the allocation compliance, which is the sharper number:

```
배정 대비 실제 (A)                     배정 대비 실제 (B)
  2인칭  배정 [7, 8]  실제 [7, 8]  일치    2인칭  배정 [1, 5]  실제 [1, 5]  일치
  질문   배정 [1, 7]  실제 [1, 7]  일치    질문   배정 [1, 8]  실제 [1, 8]  일치
  리액션  배정 [3]     실제 [1,2,3,5,7]     리액션  배정 [2, 6]  실제 [2,3,4,6,7]
```

**질문 and 2인칭 landed in exactly the assigned scenes and nowhere else, in both arms —
4 of 4 axis-arms exact.** 씬당 질문 1.12 → 0.22 / 0.25; 씬당 2인칭 0.88 → 0.22 / 0.25.

The 리액션 mismatch is mostly the instrument. Splitting the lexicon by what actually
fired: the **narrator-stance** words (솔직히 / 소름 / 놀랍게) appear **only in assigned
scenes** in both arms — A 씬3 `놀랍게`, B 씬2 `솔직히·소름`, B 씬6 `솔직히·오싹`. Every
unassigned hit is a lurid adjective about the object, not the narrator reacting: A 씬1
`기괴한`, A 씬2 `섬뜩할 정도로`, A 씬5 `끔찍한 대역병`·`섬뜩한 선언`, B 씬3·4 `기괴한`,
B 씬7 `오싹할 정도의 정중함`. Those are 분위기 묘사, which both arms deliberately left
free. Counted that way the narrator-reaction device is 4 scenes in control → 1 in A → 2
in B, again exactly the allocation.

## 2. `measure_script.py` metrics

| metric | control (12-6-after) | A (12-6-armA) | B (12-6-armB) | contract |
|---|---|---|---|---|
| 씬 | 8 | 9 | 8 | 8–12 ✅ |
| 총 어절 | 417 | 432 | **494** | 370–500 ✅ |
| 실측 spread (max/min) | 2.03 | 2.06 | 1.93 | ≥1.6 ✅ |
| 선언 총 `word_budget` | 430 | 470 | 480 | 370–500 ✅ |
| 선언 예산 spread | 1.62 | 2.14 | 1.67 | ≥1.6 ✅ |
| 오프닝 비중 | 16.07 % | 12.27 % | 11.13 % | ≤20 % ✅ |
| 마지막 비중 | 9.35 % | 8.80 % | 13.16 % | ≤20 % ✅ |
| 최대 씬 비중 | 16.07 % | 15.28 % | 16.40 % | ≤30 % ✅ |
| 나레이션 분 | 2.82 | 2.98 | 3.13 | — |
| **WPM** | 148.1 | 144.9 | **158.1** | ≤165 ✅ |
| 원문 소진율 | 11/11 = 100 % | **9/11 = 81.8 %** | 14/14 = 100 % | — |
| 원문 자수 | 739 | 739 | 739 | — |

씬별 어절(비중)[선언 예산 delta]:

```
control  67(16.1)[65 +2] 63(15.1)[55 +8] 63(15.1)[65 -2] 51(12.2)[60 -9] 56(13.4)[55 +1]
         45(10.8)[45 +0] 33(7.9)[40 -7]  39(9.4)[45 -6]
A        53(12.3)[45 +8] 54(12.5)[60 -6] 35(8.1)[35 +0]  66(15.3)[75 -9] 55(12.7)[55 +0]
         37(8.6)[45 -8]  62(14.4)[75 -13] 32(7.4)[35 -3] 38(8.8)[45 -7]
B        55(11.1)[55 +0] 75(15.2)[65 +10] 66(13.4)[75 -9] 81(16.4)[70 +11] 48(9.7)[45 +3]
         62(12.6)[65 -3] 42(8.5)[50 -8]  65(13.2)[55 +10]
```

Arm A's two dropped facts are **중세 역병 의사의 외형** and **일반적으로 협조적이다**. Both
were absent from arm A's own outline: its 12 `fact_references` never mention the plague
doctor look or the entity's cooperativeness (control's 16 do, B's 18 do). So the loss
entered at the **structure** stage, which neither arm modified — not at writing. It is
still a worse script, and it is still an outcome of this run.

## 3. Did the prose actually change? (A vs B)

| | control | A | B |
|---|---|---|---|
| 문장 수 | 52 | 55 | **47** |
| 평균 문장 길이 | 33.1자 | 33.9자 | **42.5자** |
| 평균 어절/문장 | 8.02 | 7.85 | **10.51** |
| 씬별 문장 수 | 8 6 6 9 6 6 6 5 | 5 7 6 9 6 6 7 4 5 | 4 7 5 8 5 6 5 7 |

Arm B is +28 % mean sentence length and +31 % 어절 per sentence on **fewer** sentences
carrying **more** words — the relaxation changed the sentences, not just the
instruction. Arm A is within 2.4 % of control on both, which is what an arm that only
touched the device rules should look like.

The opening-sentence rule shows up too. Arm B's scene openings, in order:

```
2 "단 한 번의 손길로 목숨을 빼앗은 직후, …"      5 "가면 뒤의 기묘한 침묵 속에서, …"
3 "아무런 병도 없다는 이 기이한 존재를, …"       6 "방금 손길 한 번에 목숨을 잃은 … 앞에, …"
4 "이처럼 삼엄하게 접근을 통제하던 이유가 …"     7 "광기 어린 수술을 마친 존재는, …"
                                              8 "그 차가운 손을 피해 셀이 닫힌 뒤, …"
```

Seven of seven non-hook scenes open on the previous scene's state. Arm A manages 3 of 8
(씬2 "조금 전 …", 씬3, 씬7 "아까, …") and the control 0 of 7 — the control's scene 4 opens
"이름은 삭제되었습니다.", scene 5 "차가운 격리 셀 안, 소독약 냄새만 감도는 정적." That is
the reading, not a measurement: no committed script scores it.

## 4. Gates

The retention contract (`_validate_retention_outline`) **passed in all three runs** — it
hard-fails the run on violation, and all three completed. The device allocation adds a
field it does not read, so this is expected rather than reassuring.

| | control | A | B |
|---|---|---|---|
| final pass | 2 (scene-scoped repair) | 2 (scene-scoped repair) | 2 (scene-scoped repair) |
| `review_overall_pass` | true | true | **false** |
| critic verdict | retry | retry | retry |
| gate `categories` | `descriptor_violation`, `report_tone`, `ungrounded_claim` | `descriptor_violation`, `invented_content`, `report_tone`, `ungrounded_claim` | `descriptor_violation`, `pacing`, `ungrounded_claim` |
| critic scene notes | 씬4 `report_tone`, 씬7 `ungrounded_claim` | 씬1·6 `ungrounded_claim`, 씬3·4 `report_tone` | 씬1 `pacing`, 씬3·4 `ungrounded_claim` |

All three end at `unresolved_pass2` with `critic=retry`. **No arm made the critic
happier**, and the critic never once complained that a scene lacked an immersion
technique — criterion 6 of `critic_agent.md` explicitly forbids judging by technique
use, and criterion 4 (Immersion) did not fire against either arm's device-free scenes.
That was the main risk to arm A and it did not materialise in this sample.

## 5. The honest read

**The hypothesis held, and it held cleanly.** A script-wide quota executed once per
scene does become N times the intended density: moving the quota into a per-scene
allocation dropped 질문 from 8/8 scenes to 2, and 2인칭 from 6/8 to 2, with the surviving
instances landing in exactly the scenes the allocation named — 4 of 4 exact matches
across two arms. Nothing else in the chain had to change. Jay's first complaint is the
one this ablation moves, and it moves it a lot.

**The framing was half right about the cause.** The prompt required a question in every
scene in **two** independent places, and the "필수 몰입 기법" quota is only one of them.
The 종결어미 리듬 규칙 tells each scene to mix in 의문형 as one of its required ending
forms, and that rule is scene-scoped by construction — it would have held 질문 at 1.0 per
scene on its own. Arm A neutralised both. **Anyone who ships this change by editing only
the technique block will get a null result and conclude the hypothesis was wrong.**

**Complaint 2 is the one to be careful about.** Arm B did what it was asked: sentences
are 28 % longer, seven of seven non-hook scenes now open by connecting to the previous
scene, source exhaustion stayed at 100 %, and the script grew to 494 어절 without
breaking any measured contract. Whether it is *easier to follow* is Jay's call — the mp3
exists for that — but three things about arm B's output are worse than the control's,
and one of them turns out not to be arm B's doing:

- **Arm B's script asserts things the SCP source does not contain** — 씬3 *"통제가
  이어질수록 개체가 집요하게 요구한 것은 더 많은 수술 도구였습니다"*, 씬4 *"보고서에 기록된
  등급은 유클리드"*, 씬8 *"파일 속엔 수많은 실패와 불완전한 재활성화 기록뿐"* and *"더 많은
  환자를 요구하는 메모"*. The 739-char source names no classification, no archive of failed
  reanimations, and no request for tools or patients. Two of these the critic caught; two
  it did not. **But see the next point before blaming the prose relaxation for any of
  them.**
- **Arm B's `review_overall_pass` went false** (control and A: true), and its critic
  raised `pacing` on the hook for restating the same fact twice in four sentences — a
  plausible cost of longer sentences with more room to repeat.
- **Arm B's WPM rose to 158.1** from 148.1, against a 165 ceiling. Long sentences read
  with fewer pauses, so the same voice at the same 1.2 speed delivers 7 % more 어절 per
  minute. There is not much headroom left on that axis.

**Every ungrounded statement in this ablation was minted by the STRUCTURE stage, which
neither arm touched.** This is the finding that most contradicts the framing, and it
survives tracing each one back to the outline the writer was handed:

| statement | where the writer got it |
|---|---|
| B 씬4 "등급은 유클리드" | B's own `fact_references`: *"SCP-049는 유클리드 등급의 인간형 개체이며…"* |
| B 씬3 "더 많은 수술 도구를 요구" | B 씬3 `event.consequence`: *"…그가 요구하는 것은 더 많은 수술 도구다"* |
| B 씬8 "실패한 재활성화 기록", "더 많은 환자를 요구하는 메모" | B 씬8 `event.what` / `event.consequence`, verbatim |
| B 씬4, A 씬1, A 씬6, control 씬7 "가면이 융합되어 있다" (단언) | each outline's `fact_references` had **already dropped the source's "appears"**: A 씬1 *"그 가면은 피부에 융합되어 있어…"*, control 씬7 *"마스크는 착용된 것이 아니라 융합된 것이며…"* |

The writing prompt tells the writer that `fact_references` **is** the totality of its
facts, and the retention contract tells it to deliver `event.who/what/consequence` and
never to change the consequence. So in every one of these the writer did exactly what it
was instructed to do. The critic then charged it with `ungrounded_claim`, because
`critic_agent.md` judges the narration against the **SCP fact sheet** rather than against
the outline the narration was told to execute — so a structure-stage fabrication is
reported as a writing-stage one, in every arm including the control.

Two consequences. First: **no arm regressed grounding at the writing stage** — arm B is
not shippable as-is, but the reason is upstream of the change under test, and rewriting
the writing prompt will not fix it. Second: the certainty-upgrade defect that `after.md`
attributed to the writer ("확실성을 올리는 것도 지어내는 것입니다") is being committed by
`structure.md`, whose `fact_references` are where the source's hedges are getting lost.
That is the next thing to measure, and it is not a writing-prompt problem.

**Arm A's costs.** Two dropped source facts (traced above to its own outline, not to the
device change), one more `report_tone` note than control, and two things the allocation
itself caused:

- **The closing scene drew no device.** The rule "the second dramatic question goes to
  the scene that closes the last loop" put it in 씬7 of 9, so arm A ends on five plain
  sentences (two of them nominal fragments) and no question. If this ships, the rule
  should be "the hook scene **and the final scene**", with the last-loop-closer as the
  fallback — B's outline happened to close its last loop in scene 8, which is why B does
  not show the same hole.
- **상황 가정 disappeared entirely from arm A** (control 4 scenes → A 0 → B 2). The
  allocation folds 2인칭 and 상황 가정 into one `second_person` device, and arm A's two
  assigned scenes chose plain direct address without a hypothetical. Merging them was a
  guess; if the hypothetical is worth keeping, it needs its own allocation slot rather
  than sharing one.

**Neither arm is the whole fix.** All three runs still end `unresolved_pass2` with the
same *"appears fused → asserted as fact"* violation the control had (control 씬7, A 씬1
and 씬6, B 씬4). That defect is arm-independent and untouched by anything tested here.

## What this cannot answer

- **One run per arm.** Three scripts, three outlines, three sets of dice. The device
  numbers are large enough to survive that (8/8 → 2/9 is not sampling noise, and the
  allocation compliance is exact), but every second-order number here — spread, WPM,
  소진율, the count of `report_tone` notes — is one sample
  (`gotcha_measure-densely-before-declaring-a-fix`).
- **The whole chain was re-rolled, not just writing.** Only the writing prompt differs
  by construction, but research and structure ran fresh for each arm, so the arms have
  different outlines (9 scenes vs 8, different `word_budget`s, different
  `fact_references`, different `pattern_interrupt` placements). Any comparison other
  than the device counts inherits that confound; where a difference traces to the
  outline, it is said so above.
- **소진율's denominator wobbles** (11 / 11 / 14 facts from three calls of the same judge
  on the same 739-char source) — `after.md` records the same instability. Only arm A's
  two *named* dropped facts are load-bearing here.
- **Nobody has listened yet.** The tic is an auditory complaint. The counts say the
  device density fell; only Jay can say whether the scripts sound better.

## Artifacts

| | control | A | B |
|---|---|---|---|
| scenes | `after_scenes.json` | `armA_scenes.json` | `armB_scenes.json` |
| metrics | `ablation_control.json` | `armA.json` | `armB.json` |
| durations | `after_durations.json` | `armA_durations.json` | `armB_durations.json` |
| rendered prompt | — (production, unmodified) | `armA_prompt_writing.txt`, `armA_prompt_writing_scene_repair.txt` | `armB_prompt_*.txt` |
| **mp3** | `12-6-after-narration.mp3` (2:49) | `12-6-armA-narration.mp3` (2:59) | `12-6-armB-narration.mp3` (3:08) |
| 대본 텍스트 | `12-6-after-narration.txt` | `12-6-armA-narration.txt` | `12-6-armB-narration.txt` |

Device counts: `devices.json`. The mp3/txt pairs are gitignored and rebuilt by
`make_listening_copy.py`; the WAVs they concatenate live under `tts_audio/12-6-arm{A,B}/`
(also ignored). See the `.gitignore` header.
