# 사전등록 — Story 14.1 승인 플레이트 42장 측정 + 커버리지 기준 (2026-08-25)

이 파일은 **플레이트 이미지를 한 장도 보기 전에** 작성했고 이후 수정하지 않는다.
결과를 보고 기준을 다시 쓰지 않는다 — 14.2 가 사전등록 기준 `재현 ≥6/7` 이 구성상 도달 불가임을
알고도 기준을 고치지 않고 "도달 불가"로 기록한 것과 같은 규율이다
(`gotcha_a-screening-gate-can-fail-on-its-own-threshold` 는 *결과를 보고 기준을 고치지 말라*는
반대 교훈을 함께 준다).

---

## 1. 측정 대상 (표본 밴드)

`location_plates` 에서 `status='approved'` · `style_epoch=2` 인 **42행** = 14 `location_key` × 3 variant(a/b/c).
전부 1920×1080 PNG, `assets/locations/<key>/<variant>.png`, `assets/manifest.json` 에도 42건 전부 `approved`.
2026-08-25 시점 스냅샷이며 `measure_plates.py --dry-run` 이 이 42행을 열거한다(VLM 콜 0).

`assets/locations/control-room/a.depth.png` 는 플레이트가 아니라 8.16 깊이 companion 이므로 대상에서 제외한다
(대상 목록은 파일 glob 이 아니라 **DB 행**에서 만든다).

**수요 측 표본**: run `4b35c0ed` 체크포인트의 43샷 중 `location_key` 보유 **31샷**.
이 표는 플레이트를 보기 전에 산출했다(수요는 플레이트 픽셀의 함수가 아니다):

| location_key | wide | medium | OTS | low-angle | high-angle | close-up | POV | 계 |
|---|---|---|---|---|---|---|---|---|
| containment-chamber | 4 | 2 | 1 | 2 | 0 | 1 | 0 | 10 |
| observation-room | 0 | 2 | 1 | 1 | 2 | 1 | 1 | 8 |
| autopsy-room | 2 | 1 | 0 | 0 | 0 | 2 | 0 | 5 |
| medical-bay | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 5 |
| control-room | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| corridor | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 |
| storage-vault | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| **계** | 7 | 7 | 3 | 3 | 4 | 6 | 1 | **31** |

cast 보유 31샷 중 24샷. `location_key` 미보유 12샷(씬 1 전체 6 · 씬 5 전체 5 · `S00903`)은
플레이트 배정 대상이 아니므로 커버리지 분모 밖이다.

---

## 2. 시점 판정 규칙 (프롬프트 비열람, 이미지 단독)

14.0 §4-4 `PREREGISTRATION-4-4-hypotheses.md` 의 규칙을 **문면 그대로** 재사용한다.
1차 지표는 소실점/지평선(눈높이 선)의 프레임 세로 위치 `y_h` — 0.0=상단, 1.0=하단.
수평 카메라에서 지평선은 정확히 0.5 에 온다(투영기하).

| 판정 | 규칙 |
|------|------|
| `HIGH` (부감) | `y_h < 0.40`, 또는 지평선이 상단 밖(바닥면이 프레임을 채움) |
| `EYE` (눈높이) | `0.40 ≤ y_h ≤ 0.60` |
| `LOW` (앙각) | `y_h > 0.60`, 또는 천장면이 지배적이고 바닥이 거의 없음 |
| `UNREADABLE` | 판독 가능한 지면/원근 단서 없음 (추상·클로즈업 등) |

판독 보조선 `y=0.40`(빨강)·`0.50`(회색)·`0.60`(파랑)을 각 타일에 굽는다.
`marginal=1` 은 `y_h` 가 경계에서 ±0.05 안. 부수 기록 `ceiling_visible`(Y/N),
`floor_share`(0.00–1.00 버킷). CSV 스키마는 14.0 과 동일하되 첫 열만
`shot` → `plate`(= `<location_key>/<variant>`)로 바꾼다.

### 판정 순서(맹검 확보)와 그 한계

- `location_key/variant` **오름차순으로만** 본다.
- 판정 중 `scripts/seed_location_plates.py` 의 `VARIANT_CAMERAS` · `LOCATION_PROMPTS`,
  매니페스트의 `source.label.notes`, 그 밖의 플레이트 생성 프롬프트를 **열람하지 않는다**.
  선언된 카메라가 검정 대상 가설이므로 판정 중에 그것을 아는 것은 측정을 파괴한다.
- **⚠️ 맹검 침해를 사전에 기록한다.** 이 세션의 작업 지시문에 `VARIANT_CAMERAS` 의 선언
  (a=wide-establishing/eye-level, b=corner-three-quarter/low-angle, c=closer-asymmetric/off-axis)이
  **이미 문장으로 들어 있었다**. 판정자는 그 사전확률을 모르는 상태가 아니다.
  따라서 §5 의 선언-대-실측 일치율은 **맹검 하한이 아니라 상한**으로 읽어야 하고,
  일치가 높게 나와도 그것이 ControlNet 기하 제어의 유효성을 확증하지 않는다.
  이 한계는 결과와 무관하게 여기에 먼저 적었고, report.md 에도 그대로 옮긴다.
- 판정은 픽셀에서만 내린다. 위 사전확률과 어긋나는 판정이 나오면 **판정을 고치지 않는다**.

---

## 3. 어포던스 · 그림 속 인물 (VLM 측정)

- **어포던스**: `vision_check.plate_has_standing_room(image_bytes, settings)` 를 **import 해서** 호출한다.
  문구(`STANDING_ROOM_PROMPT`)도 요청 봉투(`image_first=True`)도 복사하지 않는다 —
  14.2 가 봉투가 갈리면 재현이 3/7 ↔ 5/7 로 갈리는 것을 실측했다.
  `None` 은 **"설 자리 없음"이 아니라 "판정 불가"** 다(14.2: 시신·의료·훼손 플레이트는
  이 엔드포인트에서 결정적으로 거부된다). `standing_room` 키가 아예 없는 것으로 기록한다.
