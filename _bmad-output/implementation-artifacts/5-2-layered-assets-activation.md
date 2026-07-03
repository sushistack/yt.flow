# Story 5.2: 레이어드 에셋 실전 가동 — 투명 캐릭터 + 배경 분리 워크플로우

Status: draft

## Story

As Jay,
I want the already-built layered-asset pipeline (Story 1.6b image split + Story 1.9c character idle-motion overlay) to actually run in real renders,
so that videos show an independently-moving character over a panning background instead of a single flat Ken-Burns image.

## Context (2026-07-03 라이브 리뷰 피드백 #3)

"투명 배경 + 캐릭터 오버레이 + 움직임" 방식이 설계·구현(1.6b, 1.9c)까지 끝났는데 실전 런에 하나도 안 나옴. 원인 확정됨:
- `.env`에 `YTFLOW_COMFYUI_LAYERED`가 없음 (기본 false)
- 현재 워크플로우 `comfyui_sdxl_anime_lora_workflow_api2.json`은 `SaveImage` 노드가 1개뿐 — 플래그를 켜도 배경/캐릭터 2-출력이 불가능

즉 코드 문제가 아니라 **ComfyUI 워크플로우 에셋 + 설정 배선** 문제.

## Acceptance Criteria

1. **Given** 새 레이어드 워크플로우 JSON, **Then** 출력 노드 2개를 가진다 — 배경(불투명 PNG)과 캐릭터(배경 제거를 거친 RGBA PNG). 노드 ID는 `Settings.comfyui_background_node` / `comfyui_character_node`와 일치
2. **Given** 로컬 ComfyUI(:8188)에 워크플로우 제출, **When** 실제 생성 실행, **Then** 검증 거부 없이 두 출력이 생성되고 캐릭터 PNG는 `_has_alpha()` 통과 (color_type 4 또는 6)
3. **Given** `.env`에 `YTFLOW_COMFYUI_LAYERED=true` + 새 워크플로우 경로, **When** 실전 런 실행, **Then** `workspace/{run_id}/images/`에 shot별 `*_background.png` + `*_character.png`가 생기고 ShotData에 두 경로가 채워진다
4. **Given** 레이어드 에셋이 있는 씬, **When** video_node 렌더, **Then** 1.9c 오버레이 경로(배경 zoompan + 캐릭터 idle-motion 오버레이)가 실제로 타는 것을 최종 mp4 프레임으로 확인
5. 배경 제거가 실패해 캐릭터 출력이 없는 shot은 기존 폴백(배경 단독, 1.6b AC2)으로 계속 진행 — 런 전체가 죽지 않음
6. 문서화: 워크플로우에 필요한 ComfyUI 커스텀 노드(배경 제거 노드 등)와 설치 방법을 워크플로우 JSON 옆 README에 기록

## Tasks / Subtasks

- [ ] 배경 제거용 ComfyUI 커스텀 노드 선정·설치 (후보: rembg 계열, Segment Anything 계열 — 로컬 ROCm 환경에서 동작 확인) (AC: 2, 6)
- [ ] 레이어드 워크플로우 JSON 작성: 기존 SDXL+LoRA 그래프에서 분기 — ①배경 프롬프트→SaveImage(배경), ②캐릭터 생성→배경제거→SaveImage(RGBA) (AC: 1, 2)
- [ ] ComfyUI에 직접 제출해 단독 검증 (image_node 경유 전, 워크플로우 자체 검증) (AC: 2)
- [ ] `.env` 배선: `YTFLOW_COMFYUI_LAYERED=true`, `YTFLOW_COMFYUI_WORKFLOW_PATH` 교체, background/character 노드 ID 설정 (AC: 3)
- [ ] 실전 런 1회: image 게이트에서 레이어 산출물 확인 → video 게이트에서 오버레이 모션 확인 (AC: 3, 4, 5)
- [ ] 워크플로우 README 작성 (AC: 6)

## Dev Notes

- **Python 코드 변경은 원칙적으로 0** — image.py의 `_generate_layered_shot`, video.py의 오버레이 합성, `_has_alpha` 전부 구현·테스트 완료 상태. 이 스토리는 에셋+설정+라이브 검증.
- 캐릭터 프롬프트를 배경 프롬프트와 어떻게 분리할지가 유일한 설계 판단 지점: 현재 `_inject_prompts`는 노드 6/7(positive/negative) 한 쌍만 주입. 캐릭터 전용 positive 노드가 필요하면 image.py에 소폭 수정 발생 가능 — 그 경우에만 코드 스토리로 확장.
- 알려진 인접 이슈(이 스토리 범위 밖, 1.9b/1.9c deferral): 씬당 첫 shot만 렌더되므로 shots[1:]의 캐릭터는 여전히 드롭됨. per-shot 타이밍 모델 결정은 Story 5.3과 함께 재론.
- Epic 1에 캐릭터 생성/앵글 선택 인프라(1.11~1.13) 존재 — 캐릭터 이미지를 매 shot 생성하는 대신 캐릭터 라이브러리에서 재사용하는 통합은 이 스토리에서 판단.
