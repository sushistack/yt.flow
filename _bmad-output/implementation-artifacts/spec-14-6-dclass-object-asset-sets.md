---
title: 'Story 14.6: D급·오브젝트 자산 세트 + 카드 라이브러리 재생성 — 게이트·계약·수요를 먼저 세운다'
type: 'feature'
created: '2026-08-29'
baseline_revision: '1bd0e84'
status: 'done' # draft | ready-for-dev | in-progress | in-review | done | blocked
review_loop_iteration: 1
followup_review_recommended: true
context: []
warnings: [multiple-goals, oversized]
---

<intent-contract>

## Intent

**Problem:** 10.8이 `character-generation` v5를 2026-08-16에 시딩하면서 남긴 **비소급 상태**가 열려 있다 — 라이브러리 52장 카드 중 그날 이전 생성분 전부가 약한 프롬프트 산물이고, run `4b35c0ed`의 `cast_card_fallback` 4건·`special_pose_cap_exceeded` 1건이 그 대가다. 그런데 재생성을 안전하게 실행할 **길이 없다**: `characters.angle_*_path`에 쓰는 것이 곧 출판이고(`gotcha_standing-cards-have-no-approval-gate`), 유일한 승인 게이트(`seed_stock_cast.py --stage` → `approve_stock_cast.py`)는 `_validate_stage_target`이 **STOCK 3키·standing 전용**으로 막아둬서 정작 재생성이 필요한 대상(sitting 세트, `SCP-*` 키)에는 닿지 않는다.

**Approach:** 픽셀을 만들기 전에 **게이트·계약·수요**를 세운다. ① 스테이징 게이트를 임의 키·임의 포즈로 넓히고, ② 스프라이트 계약을 선언(IHDR 색상타입)이 아니라 **실측 알파**로 바꿔 승인 경계에서 강제하며, ③ `report_card_coverage.py`를 확장해 라이브러리 전수를 계약·프롬프트 출처·레지스트리 정합으로 훑고 **관측된 수요**로 재생성 배치를 산정한다. 렌더와 사람 판정은 이 스토리가 하지 않는다.

## Boundaries & Constraints

**Always:**
- **GPU 0.** 이 세션에 NVIDIA 드라이버가 없다(실측: `/dev/nvidia*` 부재, `/proc/driver/nvidia/version` 부재, 커널 모듈 0건, ComfyUI `127.0.0.1:8188` 무응답). 13.3의 "이 머신엔 ComfyUI 없다"가 **거짓 단언이었던 전례**가 있으므로 이 실측 명령과 출력을 리포트에 그대로 남긴다.
- **재생성은 승인 게이트 뒤에서.** 스테이징은 매니페스트 엔트리·카드 행·`angle_*_path` 재지정을 **하나도** 만들지 않는다. 이 불변식이 깨지면 스토리 전체가 무효다.
- **부류를 닫으려면 모집단 전수 대조**(`gotcha_closing-a-class-needs-a-population-sweep`). SCP-1471/682 2키를 고치는 것이 아니라 **모든 카드**를 계약에 통과시킨다.
- **자산 상태 변경은 안전한 방향으로만** — `retire`는 하되 `approve`는 하지 않는다.
- 측정치에는 표본 밴드·재산출 스크립트를 함께 남긴다(`gotcha_a-measurement-without-its-sample-band`).

**Block If:**
- `SCP-1471`/`SCP-682`의 `visual_descriptor`가 비어 있다(실측: 둘 다 길이 0). 사람이 쓴 서술자 없이는 재생성이 불가능하므로 **두 키의 재생성은 배치에서 제외**하고 사유와 함께 인계한다. 이것으로 HALT하지 말 것 — 나머지 7키는 진행 가능하다.
- 매니페스트↔DB 상태 불일치 중 **DB가 `approved`이고 매니페스트가 `retired`인** 행이 나오면 HALT한다(승인 방향의 드리프트는 이 스토리가 임의로 판정할 수 없다). 반대 방향(매니페스트 `approved` / DB `retired`)은 10.8이 이미 판정한 것이므로 진행한다.
- 오브젝트 자산의 **소비 seam을 새로 설계해야 한다면** 만들지 말고 인계한다.

**Never:**
- 카드를 렌더하지 않는다. `--stage`도 실행하지 않는다(GPU가 없어 실행 불가이며, 명령 목록만 리포트에 남긴다).
- `characters.angle_*_path`를 쓰지 않는다. `bump_style_epoch()`를 호출하지 않는다.
- **오브젝트 자산 세트를 만들지 않는다** — `ShotData`에 오브젝트 축이 없고(`cast`/`location_key`가 전부), `AssetService._SUBDIRS`에 오브젝트 종류가 없으며 엔트리에 `kind` 필드 자체가 없다. 소비자 없는 라이브러리는 읽히지 않는 픽셀이다. 측정된 부재와 필요한 seam을 기록하고 에픽에 인계한다.
- `special_pose_max_per_run` 기본값을 바꾸지 않는다 — 런당 GPU 비용을 올리는 제품 판단이고 **날짜 붙은 판정이 없다**(`config.DECISIONS` 행도 추가 금지). 대신 세트를 미리 채우면 캡이 무의미해진다는 것이 이 스토리의 논지다.
- `has_alpha`를 대체하지 않는다 — `video.py:2537`의 런타임 계약이고 하드 실패가 옳다. **추가**한다.
- 디스크의 미등록 파일 21개와 `assets/characters/STOCK-d-class/epoch_3/`(2026-08-16 스테이징 잔류)를 삭제하지 않는다. 보고만 한다.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 스프라이트 계약 통과 | RGBA 832×1216, 투명 비율 0.71 | `alpha_profile` → `{has_alpha_channel: True, transparent_fraction: 0.71, canvas_aspect: 0.684, bbox: …}`, 계약 PASS | 없음 |
| 알파 채널 부재 | RGB 1664×928 (SCP-682 front) | 계약 FAIL `reason=no_alpha_channel`, `transparent_fraction=None` | 예외 아님 — 판정값 반환 |
| 완전 불투명 RGBA | RGBA인데 투명 픽셀 0 | 계약 FAIL `reason=opaque` | 예외 아님 |
| 가로 캔버스 | 캔버스 aspect ≥ 1.0 | 계약 FAIL `reason=landscape_canvas` | 예외 아님 |
| PNG 아님/손상 | 임의 바이트 | `alpha_profile` → `None`, 계약 FAIL `reason=unreadable` | 삼키지 않고 사유로 보고 |
| 스테이징: sitting | `--stage --key SCP-049-2 --pose sitting` | `epoch_{N+1}/sitting_{angle}.png` 4장(기존 규약 그대로) + `_prestage_descriptor.txt`, 매니페스트 0·카드행 0·`angle_*_path` 0 | 4장 미만이면 raise |
| 스테이징: 비-STOCK 키 | `--stage --key SCP-096` | 허용(현재는 거부됨) | 알 수 없는 키 + `--descriptor` 부재는 기존대로 거부 |
| 승인: 계약 위반 스테이징 | 스테이징 파일 중 1장이 RGB | **전 키 승격 거부**, 위반 파일·측정치 출력, 변경 0 | exit 1, 부분 승격 없음 |
| 빈 서술자 생성 시도 | `visual_descriptor == ""` | 생성 스킵 + `character_descriptor_missing` 경고 | 런 실패 아님(AD-10) |
| 레지스트리 불일치 | 매니페스트 `approved` / DB `retired` | 감사 리포트에 divergence 행, 매니페스트 엔트리 `retire` | DB `approved`/매니페스트 `retired`면 HALT |
| 수요 산정 | run `4b35c0ed` 체크포인트 | 요청된 `(card_key,pose,angle,hint,guide)` 튜플 전수 + 미충족분 | 역직렬화 실패는 삼키지 않는다 |

</intent-contract>

## Code Map

