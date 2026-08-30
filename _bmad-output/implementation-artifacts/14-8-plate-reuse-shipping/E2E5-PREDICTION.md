# E2E iteration 5 — 측정 전 예측 (run `780cb8b3`)

**작성 시각: image 단계 진입 직후, 사이드카 0건.** 이 파일이 커밋된 뒤의 측정만 유효하다.
`git log --diff-filter=A -- <this file>` 와 `report_substitution_firing.py` 실행 시각으로 순서를 확인할 수 있다.

## 입력 (시나리오 체크포인트에서 실측, GPU 0)

| 항목 | 값 |
|---|---|
| 씬 / 샷 | 9 / **41** |
| `location_key` 보유 | **27/41** — 치환 후보의 상한 |
| 요구 키 | containment-chamber 18 · medical-bay 4 · observation-room 2 · control-room 2 · corridor 1 |
| `camera_angle` | wide 10 · medium 10 · close-up 9 · low-angle 5 · high-angle 3 · over-the-shoulder 2 · POV 2 |
| servable (키 보유 ∧ 프레이밍 서빙가능) | **19** — close-up 9 + POV 2 는 설계상 영구 폴백 |
| 그중 cast 보유 | 16 |

## 예측

1. **plate-served = 19 / 41**, generated = 22. 요구 5키가 전부 승인 3장씩을 갖고 D1이 거르는 유일한 플레이트(`entrance-checkpoint/b`)는 요구 키가 아니므로, servable 19가 전부 히트해야 한다.
2. **폴백 사유는 `unservable_framing` 11건**(close-up 9 + POV 2)**이 전부**여야 한다. `no_metadata`·`plate_shows_person`·`no_standing_room`·`unknown_framing`은 **0**을 예측한다.
   - 키 없는 14샷은 그냥 생성으로 가고 경고를 내지 않는다(플래그 분기에 진입하지 않으므로).
3. **은퇴한 축이었다면 8샷을 더 놓쳤다**: high-angle 3 + low-angle 5 는 요구 5키의 승인 플레이트가 전부 EYE라 `no_viewpoint_match`였다. 즉 옛 축 11/19(57.9%) → 새 축 19/19(100%)를 예측한다.
4. **C4′(시점 불일치) = 8/19** 를 예측한다 — 3번의 그 8샷이 눈높이 플레이트를 받는다. 이것이 축 ②가 치르는 대가이고 Jay가 볼 것도 그 8장이다.
5. **프롬프트 층 도달 = 22/41.** 켜기 전 41/41에서 준다.

## 예측이 빗나가면

빗나간 방향 자체가 발견이다. 특히:
- plate-served < 19 → `no_metadata`가 발화했다는 뜻이고, 그건 `label`/`plate_meta` 병합(14.8 H1 패치)이 라이브에서 기대와 다르게 동작한다는 신호다.
- plate-served > 19 → servable 판정이 재생기와 런타임에서 갈렸다는 뜻이다.
- 어느 쪽이든 **기준을 결과에 맞춰 고치지 않는다.** 이 파일은 수정하지 않고, 차이를 report에 적는다.
