# 10.1b Live Validation — tier 1 vs tier 3 (IC-Light) 프레임 증거

Story 10.1b의 판정 자료. 물음은 하나다: **카드와 배경이 같은 빛을 공유하는가?**

10.1의 평결은 `STILL FLOATING`이었고, 끊긴 고리로 `harmonization`을 지목했다. 발견 11(부유)은
8.16 접지로 닫혔지만 발견 3("인물이 배경에서 오려내 붙인 것처럼 보인다")은 살아남았다 — 카드와
플레이트가 빛을 공유하지 않기 때문이다. 여기 있는 프레임 쌍이 tier 3(IC-Light 배경 조건 재조명)이
그 고리를 잇는지 판정한다.

대상 런은 10.1과 **동일한** `8a9a288b-800f-4c73-88a2-25ae6b5a4d7d`(SCP-049)이고, 슬레이트도
**동일한 6샷·동일 타임스탬프**다. 샷 시드에 run_id가 들어가므로 새 런은 배경도 샷 목록도 달라져
쌍을 이룰 수 없다. video 스테이지만 재실행해 바뀌는 것은 harmonization tier 하나뿐이다.

## 레이아웃

| 경로 | 내용 |
|---|---|
| `off/` | 기능 전부 OFF 상태. 10.1이 18:22에 복사해 둔 **대체 불가** 원본(6 PNG + 6 클립 + `video_off.mp4`) |
| `tier1/` | 10.1의 features-on = **depth 접지 + tier 1 harmonization**. 이 스토리의 **대조군**(6 PNG + `video_on.mp4`) |
| `tier1_clips/` | tier 1 슬레이트 샷 클립 6개. video 재렌더가 워크스페이스 원본을 지우기 전에 빼둔 것 |
| `tier3/` | tier 3 재렌더 프레임. 같은 샷 id·같은 타임스탬프 |
| `pairs/` | `tier1 \| tier3` — **1차 판정 산출물** |
| `pairs_off/` | `off \| tier3` — 10.1의 세 번째 기준점 대비 |
| `probe/` | 라이브 단일 쌍 프로브(SCP-049 × containment-chamber). 마커를 켜기 전 근거 |
| `make_pairs.sh` | `tier3/`·`pairs/`·`pairs_off/`를 다시 만든다. `off/`·`tier1/`은 **절대** 건드리지 않는다 |
| `measure.py` | 카드 영역이 플레이트 색·휘도에 얼마나 근접했는지. 모든 수치가 샘플 밴드·대조 밴드·노이즈 플로어를 달고 출력된다 |

`off/`와 `tier1/`은 재생성 불가다. `video.py:1885`는 씬을 다시 렌더하기 전에 그 씬의
`shots/scene_NNN_*.mp4`를 전부 unlink하고, 세그먼트/최종 concat은 제자리 덮어쓰기다.

## 측정을 읽는 법

tier1과 tier3은 **서로 다른 두 번의 h264 인코드**다. 배경만 있는 영역도 0이 아닌 차이를 낸다 —
그게 노이즈 플로어이고, `measure.py`가 프레임마다 먼저 출력한다. 카드 영역의 차이는 그 플로어를
넘어야만 증거가 된다. 절대 diff만 읽으면 0.87짜리 노이즈와 15.7짜리 신호가 같은 눈금에 올라간다
(10.1이 컨택트 섀도를 이렇게 측정했고, 잘못된 "그림자 없음" 육안 판정을 그렇게 정정했다).

10.1이 물은 것은 "카드가 움직였는가"(기하)였고, 10.1b가 묻는 것은 "카드의 색·휘도가 플레이트
쪽으로 갔는가"(융합)다. 그래서 모든 수치는 **같은 프레임 안의** 카드 밴드와 플레이트 대조 밴드
한 쌍으로 낸다 — 두 밴드는 같은 행(y)을 쓰므로 같은 Ken Burns 크롭과 같은 인코드를 겪는다.

## 알려진 한계

- **재조명 캐시 키는 `(card_key, location_key)`이고 샷이 아니다.** 그래서 그래프는 플레이트 전체를
  카드 캔버스로 센터 크롭해 fbc에 넘긴다 — 카드가 실제로 놓이는 국소 밴드가 아니다. `S00202`에서
  크롭은 L=71.8, 카드가 놓이는 영역은 L=113.4다.
- **`light_position`은 사실상 무효다.** denoise 1.0에서 ComfyUI는 init latent의 내용을 무시한다.
  자세한 근거와 수치는 `data/workflows/README-iclight-relight.md`에 있다.
- 10.1과 마찬가지로 **11.5 2.5D 패럴랙스는 여기서 검증되지 않는다.** 이 런의 image 스테이지는
  depth 리졸버가 꺼진 채 돌아 66샷 중 0샷이 `depth_map_path`를 갖는다.

## 재현

```bash
# off/ 와 tier1/ 은 이미 디스크에 있고 재생성하면 안 된다.
echo 'YTFLOW_COMPOSITE_HARMONIZATION_TIER=3' >> .env     # video.py:2201 이 매 호출마다 Settings() 를 만든다
systemctl --user restart ytflow-api                       # 코드 변경분 반영에 필요(모듈이 이미 임포트돼 있다)
curl -X POST localhost:8000/runs/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d/stages/video/gate \
     -H 'Content-Type: application/json' -d '{"action":"reject"}'   # retry 는 pending 게이트에서 409
./make_pairs.sh
PYTHONPATH=src python3 measure.py
```

`image` 스테이지는 **절대** 재실행하지 않는다 — `_delete_image_artifacts`가 66장을 전부 지우고,
그 순간 이 비교는 재현 불가능해진다.