- `src/yt_flow/domain/png.py:21` `has_alpha` -- **IHDR 색상타입 + 청크 CRC만** 본다. 완전 불투명 RGBA가 통과하고 RGB는 탈락한다. 모듈 docstring이 *"stdlib-only"*를 선언하므로 신규 함수는 그 계약이 자기에게 적용되지 않음을 명시하고 PIL을 **지연 임포트**한다(`character_image_provider._normalize_subject_scale`와 같은 자세).
- `src/yt_flow/pipeline/nodes/video.py:2528-2542` -- 해결된 카드 경로에 `has_alpha` 하드 검증. **여기서 raise한다** — 따라서 SCP-1471/682는 "그려지는" 것이 아니라 **video 스테이지를 죽인다**. `deferred-work.md:715`의 *"any run whose entity is one of these keys draws them"*는 거짓이고 정정 대상이다(`gotcha_recorded-root-cause-can-be-inverted`).
- `src/yt_flow/services/character_image_provider.py:91-138` `_normalize_subject_scale` -- `:124-126`이 `new_w > width`일 때 **폭에 딱 맞춰** 축소하고 `:135`가 `x=(width-new_w)//2 = 0`에 붙인다. 즉 누운 카드의 alpha bbox `(0, 821, 832, 1208)`은 생성 결함이 아니라 **가로 여백이 0이라 구조적으로 양끝에 닿는 것**이다. `_BOTTOM_GUTTER=8`(`:88`)의 가로 대응물이 없다 — 수정 지점. docstring `:100-105`가 bbox 기반 2인 판정을 **시도했다가 제거한** 기록을 담고 있다(0.359 vs 0.358) — 폭/높이비를 계약에 넣지 말라는 근거.
- `src/yt_flow/services/character_service.py:1029-1032` -- `generate_cards_from_descriptor`의 **출판 지점**(`angle_*_path` + `selected_image_path`). docstring `:963-965`가 스스로 *"repointing them is going live"*라고 적는다.
- `src/yt_flow/services/character_service.py:1084` -- 포즈 가이드가 *"Off by default"*라는 **스테일 docstring**. `config.py:210` `pose_guide_conditioning_enabled: bool = True`(2026-08-14 Jay 승격) 이후 거짓.
- `src/yt_flow/services/character_service.py:1198-1199` -- `generate_special_pose_card`의 `approve_asset` + `save_card`(status 하드코딩 `approved`). hint 카드에는 **스테이징 경로가 아예 없다**.
- `src/yt_flow/services/character_service.py:1247` -- `get_prompt("character-generation")`. v5가 라이브인 이름.
- `src/yt_flow/services/run_service.py:508-520`, `:715-722` -- 5.8 자동 프로비저닝과 파생 엔티티의 무게이트 출판. `:715-722`에 *"an authored look no human has seen goes live"*라는 `ponytail:` 주석이 이미 달려 있다. ⚠️ **`:510`은 `generate_candidates_from_reference`를 직접 부르고 `:517-519`가 `angle_*_path`를 스스로 쓴다** — `generate_cards_from_descriptor`를 지나지 않는다. 빈-서술자 가드가 반드시 덮어야 하는 경로이고, 리뷰 루프 1이 정확히 여기를 놓쳤다.
- `src/yt_flow/services/character_service.py:815-936` `generate_candidates_from_reference` -- 모든 카드 생성이 지나는 **funnel**. `:862` `visual_desc or ""`가 빈 서술자를 그대로 템플릿에 넣는 지점, `:877-879`가 포즈별 파일명 분기, `:918-920`의 `if not stage:`가 매니페스트·승인·카드행을 막는 지점. `generate_cards_from_descriptor`도 `:991-999`로 여기를 부른다 — 가드의 자리.
- `src/yt_flow/services/character_service.py:853` -- `staged_dir = characters/{safe}/epoch_{style_epoch + 1}`. **스테이징 자리 = 다음 라이브 자리**이고 둘을 가르는 것은 승격이 던지는 `bump_style_epoch()`뿐이다. 원자적 승격 설계의 근거.
- `src/yt_flow/services/run_service.py:538-621` `_ensure_special_pose_cards` -- `:586`이 **승인 카드가 있는 hint를 건너뛴다** → 세트를 미리 채우면 캡(`:588-601`, `config.py:195` 기본 3)이 무의미해진다. 이 스토리의 논지.
- `scripts/seed_stock_cast.py` `_validate_stage_target` -- `--stage`를 **standing + `STOCK_CAST_KEYS`**로 제한. 이유는 정책이 아니라 승인기의 `_staged_paths`가 `{angle}_candidate_1.png`만 찾기 때문이다 — 비-standing은 `character_service.py:877-879`에서 `{pose}_{angle}.png`로 저장된다. **제한 해제 지점**(파일명 규약은 건드리지 않고 승인기를 포즈 인지하게 만든다).
- `scripts/approve_stock_cast.py:105-114` -- 전 키 선행 검증(행 존재 / 4장 존재 / `has_alpha`). **스프라이트 계약을 여기 끼운다** — 변이 이전이라 부분 승격이 불가능한 자리다. `:118-125` 고아 검사, `:126-141` 유일한 `angle_*_path` 재지정, `:145` 에폭 범프.
- `scripts/report_card_coverage.py` -- tier A(`angle_*_path`, 상태·에폭 없음) / tier B(`character_cards`) 분리 리포터. 분모가 **9키×2포즈×4앵글=72의 전 어휘**이고 스스로 *"NOT observed demand"*라고 적는다. **확장 지점**(신규 스크립트 금지 — 같은 모집단을 두 번 훑지 않는다).
- `src/yt_flow/services/asset_service.py:130` `approve_asset` / `:143` `retire_asset` / `:76` `record_source` -- 라이프사이클. `approve`의 역함수는 없다.
- `src/yt_flow/domain/state.py:303-325` `ShotData` -- `cast`와 `location_key`가 전부. **오브젝트 축 부재의 근거.**
- `_bmad-output/implementation-artifacts/14-0-angle-conflict/measure_angle_agreement.py` `load_scenes` -- 체크포인트에서 `scenes`를 읽는 선례(thread 접두사 처리 포함). 수요 산정이 재사용한다.
## Tasks & Acceptance

