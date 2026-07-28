웹 검색까지 해서 **2026년 7월 29일 KST 기준** 공개 자료를 맞춰봤어. 패킷에서 정한 8개 작업 축과 “벤더 발표·독립 평가 분리, 근거 없는 축은 근거 없다고 명시”라는 조건을 그대로 따랐어. 

## 먼저 결론

현재 공개 실측은 기존 라우팅 문구를 **절반만 지지해**.

* **Sol/Codex는 구현·터미널 실행·검증 그라인드에서 강하다.** `DeepSWE`와 `Terminal-Bench v2`에서 앞서.
* **Opus 5는 저장소 이해·불명확한 문제 진단·SWE-bench형 버그 수정·실동작 frontend·research synthesis에서 강하다.**
* **시각 디자인 취향은 더 이상 “Claude 고정 우위”가 아니다.** `Design Arena` 전체 점수는 Opus 5와 Sol이 동률이고, 세부 카테고리별로 서로 갈린다.
* **Fable 5는 비싼 만큼 전반적으로 더 좋은 모델이 아니다.** 공개 수치만 보면 “판단이 무거우면 Fable”이라는 기본 라우팅은 근거가 약해. `DeepSWE`형 장기 구현에서 Opus보다 조금 높지만 Sol보다 낮고, frontend·repository comprehension·research에서는 오히려 Opus 5가 더 좋다.
* 전체 종합점수도 `Artificial Analysis Coding Agent Index v1.3`에서 **Sol 67, Opus 5 xhigh 67, Fable 5 66**이라 사실상 동률이야. 다만 내부 구성은 완전히 다르다. ([Artificial Analysis][1])

---

# 1. 비교한 모델 버전

