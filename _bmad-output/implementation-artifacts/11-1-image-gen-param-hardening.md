---
baseline_commit: 9a6d2f14dcad6e1725775e1863eabb1889c77395
---

# Story 11.1: 이미지 생성 파라미터 하드닝 — seed/AR/tier 퀵윈 묶음

Status: done

## Story

As a **yt.flow 운영자 (Jay)**,
I want **배경 이미지 생성 파라미터(seed/latent AR)와 합성 기본값(harmonization tier/카드 알파 엣지)의 4가지 확정 결함을 반나절 규모 설정·상수 수정으로 일괄 제거**,
so that **8-16(depth-aware placement + IC-Light) 착수 전에 베이스라인이 오염 없이 확보되고, "조잡함"의 코드-확정 원인 4개(전 배경 seed 0 공유, 세로 18% 크롭-업스케일, 꺼져 있는 harmonization, 카드의 바이너리 알파 엣지)가 사라진다**.

## Acceptance Criteria

1. **Per-shot deterministic seed injection**: `image.py`의 실제 생성 경로가 워크플로의 **모든 `KSampler` 노드**(class_type 매칭, 노드 ID 하드코딩 금지)에 샷별 결정론적 seed를 주입한다. seed는 `sha256(f"{run_id}:{scene_num}:{shot_id}")` 기반(`% 2**32`) — 빌트인 `hash()` 금지(PYTHONHASHSEED로 프로세스 재시작 시 값이 바뀌어 resume이 깨짐). 같은 run 안에서 같은 샷은 항상 같은 seed, 다른 샷은 다른 seed. 로드된 template은 변형되지 않는다(기존 `_inject_prompts`의 deep-copy 순수성 유지). Mock 모드는 워크플로를 만들지 않으므로 동작 불변.
2. **Sidecar resume에 seed 포함**: `_write_sidecar`가 seed를 기록하고 `_existing_complete_shot`이 이를 비교한다. seed는 (run_id, scene_num, shot_id)의 순수 함수이므로 stock-plate/mock/생성 3경로 모두 **무조건 동일하게** 기록·비교한다(경로 분기 금지 — 비교 시점엔 어느 경로일지 모름). seed 키가 없는 레거시 사이드카는 mismatch → 재생성(의도된 1회 캐시 무효화 — AR 변경으로 기존 캐시는 어차피 시각적으로 무효).
3. **배경 latent 16:9 네이티브화**: `data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json`의 `EmptyLatentImage`(노드 "5")를 1216×832 → **1344×768**(SDXL 표준 버킷, AR 1.75)로 교체. 결과: `_zoompan_filter`의 `scale=1728:-2 → crop=1728:972` 체인에서 세로 크롭 손실이 ~17.8%(1182→972) → **~1.6%**(988→972)로 감소. 캐릭터 워크플로(832×1216 세로형)와 location plate 워크플로(1920×1080)는 **건드리지 않는다**.
4. **`composite_harmonization_tier` 기본 0→1**: `config.py:155`의 default를 1로 변경, 동반 주석("Default stays off until a real tier-0 vs tier-1 A/B run confirms the visual win")을 리서치 근거로 갱신. 이미 구현된 tier 1(무드 틴트 + 컨택트 섀도)이 기본 활성화된다. 8-16의 IC-Light(tier 3)가 오면 이 tier 1이 폴백으로 정착.
5. **`_clean_alpha_noise` 안티에일리어스 엣지 보존**: `character_image_provider.py:72`의 `np.where(keep_mask, 255, 0)` 하드 스냅을 제거하되, 함수의 존재 이유(InSPyReNet 디더 밴드 제거)는 보존한다 — 권장 구현: keep_mask **내부**(2px erode)는 255로 스냅(디더 밴드 제거 유지), **엣지 밴드**는 원본 알파 유지(AA 보존), keep_mask 밖은 0. 신규 생성 카드에만 적용되며 기존 자산은 재생성하지 않는다.
6. **합성 시점 카드 엣지 페더 2–5px**: `video.py _build_card_chain`의 카드 필터 체인에 페더 스테이지를 추가해 **기존 카드 자산(41개, 재생성 없음)**의 하드 엣지를 합성 시점에 소프트화. `_build_card_chain`은 fast-path와 8.11 per-shot 경로가 공유하므로 한 곳 수정으로 두 경로 모두 커버.
7. **회귀 가드**: seed/AR 변경 검증은 골든 렌더 픽셀 비교가 아닌 **파라미터 단위 테스트**로 한다(seed 변경 자체가 픽셀 비교를 무의미하게 만듦). 기존 테스트 스위트 전체 green — 영향받는 기존 테스트(아래 Testing 절)는 새 동작에 맞게 갱신하되, 갱신 사유를 각 테스트에서 설명 가능해야 한다.

