# Story 12.6 — baseline measurement (Task 0)

Measured 2026-08-15, before any code or prompt in this story was touched. Both runs
are SCP-049, so the source material is identical and every difference below is the
pipeline's.

## Commands

```
uv run python scripts/measure_script.py \
  --run e5ed4b3a-fabb-46e6-8adb-5c1c0fc68889 \
  --baseline c6be1954-da0f-4dee-ab07-a2b4f3bcf21e \
  --coverage > _bmad-output/implementation-artifacts/12-6-live-validation/baseline.json
```

Raw JSON: [`baseline.json`](./baseline.json). Instrument: `scripts/measure_script.py`.
Source of the scripts: `yt_flow.db` → `checkpoints`, newest row per thread, read-only.

## Result

| metric | `e5ed4b3a` (iteration 3, 2026-08-15) | `c6be1954` (iteration 2, 2026-07-12) |
|---|---|---|
| SCP | SCP-049 | SCP-049 |
| 씬 | 9 | 10 |
| 총 어절 (`narration`) | **298** | **869** |
| 총 어절 (`display_narration`) | 292 | 854 |
| 나레이션 길이 | 2.01 분 | 7.87 분 |
| WPM | **148.2** | **110.4** |
| 분량 spread (max/min 어절) | **1.54** | **1.48** |
| 최대 씬 비중 | 13.42 % | 12.43 % |
| 오프닝 비중 | 10.40 % | 11.05 % |
| 마지막 비중 | 8.72 % | 12.43 % |
| 원문 소진율 (LLM, 1 call) | 12/12 = 100 % | 10/11 = 90.9 % |
| 원문 자수 | 739 | 739 |

씬별 어절(비중):

- `e5ed4b3a`: 31(10.4) 35(11.7) 34(11.4) 40(13.4) 39(13.1) 30(10.1) 29(9.7) 34(11.4) 26(8.7)
- `c6be1954`: 96(11.1) 87(10.0) 87(10.0) 81(9.3) 95(10.9) 88(10.1) 79(9.1) 75(8.6) 73(8.4) 108(12.4)

## What the two measurements answer

**"무엇이 언제 조여졌는가"는 씬 수가 아니라 씬 크기다.** 10씬 → 9씬은 거의 변화가
없고, 씬당 어절이 **87 → 33** 으로 떨어졌다. 이 값은 정확히
`structure.md:114` 의 밴드(`씬당 20~90`, `총합 180~360`)가 강제하는 크기다 —
`c6be1954` 의 씬당 87 어절은 그 밴드 상단에 겨우 걸치고 총합 869 는 밴드를
2.4배 초과한다. 즉 **iteration 2 의 대본은 지금 규정에서는 애초에 통과하지 못한다.**
회귀는 모델의 것이 아니라 규정의 것이다.

**밀도는 문제가 아니다.** 148.2 WPM 은 스토리가 인용한 최고 리텐션 대역(≈145)
안이고 165 상한 아래다. `c6be1954` 의 110.4 WPM 은 오히려 느린 쪽이다. 길이를
늘리는 수단이 "빨리 말하기"가 되면 안 된다는 AC4 의 우려는, 지금 실측 기준으로는
**여유가 있는 축**이다.

**균질성은 두 런 모두의 결함이다.** spread 1.54 / 1.48 — `format_guide.md:113`
의 "오프닝 ~15% / 중심 최대 / 마지막 ~15%" 규정은 어느 런에서도 지켜지지 않았고,
최대 씬조차 전체의 13% 를 넘지 못한다. 12씬 균등 배분이면 8.3% 이므로 두 런 다
사실상 균등 배분이다. **이건 iteration 3 의 회귀가 아니라 한 번도 지켜진 적 없는
규정이다** — 그래서 이 스토리가 검사를 코드로 옮긴다.

**원문 소진율은 이미 상한이다.** SCP-049 원문 739자에서 뽑히는 독립 사실은 12개 안팎이고
`e5ed4b3a` 는 그 전부를 전달했다. 그러므로 **"살을 붙인다"의 여지는 "원문을 더 많이
쓰기"가 아니라 전적으로 "쓴 것을 더 깊게 다루기"에 있다.** 298어절/12사실 = 사실당
24.8어절이고, `c6be1954` 는 869/11 = 79어절이었다. AC6 가 요구한 두 축 중 어느 쪽이
부족한지에 대한 답: **깊이 쪽이다.**

## Notes on the instrument (read before trusting a number)

- **스토리의 "304 어절 / 151 WPM"은 재현되지 않는다 — 실측은 298 / 148.2.**
  체크포인트의 `narration`(TTS가 실제로 읽은 텍스트) 기준이다. 304 는
  `workspace/<run>/scenario/scene_00N.txt` 를 센 값으로 보이며, 그 파일들은
  나레이션 편집 엔드포인트가 쓴 **사람 손 수정본**이지 파이프라인 산출물이 아니다.
  결론(짧다·균질하다·밀도는 정상)은 어느 쪽으로 재도 동일하다.
- **`declared word_budget` 대비 delta 는 두 런 모두 측정 불가다.** 스펙은 이
  항목을 요구하지만 `structure` 아웃라인은 상태에 저장되지 않는다 —
  `SceneState`(`domain/state.py:267`)에 `word_budget` 필드가 없고 체크포인트의
  `channel_values` 에도 `structure` 채널이 없다(두 스레드 전 체크포인트 51/20행
  전수 확인). 스크립트는 이 값을 `null` 로 보고하며 표에 "체크포인트에 없음"을
  찍는다. 0 으로 때우지 않는다.
- **소진율의 분모는 판정기의 분해 입도이지 원문의 성질이 아니다.** 같은 원문·같은
  프롬프트로 두 번 재면 11~13 사이를 오간다(실측: 12/12, 13/13, 10/11). 런 간 비교와
  "버려진 사실이 무엇인가"에는 유효하지만, 절대값은 "원문이 12개 사실로 이루어져
  있다"는 주장이 아니라 "이 프롬프트가 대략 12개로 쪼갠다"는 뜻이다.
- **크리틱의 "두개골에 융합" 지적은 원문 대조상 절반만 맞다.** 원문은 가면이 머리에
  융합된 것처럼 **보인다**고 말하고(소진율 표 4번 항목), 나레이션은 "완전히 융합되어"
  라고 단언했다. 위반은 융합 자체가 아니라 확실성의 상향이다 — 각색 범주를
  선언할 때 이 구분이 정확히 문제의 자리다.