| 답변에서 쓰는 이름         | 실제 공개 평가 대상                                       | 주의점                                                                                                                                                                                                                                                                                                            |
| ------------------ | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **GPT-5.6 Sol**    | 주로 `Codex + GPT-5.6 Sol (max)`, WebDev에서는 `xhigh` | `GPT-5.6 Sol Pro`는 ChatGPT 선택 모드로 공개돼 있지만, 별도 공개 benchmark row는 없어. 따라서 아래 수치는 **Sol max/xhigh를 Sol Pro의 대리 지표**로 쓴 거야. `Ultra`는 여러 agent를 사용하는 orchestration 설정이라 제외했어. GPT-5.6 Sol은 2026년 7월 9일 공개됐고 API 정가는 input $5, output $30/M tokens야. [OpenAI 공식 발표](https://openai.com/index/gpt-5-6/) ([OpenAI][2]) |
| **Claude Opus 5**  | `Claude Code + claude-opus-5`, 주로 max/xhigh       | 2026년 7월 24일 공개. API 정가는 input $5, output $25/M tokens야. [Anthropic 공식 발표](https://www.anthropic.com/news/claude-opus-5) ([Anthropic][3])                                                                                                                                                                      |
| **Claude Fable 5** | `Claude Code + Fable 5 (max)`                     | API 정가는 input $10, output $50/M tokens로 **Opus 5의 정확히 2배**야. production에서는 일부 분야를 Opus 4.8로 fallback하며, Anthropic은 전체 session 중 5% 미만이라고 설명해. 일부 독립 leaderboard도 Fable row를 `with fallback`으로 표시한다. [Anthropic 공식 발표](https://www.anthropic.com/news/claude-fable-5-mythos-5) ([Anthropic][4])                 |

여기서 꽤 중요한 점이 하나 있어. 아래 `Claude Code vs Codex` 비교는 순수 모델만 보는 게 아니라 **모델+하네스 조합**을 재는 평가야. 하지만 네 실제 라우팅도 Claude Code subagent와 Codex CLI worker 사이의 선택이므로, 오히려 사용 사례 대표성은 높은 편이야.

---

# 2. 작업 종류별 실측 표

점수 순서는 전부 **Sol / Opus 5 / Fable 5**야.

| 작업 종류                                    | 최신 공개 수치                                                                                                     | 출처·발표/측정 시점                                                                                                                                                                                                                                                                                                            | 실제 위임 작업 대표성 및 판정                                                                                                                                                                                                                                     |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. 백엔드 로직·알고리즘 구현**                    | `DeepSWE`: **69 / 63 / 66%**. Opus 5는 max 63%, xhigh 60%. Fable은 max, fallback 포함.                           | [Artificial Analysis Coding Agent Index v1.3](https://artificialanalysis.ai/agents/coding-agents/comparisons/claude-code-vs-codex), 2026-07-29 조회, **독립 평가**. ([Artificial Analysis][1]) `DeepSWE`는 91개 open-source repo, 5개 언어에 걸친 113개 장기 구현 과제로 구성돼. [DeepSWE paper](https://arxiv.org/abs/2607.07946) ([arXiv][5]) | **저장소 단위 구현 대표성은 중상**, 순수 알고리즘·DB schema·분산 시스템 architecture 대표성은 낮아. `DeepSWE` reference solution은 기존 SWE-bench Pro보다 훨씬 넓은 코드를 건드리지만, “좋은 backend architecture” 자체를 평가하는 건 아니야. **실행 가능한 구현은 Sol 우위.**                                              |
| **2. 버그 수정 / repository 단위 문제 해결**       | `SWE-bench Verified`: **96.2 / 97.0 / 95.0%**                                                                | [Vals SWE-bench Verified](https://www.vals.ai/benchmarks/swebench), page update 2026-07-22, **독립 평가**. 세 모델 모두 동일한 bash-only `mini-swe-agent` harness와 provider 기본 설정을 사용했어. ([Vals AI][6])                                                                                                                            | **대표성 중간.** 실제 GitHub issue 500개라는 장점은 있지만 Python 중심이고 benchmark가 거의 포화됐어. 과제 대부분이 인간 기준 4시간 미만이고, 4시간 이상은 3개뿐이야. Opus가 명목상 Sol보다 **0.8%p** 높지만 confidence interval이 공개되지 않아 “유의미한 승리”로 보긴 어려워. 그래도 **“버그 수정은 무조건 GPT”는 반박된다.**                       |
| **3. 긴 agentic 실행·터미널 작업**               | `Terminal-Bench v2`: **88 / 85 / 83%**                                                                       | 위와 같은 [AA Coding Agent Index v1.3](https://artificialanalysis.ai/agents/coding-agents/comparisons/claude-code-vs-codex), 2026-07-29 조회, **독립 평가**. ([Artificial Analysis][1])                                                                                                                                          | **terminal-heavy 작업 대표성 중상**, 며칠짜리 자율 실행 대표성은 낮아. 명령 실행·환경 복구·반복 검증에서는 Sol이 Opus보다 3%p, Fable보다 5%p 앞서. **Codex/Sol 우위가 가장 또렷한 축**이야.                                                                                                                 |
|                                          | `Frontier-Bench v0.1`: **34.4 / 43.3 / 33.7%**                                                               | Anthropic의 2026-07-24 Opus 5 발표표, **벤더 자체 측정**. [공식 발표](https://www.anthropic.com/news/claude-opus-5) ([Anthropic][7])                                                                                                                                                                                                 | 더 폭넓고 불명확한 computer-work 과제에서는 반대로 Opus가 앞서. 다만 Anthropic 측정이고 harness 차이가 있으므로 독립 `Terminal-Bench`와 직접 섞으면 안 돼. **명확한 터미널 실행은 Sol, 모호하고 넓은 computer-work는 Opus**라는 분리가 더 정확해.                                                                        |
| **4. frontend 구현 — 실제 동작 React/Next UI** | `WebDev Arena`: **1623±10 / 1712±20 / 1628±10 Elo**. Opus 5 max는 preliminary. Opus 5 high도 1669±13으로 여전히 앞서. | [WebDev Arena](https://arena.ai/leaderboard/code/webdev), 2026-07-28, 총 492,170표 기반 **독립·사람 선호 평가**. ([아레나 AI][8])                                                                                                                                                                                                     | **실제 browser-rendered frontend 대표성 높음.** 다만 유지보수성·accessibility·analytics·대규모 design system 적합성까지 충분히 재지는 않아. **Opus 5가 확실히 우위.** 반면 Fable 1628과 Sol 1623은 오차 범위가 겹쳐 사실상 동률이야. 즉 “Claude 계열 전체가 frontend 우위”가 아니라 **Opus 5가 우위**야.                    |
| **5. UX·visual design 판단**               | `Design Arena – Web Design Overall`: **1357 / 1357 / 1342 Elo**                                              | [Design Arena 원본](https://www.designarena.ai/leaderboard)은 methodology 출처. 현재 정확한 leaderboard 값은 client-side라 [2026-07-27 static mirror](https://benchmarklist.com/arenas/)를 사용했어. 따라서 수치 출처 등급은 **2차 집계**야. ([Design Arena][9])                                                                                       | **시각 결과물 선호 대표성 중간, 진짜 UX 대표성은 낮음.** 단일 HTML 산출물과 Website/UI Component/Data Viz/Game/3D 등의 사람 선호를 주로 재지, user research·information architecture·conversion·task completion은 안 재. **Opus와 Sol 동률이며 Fable이 뒤야. “Claude visual taste 고정 우위”는 유지되지 않는다.** |
| **6. 대규모 refactor / cross-cutting 변경**   | `SWE Atlas Refactoring`: **미측정 / 미측정 / 54.76±6.76**                                                          | [Scale SWE Atlas Refactoring](https://labs.scale.com/leaderboard/sweatlas-refactoring), 2026-07-29 조회, **독립 평가**. 페이지에 개별 run date는 표시되지 않아. 70개 과제, 10개 production repo, 6개 언어를 포함해. ([Scale Labs][10])                                                                                                               | Benchmark 자체는 이 축을 **상당히 잘 대표**해. 불명확한 고수준 지시, 여러 파일 수정, 기존 테스트 유지, cleanup과 문서화를 평가하거든. 문제는 최신 Opus 5와 Sol row가 아예 없다는 거야. **현재 세 모델 승자를 말할 근거가 없다.** 대리 지표상 repository 이해는 Opus, 구현 실행은 Sol로 갈린다.                                                   |
| **7. 테스트 작성과 검증**                        | `SWE Atlas Test Writing`: **미측정 / 미측정 / 58.52±5.96**                                                         | [Scale SWE Atlas Test Writing](https://labs.scale.com/leaderboard/sweatlas-tw), 2026-07-29 조회, **독립 평가**. 90개 과제, 11개 production repo, 4개 언어. mutation testing과 rubric을 함께 사용해. ([Scale Labs][11])                                                                                                                     | Benchmark 대표성은 **높은 편**이지만, 이번에도 최신 Sol·Opus 5 점수가 없어 비교 불가야. `SWE-bench`나 `DeepSWE`는 테스트를 돌리며 구현하는 능력의 대리 지표일 뿐, 좋은 unit/integration/acceptance test를 설계하는 능력과 동일하지 않아. **Fable이 현재 leaderboard 선두라는 사실만 있고, 세 모델 중 승자라는 결론은 못 내려.**                 |
| **8. research·문서 종합**                    | `AA-Briefcase`: **1505 / 1720 / 1574 Elo**                                                                   | [Artificial Analysis AA-Briefcase](https://artificialanalysis.ai/articles/claude-opus-5-leader-agentic-knowledge-work), 2026-07-24, **독립 평가**. 대량 입력 파일에서 report·presentation·spreadsheet 같은 최종 deliverable을 만드는 과제야. ([Artificial Analysis][12])                                                                      | **네가 consult agent에 맡기는 research·문서 종합과 대표성이 높아.** 다만 task set이 private라 완전한 재현성은 낮아. Opus가 Fable보다 146 Elo, Sol보다 215 Elo 앞서며 **Opus 5가 명확한 기본값**이야. 단 presentation-only 항목은 Sol 1666, Opus 1628로 Sol이 앞서므로 시각적 마감 pass는 분리할 여지가 있어.                 |

---

# 3. “Claude가 UX·frontend에서 앞선다”는 지금도 맞나?

## Frontend 구현: **Opus 5에 한해 맞아**

`WebDev Arena`에서는 Opus 5가 확실하게 앞서. 더 비싼 max 설정뿐 아니라 Opus 5 high도 1669±13으로 Fable 1628±10, Sol 1623±10보다 높아. 따라서 실제 React/Next 페이지를 만들고 browser 결과를 비교하는 작업은 지금도 **Opus 5 우선**이 합리적이야. ([아레나 AI][8])

그런데 여기서 **Claude 전체로 일반화하면 틀려**. Fable과 Sol은 각각 1628, 1623으로 거의 같아. “판단이 더 무거우니 Fable을 frontend에 투입”하는 건 실측상 오히려 Opus 5보다 손해일 가능성이 커.

## Visual design: **격차가 사라졌고 카테고리별로 뒤집혀**

`Design Arena`의 전체 점수는 Opus 5와 Sol이 똑같이 1357이고, Fable이 1342야. 세부 항목은 다음처럼 갈려. 다만 이 정확한 수치는 2차 static mirror이므로 신뢰 등급은 WebDev Arena보다 낮게 봐야 해. ([BenchmarkList][13])

| Design Arena 세부 축  |  Sol | Opus 5 | Fable 5 | 명목상 선두      |
| ------------------ | ---: | -----: | ------: | ----------- |
| Website            | 1345 |   1336 |    1325 | Sol         |
| UI Component       | 1374 |   1391 |    1355 | Opus 5      |
| Data Viz           | 1355 |   1379 |    1347 | Opus 5      |
| Web Design Overall | 1357 |   1357 |    1342 | Sol·Opus 동률 |

따라서 현재 세대에 맞는 문장은 이거야.

> **Opus 5는 agentic frontend 구현에서 강하지만, visual taste 자체는 Sol과 카테고리별로 갈리며 Claude 고정 우위가 아니다.**

그리고 “UX”라는 단어를 visual design과 섞어 쓰면 안 돼. 공개 arena는 만들어진 화면을 보고 “어느 쪽이 더 낫나”를 고르게 하지, 사용자의 문제 발견, task flow 검증, IA, 접근성, conversion, 장기 usability를 제대로 측정하지 않아. **진짜 UX 판단의 세 모델 비교 benchmark는 현재 없다고 보는 게 맞아.**

---

# 4. “백엔드·debugging은 GPT-5.6이 앞선다”는 맞나?

## 구현·터미널 실행: **맞아**

독립 평가에서 Sol은:

* `DeepSWE`: 69%, Opus max 63%, Fable 66%
* `Terminal-Bench v2`: 88%, Opus 85%, Fable 83%

이므로, 요구사항이 이미 닫혀 있고 test나 verifier가 있으며 terminal에서 구현→실행→수정→재검증을 반복하는 작업은 Sol/Codex가 우세해. ([Artificial Analysis][1])

## 버그 원인 진단·repository 이해: **아니야**

같은 `AA Coding Agent Index`의 `SWE-Atlas-QnA`는 다음과 같아.

* Sol max: **43%**
* Opus 5 xhigh: **55%**
* Fable 5: **49%**

Opus가 Sol보다 12%p 높아. 이 benchmark는 코드를 직접 고치는 것보다 repository를 읽고 구조·동작을 정확히 파악하는 쪽에 가깝다. ([Artificial Analysis][1])

또 `HiL-Bench`에서는 “필수 정보가 빠졌을 때 바로 작업하지 않고 유용한 질문을 하는가”를 평가하는데:

* Sol: **32.33±5.49**
* Opus 5: **57.00±5.48**
* Fable 5: **56.33±5.50**

였어. 불명확한 요구사항이나 재현 조건을 찾아내고 사용자에게 질문해야 하는 상황에서는 Claude 계열이 훨씬 앞서. Opus와 Fable 차이는 0.67%p라 사실상 없어. [Scale HiL-Bench](https://labs.scale.com/leaderboard/hil) ([Scale Labs][14])

`SWE-bench Verified`에서도 Opus 97.0%, Sol 96.2%라 Sol 우위가 아니야. 다만 둘의 차이가 작고 benchmark가 포화됐으므로, 이걸 “Opus가 디버깅 전체에서 우월하다”고 확대하면 그것도 틀려. ([Vals AI][6])

그러니까 debugging을 한 덩어리로 잡지 말고 이렇게 둘로 쪼개야 해.

| Debugging 단계                                               | 더 강한 쪽               | 근거                              |
| ---------------------------------------------------------- | -------------------- | ------------------------------- |
| 재현 조건 탐색, repository 이해, root-cause hypothesis, 누락 요구사항 질문 | **Opus 5**           | SWE-Atlas-QnA, HiL-Bench        |
| patch 구현, terminal 반복 실행, test failure를 따라가며 수정            | **Sol/Codex**        | DeepSWE, Terminal-Bench         |
| 정형화된 GitHub issue 해결                                       | **사실상 동률, 명목상 Opus** | SWE-bench Verified 97.0 vs 96.2 |

---

# 5. Fable 5가 Opus 5보다 값을 하는 자리는 어디인가?

공개 수치만 보면 꽤 냉정하게 말해야 해.

## Fable이 Opus보다 앞선 직접 비교

| 축                                    | Fable 5 | Opus 5 |                   차이 |
| ------------------------------------ | ------: | -----: | -------------------: |
| DeepSWE                              |      66 | 63 max |           Fable +3%p |
| FrontierCode v1.1 Main, Anthropic 측정 |    53.5 |   53.4 | Fable +0.1%p, 사실상 동률 |

`DeepSWE`형으로 범위가 넓은 구현을 오래 밀어붙이는 작업에서는 Fable이 Opus max보다 조금 높아. 하지만 그 자리에서도 Sol이 69로 더 높아. `FrontierCode`의 0.1%p 차이는 의미 있는 우위로 보기 어려워. ([Artificial Analysis][1])

## Opus가 Fable보다 앞서는 직접 비교

| 축                                 |               Opus 5 | Fable 5 |                 차이 |
| --------------------------------- | -------------------: | ------: | -----------------: |
| Terminal-Bench v2                 |                   85 |      83 |          Opus +2%p |
| SWE-Atlas-QnA                     |             55 xhigh |      49 |          Opus +6%p |
| SWE-bench Verified                |                   97 |      95 |          Opus +2%p |
| WebDev Arena                      | 1712 max / 1669 high |    1628 | Opus +84 / +41 Elo |
| AA-Briefcase                      |                 1720 |    1574 |      Opus +146 Elo |
| Frontier-Bench v0.1, Anthropic 측정 |                 43.3 |    33.7 |        Opus +9.6%p |

즉 Fable은 “더 크고 비싸니까 어려운 판단에 넣는 상위 tier”가 아니라, **특정 task distribution에서만 강점이 나타나는 별도 성향 모델**로 봐야 해. ([Vals AI][6])

비용도 만만치 않아.

* API list price는 Fable이 Opus의 **2배**.
* 실제 `AA Coding Agent Index` 평균 task cost는 Fable **$11.71**, Opus xhigh **$8.23**, Opus max **$8.95**였어.
* 실제 agent task 기준으로도 Fable이 각각 약 **1.42배, 1.31배** 비쌌는데 종합점수는 Fable 66, Opus xhigh 67, Opus max 66이야. ([Artificial Analysis][1])

### 판정

**“판단이 무거우면 Fable”은 폐기하는 게 맞아.**

현재 공개 근거로 Fable을 쓸 만한 자리는 다음처럼 아주 좁아.

1. `DeepSWE`와 닮은 장범위 구현인데 Sol을 쓰기 어렵고, 내부 A/B에서 Opus보다 개입 횟수가 실제로 줄어든 경우.
2. `SWE Atlas Refactoring`이나 `Test Writing`과 정확히 닮은 작업. 단, 현재는 최신 Sol·Opus 5 비교값이 없으므로 Fable 우위라고 확정하면 안 돼.
3. Opus 5가 반복적으로 실패한 고가치 작업에 대한 **escalation trial**.

반대로 frontend, repository comprehension, research synthesis, 애매한 요구사항 해석에는 Fable 대신 Opus 5가 더 싸고 더 강해.

그리고 Fable은 production fallback이 섞일 수 있으므로, 보안·cyber 관련 결과에서는 실제 응답 모델이 순수 Fable인지까지 기록해야 해. ([Anthropic][4])

---

# 6. 공개 benchmark가 부족한 축

| 부족한 축                                                 | 왜 현재 benchmark로 결론을 못 내리는가                                                                                             | 쓸 수 있는 대리 지표                                                       |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| **backend architecture·domain modeling·algorithm 설계** | `DeepSWE`는 구현 성공을 재지만 schema evolution, distributed consistency, API boundary 품질, 복잡도 선택의 장기 비용을 직접 평가하지 않아.           | DeepSWE + 내부 architecture review rubric + hidden integration tests |
| **며칠짜리 agent 자율성**                                    | Terminal-Bench는 terminal competence이지 며칠 동안 context와 계획을 유지하는 능력 자체는 아니야. vendor의 “long horizon” 주장도 동일 환경 독립 비교가 부족해. | Terminal-Bench + Frontier-Bench + 내부 4~8시간 unattended run          |
| **진짜 UX 판단**                                          | WebDev/Design Arena는 결과물 선호 평가에 가깝고 user research, IA, accessibility, task completion을 안 재.                            | WebDev Arena + 실제 사용자 task completion + accessibility audit        |
| **대규모 refactor 최신 3자 비교**                             | 가장 직접적인 `SWE Atlas Refactoring`에 Fable만 있고 Sol·Opus 5가 없어.                                                             | SWE-Atlas-QnA로 이해력, DeepSWE로 구현력 분리 측정                             |
| **test 설계 최신 3자 비교**                                  | `SWE Atlas Test Writing`에 Fable만 있어. SWE-bench 성공은 test 작성 품질과 달라.                                                     | mutation score, bug-seeding recall, flaky-test rate를 내부 평가         |
| **장기 maintainability**                                | 공개 benchmark는 대부분 한 번의 patch와 즉시 verifier 통과를 본다. 3개월 뒤 수정 용이성이나 팀 convention 적합성을 못 재.                                | 후속 change task, review defect count, rollback rate                 |
| **code review 품질**                                    | finding의 정확도·중요도·중복률을 최신 세 모델로 동일 비교한 공개 benchmark가 부족해.                                                               | seeded defects + precision/recall + human severity rating          |

---

# 7. 기존 8개 분류는 라우팅 기준으로 적절한가?

**보고서 목차로는 괜찮지만 router의 1차 분류로는 별로야.**

이유는 서로 다른 종류의 축을 한 줄에 섞었기 때문이야.

* backend/frontend는 **제품 표면**
* bugfix/refactor/test는 **작업 연산**
* long agentic은 **시간·범위**
* research/document는 **산출물 형태**
* UX는 **평가 oracle이 사람 선호인지 여부**

예를 들어 “Next.js 결제 화면의 상태 관리 버그를 5시간 동안 repository 전체 refactor로 고친다”는 작업은 frontend, bugfix, long agentic, refactor, test에 동시에 걸려. 단일 category router로는 충돌이 날 수밖에 없어.

## 더 나은 라우팅 축

| 축                  | 값의 예                                                | 라우팅에 주는 영향                                        |
| ------------------ | --------------------------------------------------- | ------------------------------------------------- |
| **1. Oracle 명확성**  | unit test·typecheck·verifier로 닫힘 / 사람 판단 필요         | 명확할수록 Sol, 주관적·불명확할수록 Opus                        |
| **2. 현재 단계**       | 이해·진단·계획 / 구현·실행 / 검토·평가 / 종합·문서화                   | 이해·진단·종합은 Opus, 구현·실행은 Sol                        |
| **3. 범위와 horizon** | 함수 / module / repo / cross-repo / 장시간 autonomous    | 범위가 커질수록 별도 planning pass와 checkpoint 필요          |
| **4. 요구사항 불확실성**   | 명세 완결 / 누락 가능 / 사용자 질문 필요                           | 질문·정의가 필요하면 Opus 우선                               |
| **5. 실행 환경**       | terminal / browser UI / MCP·SaaS / GUI computer use | terminal은 Sol, browser frontend는 Opus가 강한 경향      |
| **6. 검토 위험**       | 쉽게 rollback / 금전·보안·migration 위험                    | 고위험이면 단일 모델 승자보다 model diversity와 reviewer 분리가 중요 |
| **7. 산출물 평가 방식**   | compile·test / human preference / factual accuracy  | benchmark도 같은 oracle을 쓰는 걸 선택해야 함                 |

---

# 8. 실제 라우팅 권고

| 작업 signature                                       | 기본 worker                | 이유                                   |
| -------------------------------------------------- | ------------------------ | ------------------------------------ |
| 요구사항이 닫혀 있고 test가 있으며 terminal에서 구현·수정·검증을 반복      | **Codex + Sol**          | DeepSWE·Terminal-Bench 우위            |
| 원인이 불명확하고 repository 구조부터 파악해야 함                   | **Claude Code + Opus 5** | SWE-Atlas-QnA 우위                     |
| 요구사항 누락 가능성이 높고 먼저 질문해야 함                          | **Opus 5**               | HiL-Bench 우위                         |
| 실제 React/Next frontend 구현                          | **Opus 5**               | WebDev Arena 명확한 우위                  |
| 순수 visual exploration·landing page concept         | **Opus 5와 Sol A/B**      | Design Arena 전체 동률, category별 승자가 다름 |
| research·대량 문서 종합·보고서                              | **Opus 5**               | AA-Briefcase 큰 격차                    |
| terminal-heavy 구현 뒤 architecture·regression review | **Sol 구현 → Opus review** | 각 모델의 강점을 단계별로 분리                    |
| “매우 어려워 보임”이라는 이유만 있는 escalation                   | **Fable로 바로 보내지 않음**     | 비용 대비 광범위 우위 없음                      |
| Fable 특화 가능성이 내부 실측으로 확인된 DeepSWE형 장기 구현           | **Fable trial**          | 공개 근거상 유일하게 Opus보다 앞선 주요 coding 축    |

---

# 최종 수정 문구

현재 라우팅 문서의 기존 문장 대신 이 정도가 실측에 더 잘 맞아.

> **Codex/Sol은 test나 verifier로 성공 조건이 닫힌 terminal-heavy 구현·수정·검증에 강하다. Claude/Opus 5는 repository 이해, 불명확한 요구사항과 root-cause 진단, human-in-the-loop 질문, agentic frontend 구현, research synthesis에 강하다. Visual design은 벤더별 고정 우위가 아니므로 Opus와 Sol을 결과물 기준으로 비교한다. Fable 5는 난도만으로 자동 승격하지 않고, task-specific evaluation에서 Opus 대비 비용 이상의 개선이 확인될 때만 escalation한다.**

그래서 기존의 **“Codex=backend, Claude=frontend”**보다 정확한 핵심 구분은 이거야.

> **Sol은 실행·수렴형, Opus 5는 이해·진단·종합형이다. Backend와 frontend라는 영역 구분은 2차 조건일 뿐이다.**

[1]: https://artificialanalysis.ai/agents/coding-agents/comparisons/claude-code-vs-codex "https://artificialanalysis.ai/agents/coding-agents/comparisons/claude-code-vs-codex"
[2]: https://openai.com/index/gpt-5-6/ "https://openai.com/index/gpt-5-6/"
[3]: https://www.anthropic.com/news/claude-opus-5 "https://www.anthropic.com/news/claude-opus-5"
[4]: https://www.anthropic.com/news/claude-fable-5-mythos-5 "https://www.anthropic.com/news/claude-fable-5-mythos-5"
[5]: https://arxiv.org/abs/2607.07946 "https://arxiv.org/abs/2607.07946"
[6]: https://www.vals.ai/benchmarks/swebench "https://www.vals.ai/benchmarks/swebench"
[7]: https://www.anthropic.com/_next/image?q=75&url=https%3A%2F%2Fwww-cdn.anthropic.com%2Fimages%2F4zrzovbb%2Fwebsite%2Fa8fb4f77a9fe240e6f27f3bdc47a137f3c74a29d-2600x2578.png&w=3840 "https://www.anthropic.com/_next/image?q=75&url=https%3A%2F%2Fwww-cdn.anthropic.com%2Fimages%2F4zrzovbb%2Fwebsite%2Fa8fb4f77a9fe240e6f27f3bdc47a137f3c74a29d-2600x2578.png&w=3840"
[8]: https://arena.ai/leaderboard/code/webdev "https://arena.ai/leaderboard/code/webdev"
[9]: https://www.designarena.ai/leaderboard "https://www.designarena.ai/leaderboard"
[10]: https://labs.scale.com/leaderboard/sweatlas-refactoring "https://labs.scale.com/leaderboard/sweatlas-refactoring"
[11]: https://labs.scale.com/leaderboard/sweatlas-tw "https://labs.scale.com/leaderboard/sweatlas-tw"
[12]: https://artificialanalysis.ai/articles/claude-opus-5-leader-agentic-knowledge-work "https://artificialanalysis.ai/articles/claude-opus-5-leader-agentic-knowledge-work"
[13]: https://benchmarklist.com/arenas/ "https://benchmarklist.com/arenas/"
[14]: https://labs.scale.com/leaderboard/hil "https://labs.scale.com/leaderboard/hil"