## Tasks / Subtasks

- [x] Task 1: per-shot seed 주입 (AC: 1)
  - [x] `image.py`에 `_shot_seed(run_id, scene_num, shot_id) -> int` 순수 함수 추가 — `hashlib.sha256` 기반, `_plate_variant_index`(image.py:237-247)와 같은 근거·같은 패턴
  - [x] `_inject_prompts`에 seed 파라미터 추가(또는 별도 `_inject_seed` — `character_image_provider.py:232` `_inject_seed`가 class_type 매칭 선례) 후 `image_node`의 실제 생성 경로(image.py:334)에서 호출
  - [x] 단위 테스트: 같은 (run_id, scene, shot) → 같은 seed / 다른 shot → 다른 seed / template 비변형 / KSampler 없는 워크플로에서 무해
- [x] Task 2: sidecar seed 확장 (AC: 2)
  - [x] `_write_sidecar`에 `"seed"` 키 추가(3경로 공통), `_existing_complete_shot`에 비교 추가
  - [x] 기존 resume 테스트(test_image.py:271-385) 갱신 + 신규: seed mismatch → 재생성, 레거시 사이드카(seed 없음) → 재생성
- [x] Task 3: latent AR 교체 (AC: 3)
  - [x] `comfyui_sdxl_anime_lora_workflow_api2.json` 노드 "5": width 1216→1344, height 832→768
  - [x] `.env`의 `YTFLOW_COMFYUI_WORKFLOW_PATH`가 같은 파일(api2.json)을 가리키는지 확인(이미 확인됨 — 그래도 커밋 전 재확인, iteration-1 스테일 .env 전례)
  - [x] `_zoompan_filter` 코드 변경 **불필요**함을 확인: `scale=1728`/`crop=1728:972`는 `COMP_W×(1−ZOOM_SAFE_MARGIN)`에서 유도된 값(video.py:274-276)이라 소스 크기 무관 — 1344×768 입력이면 scale=1728:-2 → 1728×988 → crop 972로 산술 검증만 기록
  - [x] 라이브 스팟 체크 1샷: 실제 ComfyUI로 1344×768 배경 1장 생성 → ffprobe로 치수 확인 (ComfyUI: `$HOME/workspaces/ComfyUI/`, `./run.sh`, :8188)
- [x] Task 4: harmonization tier 기본 1 (AC: 4)
  - [x] `config.py:155` default 0→1 + 주석 갱신(리서치 §Phase 1 quick-win 3 근거, 8-16 폴백 역할 명시)
  - [x] `test_config.py:90`(`== 0` 단언) 갱신
- [x] Task 5: `_clean_alpha_noise` AA 엣지 보존 (AC: 5)
  - [x] 내부 스냅 + 엣지 밴드 원본 알파 방식으로 재작성(scipy `binary_erosion` — 이미 ndimage 사용 중, 신규 의존성 없음), 독스트링의 "Snap to fully opaque/transparent" 근거 주석 갱신
  - [x] `test_character_service_generation.py:673-696` 갱신: 내부 255 유지 단언은 그대로 유효, 엣지 밴드 AA 보존 단언 추가
