# v3 Pipeline — 설계·검증 회고와 고도화 가이드 (2026-07-14)

> **후속 (같은 날 밤~심야)**: 이 문서의 "sol 워커" 표현과 consult 용어는 이후
> 두 번 더 개편됐다 — ① mate/worker 역할 분리
> ([`mate-worker-role-split`](../decisions/2026-07-14-mate-worker-role-split.md)),
> ② 반나절 뒤 `--role` 폐지, 단일 축 `--mode design|review|delegate`로 통합 +
> consult→blind/anchored design 용어 교체
> ([`mode-axis-collapse`](../decisions/2026-07-14-mode-axis-collapse.md)).
> **현재 상태의 SSOT는 [`docs/CONTEXT.md`](./CONTEXT.md)** — 이 문서는 v3 채택
> 시점의 경위·리서치·검증 기록으로 읽을 것.

이 문서는 2026-07-14에 채택된 v3 운영 모델(plan-review loop + luna 기본 일꾼
체제)이 **어떤 과정으로 설계·검증·반영됐는지**의 전체 기록이다. 목적은 두 가지:
(1) 이후 고도화 작업의 출발점 — 무엇이 왜 이렇게 결정됐고, 어디까지가 실측이며,
어디부터가 미검증 가정인지 구분해 준다. (2) 이 파이프라인 자체의 첫 실전 사례
기록 — v3는 v3 자신의 절차로 만들어졌다.

승인 계약(SSOT)은 [`decisions/2026-07-14-consensus-pipeline-luna-promotion.md`](../decisions/2026-07-14-consensus-pipeline-luna-promotion.md).
이 문서는 그 계약의 서사·근거·검증 기록이다. 둘이 충돌하면 decision record가 이긴다.

---

## 1. 배경과 동기

### 기존 체제 (07-03 대개편 이후)

- dispatcher(Claude)가 WHAT/WHY 소유, Codex 워커가 HOW 소유.
- 모델 라우팅: **sol이 코드 작업 기본**, terra가 browser/step-heavy, luna는
  trivial 조회 전용.
- 설계 협업은 **blind consult 1회** + 불일치 해소 프로토콜 — 방향 fork에서
  두 읽기를 비교하는 구조였지 반복적 공동 다듬기는 아니었다.
- 리뷰는 risk-conditional: 위험할 때만 독립 리뷰어.

### 문제 인식

sol급 모델을 "일방적으로 지시받는 워커"로 쓰는 것은 능력 낭비다. sol은
기술적 디테일에 집요하고, dispatcher(Fable 계열)는 큰 그림에 강하다 —
분야가 다른 동급 지능이라면 설계 단계에서 **왕복**해야 한다. 동시에 구현은
승인된 계획 + 이중 리뷰 그물이 있으면 더 싼 모델(luna)로 내려도 총비용이
줄어든다는 필드 리포트가 축적되고 있었다 (r/ClaudeCode의 TRIP-workflow 사례:
"fable plans → sol reviews plan in loop → luna implements → fable reads whole
diff → sol reviews code"; 커뮤니티의 절반이 독립적으로 같은 구조에 수렴했다는
증언 포함).

### 설계 제약 (우리가 이미 알고 있던 것)

- **07-03 앵커링 교훈**: anchored consult는 동조 편향을 만든다. blind가 기본.
  → plan-review 루프는 본질적으로 anchored이므로, 방향 fork(blind)와 방향
  확정 후 다듬기(anchored loop)를 단계로 분리해야 양립한다.
- **07-10 A/B**: "sol medium ≥ terra high" 소문은 우리 워크로드에서 재현 안
  됨. sol medium은 심각도 과승격 경향 → 리뷰어 노이즈 억제 장치가 필요하다는
  복선.
- 사용자 원칙: 새 CLI/인프라는 패턴이 정착한 후에만. → v1은 독트린(문서)만,
  하네스 코드는 측정 후 하드닝.

---

## 2. 설계 과정 — v3는 v3의 절차로 만들어졌다

설계 자체를 plan-review 루프로 돌렸다. 전 과정:

### 라운드 1 (worker `plan-review-consensus`, sol high, collab) — REVISE

dispatcher 초안: blind/anchored 분리, luna 승격(단 "pseudo-code급 계획일
때만"), 3라운드 캡, "하네스 코드 변경 없이 persistent thread 루프".

sol이 잡은 것:

- **P1 (실측)**: "코드 변경 없는 persistent 루프" 전제가 현재 구현과 충돌.
  일반 완료 턴은 Codex thread/runtime을 해제하므로 두 번째 왕복 시점엔
  스레드가 없다. 우회책 제시: **REVISE를 dispatcher-targeted `QUESTION:`으로
  끝내면 needs_input 경로가 스레드를 보존한다** — 이것이 루프 메커니즘의
  핵심이 됐다. (직후 dispatcher가 완료된 워커에 steer를 시도하다 "not
  running" 에러를 받아 이 지적이 즉석에서 실증됨.)
- P1: "pseudo-code-level"은 라우팅 기준으로 측정 불가.
- P1: 루프 상한 부재, 기존 2턴 캡과 충돌.
- P2: plan freeze 절차 부재, 3라운드 후 disagreement protocol 오용, 측정
  항목 미정의, SKILL.md 단독 수정 시 문서 계약 drift.

### 사용자 수정 (라운드 사이)

- pseudo-code 요구 폐기 — 계획 단계가 너무 무거워짐. 계획은 파일/계약/엣지
  케이스 수준까지만, 모호함은 **luna의 QUESTION 승격**으로 처리 (기존
  TARGET/KIND 인프라 재사용).
- luna는 판단 가능한 모델(xhigh, Fast 가용) — 구현만이 아니라 테스트·검증·
  로그 조사·브라우저/런타임 QA 등 **모든 grunt work의 기본 일꾼**으로.

### 라운드 2 (worker `plan-review-r2`, sol high) — REVISE

- **P1: "center of gravity"(작업 물량) 게이트는 잘못된 축.** 90%가 루틴인
  작업에 섞인 작지만 acceptance-critical한 auth/마이그레이션 조각이 luna로
  흘러간다. 축은 **failure cost**여야 한다. 사후 리뷰 그물의 구조적 한계
  논증: 리뷰는 diff에 "있는 것"에 강하고 "없는 것"(누락된 락, 누락된 권한
  체크, 없는 테스트)에 약하다; QUESTION 승격은 워커가 모호함을 인지해야만
  작동한다(unknown unknowns); 잘못된 설계는 잡혀도 재작업이 통으로 돈다.
- P2: luna 확대가 terra의 기존 테이블 소유권과 정면 충돌 — 테이블을 명시적
  으로 교체하고 terra는 기본 담당 없는 capability 폴백으로 (07-10 A/B에서
  terra 우위가 재현되지 않았으므로 근거 있는 강등).
- 이 라운드는 REVISE를 dispatcher-targeted QUESTION으로 종료 — **스레드 보존
  트릭의 첫 실전 성공**. 라운드 3은 같은 스레드에 `reply`로 진행됐다.

### 라운드 3 (같은 스레드, reply) — APPROVE

failure-cost 하드게이트 문구 확정, 모델 테이블 v3 확정, 지표 정의 확정.
sol의 잔여 반론(승인하되 기록): "라우팅은 dispatcher가 acceptance-critical
의존을 사전 식별하는 데 의존한다 — plan review가 발화 조항(또는 none—luna
eligible)을 명시 검증하는 백스톱을 겸해야 한다." → 계약에 반영됨.

### 사용자 AMENDMENT (승인 후, 같은 날)

- luna 리포트에 rationale 의무화 (plan 편차 + 이유 + 의도적으로 안 한 것).
- 승격 축은 luna→sol 단일이 아님 — luna→terra도 열어둠, 규칙은 실측 후.
- **하네스/코어 수술 라우팅: Claude fork → Codex sol** (비용; dispatcher는
  오케스트레이션·아비트레이션·사인오프 전담). 07-03 preference 대체.

---

## 3. 아키텍처: Before → After

### 모델 라우팅

| | Before (07-03~) | After (v3) |
|---|---|---|
| 코드 작업 기본 | sol medium | **luna xhigh (+Fast)** |
| browser QA / runtime / computer use | terra | **luna** |
| 탐색/조회 | luna low-med (trivial 한정) | luna (전면) |
| 설계·plan리뷰·적대리뷰 | sol high | sol high/xhigh (불변) |
| 하드게이트 구현 | (개념 없음 — risk면 sol) | **failure-cost 게이트**: acceptance-critical이 concurrency/security/공개 API 계약/데이터 마이그레이션/횡단 리팩터에 의존하거나 돈·데이터·비가역 피해면 sol |
| terra | browser/step-heavy 기본 소유 | 기본 담당 없음, capability 폴백, 실측 시 재승격 |
| 하네스 수술 | Claude fork | **sol** + Claude context-holding 리뷰(plan/diff 양 단계) |

### 협업 프로토콜

| | Before | After |
|---|---|---|
| 설계 | blind consult 1회 + 불일치 해소 | blind consult(방향 fork, 불변) → **plan-review 루프**(방향 확정 후, 최대 3라운드) |
| 계획의 지위 | 브리프에 흡수 | **PLAN.md로 동결**(버전) — 구현·리뷰의 계약; 범위 변경은 재승인 |
| 리뷰 | risk-conditional | plan-governed 구현은 **sol 적대 리뷰(2라운드 캡) + dispatcher full-diff 정독** 필수; plan 없는 잡무만 검증+사인오프로 충분 |
| 재리뷰 | (규정 없음) | **증분 재리뷰**: 이전 지적마다 addressed/partially/not 판정 후 새 이슈 별도 |
| 리뷰어 노이즈 | (규정 없음) | **noise-suppression 리스트**: 스타일 취향·비현실 엣지케이스·범위 밖 가정·해소된 지적 재탕 금지 |
| stale 방어 | (규정 없음) | verdict는 **reviewed-input identity**(PLAN 버전/커밋 해시) 명시 — 현재 artifact와 불일치 시 폐기 |
| 학습 | 3원장 (decisions/preferences/lessons) | + **파이프라인 지표**: plan 라운드 수, revise 원인, luna→sol\|terra 승격률(일반 QUESTION 별도), 발화 게이트 조항, false-approve |

### 루프 메커니즘 (런타임 계약)

- REVISE = 스레드 보존: text 모드는 dispatcher-targeted `QUESTION:` 종료,
  decision 모드는 `outcome=needs_decision` + dispatcher-owned decision.
- APPROVE = terminal.
- **decision 모드 인코딩** (strict schema에 APPROVE/REVISE 값이 없으므로):
  APPROVE ⇒ `outcome=done, verdict=GO`, summary `"APPROVE — <plan identity>"`;
  REVISE ⇒ `outcome=needs_decision, verdict=NO-GO`, summary `"REVISE — …"`.
  위험 원장(new-risks/resolved-risks)은 evidence artifact에 분리 헤딩으로.
- 라우팅 실체: 데몬은 `decisions[]` 중 **user-targeted 항목을 우선** 선택,
  없을 때만 `decisions[0]` — 문서가 런타임에 맞춰 정정됨 (tests/test_meight.py
  `DecisionRoutingTests`가 회귀 고정).

### 바뀌지 않은 것 (의도적)

- meight.py — 한 줄도 안 바뀜. `--fast`(service_tier=priority), xhigh,
  스레드 보존 경로 모두 기존 구현으로 충분함을 SDK probe로 실측.
- blind consult 독트린, QUESTION TARGET/KIND, decision schema, 학습 3원장,
  단일 dispatcher 전제, 머니패스 사인오프 게이트.

---

## 4. 외부 리서치 — 무엇을 흡수하고 무엇을 버렸나

방법: GPT-5.6 Pro 컨설트(레포 5개 코드 레벨 열람) + dispatcher의
TRIP-workflow 직접 정독, 두 읽기 교차.

| 레포 | 판정 | 흡수한 것 | 버린 것 (이유) |
|---|---|---|---|
| PiLastDigit/TRIP-workflow | 변형 채택 | 리뷰어 noise-suppression 리스트, 증분 재리뷰 계약, implementer notes(→rationale 의무), implement=luna/review=sol/xhigh 수렴의 외부 실증 | bash 파일 상태 관리(데몬이 상위 호환), trailing 문자열 태그 판정(strict schema가 상위 호환), 모델명-워크플로 결박 |
| hristo2612/jinn | 대부분 기각 | (stale-result 방어 아이디어 → reviewed-input identity로 흡수) | 게이트웨이 데몬/조직 계층(범위 밖), `--dangerously-bypass-approvals-and-sandbox` 상시 사용(**절대 금지**), self-editing facts(주입 위험) |
| openai/codex-plugin-cc | 해당 없음 | — | 우리는 이미 openai-codex SDK 직결이라 transport 대체 불필요; 15분 Stop gate 기본 활성화는 컨설트도 기각 |
| RakuenSoftware/aimee | 이연 | eval ledger 개념(→ 지표가 lessons.md로 경량 커버) | 단어 겹침 기반 자동 rule weight(인과 아님), DB/서버 스택(패턴 정착 전 인프라 금지) |
| rustykuntz/clideck | 기각 | explicit-busy 정책 참고만 | PTY 키 주입, quiet-timer 완료 감지(둘 다 취약) |

이연 항목(측정 후 하드닝 단계에서 재고): 상태 머신/원장의 DB화, verdict의
스키마 1급 필드화(현재는 인코딩 규약), NEEDS_REWORK 3단 verdict(조기 탈출
신호 — 승인 계약 밖이라 다음 사이클).

---

## 5. 검증 기록 — 무엇이 실측이고 무엇이 가정인가

### 실측된 것

1. **스레드 보존 루프**: 라운드 2→3이 실제로 같은 스레드에서 reply로 진행됨.
   최종 재리뷰에서 sol이 런타임 시뮬레이션으로 재확인 (REVISE→needs_input
   보존, APPROVE→terminal).
2. **Fast/xhigh 경로**: SDK(openai-codex 0.1.0b3) probe — `gpt-5.6-luna` +
   `effort=xhigh` + `serviceTier=priority` 직렬화 확인 (effort-echo 완화
   전후 동일).
3. **luna xhigh+fast 실전 2건**: 문서 흡수 패치(GO — 단 아래 NO-GO 사례의
   원인 제공), 라우팅 회귀 테스트 작성(GO, 5/5 pass). rationale 보고 계약
   준수. 참고: luna가 "테스트 1건 실패"를 보고했으나 dispatcher 재현 결과
   환경 문제(.venv 미사용)로 판명 — **워커 주장 재검증 원칙의 실증**.
4. **적대 리뷰의 가치**: 최종 관문 라운드 1이 **NO-GO** — luna가 추가한
   "--report decision 권장"이 strict schema에 없는 APPROVE/REVISE 계약을
   약속함을 meight.py 대조로 적발. 문서 간 정합 스윕만으로는 못 잡는 결함
   유형(문서↔런타임 drift). dispatcher가 인코딩 규약 정의로 수정, 라운드
   2 GO. **교훈: 독트린 변경 리뷰는 반드시 런타임 소스와 대조시켜라.**
5. **검증 체인 전체**: 스킬 validator ×2, unittest(4→5개), git diff --check,
   6문서 stale 문구 grep 스윕 0건, 커밋별 계약 대조.

### 미검증 가정 (고도화 대상)

- **luna 기본 일꾼의 실제 결함률** — 오늘 2건은 문서/테스트 작업. 코드 구현
  에서의 luna 품질, luna→sol 승격률, false-approve율은 데이터 없음. 지표가
  쌓여야 게이트를 넓히든 좁히든 결정 가능.
- **하드게이트 조항의 적정선** — 현재 조항은 sol의 논증 기반이지 실측 기반이
  아님. 사용자 직관은 "이중 리뷰가 웬만하면 잡는다" 쪽 — 게이트 완화는
  false-approve 데이터가 근거가 된다.
- **terra의 자리** — 강등은 07-10 A/B(n=1) 근거. capability별 재승격 기준선
  없음.
- 벤치마크성 주장("luna가 sonnet-5급 이상")은 사용자 경험 기반, 미계측.

### 첫 사이클 지표 (기준선)

plan-review 3라운드(REVISE×2→APPROVE), 구현 sol 1건(하네스급)+luna 2건,
luna→sol 승격 0회, 코드리뷰 2라운드(NO-GO→GO), dispatcher 직접 수정 2회
(evidence 커밋 제거, P1 인코딩 정의), 하드게이트 발화: harness-grade 1회.

---

## 6. 반영 상태와 파일 맵

커밋 스택 (origin/main, 2026-07-14): `602f87e`(decision record) →
`780680f`(6문서 전파) → `aabd996`(리서치 흡수 4건) → `b0effa7`(evidence
untrack) → `cb958c0`(NO-GO 수정: 인코딩 규약+stale 문구+라우팅 서술) →
`1065764`(라우팅 회귀 테스트).

| 파일 | 역할 |
|---|---|
| `decisions/2026-07-14-consensus-pipeline-luna-promotion.md` | 승인 계약 SSOT (v3 + AMENDMENT) |
| `skills/meight/SKILL.md` | dispatcher 독트린 — 모델 테이블, 하드게이트 verbatim, plan-review 루프, 리뷰 체인, 지표. `~/.claude/skills/meight`가 심링크 (Claude 측 자동 최신) |
| `skills/meight-worker/SKILL.md` | 워커 계약 — plan-reviewer 역할, decision 인코딩, rationale 리포트. `meight.py:42`가 직접 참조 (Codex 측 설치본 없음, 워커 시작마다 로드) |
| `README.md` / `ARCHITECTURE.md` / `AGENTS.md` / `CLAUDE.md` | 파이프라인 요약 + SKILL.md로의 SSOT 포인터 (상세 매핑 복제 금지 — drift 방지) |
| `tests/test_meight.py::DecisionRoutingTests` | user-priority 라우팅 회귀 고정 |
| `~/.meight/notes/lessons.md` | 첫 사이클 지표, 운영 교훈 |
| `~/.meight/notes/preferences.md` | 07-14 사용자 결정 3건 (rationale 의무, 승격 축 defer, 하네스→sol) |

meight.py 무변경 → 데몬 재시작 불필요. 스킬 파일은 라이브 반영.

---

## 7. 고도화 로드맵 (다음 작업자를 위한 진입점)

1. **지표 수집 운영**: 실전 태스크마다 lessons.md에 첫 사이클 지표 형식으로
   기록. 게이트 튜닝은 이 데이터가 전제 (§5 미검증 가정 참조).
2. **하드닝 후보 (측정 후)**: verdict 인코딩의 스키마 1급 필드화, plan-review
   전용 report 모드, 지표의 구조화 저장. — "no new infra until patterns
   settle" 원칙 유지.
3. **NEEDS_REWORK 3단 verdict**: 3라운드 소진 전 "방향 자체가 틀림" 조기
   탈출 신호. 승인 계약 밖이라 도입 시 plan 재승인 필요.
4. **terra 재승격 기준선**: capability별(computer use 장시간 세션 등) A/B를
   lessons.md에 축적.
5. **알려진 도구 버그**: consult 스킬 `build_consult_packet.py`가 `--files`
   마크다운 첨부를 `<binary file omitted>`로 떨굼 — 수정 전까지 패킷 본문에
   인라인 (lessons.md 기록).
6. **운영 주의**: 워커가 skills/*.md를 수정하는 동안 새 워커 시작 금지
   (프리앰블 read race, 07-03 교훈). 하네스급 문서/코드 변경의 적대 리뷰
   브리프에는 "meight.py 런타임과 대조" 요구를 반드시 포함 (§5-4).