**Execution:**
- [x] `src/yt_flow/domain/png.py` -- `alpha_profile(png_bytes) -> dict | None` 추가. 반환: `has_alpha_channel`·`transparent_fraction`·`opaque_fraction`·`canvas_w/h`·`canvas_aspect`·`alpha_bbox`. **디코드 전 구간을 `try`가 덮는다** — `Image.open`/`load`뿐 아니라 `convert("RGBA")`와 배열화까지. 하나라도 실패하면 `None`이고 docstring의 "never raises"는 그 범위에서만 참이라야 한다. PIL **과 numpy** 둘 다 지연 임포트이고 모듈 docstring이 **둘 다** 명시한다(의존성 계약을 반쪽만 적으면 감사자가 오도된다). RGB에는 알파 통계를 `None`으로 두고 **`0.0`으로 두지 않는다**(미측정과 측정된 0의 구분).
- [x] `src/yt_flow/domain/png.py` -- `sprite_contract(png_bytes) -> tuple[bool, str]` 추가. 사유 어휘 **5종**: `unreadable` / `no_alpha_channel` / `empty_alpha` / `opaque` / `landscape_canvas`. `empty_alpha`(알파 전면 0, `alpha_bbox is None`)를 빼면 백지 카드가 게이트를 통과하고 `_normalize_subject_scale`이 나중에 raise한다. 임계는 **전 모집단 44장에서 유도**하고 상수 위에 날짜·표본·재산출 방법을 주석으로 남긴다 — 실측 밴드는 `transparent_fraction` **0.4377~0.8556**이다. ⚠️ 이 밴드는 앞선 반복이 인용한 front 6장 밴드(0.7055~0.8421)보다 **훨씬 넓고**, 6장 밴드에 맞춰 하한을 잡으면 정상 카드를 떨군다 — 하한은 "완전 불투명"만 잡을 만큼 보수적으로. **폭/높이 bbox 비를 계약에 넣지 마라**(`_normalize_subject_scale` docstring이 2인 0.359 vs 정상 0.358로 이미 반증; 누운 카드가 정당한 광폭이다). 팔레트 PNG의 `tRNS`는 이 파이프라인이 생성하지 않으므로 다루지 않는다 — `# ponytail:` 주석으로 그 천장을 적는다.
- [x] `scripts/approve_stock_cast.py` -- **에폭은 원자적으로 승격된다: 그 에폭에 스테이징된 모든 키·모든 포즈를 한 번에, 그리고 승격은 항상 `bump_style_epoch()`로 닫는다.** 앞선 반복이 "포즈별 고아 검사 + standing만 범프"를 택했고 리뷰가 그 조합에서 **검증된 고위험 3건**을 재현했다: ① standing 승격이 스테이징된 sitting을 라이브 `epoch_N`에 영구 고립시킨다(도구로 도달 불가, `--reject`도 `nothing staged`), ② 범프가 없으니 승격 후 `--reject`가 같은 에폭을 재계산해 **라이브 승인 카드 4장을 삭제하고** `visual_descriptor`를 `None`으로 만들고 exit 0, ③ 재스테이징이 승인된 매니페스트 엔트리 아래의 픽셀을 덮어 `verify_asset`을 깨뜨리고 1회-스냅샷 사이드카 규칙까지 깬다. **범프가 스테이징을 라이브에서 분리하는 유일한 기구**다.
  - ① `_staged_paths(key, pose)`가 서비스의 파일명 분기를 그대로 미러링한다(standing `{angle}_candidate_1.png` / 그 외 `{pose}_{angle}.png`, `character_service.py:877-879`). 규약은 바꾸지 않는다.
  - ② 기본 동작은 **에폭 전체 승격**: `epoch_{style_epoch+1}`에 스테이징된 (키, 포즈) 조합을 전수 발견해 함께 승격한다. `--key`/`--pose`는 좁히는 필터이되, **좁힌 뒤에도 남은 스테이징이 있으면 거부**한다(부분 승격 금지 — 기존 계약). 고아 검사는 사이드카만 남은 실패 스테이징도 잡아야 한다(파일 존재만 보면 놓친다).
  - ③ 선행 검증은 전 변이 이전에, 전 대상에 대해: character 행 존재 / 4장 존재 / **`has_alpha`(형식) `그리고` `sprite_contract`(픽셀) 둘 다**. `has_alpha`를 **떼지 마라** — 잘린 PNG나 CRC 깨진 PNG에서 `sprite_contract`는 `has_alpha`보다 **약하고**, 그런 카드가 승격되면 `video.py`가 런을 죽인다. 스펙의 Never이고 앞선 반복이 위반했다. 위반은 **전량 수집해** 파일별 측정치와 함께 출력하고 어느 키도 승격하지 않는다.
  - ④ standing만 `angle_*_path`와 `selected_image_path`를 재지정한다(비-standing은 tier B `save_card`만). `save_card`가 찍는 `style_epoch`이 **파일이 사는 에폭과 일치**해야 한다 — 범프 순서를 그렇게 잡거나 행을 명시적으로 스탬프하라(불일치하면 가장 새 카드가 off-epoch로 보고된다).
  - ⑤ `_retire_special_pose_cards`는 standing 승격에서만(hint 카드는 standing front에서 파생된다).
  - ⑥ `_reject`: 디렉터리 트리 삭제는 `shutil.rmtree`로 되돌린다(`iterdir()+unlink()`는 하위 디렉터리에서 `IsADirectoryError`). 사이드카가 없으면 **`visual_descriptor`를 건드리지 않는다** — `None`을 "복원"하면 살아 있는 서술자를 지운다. 이미 승격된 대상에는 발화하지 않아야 한다(범프가 그것을 구조적으로 보장하지만, 그 보장에 기대는 이유를 주석으로 남겨라).
