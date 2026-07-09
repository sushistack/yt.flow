# E2E Iteration 1 — 2026-07-09 (run d55a265b, SCP-049)

베이스라인(iteration 0, run 272b05a4, `e2e-baseline-2026-07-06.md`)과 동일 개체(SCP-049)로 Epic 8 완료 후 재렌더. 실 서버(FastAPI :8000 + ComfyUI :8188), 5게이트 전부 실 API 승인, status **complete**. 하모나이즈 tier=1(mood tint + contact shadow) 환경변수로 활성.

- 산출물: `workspace/d55a265b-6f24-4159-b94f-bb30736142e8/video.mp4` (3분 58초), 8씬 87샷, 챕터 카드 7장(제목+킥커), 엔딩 크레딧 카드 + `description.txt`(CC BY-SA)
- cast 배선: 72/87샷 cast 채워짐(8-10 수정 라이브 확인), 배경 전용 15샷

## J-score (iteration 0 → 1)

| 축 | it.0 | it.1 | 근거 |
|---|---|---|---|
| J1 전환 | 4 | **4.5** | 챕터 카드가 제목+킥커 실림(5-17), fadeblack 유지 |
| J2 역동성 | 2 | **3.5** | D13 소멸, Ken Burns+카드 모션 체감. 감점: 카드 전원 제자리(8-8 candidate 미승격 → motion_style 미배정, 8-9 미구현) |
| J3 합성 | 2 | **4** | 컷아웃 경계 깨끗, 스케일/배치 자연, 콘택트 섀도 확인. 감점: 카드↔배경 조명 불일치의 "붙임" 느낌 잔존(tier3 IC-Light 대상) |
| J4 정합 | 2 | **3.5** | 개체 정체성 5/5(플레이그 닥터), 배경↔프롬프트 정합 양호. 감점: SCP-049-2 카드 부재로 10샷이 나레이션("049-2로 분류됩니다")과 불일치한 빈 배경, D계급 카드의 가면 룩 이질감 |
| J5 TTS | 4 | **4** (프록시) | 1.2배속 적용 확인. 억양 판정 Jay 몫 |
| J6 사운드 | 3 | **3.5** (프록시) | mood 다양화 실현(dread3/clinical2/revelation2/escalation1, D1 해소) → 씬별 베드 교체 관찰 가능. 믹스 청취 Jay 몫 |
| J7 후처리 | 관찰불가 | **관찰가능** | mood 다양화로 그레이드 차이 검증 가능해짐(프레임상 dread/clinical 톤 구분됨) |
| J8 자막 | 3 | **3.5** | 키네틱+가독성 유지, 그레이드 간섭 없음 |

## 런 중 발견·조치

1. **[critical, 수정됨] .env 스테일 워크플로**: `YTFLOW_COMFYUI_WORKFLOW_PATH`가 8-3에서 은퇴한 layered InSPyReNet 워크플로를 가리켜 **87장 배경 전부 RGBA 컷아웃**(최대 97% 투명)으로 생성됨. config.py 기본값은 정상 — .env가 8-3 이전 값. bg 전용 `comfyui_sdxl_anime_lora_workflow_api2.json`으로 수정, 죽은 키(`YTFLOW_COMFYUI_LAYERED`/`BACKGROUND_NODE`/`CHARACTER_NODE`) 주석 처리, 게이트 reject→재실행으로 87장 재생성. 교훈: 스토리가 config 기본값을 바꿀 때 .env 오버라이드 잔존 여부를 DoD에 포함할 것.
2. **[검증됨] 크래시 복구 경로**: ComfyUI가 42샷에서 hipErrorIllegalAddress로 사망(전례 재현). 런은 명확한 에러로 실패 처리(무한 침묵 아님), `POST /stages/image/retry`(3-8) + 샷 재개(5-14)로 42장 스킵 후 이어서 완주. 두 스토리 라이브 검증 완료.
3. **[갭] SCP-049-2 파생 카드**: cast_decision이 자산에 없는 `SCP-049-2`를 10샷에 배정 → video에서 전부 스킵(`no character row ... skipping` ×10). 파생 개체 카드는 온디맨드 생성 경로가 없음(8-4는 기존 카드의 pose 변형만).
4. **[잠김] 미승격 candidate 프롬프트**: location_key 전부 None(8-5), motion_style 전부 None(8-8) — 두 기능이 코드는 완성이나 프롬프트 미승격으로 비활성. 플레이트 fast path·마이크로모션 스타일이 이번 런에 미반영.

## 다음 액션 후보 (우선순위)

1. SCP-049-2류 파생 카드 갭 해소 — (a) cast_decision 어휘를 실재 카드로 제한 or (b) 파생 카드 온디맨드 생성 (Jay 결정)
2. 8-5/8-8 candidate 승격 (golden-set 게이트, Jay)
3. 8-7 마무리: tier0↔1 A/B는 이 런으로 부분 충족, real IC-Light 워크플로(커스텀 노드 설치) 남음
4. 8-9 착수 — J2 잔여 갭("들어섰습니다" 나레이션에 정적 카드)의 직접 해법