- [x] Task 6: 합성 시점 페더 (AC: 6)
  - [x] `_build_card_chain`의 `char_chain` **첫 스테이지**(스케일 필터들보다 앞)에 알파 페더 삽입 — 권장 ffmpeg 관용구: `split[rgb][a];[a]alphaextract,gblur=sigma=1.5[fa];[rgb][fa]alphamerge`(체인 파트로 분리 필요) 또는 단일 필터 `boxblur=lr=0:cr=0:ar=2`(체인 인라인 가능, 이쪽이 lazy — 동작 확인되면 이걸로)
  - [x] 라벨 이중 소비 금지: light_wrap이 같은 함정을 split으로 회피한 선례(video.py:857-869 주석 "ffmpeg rejects a label consumed twice") — split 방식 채택 시 동일 패턴 준수 (boxblur 인라인 채택으로 함정 자체가 없음)
  - [x] 필터 문자열 단위 테스트(test_video.py의 기존 체인 문자열 테스트 패턴) + 라이브 1신 렌더로 ffmpeg 수용 확인
- [x] Task 7: 전체 검증 (AC: 7)
  - [x] `PYTHONPATH=$PWD/src pytest tests/` 전체 green (워크트리에서 작업 시 PYTHONPATH 필수 — 글로벌 editable install이 메인 트리 src를 가림)
  - [x] 갱신 필요 예상 지점: test_config.py:90, test_image.py resume 계열, test_character_service_generation.py alpha 계열

## Dev Notes

### 이 스토리가 존재하는 이유 (리서치 근거)

2026-08-01 품질 우선 리서치(`_bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md` §Phase 1 quick-wins 1–4, §5.2, §3.4)가 코드에서 확정한 결함 4개의 일괄 수정. **신규 아키텍처 없음** — 전부 기존 코드의 파라미터/상수/기본값 수정. **8-16 착수 전 완료 필수**(8-16의 before/after 비교 베이스라인이 이 결함들로 오염되는 것을 방지).

### 수정 대상 파일 현황 (전부 UPDATE, NEW 없음)

**`src/yt_flow/pipeline/nodes/image.py`** (368줄):
- 현재: `_inject_prompts(template, image_prompt, negative_prompt)`(L111-121)는 노드 "6"/"7"에 프롬프트만 주입, deep-copy 순수 함수. seed는 어디서도 주입 안 됨 → 워크플로 JSON의 `"seed": 0`이 배경 155장 전부에 적용.
- sidecar: `_write_sidecar`(L141-153)는 `image_prompt`/`negative_prompt` 2키만 기록. `_existing_complete_shot`(L156-177)이 이 2키 + 파일 크기(`MIN_VALID_IMAGE_BYTES`)로 resume 판정. **모든 파일시스템 오류는 "incomplete" 처리(raise 금지)** — 이 AD-10 방어 자세를 seed 비교에도 유지할 것.
- sidecar를 쓰는 경로는 3개: stock plate 복사(L301), mock(L344 경유), 실제 생성(L344). `_existing_complete_shot`은 경로 판정 **이전**에 실행되므로 seed 비교는 경로 무관하게 균일해야 함.
- 보존할 것: template 재사용(shot 루프 밖에서 1회 로드), AD-4(입력 state 비변형), AD-10(예외는 `error` 필드로), 5.23 헬스체크/복구 루프, 8.5 plate 캐시.
- **선례**: `_plate_variant_index`(L237-247)가 "builtin `hash()` 금지, sha256 사용" 근거를 독스트링으로 이미 문서화 — 같은 이유가 seed에 그대로 적용됨(resume된 런은 다른 프로세스).

**`data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json`**:
- 노드 구성: "4" CheckpointLoaderSimple(AnimagineXL v3.1) → "10"/"11" LoraLoader(horror/darkness) → "6"/"7" CLIPTextEncode → "5" EmptyLatentImage(**1216×832**) → "3" KSampler(**seed 0**, 30 steps, dpmpp_2m/karras) → "8" VAEDecode → "9" SaveImage.
- `.env`가 `YTFLOW_COMFYUI_WORKFLOW_PATH=data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json`으로 이 파일을 가리킴(확인됨). config.py:38 기본값과 일치.

**`src/yt_flow/config.py`** (162줄):
- L151-155: `composite_harmonization_tier: int = Field(0, ge=0, le=3)` + "Default stays off until a real tier-0 vs tier-1 A/B run confirms" 주석 — 이 스토리가 그 결정을 리서치 근거로 뒤집는 것이므로 주석도 함께 갱신(주석만 남기면 미래 세션이 다시 0으로 되돌릴 위험).