- [x] `scripts/seed_stock_cast.py` -- `_validate_stage_target`의 **standing 전용·STOCK 3키 전용 제한을 해제**한다. 서비스 계층은 이미 안전하다: `character_service.py:918-920`의 `if not stage:`가 매니페스트·승인·카드행을 전부 막고 `:1027-1029`가 `angle_*_path`를 standing에만 쓴다. 제한이 있던 진짜 이유는 승인기의 파일명 조회였고 위 태스크가 그것을 닫는다. **삭제가 아니라 재서술**: 원래 docstring이 경고한 *"stranded in a directory that the next epoch bump turns live"*는 실재하는 위험이고, 이제 그것을 막는 것은 **원자적 에폭 승격 + 항상 범프**라는 것을 주석으로 남긴다(경고를 지우면 다음 사람이 같은 조합을 다시 만든다). 알 수 없는 키에 `--descriptor`를 요구하는 거부는 유지. `_prestage_descriptor.txt` 1회 스냅샷 규칙 불변.
- [x] `src/yt_flow/services/character_service.py` -- ① 빈/공백 `visual_descriptor`로는 카드를 생성하지 않는다. **가드는 생산자 전수가 지나는 지점에 둔다** — 앞선 반복은 `generate_cards_from_descriptor`에 달았는데 그 함수는 프로덕션에서 **도달 불가**했고(두 호출부 모두 서술자를 보장한다), 실제 출판 경로인 `run_service.py:510` → `generate_candidates_from_reference` → `run_service.py:517-519`의 `angle_*_path` 쓰기는 **가드 없이 지나갔다**. 즉 SCP-1471/682를 만든 바로 그 경로가 그대로 열려 있었는데 리포트·epics·deferred-work 세 문서가 "이제 거부한다"고 적었다. **착수 전 생산자 전수조사를 하고 그 목록을 리포트에 싣는다**(`gotcha_deleting-a-constant-needs-a-reader-census`의 쌍대: 가드는 독자가 아니라 생산자 전수가 필요하다). raise 금지 — `self._warn("character_descriptor_missing", …)` 후 스킵(AD-10 봉투). ② 공백-only `descriptor` 인자가 저장된 서술자를 **덮어쓰지 못하게** 한다(`"   "`가 키를 영구 오염시켰다). ③ `:1084` docstring의 *"Off by default"* 정정(`config.py:210`이 2026-08-14부터 `True`).
- [x] `src/yt_flow/domain/warnings.py` + `src/yt_flow/domain/state.py` -- `character_descriptor_missing` 코드 + 카탈로그 문안 + `RunWarningCode` 리터럴. **`stage`는 발화 경로 전수조사가 확정한 채널에 맞춘다**(`gotcha_attribution-must-ride-the-channel-that-fires`) — 형제 코드와의 유추가 아니라 실제 호출부. 그 호출부가 `_run_warnings`를 실제로 들고 있는지 확인하라: `CharacterService`를 `warnings=` 없이 만들면 `_warn`은 무발화 no-op이고, 그러면 가드가 있어도 경고는 영원히 0건이다. 문안은 **사유 중립**으로.
- [x] `src/yt_flow/services/character_image_provider.py` -- `_normalize_subject_scale`에 `_SIDE_GUTTER`(`_BOTTOM_GUTTER`와 대칭) 도입. 좁은 캔버스에서 `width - 2*_SIDE_GUTTER <= 0`이면 1×1로 붕괴하지 않도록 폭에 폴백하고, **주석이 실제 동작과 일치**해야 한다(앞선 반복의 주석은 폭 16에서 거짓이었다). **한계 명기**: 이것은 프레이밍을 고칠 뿐 이미 잘린 해부를 복원하지 못한다.
- [x] `scripts/report_card_coverage.py` -- 신규 스크립트를 만들지 말고 확장한다(같은 모집단을 두 리포터가 훑으면 갈라진다 — `deferred-work.md:725-727` 전례). ① **스프라이트 계약 열**: tier A 경로 + `character_cards` 경로 전수, 실패를 사유·측정치와 함께. ② **프롬프트 출처**: `character-generation` v5 라이브(2026-08-16) 기준 3버킷 — `pre-v5` / `same-day`(시딩에 타임스탬프가 없어 귀속 불가, **재생성된 것으로 세지 않는다**) / `post-v5`. ③ **레지스트리 정합**: 방향과 함께 출력하고 **tier A 매니페스트 엔트리도 포함**한다 — `character_cards`만 돌면 52개 중 20개만 보고 나머지 32개(standing)는 사각지대이며, 가장 위험한 형태(매니페스트 `retired`인데 `angle_*_path`가 여전히 출판)가 출력조차 안 된다. 부류를 닫으려면 계약 축과 정합 축 **둘 다** 모집단 전수여야 한다. ④ `--demand <run-id>`: 체크포인트에서 요청된 `(card_key, pose, angle, pose_hint, pose_guide_key)` 전수. 역직렬화 실패는 **re-raise**, 접두사 다중 매치는 거부, DB 부재·테이블 부재는 traceback이 아니라 사유로 보고. **`served` 판정은 계약을 참조한다** — 컬럼이 비어 있지 않은 것만으로 `served: yes`를 찍으면 `SCP-682`가 "served"로 나오고 그것이 정확히 §7이 정정하려는 역전이다(파일 존재 + `sprite_contract` 통과까지 봐야 한다). **경고 대응은 `(shot_id, card_key)`로 키잉**한다 — `shot_id` 단독은 유일하지 않고(이 런에서 8샷이 다중 cast, `S00301`·`S00504` 포함) 한 샷 2건이면 두 행이 같은 경고를 인용하고 두 번째가 사라진다. LLM 콜 0.
- [x] `_bmad-output/implementation-artifacts/14-6-dclass-object-asset-sets/reconcile_manifest.py` -- 신규. 매니페스트 `approved` / DB `retired` 행을 `AssetService.retire_asset`으로 정렬. **`--dry-run` 기본이되 `--commit`과 상호배타로 파서가 거부**한다(앞선 반복은 둘 다 주면 조용히 썼다 — `retire_asset`은 역함수가 없다). **cwd 독립**: `Settings()`의 `db_path`/`assets_path`가 상대 경로라 다른 디렉터리에서 돌리면 빈 DB와 빈 `assets/` 트리를 **만들고** "정렬할 것 없음 / exit 0"이라는 초록 거짓말을 낸다 — 14.5 하니스가 같은 부류로 `os.chdir`를 썼다. 역방향 정의는 **`db approved` ∧ `manifest retired`**만이다(`draft`는 정상적인 add/approve 간극이므로 HALT 사유가 아니다 — 그러면 7행이 영원히 정렬 불가가 된다). 매니페스트 엔트리가 없는 카드 행은 **조용히 건너뛰지 말고 출력**한다. 선언한 종료코드는 실제로 반환되는 것만 적는다.
- [x] `_bmad-output/implementation-artifacts/14-6-dclass-object-asset-sets/report.md` -- 신규. (1) **GPU 부재 실측**(명령 4개 + 출력 원문), (2) 라이브러리 전수 표: 카드×계약×출처×정합, (3) **비소급 상태의 크기**(분모 동반), (4) run `4b35c0ed` 관측 수요와 5건 경고의 귀속 — 3건은 sitting 부재(`asset`), `S00504`는 `asset+pose_hint`이고 **`special_pose_cap_exceeded`와 같은 사건**(캡 3을 `f5a7540b92`·`b0f00082b3`·`fa04528c05`가 소진, `hint:a6f1ed6a29`="collapsed dead"가 밀림), (5) **재생성 배치** — `--stage`/`approve` 명령 목록. ⚠️ **명령을 적기 전에 그 명령이 실제로 통과하는지 드라이런으로 확인하라**: 앞선 반복이 실은 exit 1인 배치를 인계했다(단일 `--key` × 전역 고아 검사 충돌). 디스크에 남은 `STOCK-d-class/epoch_3/` 스테이징 잔류가 **원자적 승격의 첫 차단 대상**이므로 배치의 0단계는 그것의 승격 또는 `--reject`다, (6) **오브젝트 세트: 만들지 않은 이유와 필요한 seam**, (7) SCP-1471/682 정정: 그려지는 것이 아니라 `video.py`가 런을 죽인다, (8) **생산자 전수조사 표** — `angle_*_path`나 카드 파일을 쓰는 모든 경로와 각각이 빈-서술자 가드에 덮이는지, (9) 미주장 — 픽셀 0장, 사람 판정 0건. **리포트는 코드가 실제로 하는 것만 주장한다.**
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- ① `:715`의 *"draws them"* 정정(원문 보존 + 반증 주석 — `video.py`가 `has_alpha`로 raise하므로 나쁜 프레임이 아니라 죽는 런이고, `has_alpha`의 진짜 사각지대는 그 반대인 불투명 RGBA다), ② 신규 등재: 오브젝트 자산 seam 부재 / 미등록 디스크 파일 + `epoch_3` 잔류의 GC 부재 / `SCP-682`를 `data/scps.json`에서 끌어오는 경로와 `SCP-1471` 앵커 큐레이션.
- [x] `tests/domain/test_png.py` + `tests/domain/test_run_warnings.py` + `tests/services/test_character_service_generation.py` + `tests/test_seed_stock_cast.py` + `tests/test_approve_stock_cast.py` (기존) + `tests/test_report_card_coverage.py` (신규) -- I/O 매트릭스 11행 전부, 그리고 **리뷰가 재현한 3건을 회귀로 고정**한다: standing 승격 후 스테이징된 sitting이 고립되지 않는가 / 승격 후 `--reject`가 라이브 카드를 지우지 않는가 / 재스테이징이 승인된 파일을 덮지 않는가. 계약은 **정상 6장에 오탐 0**의 양성 대조군을 포함한다. `_normalize_subject_scale`은 수정 전/후 **양방향** 고정. 변경된 코드 경로를 실제로 지나야 한다 — `seed_stock_cast`의 넓혀진 조합은 `run()`을 통과시켜라(`seed_key`만 부르면 바뀐 배선이 미검증이다). **테스트 격리**: `AssetService`를 만드는 모든 테스트가 `YTFLOW_ASSETS_PATH`를 tmp로 설정한다 — 기본 `./assets`는 개발자의 **실제 라이브러리**이고 앞선 반복의 신규 테스트 하나가 거기에 mkdir했다(`project_test-isolation-workspace-pollution`).
- [x] `_bmad-output/planning-artifacts/epics.md` Story 14.6 + `_bmad-output/implementation-artifacts/sprint-status.yaml` 14-6 행 -- 결과로 갱신. **닫힌 것**(게이트·계약·감사·수요 산정)과 **열린 것**(픽셀·사람 판정·에폭 범프 실행·SCP-1471/682 서술자·오브젝트 seam)을 분리해 적는다. 코드가 하지 않는 것을 적지 않는다.

**Acceptance Criteria:**
- Given 라이브러리의 tier A·tier B 카드 전수, when 확장된 `report_card_coverage.py`를 돌리면, then 모든 카드가 계약 판정을 받고 **SCP-1471·SCP-682의 8장이 `no_alpha_channel`로 실패**하며 정상 카드 오탐은 **0**이다.
- Given 같은 리포트, when 정합 축을 보면, then 대조 모집단이 **`character_cards` 20행이 아니라 카드 매니페스트 엔트리 52개 전부**이고, 방향별 건수가 출력된다.
- Given 잘린 PNG나 CRC가 깨진 PNG가 스테이징돼 있을 때, when `approve_stock_cast.py`를 돌리면, then **승격이 거부된다** — `sprite_contract`가 통과시키더라도 `has_alpha`가 잡는다(두 검사가 함께 선다).
- Given `--stage --key SCP-049-2 --pose sitting`, when 실행하면, then 매니페스트 엔트리 0 · `character_cards` 행 0 · `angle_*_path` 변경 0이다.
- Given 같은 에폭에 standing과 sitting이 함께 스테이징돼 있을 때, when 승격하면, then **둘 다 함께 승격되고** 어느 쪽도 라이브 에폭에 고립되지 않는다. 좁힌 `--key`/`--pose`로 일부만 승격하려 하면 **거부**된다.
- Given 어떤 포즈를 승격한 직후, when 같은 키·같은 포즈로 `--reject`를 돌리면, then **라이브 카드 파일이 삭제되지 않고** `visual_descriptor`가 변경되지 않으며 "스테이징된 것 없음"으로 끝난다.
- Given 어떤 포즈를 승격한 직후, when 같은 키·같은 포즈를 다시 `--stage`하면, then **승인된 매니페스트 엔트리가 가리키는 파일이 덮이지 않는다**(`verify_asset`이 승격 전후로 통과 유지).
- Given 비-standing 승격, when `character_cards` 행을 보면, then 그 행의 `style_epoch`이 **파일이 실제로 사는 에폭과 같다**.
- Given `visual_descriptor`가 비어 있는 캐릭터가 **자동 프로비저닝 경로로** 카드를 만들려 할 때, when 그 경로가 실행되면, then 생성이 스킵되고 `character_descriptor_missing` 경고가 **실제로 발화하며**(`_run_warnings`가 연결돼 있다) `angle_*_path`는 그대로다.
- Given 리포트의 생산자 전수조사 표, when 확인하면, then `angle_*_path` 또는 카드 파일을 쓰는 **모든** 경로가 열거되고 각각이 가드에 덮이는지가 명시되며, 덮이지 않는 경로가 있으면 리포트가 그것을 **덮인다고 주장하지 않는다**.
- Given `hint_475c8a9231_front.png`의 원본 바이트, when 수정된 `_normalize_subject_scale`을 통과시키면, then 결과 alpha bbox의 좌우가 **캔버스 양끝에 닿지 않는다**(수정 전 동일 입력은 닿는다 — 양방향 고정).
- Given `--demand 4b35c0ed`, when 돌리면, then 관측 수요가 72셀 분모와 **분리**되고, 미충족분이 `cast_card_fallback` 4건과 **`(shot_id, card_key)` 단위로** 대응하며, 계약에 실패하는 카드가 `served`로 계상되지 **않는다**.
- Given `reconcile_manifest.py --dry-run --commit`, when 실행하면, then 파서가 **거부**하고 매니페스트는 바이트 불변이다. `--dry-run` 단독은 7행을 열거하고 역방향 0행이며 매니페스트 바이트 불변이다.
- Given 리포트 §5의 재생성 배치, when 각 명령을 드라이런으로 확인하면, then **거부로 끝나는 명령이 없다**(적어둔 순서대로 실행 가능하다).
- Given `git diff --stat`, when 확인하면, then `prompts/` 변경 0이고 `assets/` 변경 0이다.
- Given 이 스토리의 산출물 전체, when 확인하면, then **렌더 0장 · GPU 0 · VLM 콜 0**이고 `bump_style_epoch()` 실행 0회이며 `angle_*_path` 쓰기 0회다(승격 코드는 작성하되 **실행하지 않는다**).

