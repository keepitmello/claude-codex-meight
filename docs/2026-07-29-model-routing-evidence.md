# 모델 라우팅 근거 — 2026-07-29 실측

> 이 문서는 라우팅 정책의 **근거**다. 정책 자체는 `skills/meight/SKILL.md`와
> `CLAUDE.md`/`AGENTS.md`에, 결정 경위는 `decisions/`에 있다. 여기 수치가
> 바뀌면 그 문서들의 판단도 다시 본다.
>
> 원문 증거: [`evidence/2026-07-29-consult-model-comparison.md`](evidence/2026-07-29-consult-model-comparison.md)
> (질문 패킷은 같은 디렉토리의 `-packet.md`). 출처는 GPT-5.6 Pro consult +
> 디스패처 직접 검증.

## 1. 공개 벤치마크 — Sol / Opus 5 / Fable 5

Artificial Analysis Coding Agent Index v1.3, 2026-07-29 조회. **디스패처가
원본 페이지를 직접 열어 아래 수치를 확인함** (consult 인용값과 일치).

| | Codex + Sol (max) | Claude Code + Opus 5 (xhigh) | Claude Code + Fable 5 (max) |
|---|---|---|---|
| Coding Agent Index | **67** | **67** | 66 |
| DeepSWE (장범위 구현) | **69%** | 60% | 66% |
| Terminal-Bench v2 | **88%** | 85% | 83% |
| SWE-Atlas-QnA (레포 이해) | 43% | **55%** | 49% |
| 태스크당 비용 | **$7.08** | $8.23 | $11.71 |

출처: <https://artificialanalysis.ai/agents/coding-agents/comparisons/claude-code-vs-codex>

보조 지표 (consult 인용, 디스패처 미검증):

| 축 | Sol | Opus 5 | Fable 5 | 출처 |
|---|---|---|---|---|
| SWE-bench Verified | 96.2% | 97.0% | 95.0% | Vals AI, 2026-07-22 |
| HiL-Bench (정보 부족 시 질문) | 32.3 | **57.0** | 56.3 | Scale Labs |
| WebDev Arena (실동작 프론트) | 1623 | **1712** | 1628 | arena.ai, 2026-07-28 |
| AA-Briefcase (리서치 종합) | 1505 | **1720** | 1574 | Artificial Analysis, 2026-07-24 |
| Design Arena (시각 취향) | 1357 | 1357 | 1342 | 2차 미러 — 신뢰 등급 낮음 |

## 2. 결론 — 축은 영역이 아니라 단계

"백엔드는 Codex, 프론트는 Claude"는 공개 실측이 절반만 지지한다. 실제로
갈리는 축은 **작업의 단계**다.

- **Sol = 실행·수렴형.** 요구사항이 닫혀 있고 테스트나 verifier가 완료를
  선언하며, 구현→실행→수정을 반복하는 그라인드 (DeepSWE 69 vs 60,
  Terminal-Bench 88 vs 85).
- **Opus 5 = 이해·진단·종합형.** 낯선 레포 읽기, 아무도 이름 붙이지 않은
  원인 진단, 얇은 스펙이 빠뜨린 것을 질문하기, 실제로 도는 프론트엔드, 리서치
  종합 (SWE-Atlas-QnA 55 vs 43, HiL-Bench 57 vs 32, WebDev Arena 1712 vs 1623).

백엔드/프론트는 2차 조건이다 — 원인 모를 백엔드 버그는 Opus에서 시작하고,
스펙이 닫힌 UI는 Codex가 마무리해도 된다.

## 3. Fable 5 — 난도만으로 승격하지 않는다

Opus 5의 2배 정가, 실측 태스크 비용 1.4배인데 종합 66 대 67이다. Fable이
Opus를 앞선 주요 축은 DeepSWE(+3%p) 하나뿐이고 그마저 Sol이 69로 더 높다.
Terminal-Bench, SWE-Atlas-QnA, SWE-bench Verified, WebDev Arena, AA-Briefcase는
모두 Opus가 앞선다.

따라서 "판단이 무거우면 Fable"은 근거가 없다. 승격에는 그 작업 종류에서
값을 했다는 별도 이유가 필요하다.

