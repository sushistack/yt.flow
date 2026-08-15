# Story 12.6 — after measurement (Task 5 / AC8)

One live scenario chain on SCP-049, run **after** the four prompts were seeded to
Langfuse `production` (see [`seeding.md`](./seeding.md)), measured with the same
`scripts/measure_script.py` that produced [`baseline.md`](./baseline.md). AC8's WPM
half needed speech the scenario stage never produces, so the eight narrations were
also synthesized on their own — TTS and nothing else — and the measured seconds fed
back through the same instrument.

## Commands

```
uv run python _bmad-output/implementation-artifacts/12-6-live-validation/run_after.py \
  --out _bmad-output/implementation-artifacts/12-6-live-validation/after_scenes.json

uv run python _bmad-output/implementation-artifacts/12-6-live-validation/run_after_tts.py \
  --scenes _bmad-output/implementation-artifacts/12-6-live-validation/after_scenes.json \
  --out _bmad-output/implementation-artifacts/12-6-live-validation/after_durations.json

uv run python scripts/measure_script.py \
  --run 12-6-after \
  --scenes-json _bmad-output/implementation-artifacts/12-6-live-validation/after_scenes.json \
  --durations-json _bmad-output/implementation-artifacts/12-6-live-validation/after_durations.json \
  --baseline e5ed4b3a --coverage \
  > _bmad-output/implementation-artifacts/12-6-live-validation/after.json
```

Real DeepSeek (`deepseek-v4-flash`) + Gemini (`gemini-3.6-flash`) calls, real Qwen TTS
(클론 음성), real Langfuse prompt fetches, real `_validate_retention_outline`. Raw dumps:
[`after_scenes.json`](./after_scenes.json) (scenes + the structure outline +
`scenario_quality`), [`after_durations.json`](./after_durations.json) (씬별 실측 초 +
사용한 음성), [`after.json`](./after.json) (the measurement). 합성된 WAV 8개는
`tts_audio/` 에 있고 gitignore 된다 — 읽어낸 값은 길이뿐이고 그 길이는
`after_durations.json` 에 있다(`.gitignore` 헤더 참조).

## Result

| metric | after (12-6-after) | baseline `e5ed4b3a` | contract |
|---|---|---|---|
| 씬 | 8 | 9 | 8–12 |
| **총 어절** | **417** | 298 | 370–500 ✅ |
| **분량 spread (실측 max/min)** | **2.03** | 1.54 | ≥ 1.6 ✅ |
| 선언 총 `word_budget` | 430 | 측정 불가 | 370–500 ✅ |
| 선언 `word_budget` spread | 1.62 | 측정 불가 | ≥ 1.6 ✅ |
| 오프닝 비중 | 16.07 % | 10.40 % | ≤ 20 % ✅ |
| 마지막 비중 | 9.35 % | 8.72 % | ≤ 20 % ✅ |
| 최대 씬 비중 | 16.07 % | 13.42 % | ≤ 30 % ✅ |
| 나레이션 분 / **WPM** | 2.82 / **148.1** | 2.01 / 148.2 | ≤ 165 ✅ |
| 원문 소진율 | 10/10 = 100 % | 11/11 = 100 % | — |
| 원문 자수 | 739 | 739 | — |

씬별 어절(비중)[선언 예산 delta]:

```
after     67(16.1%)[65 +2]  63(15.1%)[55 +8]  63(15.1%)[65 -2]  51(12.2%)[60 -9]
          56(13.4%)[55 +1]  45(10.8%)[45 +0]  33(7.9%)[40 -7]   39(9.4%)[45 -6]
baseline  31(10.4%) 35(11.7%) 34(11.4%) 40(13.4%) 39(13.1%) 30(10.1%) 29(9.7%) 34(11.4%)
          26(8.7%)
```

## Readings

**길이 (AC3).** 298 → 417 어절, +40 %, 파생 밴드 370–500 한가운데. 상수는 여전히
`TARGET_DURATION_MINUTES = 3` 이고 한 줄도 손대지 않았다 — 늘어난 것은 목표가 아니라
**목표와 규정 사이의 어긋남이 사라진 결과**다. 8분을 원하면 이제 상수 한 줄이다.