**`src/yt_flow/services/character_image_provider.py`** (L32-75 `_clean_alpha_noise`):
- 현재: threshold(>100) → closing(25×25) → opening(7×7) → keep-largest+2% 컴포넌트 → **`np.where(keep_mask, 255, 0)` 하드 스냅**(L72). 스냅 근거 주석(L69-71): "keeping the original dithered alpha here would just re-draw the noise band" — **디더 밴드는 컴포넌트 내부 평탄 영역에 있으므로**, 내부만 255 스냅하고 엣지 밴드(erode 2px 차집합)만 원본 알파를 유지하면 두 목적(디더 제거 + AA 보존)이 양립함. 이것이 권장 구현.
- 호출부 3곳(L168/177/184: t2i, i2i, t2i-fallback) — 함수 시그니처 불변이므로 호출부 무변경.
- 이 함수는 **카드 생성 시점**에만 실행 → 기존 41개 승인 자산엔 소급 적용 안 됨 → AC 6의 합성 시점 페더가 그 갭을 메움.

**`src/yt_flow/pipeline/nodes/video.py`** (L771-874 `_build_card_chain`):
- 카드 필터 체인 조립 순서: `[k+1:v]` 카드 입력 → `_character_scale_filter`(depth 스케일) → movement → parallax zoom → overlay-expr → pulse → tier1 tint → `[c{k}]` 라벨 → (tier1 shadow / tier2 light_wrap) → overlay. **페더는 char_chain 맨 앞**에 넣어야 이후 스케일 단계들이 소프트 엣지를 그대로 보존·축소함.
- fast-path(`_render_scene_fast`)와 8.11 per-shot(`_compose_shot_clip`)이 이 함수 하나를 공유(독스트링 명시: "one implementation of the overlay chain so the two can never drift") — 한 곳 수정으로 충분.
- **ffmpeg 함정**: 라벨 이중 소비는 "Invalid file index"/"matches no streams"로 죽음 — L857-869 주석과 light_wrap의 split 처리가 라이브 검증된 선례. `boxblur=ar=` 단일 필터를 쓰면 이 함정 자체가 없음(인라인 스테이지) — 먼저 시도할 것.
- tier 기본 1 활성화(AC 4)와 이 함수의 harmonize 분기(L794)가 상호작용: 기본 런이 이제 tint+shadow 경로를 탐 — test_video.py는 tier를 명시적으로 0으로 주입(test_video.py:47-65)하므로 기존 테스트 무영향, harmonization 동작은 test_video_harmonization.py가 커버.

**`_zoompan_filter`는 수정하지 않는다** (video.py:268-341):
- 체인 `scale={safe_w}:-2,setsar=1:1,crop={safe_w}:{safe_h},scale=8000:-1,zoompan…`의 1728/972는 `COMP_W=1920`/`COMP_H=1080`/`ZOOM_SAFE_MARGIN=0.10`(L80-84)에서 **유도**되는 값이라 소스 해상도와 무관. epics의 "상수 동기 수정" 문구는 이 유도 관계 확인으로 충족됨: 1344×768 입력 → scale=1728:-2 → 1728×988 → crop 972 → 손실 16px(1.6%). 잘못해서 이 함수를 건드리면 8000px 슈퍼샘플링 지터 픽스(L271-273)를 깨뜨릴 위험만 있음.

### 시스템 무결성 (명시 AC 밖이지만 깨지면 안 되는 것)

- **resume 의미론**: seed가 사이드카에 들어가면 "이 스토리 배포 직후 첫 retry는 전 샷 재생성"이 된다. 이는 의도된 동작(AR도 바뀌어 기존 이미지가 어차피 구형)이지만, run 중간 배포는 피할 것.
- **run_id/scene_num/shot_id 가용성**: `image_node` 루프에서 셋 다 이미 손에 있음(state, scene["scene_num"], shot["shot_id"]) — 시그니처 변경 최소화 경로로.
- **8-3 배경-only 계약**: `BG_NEGATIVE_SUFFIX` 부착, 노드 "6"/"7" 검증(`_load_workflow`) 등 기존 계약 전부 보존.
- **캐릭터 카드 latent(832×1216)는 별개** — config.py:91-92 `character_image_width/height`와 캐릭터 워크플로는 이 스토리 스코프 밖. src 전역에서 1216은 캐릭터 쪽에만 더 존재함(확인됨).
- **동시 편집 경고**: 11-2/11-3(예정)과 8-16이 `video.py`를 공유 — 이 스토리의 video.py diff는 `_build_card_chain` 한 함수로 국소화할 것. sprint-status.yaml 동시편집 충돌 전례 다수(부분 스테이징으로 처리).