## 4. 측정 공백 — 벤치마크로 결론을 낼 수 없는 축

- **진짜 UX 판단**: 공개 arena는 완성된 화면의 선호를 재지, user research,
  정보 구조, 접근성, task completion을 재지 않는다.
- **장기 유지보수성**: 대부분의 벤치는 한 번의 패치와 즉시 통과를 본다.
- **코드리뷰 품질**: finding의 정확도·중요도·중복률을 최신 3모델로 비교한
  공개 벤치가 없다.
- **며칠짜리 자율성**: Terminal-Bench는 터미널 역량이지 장기 계획 유지가 아니다.
- **창의성과 큰 그림 읽기**: 재는 벤치가 없다. 운영자 관측으로는 Fable이
  Opus보다 낫다 — 이 축에서의 Fable 승격은 실사용 관측이 유일한 근거다.
- **`luna` 전반**: 어떤 공개 벤치에도 `luna` row가 없다. 위 Sol 수치를
  `luna`에 그대로 적용할 수 없다.

## 5. worker 기본값 — `luna xhigh` → `luna max` (결정)

같은 Coding Agent Index v1.3의 **설정별** row. 디스패처가 원본에서 직접 확인.

| 설정 | Index | DeepSWE | Terminal-Bench v2 | SWE-Atlas-QnA | $/task | 시간 | 토큰 |
|---|---|---|---|---|---|---|---|
| `luna xhigh` (구 기본) | 55 | 57% | 76% | 31% | $1.26 | 6.6분 | 12.3M |
| **`luna max` (신 기본)** | **59** | **63%** | **80%** | 33% | $1.57 | 8.0분 | 15.5M |
| `sol medium` | 61 | 64% | 78% | **40%** | $2.99 | 5.2분 | 5.8M |

`xhigh` → `max`는 비용 +25%로 종합 +4점, DeepSWE +6%p — 한계수익이 분명해서
기본값이 여기 있다. 거기서 `sol medium`까지는 비용이 다시 1.9배인데 종합은
+2점뿐이다. `sol medium`이 확실히 앞서는 자리는 레포 이해·탐색(QnA 40 대 33)
이고, 그래서 사다리에서 판단이 걸릴 때 올리는 대상으로 남는다.

운영자가 처음 제시한 `49 / 0.14`, `54 / 0.31`은 **Intelligence Index v4.1**과
그 평가 과제당 가중평균 API 비용(USD)이었다 — Coding Agent Index의 태스크당
비용과 다른 축이므로 섞어 쓰지 않는다. (`luna max`는 Intelligence Index 51 /
$0.21.)

`luna xhigh`를 기본에서 내린 배경:

1. `sol medium`은 07-14 v3 이전의 원래 기본값이었고, `luna xhigh`로 바꾼
   근거는 실전 **2건**과 "luna는 판단 가능한 모델"이라는 추정이었다
   (`2026-07-14-v3-pipeline-retrospective.md`). 그 2건 중 하나는 후속
   NO-GO의 원인을 제공했고, luna가 만든 문서↔런타임 drift가 적대 리뷰에서
   적발됐다.
2. 그때 sol이 남긴 잔여 반론 — "라우팅은 dispatcher가 acceptance-critical
   의존을 사전 식별하는 데 의존한다" — 이 2026-07-29 하드게이트 목록 폐지로
   더 얇아졌다. 판단에 더 의존하는 구조라 워커의 에스컬레이션 품질이 더 중요해졌다.
3. `QUESTION:` 품질의 직접 실측은 어느 모델에도 없다. HiL-Bench에 `luna` row가
   없고, 공개된 `sol` 수치(32.33±5.49)도 ASK-F1이 아니라 `ask_human()` 가용
   조건의 task outcome이다. 벤치 전체 결론도 냉정하다 — 최고 combined ASK-F1이
   44% 수준, SWE task blocker recall 최고치가 36%다. **모델 선택으로 삭제한
   백스톱을 대신했다고 볼 수 없다.**

남은 baseline 공백: `luna`의 실제 실패율·승격률. 공개 벤치가 답할 수 없는
영역이라 로컬 관측이 쌓여야 한다.