- **그림 속 인물**: `scripts/label_location_plates.py` 의 `LABEL_PROMPT` 에 신규 boolean
  `depicts_person`(액자·모니터·포스터·해부도·조각상·마네킹 **안**의 인물)을 추가하고,
  `measure_plates.py` 가 같은 프롬프트로 42장에 대해 1콜씩 낸다.
  기존 `has_person`(방 안의 실제 인물)의 의미는 바꾸지 않는다.
- **결정성**: 두 질문 모두 `temperature=0`. 재산출 불가능한 측정치는 기록하지 않는다.
- **반복 없음**: 플레이트당 질문당 1콜(합 84콜). 14.2 가 같은 엔드포인트에서
  조건 내 뒤집힘 0 을 33플레이트×2~3회로 확인했으므로 반복을 사지 않는다.
  이 선택 자체가 표본 밴드의 일부이며 report.md 에 명시한다.
- **모델**: `qwen-vl-plus`(`Settings().character_vision_model`), DashScope 호환 엔드포인트.
  엔드포인트 뒤의 모델이 바뀌면 재현이 깨질 수 있다(`vision_check` 모듈 docstring 의 기존 경고).

---

## 4. 정합 맵 (판정 전에 고정)

샷의 `camera_angle` → 요구 플레이트 `viewpoint`:

```
wide, medium, over-the-shoulder  -> EYE
low-angle                        -> LOW
high-angle                       -> HIGH
close-up, POV                    -> (없음: 방 플레이트는 물체 클로즈업·천장 POV 를 서빙할 수 없다)
None                             -> (없음: 추측하지 않는다)
```

`UNREADABLE` 플레이트는 어느 셀에도 들어가지 않는다.
`depicts_person=true` 플레이트도 어느 셀에도 들어가지 않는다(승인은 유지, 커버리지 계상에서만 제외).
cast 보유 샷은 추가로 `standing_room=true` 를 요구한다. `standing_room` 미판정(키 부재)은
**충족으로 계상하지 않는다** — 미판정을 clean 으로 세는 것이 13.1 이 없애려는 결함이다.

이 맵의 결과로 **close-up 6샷 + POV 1샷 = 7/31 은 설계상 영구 폴백**이다.
서빙 가능(servable) 분모는 **24샷**이다.

---

## 5. "충분한 세트" 사전 기준 (플래그를 켤 조건 (a))

수요 셀 = 위 표를 정합 맵으로 접은 **(location_key, viewpoint) 10셀**:

| viewpoint | 셀 (샷수 / cast 보유 샷수) |
|---|---|
| EYE | containment-chamber(7/6) · observation-room(3/3) · autopsy-room(3/3) · medical-bay(3/2) · control-room(1/1) |
| LOW | containment-chamber(2/2) · observation-room(1/1) |
| HIGH | observation-room(2/1) · medical-bay(1/1) · corridor(1/0) |

- **C1 (셀 커버리지)** — 위 10셀 전부에 대해, 그 `location_key` 의 승인 플레이트 중
  측정 `viewpoint` 가 일치하고 `depicts_person != true` 인 것이 **≥1장** 있다.
- **C2 (어포던스 커버리지)** — cast 보유 샷이 있는 **9셀**(corridor/HIGH 제외) 각각에 대해,
  C1 을 만족하는 플레이트 중 `standing_room=true` 인 것이 **≥1장** 있다.
- **C3 (서빙률)** — 선택기 오프라인 재생에서 servable 24샷 중 **≥90%(≥22샷)** 가 정합 히트.

**세 조건 전부 충족해야 (a)가 충족된다.** 하나라도 미달이면 플래그는 계속 `False` 이고,
report.md 가 미달 셀을 **(location_key, viewpoint, 필요 장수)** 로 열거한다 —
그 목록이 증설 배치의 렌더 명세다.

(b) Jay 의 E2E iteration 5 시청 판정은 이 기준과 **AND** 이다. C1–C3 가 전부 충족돼도
이 스토리는 플래그를 켜지 않는다.

**미리 기록하는 실패 모드**: 42장 중 HIGH 가 0장이면 C1 은 HIGH 3셀에서 미달이다.
그것은 "기준이 도달 불가"가 아니라 **세트 부족**이며, 기준을 낮추지 않고 부족분으로 보고한다.

---

## 6. 이 스토리가 측정하지 **않는** 것

- **합성 산출물의 픽셀 판정을 0회 한다.** 플레이트를 배경으로 카드가 어떻게 서는지,
  배경 정합이 시청에서 어떻게 보이는지는 **E2E iteration 5** 몫이다.
  그 런 없이 "고쳤다"를 적지 않는다.
- **신규 플레이트를 렌더하지 않는다.** ComfyUI 를 기동하지 않는다.
- **승인을 철회하지 않는다.** `depicts_person=true` 가 나와도 `status` 는 `approved` 로 두고
  사람 판단 대기 목록에만 올린다.
- **릴라이트 캐시 결합**(`composite_harmonization` 이 `(card_variant, location_key)` 로 페어를 잡고
  첫 샷 배경을 쓴다)은 이 스토리가 고치지 않는다 — 샷 단위 선택이 그 결합을 씬 내부로도
  끌어들인다는 사실만 `deferred-work.md` 에 남긴다.
- **`background_has_person` 의 봉투 순서**(`image_first=False`)는 건드리지 않는다(14.2 가 미측정으로 남긴 것).