### Testing

- 프레임워크: pytest + pytest-asyncio(기존 그대로), 테스트 위치 `tests/pipeline/nodes/test_image.py`, `tests/pipeline/nodes/test_video.py`, `tests/services/test_character_service_generation.py`, `tests/test_config.py`.
- 갱신 확정 지점: `test_config.py:90`(tier 기본 0 단언), `test_image.py` resume 계열(L271-385, 사이드카 키 추가), `test_character_service_generation.py:673-696`(알파 스냅 단언).
- 신규 테스트는 **파라미터 단위**(seed 값 결정론, 사이드카 비교, 필터 문자열) — 골든 렌더 픽셀 비교 금지(AC 7).
- 알려진 테스트 함정: `test_character_service_generation.py`는 repo `./workspace/`에 실파일을 쓰는 격리 버그 이력 있음 — 새 테스트는 `tmp_path` 사용.
- 라이브 검증 2건(Task 3 스팟 렌더, Task 6 ffmpeg 수용)은 로컬 ComfyUI(`$HOME/workspaces/ComfyUI/run.sh`, :8188) 필요.

### Project Structure Notes

- 모든 변경이 기존 모듈 내부(파이프라인 노드 2, 서비스 1, config 1, 데이터 JSON 1) — 신규 파일 없음, 신규 의존성 없음(scipy/numpy/PIL/hashlib 전부 기존 사용 중). Ponytail 준수: 래더 4-5단.
- AD-1(services는 api/pipeline import 금지), AD-4(state 비변형), AD-10(노드 예외는 error 필드) 전부 기존 패턴 유지 — 이 스토리는 경계를 넘는 코드가 없음.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 11.1] — 스토리 원문, 4개 항목 + 회귀 가드 방침
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#Phase 1] — quick-wins 1–4 (이 스토리의 ①–④)
- [Source: research §3.4] — "Classic VFX comp finish: edge feather 2–5px" (AC 5/6 수치 근거)
- [Source: research §5.2] — "KSampler seed never injected — hardcoded 0 for every background", "AR 1.462 → ~18% crop", "`_clean_alpha_noise` snaps alpha to hard 0/255"
- [Source: src/yt_flow/services/character_image_provider.py:232-239] — `_inject_seed` class_type 매칭 선례(캐릭터 쪽은 이미 랜덤화)
- [Source: src/yt_flow/pipeline/nodes/image.py:237-247] — sha256-not-hash() 근거 선례
- [Source: src/yt_flow/pipeline/nodes/video.py:80-84,268-341,771-874] — 유도 상수, zoompan 체인, 공유 카드 체인 빌더
- [Source: _bmad-output/implementation-artifacts/sprint-status.yaml] — 착수 순서: 11-1 → 8-15 → 8-17 → 8-16 → …(11-1이 8-16 전제)

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Fable 5)

### Debug Log References

- 전체 스위트: `PYTHONPATH=$PWD/src pytest tests/` → **1345 passed, 1 skipped** (2026-08-01)
- Task 3 라이브 스팟: 실제 ComfyUI(:8188)로 `_load_workflow`→`_inject_prompts`(seed 3658504396)→`submit_and_fetch` 경로 1샷 렌더 → ffprobe **1344×768** 확인, 정상 배경(엔티티 없음). 최초 시도는 첫 모델 로딩 지연으로 클라이언트 폴링 타임아웃 → history 폴링으로 완료 확인 후 회수(코드 결함 아님, 콜드스타트 지연)
- Task 3 zoompan 산술 검증(라이브): 1344×768 → `scale=1728:-2` → **1728×988** → crop 972 → 세로 손실 16px = **1.6%** (기존 1216×832: 1182→972 = 17.8%). `_zoompan_filter` 무수정 확인
- Task 6 페더 라이브 검증: `boxblur=lr=0:cr=0:ar=2` rc=0, 알파만 ~4px 램프(RGB 무손상). 단, 1×1 극소 스프라이트(harmonization 라이브 테스트 픽스처)에서 radius≤min(w,h)/2 제약으로 필터그래프 전체 실패(-22) → radius 클램프 식 `ar='min(2,floor(min(w,h)/2))'`로 확정(양쪽 rc=0). 대안 `gblur=planes=8`은 1×1에서 이 ffmpeg 빌드가 힙 크래시(rc -6) — 채택 금지 근거를 상수 주석에 기록