## Spec Change Log

- 2026-08-29 **리뷰 루프 1 — 스테이징이 라이브 에폭 트리를 공유하는데 승격이 그것을 분리하지 않았다(bad_spec 6: high 5 / medium 1).**
  **트리거**: 두 리뷰어가 독립적으로 같은 뿌리에 도달했고, 셋을 **실제로 재현**했다. 원 스펙의 태스크가
  "고아 검사는 같은 포즈 안에서만" + "`bump_style_epoch()`는 standing 승격일 때만"을 **명시적으로
  지시**했는데, `staged_dir`이 `epoch_{style_epoch+1}`이므로 범프가 스테이징을 라이브에서 떼어내는
  **유일한 기구**다. 범프를 빼면 스테이징 자리와 라이브 자리가 같아지고 다음이 성립한다:
  ① standing 승격이 전역 범프를 하는데 고아 검사는 포즈별이라 **스테이징된 sitting이 라이브
  `epoch_N`에 영구 고립**된다(승격도 `--reject`도 `nothing staged`/exit 1) — 삭제된
  `_validate_stage_target` docstring이 *"stranded in a directory that the next epoch bump turns live"*로
  경고한 바로 그 결과다.
  ② 비-standing 승격 후 `--reject`가 같은 에폭을 재계산해 **라이브 승인 카드 4장을 삭제**하고,
  승격이 사이드카를 지웠으므로 `previous is None`을 "복원"해 `visual_descriptor`를 **`None`으로
  덮고**, exit 0을 낸다. 14.6 이전에는 닫는 범프 덕에 같은 명령이 무해한 `nothing staged`였다.
  ③ 승격된 포즈의 재스테이징이 **승인된 매니페스트 엔트리가 가리키는 픽셀을 덮어** `verify_asset`을
  깨고, 1회-스냅샷 사이드카 규칙까지 깬다(승격이 사이드카를 지웠으므로 다음 스테이징이 *이미
  스테이징된* 서술자를 원본으로 착각해 찍는다).
  ④ 그 결과 리포트 §5의 재생성 배치가 **실행 불가**였다(단일 `--key` × 전역 고아 검사 충돌, 양쪽
  리뷰어가 exit 1 확인) — 인계물이 통째로 무효였다.
  **개정**: "에폭은 원자적으로 승격된다 — 그 에폭의 모든 키·모든 포즈를 함께, 그리고 승격은 항상
  범프로 닫는다"로 설계를 바꿨다. 좁힌 `--key`/`--pose`는 남은 스테이징이 있으면 거부한다.
  **두 번째 뿌리(스펙 Never 직접 위반)**: 승인 게이트에서 `has_alpha`를 `sprite_contract`로
  **교체**했다. `sprite_contract`는 손상된 컨테이너(잘린 파일, IEND CRC 깨짐)에서 `has_alpha`보다
  **약하므로**, 그런 카드가 승격되고 `video.py`의 런타임 `has_alpha`가 런을 죽인다. 개정: 두 검사가
  **함께** 선다.
  **세 번째 뿌리**: 빈-서술자 가드를 `generate_cards_from_descriptor`에 달았는데 그 함수는 프로덕션
  도달 불가였고(두 호출부 모두 서술자를 보장), 실제 출판 경로(`run_service.py:510` →
  `generate_candidates_from_reference` → `:517-519`의 `angle_*_path` 쓰기)는 **가드 없이** 지나갔다.
  즉 SCP-1471/682를 만든 경로가 그대로 열린 채, 리포트·`epics.md`·`deferred-work.md` **세 문서가
  "이제 거부한다"고 거짓 주장**했다. 개정: 가드는 생산자 전수가 지나는 지점에 두고, **착수 전
  생산자 전수조사**를 리포트에 싣는다.
  **피한 기지의 나쁜 상태**: 승인 자산 삭제 + 서술자 유실 + 매니페스트 sha 깨짐 + 실행 불가 인계물,
  그리고 반증 스토리가 새 거짓을 세 문서에 심는 것(`gotcha_recorded-root-cause-can-be-inverted`).
  **KEEP — 재도출에서 살아남아야 하는 것**:
  - `domain/png.py`의 `alpha_profile`/`sprite_contract` 형태와 **전 모집단 44장에서 유도한 임계**.
    실측 밴드 `transparent_fraction` **0.4377~0.8556**이고, 스펙이 인용했던 front 6장 밴드
    (0.7055~0.8421)에 맞춰 하한을 잡으면 **정상 카드를 떨군다** — 이 정정은 반드시 살린다.
  - 계약 결과 **8실패(SCP-1471·682 각 4장) / 오탐 0 / 44장 통과**. 재도출이 이 수를 재현해야 한다.
  - `report_card_coverage.py` **확장**(신규 리포터 금지)과 3버킷 출처(`pre-v5` 45 / `same-day` 4 /
    `post-v5` 3, **same-day는 재생성으로 세지 않는다**), 역직렬화 실패 re-raise, 접두사 다중 매치 거부.
  - `--demand` 결과 **41 placements / 9 scenes / unmet 4**가 이 런의 `cast_card_fallback` 4건과 대응.
  - `_SIDE_GUTTER` 수정과 실측 검증: `hint_475c8a9231_front.png` bbox **(0,821,832,1208) →
    (8,828,824,1208)**. "프레이밍을 고칠 뿐 잘린 해부를 복원하지 못한다"는 한계 문장.
  - 정합 실측 정정 **7행**(원 스펙이 4라 적었다 — 항목 4개가 아니라 행 7개)이고 **역방향 0행**.
  - 미등록 디스크 파일은 **24개**(마커 3 포함)이지 21개가 아니다.
  - 비-standing 승격이 `angle_*_path`를 건드리지 않는 분기(옳다).
  - `deferred-work.md:715` 반증(원문 보존 + 정정), GPU 부재 실측 증거 절.

## Review Triage Log

