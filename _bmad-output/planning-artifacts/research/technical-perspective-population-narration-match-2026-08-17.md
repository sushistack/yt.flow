# 왜 ②원근·⑤배경인구·⑥나레이션정합이 안 고쳐지는가 — 진단 + 문헌 1차 수집

**작성 2026-08-17.** 발단: Jay, run `4b35c0ed`(SCP-049, 3:20) 시청 판정 직후 —
*"2,5,6은 옛날부터 계속 얘기해도 개선이 안되는것 같은데? 왜그런거임? 이거 관련해서 논문을
찾아보던 트랜드를 찾아보던해서, epic story 에 제발 자료먼저 모으고 진행하도록 해줘"*

이 문서는 Epic 14의 **선행 게이트**다. 14.2·14.3·14.5는 이 문서가 닫히기 전에 착수하지 않는다.

---

## 0. 요약: 세 항목이 안 고쳐진 이유는 서로 다르다

| | 진단 | 근거 |
|---|---|---|
| ② 원근 | **한 번도 작업된 적이 없다.** 반복 실패가 아니라 반복 오프레이밍 | 접지 계열 스토리(10.1/8.16/11.5)가 잰 것은 수직 좌표 하나뿐 — `video.py`에 `ground_y` 43회, `_GROUND_Y_MAX` 6회. 시점·지평선·소실점 일치를 잰 코드가 0줄 |
| ⑤ 배경 인구 | **고쳐졌으나 꺼진 채로 출하됐다** | 10.2가 가드를 만들고 코드 기본값 `0`으로 출하 → 15일간 `never screened`. 2026-08-17 첫 발화에서 오염 3→0, never screened 43→0. **지금도 `.env` 핀 상태** |
| ⑥ 나레이션 정합 | **세 라운드가 전부 계측기에 쓰였고, 생성기를 바꾼 라운드가 0회다** | 10.4 `blocked`(A/B 교란 사망) → 10.4b done(전제 무효, `visible_event 84.9%` 인계) → 13.2 done(리커트→DSG 교체). image_prompt 도출 방식은 그대로 |

**그리고 ⑥의 새 계측기조차 검증되지 않았다**: 13.2 자신의 기록으로 `dsg_score`↔`readable`
순위상관 **0.0263**, 판독불가 프레임의 mean DSG가 **더 높다**(0.5694 vs 0.4892). 즉 네 번째
계측기 라운드를 도는 것은 낭비이며, 개입은 생성기 쪽이어야 한다.

---

## 1. ② 원근 — 우리 실패 모드에 문헌상 이름과 처방이 있다

우리가 겪는 것(run `4b35c0ed` `S00100`: 유리 바닥 **부감** 플레이트 위에 **눈높이 정면** 인물,
프레임 내 접지 불일치 — 049는 그림자 있고 D계급은 없음)은 문헌에서 **pose–scene mismatch**로
불리며, 처방 계열이 셋 있다.

