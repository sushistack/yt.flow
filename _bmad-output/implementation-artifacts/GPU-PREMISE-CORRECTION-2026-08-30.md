# ⚠️ 정정 — "이 박스에 GPU가 없다"는 **거짓**이다 (2026-08-30)

Stories **14.3**과 **14.6**이 렌더 0장을 정당화하며 쓴 전제가 틀렸다.
아래 문서들에 그 전제가 심겨 있으므로 **인용하기 전에 이 파일을 먼저 읽어라**:

`sprint-status.yaml` · `epics.md` · `deferred-work.md` ·
`spec-14-3-art-style-contract.md` · `14-3-art-style-contract/{report,PREREGISTRATION}.md` ·
`spec-14-6-dclass-object-asset-sets.md` · `14-6-dclass-object-asset-sets/report.md`

## 무엇이 틀렸나

**`nvidia-smi`로 진단했다. 이 박스는 AMD다.** AMD/ROCm 머신에서 `nvidia-smi`는
존재할 수 없으므로 그 실패는 GPU 부재의 증거가 아니라 **도구를 잘못 든 증거**다.

## 실측 (2026-08-30)

| 항목 | 값 |
|---|---|
| PCI | `03:00.0 AMD Navi 31 [Radeon RX 7900 XT/7900 XTX/7900M]` |
| 커널 | `amdgpu` 로드됨(`amdxcp` 포함), `/dev/kfd` + `/dev/dri/renderD128,129` 존재 |
| ComfyUI venv (`~/workspaces/ComfyUI/venv`) | `torch 2.11.0.dev20260206+rocm7.1`, `hip 7.1.52802` |
| `torch.cuda.is_available()` | **True** |
| 디바이스 | `gcnArchName: gfx1100`, **24.0 GB** |
| ComfyUI 프로세스 | **미기동** — `127.0.0.1:8188` 응답 `000`, 마지막 로그 2026-08-17 |

**GPU는 있고 건강하다. ComfyUI가 안 떠 있었을 뿐이다.**
프로젝트 venv(`/mnt/work/projects/yt.flow/.venv`)의 torch는 `2.8.0+cu128`(CUDA 빌드)이라
`cuda.is_available()`가 False인데, **yt.flow는 렌더에 torch를 쓰지 않는다** —
ComfyUI와 HTTP로 대화하므로 무관하다. 이것도 오진의 원인 중 하나였다.

## 함께 드러난 것 — `run.sh`가 스테일하다

`~/workspaces/ComfyUI/run.sh`의 주석과 환경변수가 **이전 카드** 기준이다.

- `export HSA_OVERRIDE_GFX_VERSION=12.0.0` + 주석 *"RX 9060 XT (RDNA 4) 강제 인식"* —
  RDNA4(gfx1200)용인데 실제 카드는 **RDNA3(gfx1100)** 이다. 오버라이드 **없이** torch가
  카드를 정상 인식하므로(위 표) 이 줄은 지금 불필요하다.
  ⚠️ **해로운지는 미확인** — 오버라이드를 건 상태의 matmul 검증이 120초 안에 끝나지
  않아 중단했다(ROCm 첫 커널 JIT일 수도, 오버라이드 문제일 수도 있다). **오버라이드 없는**
  경로에서 아키텍처·VRAM 질의는 즉시 응답했다. 기동 전에 이걸 먼저 판별하라.
- `--lowvram` 근거 주석의 *"recompose 가중치 22.6GB가 **16GB** VRAM에 안 들어간다"* —
  이제 **24GB**다. `--lowvram`이 여전히 필요한지는 재측정 대상이고, 뺄 수 있다면
  recompose가 빨라진다. **다만 `--cache-lru 10`은 그대로 필요하다**
  (`gotcha_comfyui-cache-classic-evicts-on-workflow-alternation`, 샷당 490초 → 15초).
- `recompose_preflight_min_free_ram_gb = 12.0`은 **시스템 RAM** 플로어이므로 VRAM 변경과
  무관하다. 건드리지 마라(`config.py`의 긴 주석이 이유를 적어뒀다).

## 그래서 무엇이 바뀌나

14.3·14.6이 **하지 않은 일**은 여전히 안 한 일이지만, **하지 못한 이유는 기록된 것과 다르다.**
두 스토리의 코드·측정·리뷰 결과는 유효하다(GPU가 필요 없는 작업이었다). 무효인 것은
"렌더 0장이 의도된 범위"라는 정당화뿐이다. 다음 세션은 렌더를 **할 수 있다.**

재개 순서:
1. `run.sh`의 GFX 오버라이드 판별 + VRAM 전제 정리 → ComfyUI 기동
2. 14.1 부족분 렌더(최소 2장 LOW) + HIGH 3셀 재판독 → 사전등록 C1/C3 재채점
3. **E2E iteration 5** — 14.1(b) · 14.2 · 14.3 층 2 · 14.6이 한 런에서 판정된다

## 교훈

가용성 진단은 **벤더를 먼저 확인하고 도구를 고른다.** 한 벤더의 도구가 실패한 것은
하드웨어 부재의 증거가 아니다. 그리고 이 전제는 **두 스토리에 걸쳐 여덟 문서**에
심겼다 — `gotcha_recorded-root-cause-can-be-inverted`가 경고한 그대로다.