### 2026-08-29 — Review pass 1
- intent_gap: 0
- bad_spec: 6: (high 5, medium 1)
- patch: 0
- defer: 0
- reject: 0
- addressed_findings:
  - `[high]` `[bad_spec]` 포즈별 고아 검사 + standing-전용 범프 조합이 **스테이징된 sitting을 라이브 에폭에 영구 고립**시킨다(재현) → 설계를 "에폭 원자 승격 + 항상 범프"로 개정
  - `[high]` `[bad_spec]` 비-standing 승격 후 `--reject`가 **라이브 승인 카드 4장을 삭제**하고 `visual_descriptor`를 `None`으로 덮고 exit 0(재현) → 같은 개정 + 사이드카 부재 시 서술자 불변 규칙 추가
  - `[high]` `[bad_spec]` 승격된 포즈 재스테이징이 **승인된 자산의 픽셀을 덮어** `verify_asset`과 1회-스냅샷 규칙을 깬다 → 같은 개정
  - `[high]` `[bad_spec]` 승인 게이트가 `has_alpha`를 `sprite_contract`로 **교체**(스펙 Never 직접 위반) — 손상 컨테이너에서 계약이 더 약해 잘린 PNG가 승격되고 `video.py`가 런을 죽인다 → 두 검사 병립을 태스크·AC로 명시
  - `[high]` `[bad_spec]` 빈-서술자 가드가 **프로덕션 도달 불가한 함수**에 붙었고 리포트·epics·deferred-work 3문서가 "거부한다"고 **거짓 주장** → 가드를 생산자 funnel로 옮기고 **생산자 전수조사**를 태스크·AC로 승격
  - `[medium]` `[bad_spec]` 위 조합의 귀결로 리포트 §5 **재생성 배치가 실행 불가**(exit 1) → 배치 명령을 적기 전 드라이런 확인을 태스크로, "거부로 끝나는 명령 0"을 AC로 추가
  - (하위 patch/defer 후보 다수 — `--demand`의 `served` 판정이 계약 미참조, 경고 대응이 `shot_id` 단독 키잉, 정합 축이 tier A 32엔트리 사각, `reconcile_manifest`의 `--dry-run --commit` 동시 허용·cwd 의존·`draft` 오HALT, `empty_alpha` 미검출, 공백 서술자 덮어쓰기, 테스트가 실제 `assets/` 사용, `shutil.rmtree` 회귀, docstring의 numpy 누락·"never raises" 과대주장 — 전부 개정된 태스크·AC에 흡수했다. bad_spec 루프백이므로 개별 patch로 계상하지 않는다.)

### 2026-08-29 — Review pass 2
- intent_gap: 0
- bad_spec: 0
- patch: 21: (high 4, medium 11, low 6)
- defer: 3
- reject: 0
- addressed_findings:
  - **루프 1의 high 5건 전부 닫힘 확인** — Blind Hunter가 생산자 전수를 독립 재도출해 리포트 §8과 일치를 확인했고(`angle_*_path` 기록자 5 · 카드 파일 기록자 2), `has_alpha`/`sprite_contract` 병립은 손상 컨테이너에서의 비대칭을 **실행 가능한 주장으로 고정한 테스트**로 확인됐다.
  - `[high]` `[patch]` **크래시한 스테이징이 에폭 전체를 잠근다** — 블로커가 `--reject`까지 막아 복구 수단이 `assets/` 안 `rm -rf`가 됐다(ComfyUI 크래시는 Story 5.23의 알려진 모드이고, 그 시점 라이브 서술자는 이미 스테이징 텍스트로 바뀌어 있다). `--reject`를 블로커 게이트 **앞으로** 옮기고 좁힌 reject를 허용. 회귀 3건 고정.
  - `[high]` `[patch]` **리포트 §5의 step-0 `--reject`가 라이브 서술자를 되돌린다** — 실측 라이브 701자 vs 사이드카 1600바이트, 380자에서 분기. 스테이징 이후 편집된 서술자는 복원하지 않는 가드 + `_poststage_descriptor.txt` 기록(크래시에도 남도록 `finally`) 추가, 리포트 정정. ⚠️ 구현 에이전트가 리뷰어의 "13일 롤백" 프레이밍을 **반증**했다 — `characters.updated_at`이 그 스테이징의 front 렌더보다 **1.7초 뒤**이므로 사이드카 복원은 그 스테이징의 의도된 되돌림이다. 가드는 유지하되 근거를 실측으로 교체했다.
  - `[high]` `[patch]` **리포트 §5의 다른 step-0가 현재 서빙 중인 hint 카드를 은퇴시킨다** — standing 승격이 `_retire_special_pose_cards`를 부르고, `STOCK-d-class`의 승인 hint 3장 중 2장을 `--demand`가 `served yes`로 찍는다(S00103·S00104). 코드는 설계대로 두고 부작용을 표로 명시했으며, 그것이 §4의 캡 논지를 **hint 축에서 뒤집는다**는 것까지 적었다.
  - `[high]` `[patch]` **"44장 중 14장" 반사실이 틀렸다 — 실제 18장**이고 그중 4장이 standing이다(0.4377~0.7051). 리포터가 매 실행 이 반사실과 18행을 출력하게 해서 재산출 경로 없는 수치를 없앴다. `report.md`·`epics.md`·`png.py`·테스트 전부 정정.
  - `[medium]` `[patch]` 승격 루프 중간 예외가 닫는 범프를 건너뛰어 docstring 자신의 실패모드 3을 만든다 → `try/finally` + `PARTIAL PROMOTION: n/m` 출력.
  - `[medium]` `[patch]` 빈-서술자 가드보다 `chars_dir.mkdir`이 먼저 돌아 빈 에폭 디렉터리가 승인기를 잠근다 → 가드 아래로 이동.
  - `[medium]` `[patch]` 테스트 10건이 들여쓰기로 신규 클래스에 조용히 재부모됐다 → 원 클래스로 복원.
  - `[medium]` `[patch]` `assert a, b == c`가 assert-with-message로 파싱돼 아무것도 고정하지 않았다 → 정정 + 동일 형태 전수 확인.
  - `[medium]` `[patch]` 재스테이징 회귀 테스트가 `--stage`를 돌리지 않고 `N+1 != N`만 재진술 → `seed.run()` 구동.
  - `[medium]` `[patch]` `run_service.py`의 ponytail 이연 사유가 **이 스토리가 없앤 장애물**을 인용 → 사유 정정(이연 자체는 다른 근거로 유지), `deferred-work.md` 기재.
  - `[medium]` `[patch]` 포즈 가이드 승격 귀속이 docstring `13.1` vs `DECISIONS` `10.5`로 갈렸다 → `git log -S`로 `24b2932`(2026-08-14) 확인, `10.5`가 옳고 docstring이 틀렸다.
  - `[medium]` `[patch]` `reconcile_manifest.py`가 원본 `scp_id`로 키를 만들어 정규화 필요 키에서 **역방향 HALT를 건너뛴다** → `_sanitize_scp_id`.
  - `[medium]` `[patch]` `created_at` 없는 엔트리가 빈 문자열 비교로 `pre-v5`에 조용히 합산(헤드라인 45를 부풀린다) → `unknown` 버킷 출력.
  - `[medium]` `[patch]` 정합 축에 `manifest draft / db approved` 버킷 부재 → catch-all 추가.
  - `[medium]` `[patch]` §8-4가 `_ensure_character_reference` 역전을 축소 서술(행 삭제 + `reference_images` 캐스케이드 → 매 런 DDG 재검색) → 정정. 구현 에이전트가 14.4 자격증명 프레이밍도 정정했다(그 플레이스홀더는 주석 처리됐으므로 노출은 그 이전에 복사된 `.env`뿐이다).
  - `[medium]` `[patch]` `dryrun_batch.py`가 "라이브 형태를 모사"한다고 주장하나 승인 엔트리 덮어쓰기·은퇴 행 부활을 재현하지 못한다 → 주장 철회 + 갭 이연.
  - `[medium]` `[patch]` 인계용 스크립트 2개가 리포트가 인용한 ruff 범위 밖 → 범위에 포함(0 findings).
  - `[low]` `[patch]` `opaque` 사유 문구가 0.02 하한과 불일치 / 정사각 캔버스가 `landscape_canvas`로 오판(`> 1.0`으로) / 폭 17~24에서 스프라이트가 sliver로 붕괴 / `_served`가 `_normalize_pose`를 건너뜀 / 빈 `characters` 표에서 `--demand` 무시 / 도달 불가 분기 삭제.

## Design Notes

**왜 계약이 `has_alpha`로 부족한가 — 그리고 왜 `has_alpha`를 떼면 안 되는가.** `has_alpha`는 IHDR 색상타입과 청크 CRC를 읽는 **형식 검사**다(`png.py:21`, 의도적 stdlib-only). 그 사각지대는 **완전 불투명 RGBA**이고, 빈 서술자로 생성된 카드가 라이브러리에 들어온 경로가 그것이다. 반대로 SCP-1471/682는 RGB라 `has_alpha`가 False를 주고 `video.py:2537`이 raise한다 — 이 8장은 조용히 그려지는 것이 아니라 그 키가 캐스팅되는 순간 **런을 죽인다**. 새 계약은 픽셀을 보므로 불투명 RGBA를 잡지만, **컨테이너 손상은 못 본다**(PIL이 열어버리면 통과한다). 두 검사의 사각지대가 서로 다르므로 게이트에는 **둘 다** 선다. 하나로 합치려는 시도가 리뷰 루프 1에서 정확히 이 구멍을 만들었다.