- **Kulal et al., *Putting People in Their Place: Affordance-Aware Human Insertion into Scenes*,
  CVPR 2023** — [arXiv 2304.14406](https://arxiv.org/abs/2304.14406) ·
  [코드](https://github.com/adobe-research/affordance-insertion)
  씬 이미지 + 마크된 영역 + 인물 이미지를 받아 **씬 어포던스를 존중하며** 삽입한다. 핵심은
  *"inferring realistic poses given the scene context, **re-posing** the reference person, and
  harmonizing"* — 즉 **씬이 포즈를 결정한다.** 비디오 클립 2.4M으로 self-supervised(사람을
  re-pose하는 것을 학습).
  **우리에게 왜 결정적인가**: 우리는 지금 포즈를 *카드가* 들고 오고(승인된 스프라이트), 위치는
  `ground_y` 산술이 정한다. 이 논문은 그 둘을 **씬으로부터 추론**한다. ②(원근)와 ⑥의 포즈 절반이
  같은 메커니즘으로 풀린다. 그리고 이것이 8.20이 OpenPose로 시도했다가 얻은 교훈("텍스트 포즈
  지시는 무시된다, 구조적 조건화가 필요")의 상위 버전이다.
- **InsHuman: Towards Natural and Identity-Preserving Human Insertion** —
  [arXiv 2605.07402](https://arxiv.org/abs/2605.07402)
  Kulal 계열의 알려진 약점을 정면으로 다룬다: **pose–scene mismatch(뒤틀린 팔다리, 잘못된 비율)와
  얼굴 정체성 상실.** 후자가 우리 ⑦·14.6의 키별 정체성 드리프트와 같은 축이고, 전자가 Jay가 지적한
  `near` 인물 과대 스케일과 같은 축이다. **Kulal을 그대로 쓰면 우리 정체성 요구(승인된 카드와 같은
  인물)와 충돌할 가능성이 크므로, 이 논문이 그 절충의 1차 참고다.**
- **MV-CoLight: Efficient Object Compositing with Consistent Lighting and Shadow Generation** —
  [arXiv 2505.21483](https://arxiv.org/abs/2505.21483) · **Zero-Shot Depth-Aware Image Editing
  (DAEdit)** — [프로젝트](https://rishubhpar.github.io/DAEdit/)
  조명·그림자 일관성과 **정확한 깊이에 삽입**을 다룬다. 프레임 내 접지 불일치(049 그림자 O /
  D계급 X)의 직접 처방 후보이고, 8.7 harmonization 티어 사다리의 상위 대안이다.

**⚠️ 인용 규율**: 8.20의 Qwen-Image-Edit VRAM 수치를 세 번 오용한 전례가 있다
(`gotcha_qwen-image-edit-rejection-was-version-specific`). 위 논문의 VRAM·해상도·모델 크기를
우리 16GB 박스에 옮길 때는 **버전과 용도를 확인**하고, 이 문서에 수치를 적을 때 출처 버전을 함께
적는다. 현재 이 문서에는 의도적으로 리소스 수치를 옮겨 적지 않았다.

## 2. ⑤ 배경 인구 — 문헌보다 출하 규율이 먼저다

이 항목은 기법 문제가 아니라 **결정↔출하 표류** 문제다. 가드는 존재하고 작동한다(오늘 실측
3→0). 안 고쳐진 이유는 기본값 `0`이었다는 것뿐이다. 따라서 리서치가 필요한 부분은 좁다:

- **부정 프롬프트로 사람을 없애는 것은 이 프로젝트에서 이미 두 번 실패했다**
  (`gotcha_negative-prompt-overstuffing`: 결함당 부정 절 하나를 더하니 렌더가 두 번 망가졌다 —
  빈 얼굴, 추상 폴리곤). 그리고 오늘 run `4b35c0ed`의 negative_prompt에는
  `person, human figure, character, silhouette of a person`이 **이미 들어 있는데도**
  `S00201`에 액자 속 인물이 그려졌다. 즉 **부정 프롬프트는 이 축의 해법이 아니다** —
  탐지 후 재생성(가드)이 실제로 작동한 유일한 수단이다.
- 남은 리서치 질문은 하나: **"그림 속 인물"(액자·모니터·포스터 안)을 어느 층이 책임지나.**
  중복 인물 방지 목적에서는 탐지기가 세지 않는 것이 옳다(`gotcha_person-token-regex-is-unusable-on-image-prompt`가
  경고한 구분: 카메라·척도·그림 속 인물·부재를 같이 지우면 안 된다). 하지만 Jay의 체감 결함이기도
  하다. 이것은 화풍 계약(14.3) 또는 승인 게이트(14.1)의 소관일 수 있고, **가드 확장은 마지막
  선택지**여야 한다.

## 3. ⑥ 나레이션 정합 — 개입 지점이 계측기가 아니라 **프롬프트 생성**이다

우리 결함(`visible_event 84.9%` = 장소는 있고 사건이 없다)에도 문헌상 이름이 있다:
**catastrophic neglect** — 프롬프트에 있는 핵심 객체가 생성 이미지에서 누락되는 현상.

- **Attend-and-Excite: Attention-Based Semantic Guidance** (SIGGRAPH 2023) — cross-attention이
  **모든 주어 토큰**에 주의하도록 유도해 활성을 강화한다.
- **Patcher: Repairing Catastrophic-Neglect via Attention-Guided Feature Enhancement**
  (Findings of EMNLP 2024) — [arXiv 2406.16272](https://arxiv.org/abs/2406.16272)
  ① 프롬프트에서 **누락된 객체를 먼저 판정**하고 ② 그 객체에만 attention-guided 강화를 적용.
  SD 1.4/1.5/2.1에서 수동 주석 Correct Rate **+10.1~16.3%p**.
  **우리에게 왜 맞나**: 우리는 이미 프롬프트를 갖고 있고(`image_prompt`), 13.2의 DSG가 이미
  **어느 명제가 깨졌는지**를 내놓는다. Patcher의 ①단계 입력이 우리에게 이미 있는 셈이다.
- **프롬프트 재작성 계열 — 우리가 세 라운드 동안 건드리지 않은 층**:
  **FRAP**(adaptive prompt weighting, [arXiv 2408.11706](https://arxiv.org/abs/2408.11706)),
  **VisualPrompter**(semantic-aware prompt optimization, ICLR 2026),
  **GenPilot**(test-time prompt optimization 멀티에이전트, [arXiv 2510.07217](https://arxiv.org/abs/2510.07217)),
  **Seeing is Believing: Aligning Prompt Rewriting with Visual Anchors**
  ([arXiv 2606.08492](https://arxiv.org/abs/2606.08492)).
  이 넷이 공통으로 하는 일이 **나레이션→프롬프트 도출을 바꾸는 것**이고, 그게 우리가 한 번도 안
  한 개입이다.
- **DreamShot** (video-diffusion 기반 스토리보드, multi-shot) — 다중 샷에서 **long-range temporal
  coherence, 일관된 캐릭터 정체성, 서사 흐름**을 다룬다. ⑥뿐 아니라 ③⑦(샷 간 일관성)의 참고.
- 서베이/벤치: **Text to Image Generation and Editing: A Survey**
  ([arXiv 2505.02527](https://arxiv.org/abs/2505.02527)),
  **Qwen-Image-Bench** ([arXiv 2605.28091](https://arxiv.org/abs/2605.28091)) — 우리 생성기가
  Qwen 계열이라 후자는 벤치 정합 확인용.

**⚠️ 10.4의 교훈을 반복하지 않기 위한 규율**: 매핑에 렌더를 더 쓰지 마라(손으로 짠 커버조차
`match`를 못 움직였다). 그리고 프롬프트 변경은 **렌더 전 텍스트로 스크리닝**한다
(`gotcha_screen-a-prompt-change-before-you-render-it`: 109초가 ~6 GPU-시간을 절약했다).
Attend-and-Excite/Patcher류는 샘플러 내부 개입이므로 **ComfyUI 워크플로 노드 수준에서 가능한지**가
채택 전 확인 항목이다(우리 생성 경로는 SDXL 워크플로 JSON이다).

---

## 4. 미해결 — 이 문서를 닫기 전에 답해야 할 것

1. **Kulal/InsHuman 계열을 우리 정체성 제약과 어떻게 화해시키나.** 우리는 승인된 카드의 인물이
   그대로 나와야 하고, 그 논문들은 씬에 맞춰 re-pose한다. 10.1c가 이미 "카드 픽셀이 그대로면
   여전히 오버레이"라고 판정 기준을 세웠으므로, 재포즈는 방향상 맞지만 정체성 드리프트가 대가다.
2. **어포던스를 런타임 채점으로 할 것인가, 자산 메타데이터로 할 것인가.**
   `scripts/assess_plate_affordance.py`가 이미 있고 주석에 *"the known S00104-class recompose
   failure predictor"*라고 적혀 있다. 14.1의 세트 방식이면 런당 비용 0이 된다.
3. **Patcher/Attend-and-Excite가 우리 ComfyUI 경로에서 구현 가능한가** — 커스텀 노드 필요 여부.
   불가하면 프롬프트 재작성 계열(FRAP/VisualPrompter/GenPilot)만 남는다.
4. **`camera_angle` 필드와 `image_prompt` 본문의 앵글 서술이 충돌한다**(본문이 필드를 덮어쓴다:
   `S00100` medium 선언 vs 부감 렌더, `S00803` 프롬프트가 *"low-angle shot looking up"*으로 시작).
   이것은 문헌이 아니라 우리 프롬프트 조립 버그일 가능성이 높고, ②의 가장 값싼 절반일 수 있다.
   **먼저 확인할 것.**

   > **✅ 확인 완료 — 2026-08-21, Story 14.0 §4-4. 위 주장은 반증됐다(원문은 기록으로 남긴다).**
   >
   > run `4b35c0ed` 43샷 전수 실측: 필드↔슬롯-1 앵글 **일치 43 / 불일치 0 / 판정불가 0**
   > (7값 **어휘 버킷 단위** 일치다 — 버킷 밖 수식어는 버려진다).
   > 인용된 두 사례가 바로 반례다 — `S00100`은 필드 `medium`이고 본문 첫 두 단어도 `"medium shot"`,
   > `S00803`은 필드 `low-angle`이고 본문도 `"low-angle shot looking up from the floor"`다. 두 채널이
   > 같은 말을 하고 있다.
   >
   > **다만 이 일치는 경험적 사실이고 구조적 보장이 아니다.** 같은 LLM 턴이 둘을 함께 쓰는 것은
   > 맞지만(`visual_breakdown.md:72`가 슬롯-1을, `:215`가 필드를 같은 응답에서 요구한다), 그 턴은
   > **서로 다른 어휘 두 벌**을 받는다: `:72`가 코칭하는 `dutch angle`, `extreme close-up`,
   > `slow push-in medium`, `wide establishing`, `static wide` 등에는 `camera_type` 7값 대응물이 없다.
   > 모델이 슬롯-1에 `dutch angle`을 쓰는 순간 두 채널은 어긋난다 — 이 런에서 안 어긋난 것이지
   > 어긋날 수 없는 것이 아니다. 실제로 슬롯-1 머리 43개 중 **14개**가 이미 버킷 밖 수식어를 달고
   > 있고(`extreme close-up`×4, `static wide`×4, `view down`×2, `wide establishing`, `medium two-shot`,
   > `overhead view`, `slow pull-back`), 버킷 일치 판정은 그것을 버린다. 버려진 수식어가 어포던스
   > 게이트가 정확히 원하는 정보다(14.2 인계).
   >
   > **필드는 배경 렌더러의 프롬프트에는 도달하지 않는다** — `image.py:212`는 포지티브 노드에
   > `shot["image_prompt"]`만 대입한다. 그러나 **렌더 무관(render-inert)은 아니다**:
   > `character_service.py:1500`이 이 값을 샷별 카탈로그에 실어 `_select_entity_angles`가 앵글을 고르고,
   > 그 선택이 `_ANGLE_FIELD_NAMES`를 통해 `angle_*_path` 카드 PNG로 매핑되어 프레임에 합성된다.
   > 즉 배경 프롬프트의 라벨이면서 캐스트 카드 선택의 입력이다. 그래서 "본문 파싱 → 필드 재도출"
   > 리컨실러는 만들지 않았다(할 일 0건).
   >
   > **그럼 `S00100`은 왜 부감으로 렌더됐나 — 후보 가설 둘, 어느 것도 확정 아님.** 충돌은 필드와
   > 텍스트 사이가 아니라 **텍스트 내부**에 있다는 것까지가 확정이다. 그 안의 메커니즘은 **n=1이고
   > 대조군도 용량-반응도 없다**:
   > **(a) 내용 질량** — 119단어 중 앵글은 앞 2단어이고 나머지 117단어가 *"the center floor … lit
   > harshly from above"*, *"polished concrete with hairline cracks and a central drain grate"*,
   > *"twin rows of ceiling-mounted fluorescent tubes"* 로 바닥과 천장을 서술한다.
   > **(b) 조명 어휘의 앵글 오독** — 모델이 그 조명·설비 표현을 카메라 프레이밍으로 읽었다.
   > `S00100`은 이 런에서 `lit harshly from above` + `from above` + `ceiling-mounted`를 **동시에** 가진
   > 유일한 샷이므로, 이 한 샷으로는 (a)와 (b)가 구분되지 않는다.
   > **판별은 신규 스토리 없이 된다**: 커밋된 `measure_angle_agreement.py` 출력에서 (i) 바닥/천장 서술
   > 질량, (ii) 조명 어휘 히트 수로 43샷을 각각 그룹핑해 렌더된 시점을 비교하면, 두 축이 갈라지는
   > 샷(`S00901`, `S00103`)이 답을 준다.
   > 어느 가설이 참이어도 ②의 개입 지점은 프롬프트 조립이 아니라 **프롬프트 텍스트 내부**이고
   > **§4-3의 프롬프트 재작성 층과 같은 지점**이다. 후속 소관은 **Story 14.2**.
   >
   > 어휘 위치 주의: `overhead` / `from above` / `ceiling-mounted`는 프롬프트 뒤쪽에서 램프·설비 명사
   > 옆에 있으면 **조명 어휘**이고 카메라 프레이밍이 아니다(이 런에 23건/20샷). 다만 이것은 **위치
   > 의존 규칙이고 범주 규칙이 아니다** — 슬롯-1에 오면 진짜 프레이밍일 수 있다(`S00504`
   > `"high-angle overhead view of containment cell floor"`, `S00404`/`S00702` `"view down"`).
   > 뒤쪽 조명 표현을 앵글로 세면 `high-angle` 오탐이 대량 발생하며, 위 "충돌" 인상의 출처로 보인다.
   > 단, 같은 어휘가 위 (b) 가설의 후보이기도 하다는 점을 기억할 것 — "오탐"과 "모델의 오독"은 다른 층이다.
   >
   > 부수 소득(코드 읽기가 드러낸 실제 결함 2건): ① `camera_angle`이 형제 필드 전부와
   > 달리 무검증 passthrough여서 미스케이싱 값이 대소문자 민감 소비자(cast depth 수리 R3)를 조용히
   > 건너뛸 수 있었다 → 7값 어휘 정규화 + 어휘 밖 경고. ② `_fallback_prompt`가 `"static wide shot"`을
   > 하드코딩하면서 `camera_angle`은 LLM 값을 남겨 **확정적으로** 어긋났다 → 백필 시 `wide`로 통일.
   > ①의 대가를 명시한다: 어휘 밖 값(예: `dutch angle`)이 이제 앵글 선택 카탈로그에 원문 대신 `""`로
   > 도착한다 — 이 런 발생 0건이라 라이브 영향은 0이지만 "영향 없음"이 아니라 "이 런에서 0건"이다.
   > ②는 백필 샷의 `cast`가 항상 비어 있어 카드 선택이 돌지 않으므로 픽셀 영향 0.
   >
   > 근거·재산출: `implementation-artifacts/14-0-angle-conflict/report.md`,
   > `measure_angle_agreement.py 4b35c0ed`. GPU 0.
5. **⑥의 계측기 검증**: `dsg_score`↔`readable` 무상관과 판독불가 프레임의 높은 DSG를 이해하기
   전에 어떤 축도 게이트로 쓰지 않는다(13.2가 남긴 명시적 제약).

## 5. 착수 권고 순서

**가장 싼 것부터, 그리고 문헌이 필요 없는 것부터.**

1. ~~**§4-4 앵글 충돌 확인** — 코드 읽기, GPU 0, 문헌 0. ②의 절반이 여기서 끝날 수 있다.~~
   **✅ 완료(2026-08-21, Story 14.0 §4-4) — 그리고 반증이다.** 충돌 0건(43/43 일치)이므로 ②의 절반은
   여기서 끝나지 않았다. 이 항목의 소득은 **②에서 가장 값싼 가설을 GPU 0으로 제거하고, 다음 층
   (프롬프트 텍스트 내부, §4-3과 같은 층)을 지목하고 그 안의 후보 가설 둘((a) 내용 질량,
   (b) 조명 어휘 오독)을 동등하게 열어 둔 것**이다. → **다음 순번은 2번**
   (14.4 가드 기본값 승격, 이미 실측 3→0, 결정만 남음).
2. **14.4 가드 코드 기본값 승격** — 이미 실측됨(3→0), 결정만 남았다. ⑤가 여기서 닫힌다.
3. **14.7 scenario 리뷰어 정합** — 비-GPU, 스테일 규칙 2건.
4. **§4-3 확인 후** ⑥의 개입을 프롬프트 재작성(비-GPU 스크리닝 가능)과 샘플러 개입 중에서 고른다.
5. **14.2 어포던스** — §4-2 결정 후. 14.1의 세트가 있으면 메타데이터로 내려간다.
6. **Kulal/InsHuman 계열은 마지막** — §4-1이 미해결이고 신규 모델 도입은 이 박스의 16GB VRAM
   제약과 충돌할 수 있다. 도입 전 반드시 버전·리소스 실측.
</content>
</invoke>
