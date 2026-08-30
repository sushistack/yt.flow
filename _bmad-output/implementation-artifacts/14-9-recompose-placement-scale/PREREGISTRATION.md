# 사전등록 — Story 14.9 recompose 배치·척도 3-arm

작성/커밋 시각: **2026-08-30**, **어떤 arm도 렌더되기 전, 어떤 점수도 보기 전.**
baseline revision `590db09`. 이 문서의 기준은 **결과를 본 뒤에 다시 쓰지 않는다.**

---

## 1. 무엇을 재는가

`_DEPTH_PHRASE["near"]` 한 줄의 편집이 **픽셀에서 실재하는 차이를 만드는가.**
편집 내용과 채택 이유는 `candidates.md`(같은 디렉터리, 이 문서와 같은 커밋)에 고정돼 있다.

- 편집 **전** `near`: `in the foreground close to camera, his whole body from head to feet visible in frame`
- 편집 **후** `near`: `in the foreground, his whole body from head to feet visible in frame`
- `mid` / `far` 는 **건드리지 않는다.**

## 2. 표적 7샷과 그 안의 분할

run `4b35c0ed-8a1e-4448-8594-11bd9997376d`. 14.2 인계 3건과 2026-08-30 Jay 블라인드 판정의
합성 부류 5건의 합집합.

| 샷 | 패스별 depth | 이 편집이 닿는가 |
|---|---|---|
| `S00105` | SCP-049 **near** | ✅ |
| `S00504` | SCP-049 mid · STOCK-d-class **near** | ✅ (2패스 중 1) |
| `S00802` | SCP-049 mid · SCP-049-2 **near** | ✅ (2패스 중 1) |
| `S00803` | SCP-049 **near** | ✅ |
| `S00702` | STOCK-researcher far · SCP-049-2 mid | ❌ **무효 대조군** |
| `S00800` | SCP-049 mid · SCP-049-2 mid | ❌ **무효 대조군** |
| `S00904` | SCP-049 mid | ❌ **무효 대조군** |

**처치 4샷 / 무효 대조군 3샷.** 무효 대조군에서는 arm B와 arm C의 지시문이 **바이트 동일**하고
시드도 워크플로도 같으므로, 그 3샷에서 보이는 B↔C 차이는 전부 **렌더 비결정성**이다. 그것이 이
실험의 **노이즈 하한**이며 이 사전등록의 veto 축이다.

## 3. 세 arm

| arm | 무엇 | 시드 | 지시문 |
|---|---|---|---|
| **A** | 출하된 프레임. `workspace/<run>/recomposed/` 에서 **읽기만** 한다 | 원 런의 `seed=0` | 편집 전 |
| **B** | 지금 **다시 뽑은** 프레임 | **20260830** | 편집 전 |
| **C** | 편집 후 프레임 | **20260830 (B와 동일)** | 편집 후 |

- **B가 존재하는 이유:** A↔C만 비교하면 "다시 뽑기 노이즈"가 편집 공로로 계상된다
  (`gotcha_regeneration-needs-a-same-prompt-control`, +7.14pp 전례). B가 그 다리다.
- **B와 C는 같은 워크플로 파일 하나**(`data/workflows/comfyui_shot_recompose_qwen_seed20260830.json`)를
  공유한다. 시드 레버가 코드에 없어 파일 복사가 유일한 방법이다.
- **세 arm 모두 같은 리프레이밍 체인**을 통과한다:
  `video._zoompan_filter(video._FUSION_STILL_SPEC, 1.0)` → 1920×1080. 해상도·크롭으로 arm이
  식별되면 블라인드가 아니다.

## 4. Block If — 렌더 전에 통과해야 하는 것

1. **digest 재현.** arm A 파일명의 16-hex가 깨끗한 플레이트 + 재해결 카드 경로로 재계산돼야 한다.
   불일치 샷은 **arm A가 B의 대조가 아니므로** 명시 제외한다. 7샷 전부 불일치면 HALT.
2. **ComfyUI 프리플라이트** 1회 통과(`recompose_service._preflight`).
3. 채택 문구가 **부정 절을 추가**하는 형태이면 HALT — `candidates.md` §2에서 이미 배제됨.

## 5. 판정 절차 — 사람이 한다

- 산출물: `blind_sheet.jpg` — 7행 × 3열 = **21타일**. 각 행이 한 샷, 행 안의 **arm 순서는 샷마다
  치환**되고 그 치환은 `sheet_key.json` 에만 있다. 타일 각인은 **blind id 12-hex 뿐**이다
  (shot_id도, arm 이름도, 가설도 찍지 않는다).