**왜 에폭을 원자적으로 승격하는가.** `staged_dir`은 `epoch_{style_epoch + 1}`이다. 즉 **스테이징 자리와 다음 라이브 자리는 같은 디렉터리**이고, 둘을 갈라놓는 것은 오직 승격이 마지막에 던지는 `bump_style_epoch()`뿐이다. 범프는 "이 에폭은 이제 라이브이고 다음 스테이징은 다른 곳"이라고 선언하는 **경계 자체**다. 그래서 어떤 포즈는 범프하고 어떤 포즈는 안 하는 설계는 성립하지 않는다 — 범프하지 않은 승격은 자기가 방금 출판한 파일을 다음 스테이징의 과녁으로 남긴다. `bump`가 라이브러리 전체를 리포트상 off-epoch로 만든다는 반론은 **리포트 라인이지 게이트가 아니고**, 오늘 이미 6장이 off-epoch다. 대안(에폭 트리 밖 스테이징 영역, 키별 에폭)은 매니페스트 108엔트리의 경로 규약을 건드리므로 이 스토리보다 크다 — `deferred-work.md`로 인계한다.

**왜 가드는 생산자 전수조사를 요구하는가.** 이 리포지토리는 *"플래그가 argv에 있다고 기능이 켜진 게 아니다"*와 *"결정을 `.env`에만 넣으면 출하 안 된다"*를 이미 두 번 배웠다. 리뷰 루프 1은 그 세 번째 형태였다: **가드가 코드에 있다고 경로가 막힌 게 아니다.** `angle_*_path`를 쓰는 생산자는 최소 넷이다(`generate_cards_from_descriptor`의 출판 절, `select_candidate`, 5.8 자동 프로비저닝, 파생 엔티티) — 그중 하나에만 가드를 달고 세 문서에 "닫혔다"고 적으면 거짓 원인이 세 곳에서 재인용된다. 전수 목록이 리포트에 실려야 다음 사람이 같은 실수를 안 한다.

**왜 새 스크립트가 아니라 `report_card_coverage.py` 확장인가.** 같은 모집단을 두 스크립트가 훑으면 둘이 갈라진다 — `Settings.style_epoch`와 매니페스트 에폭이 같은 이름으로 갈라져 새 스크립트를 오도한 전례가 정확히 있다(`deferred-work.md:725-727`). 리포터는 하나다. 같은 이유로 정합 축도 `character_cards` 20행이 아니라 **카드 매니페스트 52엔트리 전부**를 봐야 한다 — 계약 축만 모집단 전수이고 정합 축은 아니면 "부류를 닫았다"가 반쪽이다.

**왜 캡을 안 올리는가.** `_ensure_special_pose_cards`(`run_service.py:586`)는 **승인 카드가 있는 hint를 건너뛴다**. D급 세트를 미리 채우면 그 hint들은 캡 계산에 들어오지도 않는다. 캡을 올리는 것은 런당 GPU를 더 쓰는 것이고, 세트를 채우는 것은 한 번 쓰는 것이다 — Jay의 ③ *"미리 만들어두는게 좋을 것 같음"*이 후자다. 캡은 세트가 채워진 뒤에 다시 재는 것이 옳고, 그때가 날짜 붙은 판정을 적을 자리다.

**오브젝트 세트를 만들지 않는 근거.** `ShotData`(`state.py:303-325`)의 엔티티 축은 `cast`(사람)와 `location_key`(방) 둘뿐이다. 오브젝트는 오직 `image_prompt` 자유텍스트로만 픽셀에 닿는다. `AssetService._SUBDIRS`에도 오브젝트 종류가 없고 엔트리에 `kind` 필드 자체가 없어(종류는 `card_key`/`location_key`/`guide_key` 중 무엇이 있는지로 **추론**된다) 네 번째 종류에는 리졸버 seam이 없다. 지금 라이브러리를 만들면 아무 코드도 그것을 요청할 수 없다. 필요한 선행은 ① `ShotData`의 오브젝트 축, ② 시나리오 프롬프트가 그 축을 발행하는 것, ③ `AssetService`의 실제 `kind` 필드 — 셋 다 이 스토리보다 크고, ②는 14.5가 기각으로 끝낸 그 프롬프트 층이다.

**게이트를 좁히고 있던 것은 정책이 아니라 파일명 조회 한 줄이었다.** 서비스 계층은 이미 임의 키·임의 포즈에서 안전하게 스테이징한다 — `character_service.py:918-920`의 `if not stage:`가 매니페스트·승인·카드행을 모두 막고, `:1027-1029`는 애초에 standing에서만 `angle_*_path`를 쓴다. `_validate_stage_target`이 sitting과 비-STOCK 키를 거부하는 이유는 **승인기의 `_staged_paths`가 `{angle}_candidate_1.png`만 찾기 때문**이고, 비-standing은 `{pose}_{angle}.png`로 저장된다(`character_service.py:877-879`). **규약을 통일하는 유혹은 거부한다** — 기존 epoch 디렉터리와 매니페스트 108엔트리의 경로가 통째로 마이그레이션 대상이 되고, 이미 미등록 파일 24개가 떠다니는 상태에서 그것은 새 드리프트를 만든다. 승인기가 같은 분기를 쓰게 하는 것이 맞다. 다만 그 docstring이 경고한 **고립 위험은 실재**하므로(리뷰 루프 1이 재현했다) 지우지 말고, 이제 그것을 막는 것이 원자적 승격 + 항상 범프라고 재서술한다.

## Verification

**Commands:**
- `uv run pytest tests/domain/ tests/services/test_character_service_generation.py tests/test_seed_stock_cast.py tests/test_approve_stock_cast.py tests/test_report_card_coverage.py -q` -- expected: 신규 포함 전량 통과
- `uv run pytest -q` -- expected: `tests/test_render_pose_guides.py`의 PNG SHA 핀 1건만 실패(14.1/14.5가 stash 후에도 동일 실패임을 기록한 기존 결함). 그 외 실패 0
- `uv run ruff check src tests scripts` -- expected: clean
- `uv run python scripts/report_card_coverage.py` -- expected: exit 0, 계약 실패 8행(SCP-1471·682), 오탐 0, 정합 축 모집단 52, LLM 콜 0
- `uv run python scripts/report_card_coverage.py --demand 4b35c0ed` -- expected: 41 placements / unmet 4가 경고 4건과 `(shot_id, card_key)` 대응
- `uv run python _bmad-output/implementation-artifacts/14-6-dclass-object-asset-sets/reconcile_manifest.py --dry-run` -- expected: 7행, 역방향 0, 매니페스트 md5 불변
- `uv run python .../reconcile_manifest.py --dry-run --commit` -- expected: 파서 거부(비-0 종료), 매니페스트 불변
- `md5sum assets/manifest.json` -- expected: 세션 시작과 끝이 동일
- `git diff --stat prompts/ assets/` -- expected: 비어 있음
- `uv run python scripts/report_decision_drift.py` -- expected: exit 0, 신규 표류 없음
- **재생성 배치 드라이런** -- 리포트 §5에 적을 각 명령을 tmp 환경에서 한 번 통과시켜 exit 0을 확인한다. 확인하지 않은 명령은 리포트에 적지 않는다.

**Manual checks (if no CLI):**
- 픽셀 판정은 이 스토리가 하지 않는다. 배치는 GPU가 있는 세션에서 `--stage`로 굽고, `approve_stock_cast.py`는 Jay가 본 뒤에만 돈다.
- `nvidia-smi -L` / `ls /dev/nvidia*` / `cat /proc/driver/nvidia/version` / `curl 127.0.0.1:8188` 네 출력을 리포트에 원문으로 남긴다 — "이 머신엔 없다"는 단언이 거짓이었던 전례(13.3)가 있으므로 주장이 아니라 증거로 남긴다.

## Auto Run Result

Status: **done** — 단, **닫힌 것은 게이트·계약·감사·수요 산정이고, 픽셀과 사람 판정은 열려 있다.** 이 세션에 GPU가 없다는 것이 그 경계를 만든 사실이고, 주장이 아니라 실측으로 남겼다.

### 구현된 변경

