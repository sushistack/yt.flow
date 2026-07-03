# Story 5.3: 모션 강화 — Ken Burns 강도·다양성 상향

Status: draft

## Story

As Jay,
I want per-shot camera motion to be 3–5× more dynamic than the current near-static drift,
so that the video feels alive instead of a slideshow.

## Context (2026-07-03 라이브 리뷰 피드백 #2)

현재 `_effect_spec`의 기본 모션이 1.0→1.005 수준의 미세 드리프트라 사실상 정지 화면. 레이어드 오버레이(Story 5.2)가 역동성의 본체이고, 이 스토리는 배경/단일 이미지 쪽 Ken Burns 자체를 키운다.

## Acceptance Criteria

1. **Given** 기본 렌더, **When** 각 씬 세그먼트 생성, **Then** zoom 범위가 최소 1.0→1.08 이상(현행 대비 ≥3배 체감)이고 pan 이동량도 비례 상향된다 — 구체 수치는 구현 중 실렌더 눈검증으로 튜닝, 상수로 고정
2. **Given** 연속된 씬들, **Then** 효과가 단조 반복되지 않는다 — zoom-in / zoom-out / pan-left / pan-right / 대각 중에서 씬 인덱스 기반 결정적(deterministic) 로테이션 (랜덤 금지 — 재현성/체크포인트 재개 안전)
3. **Given** 강화된 zoompan, **Then** 기존 지터 방지 체인(scale=8000 트릭)이 유지되어 미세 떨림이 없다
4. **Given** 자막 번인, **Then** 확대/팬 중에도 자막은 프레임에 고정(모션은 자막 번인 전 단계에서만 적용 — 현행 체인 순서 유지)
5. 기존 effect 디스패처의 'static' 경로는 유지 (명시적으로 static을 지정한 shot은 그대로)

## Tasks / Subtasks

- [ ] `_effect_spec` 상수 상향 + 효과 로테이션 테이블 추가 (video.py:109 근방) (AC: 1, 2, 5)
- [ ] `_zoompan_filter` 파라미터화 확인 — 현행 시그니처로 충분하면 수정 없음 (AC: 3)
- [ ] 단위 테스트: 씬 인덱스별 효과 로테이션 결정성, zoom/pan 수치 경계 (AC: 1, 2)
- [ ] 실렌더 튜닝 루프: 기존 완료 런 video retry → 프레임/구간 추출 → 어지럽지 않은 최대 강도로 상수 확정 (AC: 1, 3)

## Dev Notes

- 순수 상수+디스패처 변경. 새 의존성 없음, ffmpeg 필터 체인 구조 불변.
- "3~5배"는 정량 스펙이 아니라 체감 목표 — AC1의 최소 수치만 하드 기준, 나머지는 튜닝.
- per-shot 렌더링(씬당 첫 shot만 렌더되는 1.9b 한계)은 이 스토리에서 다루지 않되, 튜닝 결과 씬이 너무 길어 단일 이미지 모션으로 못 버티면 per-shot 타이밍 모델 스토리를 별도 발의.