**전개 (AC5).** spread 1.54 → **2.03**. 최대 씬(67어절)이 최소 씬(33어절)의 두 배가 됐고,
오프닝은 16.1 %, 마지막은 9.4 % — `format_guide.md:113` 의 규정이 처음으로 산출물에서
확인된다. 선언 예산 자체의 spread 도 1.62 로 계약을 겨우 넘겼다: 모델은 밴드를 지켰지
넉넉히 지키지 않았다. 실측 spread(2.03)가 선언 spread(1.62)보다 큰 것은 작성자가 작은 씬을
예산보다 더 줄였기 때문이고(씬7 −7, 씬8 −6), 방향은 우리가 원한 쪽이다.

**밀도 (AC4) — 실측했다.** 시나리오 런은 오디오를 만들지 않으므로, 이 여덟 나레이션만
`tts_node` 에 직접 먹여 합성했다(`run_after_tts.py`; 이미지·자막·비디오·그래프 전부 미실행).
**168.93 초 = 2.82 분, 417 어절 → 148.1 WPM.** 상한 165 아래이고, 베이스라인 148.2 와
**0.1 차이**다 — 대본이 40 % 길어지는 동안 말하는 속도는 움직이지 않았다. "길이를 늘리는
방법이 빨리 말하기가 되어서는 안 된다"는 AC4 의 우려는 이제 추정이 아니라 측정으로 닫힌다.
이 문서의 이전 판이 적었던 **2.81분 추정치는 2.82분 실측과 0.01분 차이**였지만, 맞았다는
것과 쟀다는 것은 다른 일이다 — AC8 은 후자를 요구한다.

**같은 목소리인지 먼저 확인했다.** WPM 은 대본이 아니라 음성의 성질이므로 음성이 다르면
비교가 무효다. 베이스라인 `e5ed4b3a` 의 WAV 9개(2026-08-15 19:52 작성, 체크포인트의
`audio_duration` 과 파일 길이가 일치)는 중앙값 F0 110~126 Hz 로, 클론 원본
`data/voices/sutak.mp3`(131 Hz)·과거 A/B 산출물 `workspace/voice-ab/clone.wav`(109 Hz)와
같은 대역이고 스톡 `Cherry`(`workspace/voice-ab/stock.wav`, 247 Hz)와는 두 배 이상
떨어져 있다 — **베이스라인은 클론 음성으로 말했다.** 이번 합성도 스크립트가
`mode=clone model=qwen3-tts-vc-2026-01-22 voice=qwen-tts-vc-sutak-…-dce4 speed=1.2` 를
찍었고(`after_durations.json` 에 기록), 새 WAV 의 F0 는 102~119 Hz 로 같은 목소리다.
주의: 커밋 `f803a0d` 의 메시지는 그 시점까지 "불리언 하나가 false 라 스톡 Cherry 가
출하되고 있었다"고 적었는데, `e5ed4b3a` 의 오디오는 음향적으로 클론이다. 그 서술은 최소한
이 런의 TTS 에는 해당하지 않는다.

**밀도가 같다는 것은 두 단위에서 같다.** WPM 148.1 / 148.2 뿐 아니라 자/초 7.77 / 7.72,
어절당 자수 3.15 / 3.13 — 어절로 재든 음절로 재든 같은 속도다. 즉 늘어난 어절이 짧은
어절이어서 생긴 착시가 아니다.

**씬 단위로는 133.0 ~ 164.3 WPM 으로 흩어진다.** 가장 느린 씬1(133.0)은 무음이 30.21 초 중
8.10 초(26.8 %)로 다른 씬(씬3 14.8 %)보다 많다 — 오프닝을 뜸 들여 읽는다. 가장 빠른
씬3 은 **164.3 으로 상한 165 에 붙어 있다**. 계약이 재는 값은 런 전체의 148.1 이므로
AC8 은 통과지만, 개별 씬은 여유가 없다는 뜻이고 이 축을 더 밀면(더 긴 대본, 같은 목표 시간)
씬 단위에서 먼저 상한을 넘는다.

