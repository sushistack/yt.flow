# `_DEPTH_PHRASE["near"]` 후보 텍스트 스크리닝 — Story 14.9

작성 시각: 2026-08-30. **GPU 0 · 렌더 0 · 네트워크 0.** 이 문서는 렌더 **이전에** 쓰였고,
어떤 arm의 픽셀도 보지 않은 상태에서 하나를 고른다
(`gotcha_screen-a-prompt-change-before-you-render-it` — 109초가 ~6 GPU-시간을 절약한 전례).

## 0. 고치려는 것

현행(`shot_recompose.py:53`, revision `590db09`):

```
in the foreground close to camera, his whole body from head to feet visible in frame
```

진단은 이미 `config.py`에 기록돼 있다 — *"in the foreground close to camera"* 와
*"whole body from head to feet visible in frame"* 는 16:9에서 **양립 불가**다. 1.9 m 인물이
카메라에 정말 가까우면 전신이 프레임에 들어오지 않는다. 모델은 두 절을 동시에 만족시키려고
**인물을 방의 척도보다 크게** 그린다.

전신 절을 지우는 선택지는 **없다**. 그 절이 없을 때 `near`가 얼굴 클로즈업으로 렌더된 것이
라이브에서 관측돼 있고(`S00403`), 그것이 세 밴드 전부에 "whole body"가 들어간 이유다
(`shot_recompose.py:45-46`). 따라서 손댈 수 있는 것은 **근접 절 쪽**뿐이다.

## 1. 후보

| 후보 | `near` 문구 |
|---|---|
| **A (삭제)** | `in the foreground, his whole body from head to feet visible in frame` |
| **B (상대 심도로 치환)** | `nearer to camera than the rest of the room, his whole body from head to feet visible in frame` |
| **C (척도 앵커 추가)** | `in the foreground at the same scale as the room around him, his whole body from head to feet visible in frame` |

(이 표의 A/B/C는 **후보 이름**이다. 실험의 arm A/B/C와 무관하다 — 혼동을 막기 위해
아래에서는 후보를 `후보A` 처럼 적는다.)

## 2. 스크리닝 — 하드 기준부터

| 기준 | 후보A | 후보B | 후보C |
|---|---|---|---|
| **부정 절을 추가하는가** (Block If, `gotcha_negative-prompt-overstuffing`) | 아니오 | 아니오 | 아니오 |
| **신체를 위치 참조로 되돌리는가** (`gotcha_an-instruction-to-draw-the-trace-brings-the-body-back`) | 아니오 | 아니오 | 아니오 |
| **양립 불가 조건이 남는가** (근접 절 + 전신 절 공존) | **해소** | 약화(상대 비교) | **해소** |
| **배치 지시가 늘어나는가** (Never: "배치 지시를 더 넣어 고치지 않는다") | **−3 단어** | +3 단어 | **+7 단어** |
| `mid`/`far` 를 건드리는가 | 아니오 | 아니오 | 아니오 |

세 후보 모두 하드 Block If(부정 절·신체 복귀)는 통과한다. 갈리는 것은 아래 두 줄이다.

## 3. 채택: **후보A**, 그리고 그 이유

**진단이 "두 절이 싸운다"이므로 최소 개입은 한 절을 지우는 것이고, 지울 절은 근접 쪽이다.**
후보A는 문구에 **아무것도 더하지 않는다** — 이 스토리에서 유일하게 순수 삭제인 후보다.

- **후보B 기각.** `close to camera` 를 `nearer to camera than the rest of the room` 으로
  바꾸면 근접 토큰이 그대로 남는다. 결함이 남았을 때 "치환이 부족했나 / 근접 토큰 자체가
  문제인가"를 구분할 수 없어 **다음 반복의 검정 대상이 흐려진다.** 또 절이 길어져
  4-step Lightning LoRA · cfg 1.0(`comfyui_shot_recompose_qwen_api.json:sampler`)에서 각 절의
  가중이 희석된다.
- **후보C 기각.** `Never: 배치 지시를 더 넣어 고치려 하지 않는다` 에 정면으로 걸린다. 접지 절
  (*"Feet firmly on the ground with a contact shadow"*)과 화풍 절은 **이미 매 패스 전송된다**
  (`shot_recompose.py:77-79`). 척도 앵커를 하나 더 얹는 것은 그 층을 또 두껍게 만드는 것이고,
  같은 층에 지시를 더 넣어 고쳐진 전례가 이 에픽에 없다.

**채택 문구:**

```
in the foreground, his whole body from head to feet visible in frame
```

## 4. 이 선택이 틀릴 수 있는 방향 (사전 기록)

`close to camera` 가 사라지면 `near` 가 `mid`("at mid distance")와 **구분되지 않을** 수 있다 —
즉 결함이 "너무 큰 인물"에서 "심도 밴드가 셋에서 둘로 붕괴"로 바뀌는 것. 그 경우 블라인드 시트에서
`near` 샷의 arm C 타일이 arm B의 `mid` 샷 타일과 척도 면에서 구분되지 않는 형태로 나타난다.
**그 결과가 나오면 다음 후보는 후보C다** — 근접을 되살리지 않고 척도만 앵커하는 형태이기 때문이다.
이 문단은 결과를 본 뒤에 기준을 다시 쓰지 않기 위해 **지금** 적어 둔다.

## 5. 이 문서가 주장하지 않는 것

- 후보A가 결함을 없앤다고 주장하지 않는다. 텍스트 스크리닝은 **후보를 줄인 것**이고,
  판정은 Jay의 블라인드 시청이다.
- 세 후보 중 후보A가 픽셀에서 최선이라고 주장하지 않는다. 후보B·후보C는 렌더되지 않았다.