Jay의 ③ *"각잡아서 제대로 배경 셋, D 계급 셋, 오브젝트 셋을 미리 만들어두는게 좋을 것 같음"*을 받아, **픽셀을 만들기 전에 그것을 안전하게 만들 길**을 세웠다. 10.8이 `character-generation` v5를 2026-08-16에 시딩하며 남긴 비소급 상태의 크기를 처음으로 **측정**했고(52장 중 pre-v5 45 / same-day 4 / post-v5 3), 재생성이 곧 출판이 되던 상태를 끊었다.

- **승인 게이트를 넓혔다.** `--stage`가 STOCK 3키·standing 전용이던 이유는 정책이 아니라 승인기의 파일명 조회 한 줄이었다. 이제 임의 캐릭터 키 × `standing|sitting`을 스테이징할 수 있고, **에폭은 원자적으로 승격된다** — 그 에폭에 스테이징된 모든 키·모든 포즈를 함께, 그리고 승격은 항상 `bump_style_epoch()`로 닫는다. 범프가 스테이징 자리와 라이브 자리를 가르는 유일한 기구이기 때문이다.
- **스프라이트 계약을 픽셀로 측정한다.** `has_alpha`는 IHDR 색상타입만 보는 형식 검사라 완전 불투명 RGBA를 통과시킨다. `sprite_contract`는 디코드된 알파를 보되 손상 컨테이너에는 더 약하다. 두 사각지대가 다르므로 승인 경계에 **둘 다** 세웠다.
- **부류를 모집단 전수로 닫았다.** SCP-1471/682 8장이 `no_alpha_channel`로 떨어지고 정상 44장 오탐 0. 정합 축도 `character_cards` 20행이 아니라 카드 매니페스트 **52엔트리 전부**를 훑는다.
- **재생성 배치를 관측 수요로 산정했다.** 전 어휘 72셀이 아니라 run `4b35c0ed`가 실제로 요청한 41 placement이고, 미충족 4건이 그 런의 `cast_card_fallback` 4건과 `(shot_id, card_key)` 단위로 대응한다.
- **누운 카드의 양끝 클리핑을 고쳤다.** 원인은 생성이 아니라 `_normalize_subject_scale`이 광폭 피사체를 **가로 여백 0으로** 폭에 맞추던 것이었다.
- **빈 서술자로는 카드를 만들지 않는다.** 가드는 생산자 전수가 지나는 funnel에 있고, 전수조사 표가 리포트 §8에 실렸다.

### 변경 파일

- `src/yt_flow/domain/png.py` — `alpha_profile`/`sprite_contract`(사유 5종), 실측 밴드 주석. `has_alpha`는 불변.
- `src/yt_flow/services/character_service.py` — funnel + 특수 포즈 경로의 빈-서술자 가드, 공백 서술자 덮어쓰기 차단, 스테일 docstring 2건 정정.
- `src/yt_flow/services/character_image_provider.py` — `_SIDE_GUTTER`(좁은 캔버스 폴백 포함).
- `src/yt_flow/domain/warnings.py` + `src/yt_flow/domain/state.py` — `character_descriptor_missing`.
- `src/yt_flow/services/run_service.py` — 파생 엔티티 이연의 **거짓 사유** 정정.
- `scripts/approve_stock_cast.py` — 원자적 에폭 승격 + 항상 범프, `has_alpha`+계약 병립, 포즈 인지 조회, 블로커와 무관한 `--reject`, `try/finally` 범프.
- `scripts/seed_stock_cast.py` — `_validate_stage_target` 제거(경고는 재서술), `_poststage_descriptor.txt`.
- `scripts/report_card_coverage.py` — 계약 축 / 출처 축 / 정합 축 / `--demand`. 신규 리포터 없음.
- `_bmad-output/.../14-6-dclass-object-asset-sets/` — `report.md`, `reconcile_manifest.py`, `dryrun_batch.py`.
- 테스트 7파일(신규 `tests/test_report_card_coverage.py` 포함), `deferred-work.md`, `epics.md`, `sprint-status.yaml`.

### 리뷰 결과

**2회차.** 1회차에서 **bad_spec 6건(high 5)** — 전부 재현됐고 코드를 되돌린 뒤 스펙을 고쳐 재도출했다. 뿌리는 하나였다: 스펙이 지시한 "포즈별 고아 검사 + standing 전용 범프"가 스테이징을 라이브에서 분리하지 못해, ① 스테이징된 sitting 영구 고립 ② `--reject`가 **라이브 승인 카드 삭제** + 서술자 `None` 덮어쓰기 ③ 재스테이징이 승인 픽셀 덮어쓰기 ④ 인계 배치 실행 불가를 만들었다. 별개로 승인 게이트가 `has_alpha`를 계약으로 **교체**(스펙 Never 위반)했고, 빈-서술자 가드가 **프로덕션 도달 불가한 함수**에 붙은 채 세 문서가 "닫혔다"고 거짓 주장했다.

**2회차에서 그 5건은 전부 닫힘이 확인됐다**(리뷰어가 생산자 전수를 독립 재도출). 신규는 **patch 21(high 4 / medium 11 / low 6) · defer 3 · bad_spec 0 · intent_gap 0**이고 전량 반영했다. high 4건 중 3건이 **리포트가 Jay에게 넘기는 명령의 부작용 미기재**였다 — step-0 `--reject`가 라이브 서술자를 되돌리는 것, 다른 step-0가 현재 서빙 중인 hint 카드 2장을 은퇴시키는 것, 그리고 반사실 수치가 14가 아니라 **18**이었던 것.

⚠️ **구현 에이전트가 리뷰어를 한 번 반증했다**: "13일 롤백"이라던 서술자 되돌림은 `characters.updated_at`이 그 스테이징의 front 렌더보다 **1.7초 뒤**이므로 실은 그 스테이징 자신의 의도된 되돌림이었다. 가드는 유지하되 근거를 실측으로 교체했다.

### 검증

- `uv run pytest -q` — **1 failed, 3373 passed, 1 skipped**. 유일한 실패는 `test_render_pose_guides.py`의 PNG SHA 핀이고, **이 스토리 코드를 stash한 상태에서도 동일하게 실패**함을 확인했다(기존 결함, 14.1/14.5가 기록).
- `uv run ruff check src tests scripts _bmad-output/implementation-artifacts/14-6-dclass-object-asset-sets` — clean.
- `report_card_coverage.py` — 계약 44 PASS / 8 FAIL(SCP-1471·682), **오탐 0**, 밴드 0.4377~0.8556, 반사실 18행 출력. 출처 45/4/3/unknown 0. 정합 정방향 7 · 역방향 0.
- `--demand 4b35c0ed` — 41 placement / 9 scene / UNMET 4, **경고 미대응 0건**.
- `reconcile_manifest.py --dry-run` 7행 exit 0 / `--dry-run --commit` 파서 거부 exit 2.
- `dryrun_batch.py` 양 leg 모두 `BATCH OK` — 리포트 §5에 적힌 명령만 적었다.
- `md5sum assets/manifest.json` 세션 시작·끝 동일(`93a0df7e…`), `git diff --stat prompts/ assets/` 비어 있음, `report_decision_drift.py` exit 0.
- GPU 부재 4증거(`nvidia-smi -L` exit 9 / `/dev/nvidia*` 부재 / `/proc/driver/nvidia/version` 부재 / ComfyUI `000`)를 리포트에 원문 수록.

### 잔여 리스크

- **픽셀 판정 0건.** 재생성은 GPU 있는 세션이 `--stage`로 굽고 Jay가 본 뒤에만 `approve_stock_cast.py`가 돈다. 이 스토리는 `bump_style_epoch()`를 **0회** 실행했고 `angle_*_path`를 **0회** 썼다.
- **SCP-1471/682는 배치에서 제외**됐다 — `visual_descriptor` 길이 0이라 사람이 쓴 서술자가 먼저 필요하다. 새 가드가 그때까지 두 키의 재생성을 거부한다.
- **오브젝트 세트는 만들지 않았다.** `ShotData`에 오브젝트 축이 없고 `AssetService`에 `kind` 필드가 없어 소비 seam이 아예 없다. 부재를 측정해 인계했다.
- `assets/characters/STOCK-d-class/epoch_3/` 스테이징 잔류가 **원자적 승격의 첫 차단 대상**이다. 승격이냐 기각이냐는 Jay의 판단이고, 양쪽 부작용을 리포트 §5가 명시한다.
- 출처 축은 매니페스트 `created_at`(등록 시각)을 렌더 시각의 **대리**로 쓴다 — 이연 등재.