**소진율 (AC6).** 10/10. (분모는 판정기가 원문을 몇 조각으로 쪼개느냐에 따라 흔들린다 —
이 명령을 세 번 돌린 표본은 after 11 → 9 → 10, baseline 13 → 13 → 11 이고 `baseline.md`
는 12 로 적혀 있다. `baseline.md` 의 계기 주의사항 참조. 위 표와 `after.json` 은 **WPM 을
추가한 마지막 실행**의 값이다. 두 런 다 **버려진 사실 0건**이라는 결론은 어느 표본에서도
같다.) 베이스라인과 마찬가지로 원문 11±2개 사실을 전부 쓴다 — SCP-049 원문(739자)에서 더
캐낼 사실은 없다. 늘어난 119어절은 전부 **깊이**로 갔다: 사실당 어절이 298/11 = 27.1 →
417/10 = **41.7** 로 54 % 늘었다(분모를 어느 표본으로 짝지어도 +50 % 아래로는 내려가지
않는다). baseline.md 가 예측한 바로 그 축이다.

**판정 분리 (AC7) — 라이브에서 확인.** 게이트 페이로드:

```json
"warning": {"code": "unresolved_pass2",
            "categories": ["descriptor_violation", "report_tone", "ungrounded_claim"]}
```

세 범주가 실제로 갈렸다. 크리틱이 씬7의 *"도자기 가면이 살에 그대로 융합되어 있었죠"* 를
`ungrounded_claim` 으로(원문은 "융합된 **것처럼 보인다**"까지만 말한다 — baseline.md 가
지목한 확실성 상향이 그대로 재현·정확히 분류됐다), 씬4의 보고서 나열 톤을 `report_tone`
으로 붙였고, 리뷰의 `descriptor_violation` 이 합류했다. **크리틱은 느슨해지지 않았다** —
같은 엄격도로 계속 `retry` 를 냈고, 달라진 것은 게이트가 그 셋을 구분해 보여준다는 점뿐이다.

**AC2 회귀 확인.** 베이스라인 씬4의 `"재단 공식 기록을 낭독합니다. 대상의 지정 번호,
SCP-049."` 는 재현되지 않았다. 대신 씬4는 여전히 보고서 항목 나열 톤으로 지적받았으므로
(`report_tone`), **금지의 반대말은 아직 완전히 학습되지 않았다** — 한 번의 런으로 닫을 수
있는 항목이 아니고, 이제 최소한 게이트에서 그 사실이 이름을 갖는다.

## 이 측정이 답하지 못하는 것

- **런당 1회 표본** — spread 2.03 은 한 아웃라인의 값이다. 계약이 하한(1.6)을 강제하므로
  하한은 보장되지만, 평균이 어디에 앉는지는 표본 하나로 말할 수 없다
  (`gotcha_measure-densely-before-declaring-a-fix`).
- **WPM 도 대본 하나의 값이다.** 같은 대본을 두 번 합성했고 168.93 s / 169.23 s
  (148.1 / 147.8 WPM) 로 TTS 자체의 재현성은 0.2 % 안이지만, 이건 *이 여덟 문단*을
  이 목소리로 읽은 속도다. 다른 대본이 같은 148 에 앉는다는 뜻은 아니다 — 다만 148 은
  베이스라인(다른 대본, 같은 목소리)과 0.1 차이이므로, 목소리 쪽 상수로 볼 근거는
  표본 둘에서 이미 나온다.
- **파이프라인 배치는 재지 않았다** — 이 오디오는 `tts_node` 만 돌린 것이고, 자막·비디오
  단계가 붙는 실제 런에서 씬 간 간격·크레딧이 최종 영상 길이를 늘린다. WPM(말하기 속도)은
  그 영향을 받지 않지만, 2.82분은 나레이션 길이지 영상 길이가 아니다.
- **절단(트랩 3)** — 이 런에서 `writing_scene_repair` 절단은 발생하지 않았고
  `tts_normalize` 가 씬8에서 문장 수 불일치로 원문을 유지한 경고 1건이 있었다. 예산을
  20–90 에서 22–130 으로 올린 것이 32k 핀에 닿지 않는다는 스펙의 판단은 이 런에서 유지됐다.