- Jay에게 묻는 것은 **두 문항, 이 순서로**:
  - **Q1 (열린 문항, 먼저).** "각 행에서 이상하게 보이는 타일이 있으면 그 blind id와 이유."
  - **Q2 (척도 문항, 나중).** "각 행에서 **인물의 크기가 방의 척도와 맞는** 타일의 blind id.
    없으면 '없음', 여럿이면 전부."
- Q1이 먼저인 이유: 척도를 먼저 물으면 판정기가 척도에 고정된다
  (`gotcha_a-prompt-derived-question-is-a-leading-question`).
- **Claude는 이 시트에 라벨을 붙이지 않는다.** 이 에픽에서 Claude 단독 시각 라벨은 사람 판정에
  **세 번** 뒤집혔다(14.2 인계 2건 · 14.2 미검출 1건 · 14.3 `S00105`).

## 6. 성공 기준 — 지금 고정한다

Q2의 응답을 처치 4샷(`S00105` `S00504` `S00802` `S00803`)에 대해 집계한다. 한 샷에서
"C가 낫다" 는 **C 타일이 척도 적합으로 선택되고 B 타일은 선택되지 않은 경우**로만 센다.

| 판정 | 조건 |
|---|---|
| **채택 방향 (SHIP)** | 처치 4샷 중 **≥3샷**에서 C가 낫고, **veto가 발동하지 않음** |
| **기각 (REVERT)** | 처치 4샷 중 **≤1샷**에서만 C가 낫다 |
| **미결 (UNDECIDED)** | 그 사이(2샷). 다음 반복에서 표본을 키우거나 `candidates.md` §4의 후보C로 간다 |

**VETO (위 셋을 모두 무효화).** 무효 대조군 3샷에서 Jay가 B와 C를 **2샷 이상** 갈라내면
(즉 지시문이 바이트 동일한데도 척도 판정이 갈리면), 편집 효과 크기가 렌더 비결정성과 같은
급이라는 뜻이다. 이 경우 결론은 **"결론 없음 — 표본 부족"** 이며 SHIP을 쓰지 않는다.

**n=4는 유의성을 낼 수 없다.** 이것은 게이트가 아니라 **스크리닝**이다. SHIP은 "고쳐졌다"가
아니라 "이 방향으로 다음 E2E iteration에 태울 근거가 생겼다"를 뜻한다.

## 7. 재산출 — 커맨드와 표본 밴드

측정치는 표본 밴드·재산출 커맨드와 함께 남긴다(`gotcha_a-measurement-without-its-sample-band`).

```
# digest 게이트 (GPU 0, LLM 0) — 7샷의 16-hex 재현
uv run python _bmad-output/implementation-artifacts/14-9-recompose-placement-scale/run_arms.py digest-gate

# arm A 퍼블리시 (GPU 0 — recomposed/ 를 읽기만 한다)
uv run python _bmad-output/implementation-artifacts/14-9-recompose-placement-scale/run_arms.py render --arm a

# arm B·C 렌더 (GPU: 22패스)
uv run python _bmad-output/implementation-artifacts/14-9-recompose-placement-scale/run_arms.py render --arm b --arm c

# 블라인드 시트
uv run python _bmad-output/implementation-artifacts/14-9-recompose-placement-scale/blind_sheet.py
```

- **표본 밴드:** 7샷 · arm당 11 recompose 패스(near 4 · mid 6 · far 1) · arm B와 C 합계 22패스.
  판정 표본은 처치 4샷 · 무효 대조군 3샷.
- **비용 밴드:** 2026-08-30 실측 12~17 s/패스(ComfyUI 0.12.3, gfx1100 24 GB, ROCm 7.1,
  `--lowvram --cache-lru 10`). 22패스 ≈ 5~7분.

## 8. Never — 이 실험이 하지 않는 것

- `workspace/4b35c0ed…/recomposed/` 에 **쓰지 않는다.** 그 디렉터리가 arm A의 유일한 사본이다.
  렌더 전후로 파일 수 + `(name, size, mtime_ns)` 정렬 목록의 sha256을 찍어 대조한다.
- `recompose_service.recompose_run_shots` 로 B·C를 렌더하지 **않는다.** digest가 프롬프트도 시드도
  해싱하지 않아 캐시 히트로 **arm C가 조용히 arm A가 된다.**
- `scripts/score_shot_narration.py` 의 `BLIND_PROMPT` 를 쓰지 **않는다.** 거기 박힌 `_CARD_NOTE`가
  *"인물 부재는 결코 결함이 아니다"* 라고 말해 접지·척도 질문에 적대적이다.
- 부정 프롬프트를 늘리지 **않는다.** recompose의 negative는 의도적으로 비어 있다.
- 사람 판정 전에 **"고쳤다"를 쓰지 않는다.**