### Completion Notes List

- **AC1**: `_shot_seed` sha256 기반 순수 함수 추가, `_inject_prompts`에 필수 `seed` 파라미터 추가(class_type=="KSampler" 매칭, 노드 ID 하드코딩 없음, deep-copy 순수성 유지). Mock 모드는 워크플로를 만들지 않으므로 불변.
- **AC2**: `_write_sidecar`/`_existing_complete_shot`에 seed 키·비교 추가 — 3경로(stock plate/mock/생성) 공통, 경로 판정 이전에 seed를 루프 상단에서 1회 계산해 균일 사용. 레거시 사이드카(seed 없음)는 mismatch→재생성(의도된 1회 캐시 무효화). AD-10 방어 자세(파일시스템 오류=incomplete) 유지.
- **AC3**: 워크플로 JSON 노드 "5"만 1344×768로 교체(텍스트 치환으로 포맷 보존, 다른 노드 무변경 검증). `.env` 활성 라인이 api2.json을 가리킴 재확인(39행은 주석 처리된 스테일 항목). 캐릭터(832×1216)/location plate(1920×1080) 워크플로 무변경.
- **AC4**: `composite_harmonization_tier` 기본 0→1, 주석을 리서치 근거+8-16 폴백 역할로 갱신(미래 세션이 0으로 되돌리지 않도록). test_video.py는 tier를 명시 주입하므로 무영향 — 전체 스위트로 확인.
- **AC5**: `_clean_alpha_noise` 내부(2px erode, `binary_erosion` 5×5)만 255 스냅, 엣지 밴드는 원본 알파 유지, 마스크 밖 0. 함수 시그니처 불변 → 호출부 3곳 무변경. 기존 자산 소급 적용 없음.
- **AC6**: `CARD_EDGE_FEATHER` 상수를 `_build_card_chain`의 char_chain **첫 스테이지**로 삽입(이후 스케일 단계가 소프트 엣지를 보존·축소). fast-path와 8.11 per-shot이 이 함수를 공유하므로 한 곳 수정. 인라인 boxblur라 라벨 이중 소비 함정 없음. video.py diff는 상수 1개+한 줄로 국소화(11-2/11-3/8-16 동시편집 대비).
- **AC7**: 골든 픽셀 비교 없음, 전부 파라미터/필터 문자열 단위 테스트. 갱신된 기존 테스트 3곳 각각 갱신 사유를 테스트 주석에 기록: test_config.py(tier 기본 1), test_image.py(_inject_prompts seed 인자+사이드카 seed 키), test_video.py decorrelate(페더의 floor()가 모션 항 프록시 단언과 충돌 → 페더 스테이지 제거 후 단언).
- 신규 테스트 10개: seed 결정론/sha256 고정/전 KSampler 주입/KSampler 없음 무해(4), seed mismatch 재생성/레거시 사이드카 재생성/생성 경로 seed 기록·제출 검증(3), 알파 엣지 밴드 AA 보존(1), 페더 첫 스테이지 문자열+라이브 렌더(2 — 1개는 skipif ffmpeg).
- 참고: 로컬 ComfyUI를 이 세션에서 기동함(라이브 스팟 체크용) — 계속 떠 있는 상태.

### File List

