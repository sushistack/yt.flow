# Story 5.1: 장면 전환 개선 — 암전 전환 + 챕터 카드

Status: draft

## Story

As Jay,
I want scene-to-scene transitions to cut to black (or through a chapter title card) instead of cross-fading two images over each other,
so that scene boundaries read as intentional chapter breaks rather than accidental overlaps.

## Context (2026-07-03 라이브 리뷰 피드백 #1)

첫 실전 렌더(run eb522cf9, SCP-096)에서 씬 전환이 `xfade=fade`(크로스페이드)라 두 이미지가 겹쳐 보이는 문제. 원하는 것: fadeout→fadein(암전) 또는 씬 사이 챕터 설명 카드.

## Acceptance Criteria

1. **Given** 2개 이상의 씬, **When** video_node가 최종 조인을 수행하면, **Then** 씬 경계는 크로스페이드가 아니라 암전을 거친다 (`xfade transition=fadeblack` 또는 카드 삽입 — 두 이미지가 동시에 보이는 프레임이 없음)
2. **Given** 챕터 카드 모드 활성 (`YTFLOW_CHAPTER_CARDS=true`, 기본 true), **When** 씬 N→N+1 전환 시, **Then** 1.5~2초짜리 정적 카드 세그먼트(검정 배경 + 씬 라벨 텍스트, drawtext)가 사이에 삽입되고 카드 앞뒤로 fade in/out 된다
3. **Given** 카드 라벨 텍스트, **Then** structure 단계 산출물에 씬 제목이 있으면 그것을, 없으면 `"— N —"` 형식의 씬 번호를 사용한다 (구현 시 SceneState에 제목 필드 존재 여부 확인 후 결정)
4. **Given** 챕터 카드 비활성 (`YTFLOW_CHAPTER_CARDS=false`), **Then** 카드 없이 `fadeblack` 전환만 적용된다
5. 기존 오디오 `acrossfade` 타이밍(running_offset 누적 로직)이 카드 삽입 후에도 A/V 싱크를 유지한다 — 최종 duration = Σ(씬 duration) + Σ(카드 duration) − Σ(전환 겹침)
6. 단일 씬 런은 기존과 동일하게 동작 (전환/카드 없음)

## Tasks / Subtasks

- [ ] `XFADE_TRANSITION = "fade"` → `"fadeblack"` (video.py:53) + 기존 xfade 테스트 기대값 갱신 (AC: 1, 4)
- [ ] 카드 세그먼트 생성기: ffmpeg `color=black` + `drawtext`(한글 폰트 경로 필요 — 자막 번인에 쓰는 폰트 재사용) + 무음 오디오 트랙 (AC: 2, 3, 5)
- [ ] `_join_with_xfade` 입력 목록에 카드 세그먼트 삽입 — 씬과 동일한 세그먼트 규격(해상도/fps/오디오 스트림)이면 조인 로직 재사용 가능 (AC: 2, 5)
- [ ] Settings에 `chapter_cards: bool = True` 추가 (AC: 2, 4)
- [ ] 테스트: 카드 on/off 각각 ffmpeg 커맨드라인 조립 검증(fake_run_ffmpeg seam), 단일 씬 무전환 (AC: 1-6)
- [ ] 라이브 검증: 기존 완료 런의 video 스테이지 retry로 재렌더 후 경계 프레임 추출 확인

## Dev Notes

- 씬 세그먼트 렌더(`_compose_scene`)는 건드리지 않는다 — 조인 단계만 변경.
- 카드도 하나의 "세그먼트 파일"로 만들어 조인 목록에 끼우는 방식이 xfade 오프셋 로직 재작성보다 짧다.
- 알려진 인접 이슈(건드리지 말 것): sub-0.5s 씬 xfade 언더플로우(1.9b deferral), audio_duration 선언값 vs 실측값 드리프트(1.9b deferral).