- src/yt_flow/pipeline/nodes/image.py — `_shot_seed` 추가, `_inject_prompts`/`_write_sidecar`/`_existing_complete_shot` seed 확장, 루프 seed 계산
- src/yt_flow/pipeline/nodes/video.py — `CARD_EDGE_FEATHER` 상수 + `_build_card_chain` 첫 스테이지 페더
- src/yt_flow/config.py — `composite_harmonization_tier` 기본 0→1 + 주석 갱신
- src/yt_flow/services/character_image_provider.py — `_clean_alpha_noise` 내부 스냅+엣지 밴드 AA 보존
- data/workflows/comfyui_sdxl_anime_lora_workflow_api2.json — 노드 "5" 1216×832→1344×768
- tests/pipeline/nodes/test_image.py — seed 신규 테스트 7 + 기존 inject/resume 테스트 seed 갱신
- tests/pipeline/nodes/test_video.py — 페더 문자열/라이브 테스트 2 + decorrelate 단언 갱신
- tests/test_config.py — tier 기본값 단언 0→1
- tests/services/test_character_service_generation.py — 엣지 밴드 AA 보존 테스트 추가
- .gitignore — `.claude/.story-automator-active` 무시 항목 추가(스토리 자동화 세션 센티널 — 코드 변경 아님, 리뷰에서 File List 누락 보정)

## Senior Developer Review (AI)

2026-08-01, 자동 리뷰(story-automator, claude-fable-5). 결과: **Approve** — CRITICAL/HIGH 0건.

**검증 요약**: AC 7건 전부 구현 확인(diff 라인 단위 대조). Task [x] 13건 전부 실코드 증거 확인 — 허위 완료 없음. `_shot_seed` sha256 순수 함수 + class_type 매칭 주입 + deep-copy 순수성, 사이드카 seed 3경로 균일(루프 상단 1회 계산), 워크플로 JSON 노드 "5"만 변경, `.env` 활성 라인 api2.json 확인(39행은 주석), tier 기본 1 + 주석 갱신, `_clean_alpha_noise` 내부 스냅/엣지 밴드 보존(`np.where`가 RHS 전체 평가 후 대입 — view aliasing 무해 확인), 페더는 char_chain 유일 조립점의 첫 스테이지. 전체 스위트 재실행: **1345 passed, 1 skipped** (스토리 주장과 일치). `_inject_prompts`/`_write_sidecar`/`_existing_complete_shot` 외부 호출처 없음(grep — run_service.py/test_e2e_stub_run.py 언급은 주석뿐).

**발견 및 조치 (4건, 전부 수정/기록 완료)**:
1. [MEDIUM][수정] `.gitignore` 변경(자동화 센티널 무시 항목)이 git에 있으나 File List에 누락 → File List에 보정 항목 추가.
2. [LOW][수정] Completion Notes "신규 테스트 9개" — 실제 열거 합은 10(4+3+1+2) → 10으로 정정.
3. [LOW][수정] `test_generated_sidecar_records_shot_seed` 독스트링의 "(mock path included)"가 부정확(테스트는 mock=False 경로만 실행) → 독스트링 정정.
4. [LOW][기록만] seed 주입이 class_type "KSampler"만 매칭 — `KSamplerAdvanced`(`noise_seed` 키) 워크플로로 교체 시 무증상으로 고정 seed 회귀. 현재 data/workflows/ 전체에 KSamplerAdvanced 없음(grep 확인) → YAGNI, 코드 무변경. 향후 워크플로 교체 시 주의.

## Change Log

- 2026-08-01: Story 11.1 구현 완료 — per-shot 결정론 seed 주입+사이드카 확장, 배경 latent 1344×768(세로 크롭 17.8%→1.6%), harmonization tier 기본 1, 카드 알파 AA 엣지 보존+합성 시점 2-5px 페더. 전체 스위트 1345 passed. 라이브 검증 2건(ComfyUI 스팟 렌더, ffmpeg 페더 수용) 완료. (claude-fable-5)
- 2026-08-01: 자동 코드리뷰(Approve, CRITICAL/HIGH 0) — MEDIUM 1(File List `.gitignore` 누락)·LOW 2(테스트 개수 오기, 독스트링 부정확) 수정, LOW 1(KSamplerAdvanced 미커버) 기록. 전체 스위트 재실행 1345 passed. Status review→done. (claude-fable-5)
