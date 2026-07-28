---
date: 2026-07-29
scope: [meight, routing-policy, tech-lead, consult, model-selection]
type: refactor
---

## TL;DR

"워커 기본값에서 Fast 빼자"로 시작한 세션이 모델 라우팅 정책 전체 개편으로 번졌다.
최종 상태: **worker 기본 = `luna max` + Fast off**, **`sol`은 worker에서 항상
`medium`이고 `sol high`는 mate 전용(사용자 확인 1회)**, **모델 라우팅 하드게이트
열거 목록 폐지 → 실패 비용 판단 하나**, **난이도 대응은 워커 승급이 아니라 mate
단계 추가**. 그리고 `~/.claude/tech-lead.md`의 위임 축을 "Codex=백엔드,
Claude=UX"에서 **"Codex=실행·수렴형, Claude=이해·진단·종합형"**으로 뒤집었다 —
consult(GPT-5.6 Pro)로 공개 벤치마크를 받아 디스패처가 원본 검증한 결과다.

이번 세션의 가장 값나가는 사실 하나: **`model: fable` 승격 규칙은 실측이
반박한다.** Opus 5보다 1.4배 비싼데 Coding Agent Index 66 대 67이고, 레포 이해·
프론트·리서치·터미널 전부 Opus가 앞선다.

## Keywords

`MODE_START_DEFAULTS` `luna max` `sol medium` `Coding Agent Index v1.3`
`DeepSWE 63` `SWE-Atlas-QnA 33` `HiL-Bench` `Artificial Analysis`
`allow_dynamic_sdk_effort` `chatgpt2codex` `prompt-keyword-detector.sh`
`3a1e5d5` `c7b83ec` `71f1e01`

## Context

posture2 개편(07-28) 직후 세션. 사용자가 "워커 기본값 luna xhigh에서 fast 모드
빼자"는 단일 요청으로 열었고, 거기서 연쇄적으로 라우팅 정책 전반이 재검토됐다.
대화가 진행되며 사용자가 던진 질문이 매번 한 층씩 더 깊은 문제를 열었다.

## Full Journey Timeline

### Phase 1 — Fast off (요청 그대로)
`MODE_START_DEFAULTS["worker"]["fast"]` True → False. 문서 6곳 + 테스트 5곳.
`--fast` 플래그와 follow/reply 상속은 그대로 두고 기본값만 내렸다.

### Phase 2 — 난이도 사다리 (사용자 제안)
"어려운 거 할 땐 sol medium, 진짜 어려우면 sol high, sol high는 확인 한 번."
그대로 구현. **이게 곧 두 번 뒤집힌다.**

### Phase 3 — 하드게이트 목록 폐지 + 축 전환 (사용자 지적)
"하드게이트도 예시를 박아두기보다 알아서 판단하게. 그런 작업도 medium이 잘 할 수
있어." 그리고 결정적 한 마디: **"sol high한테 작업시키는 거 인력 낭비 토큰 낭비.
sol high한테 설계만 시키고 luna 워커 돌리는 게 가장 좋은 구조인데 그렇게 지원이
되나?"**

→ 그건 이미 이 하네스의 원형 파이프라인이었다(blind design → plan-review →
worker 구현 → 적대 리뷰). Phase 2에서 넣은 "난이도 = 워커 브레인 승급" 사다리가
오히려 그 구조를 흐리고 있었다. **난이도 대응 1순위를 단계 추가로 뒤집었다.**

### Phase 4 — 부정형 서술 제거 (사용자 지적)
"하드게이트를 빼라니까 스킬에 '하드게이트를 뺀다' 이런 걸 적어두면 어떡하냐 ㅋㅋ"
→ 스킬은 읽는 에이전트의 행동 문서인데 폐지 이력을 박아뒀다. 없앤 개념을 도로
상기시키고 슬롯만 차지한다. 전부 긍정형으로 재작성, 이력은 `decisions/`에만.

### Phase 5 — 결정 희석 교정 (사용자 지적)
"sol medium도 충분히 잘한다니까. sol high한테 코드 작업 시키는 게 비싸다는 건데
아까 했던 말 반복하잖아 나."
→ 사용자가 "낭비"라고 판단한 경로를 "확인받으면 쓸 수 있는 선택지"로 남긴 게
결정을 희석한 것이었다. **worker의 `sol`을 `medium` 고정으로 바꾸고 `sol high`를
mate 전용으로 옮겼다.**

### Phase 6 — consult 승격 (사용자 정보 제공)
"consult는 sol pro라 xhigh보다 높은 지능을 공짜로 쓸 수 있고, 리서치·설계뿐
아니라 작업도 시킬 수 있다 — 샌드박스가 있어서."
→ `tech-lead.md`에서 consult는 `Verification` 섹션의 "외부 증거 채널" 한 줄이
전부였다. **Three rails로 승격**하고, consult 스킬 자체의 코드 작업 게이트
(`only when the user explicitly wants a code draft`)도 열었다.

### Phase 7 — Codex/Claude 경계 교정 (사용자 지적)
"실패 판정 사람 눈 기준으로 가면 웬만하면 항상 코덱스만 쓰게 되는 거 아니야?
codex가 백엔드를 좀더 잘하는 경향, claude가 ux를 잘하는 경향이 있는 것뿐인데."
→ 맞다. "누가 실패를 판정하나"는 대부분의 일에서 Codex를 가리켜 판별력이 없었다.
경향 서술로 낮췄다. **그리고 이 질문이 Phase 9의 consult로 이어진다.**

### Phase 8 — chatgpt2codex 조사 (사용자 링크)
`github.com/ezBuilder/chatgpt2codex` — ChatGPT 웹에 로컬 MCP 커넥터로 레포 손을
주는 도구. 조사만 하고 백로그로. (아래 별도 섹션)

### Phase 9 — consult 실전 투입, 축 전환
사용자: "이럴 때 /consult를 보내서 물어보자. GPT-5.6 sol과 Claude Opus 5 비교를
(or fable 5)" → "작업 종류별 벤치마크를 질문하면 될듯."
→ 8개 작업 축의 벤치마크를 요구하는 패킷을 만들어 백그라운드 dispatch.
결과가 **"백엔드/프론트"라는 축 자체를 반박**했다.

### Phase 10 — luna 재고, `luna max` 착지
follow-up으로 `luna xhigh` vs `luna max` vs `sol medium`을 물었고, consult가
자기 앞 답변 두 개를 정정하며 설정별 실측표를 가져왔다. 사용자 결정: `luna max`.

## Investigation

### consult 1차 — 축이 틀렸다

Artificial Analysis Coding Agent Index v1.3 (디스패처가 원본 페이지 직접 검증):

| | Sol (max) | Opus 5 (xhigh) | Fable 5 (max) |
|---|---|---|---|
| 종합 Index | 67 | 67 | 66 |
| DeepSWE | **69%** | 60% | 66% |
| Terminal-Bench v2 | **88%** | 85% | 83% |
| SWE-Atlas-QnA | 43% | **55%** | 49% |
| $/task | $7.08 | $8.23 | $11.71 |

consult 원문의 핵심 문장:

> **Sol은 실행·수렴형, Opus 5는 이해·진단·종합형이다. Backend와 frontend라는
> 영역 구분은 2차 조건일 뿐이다.**

보조: HiL-Bench(정보 부족 시 질문) Opus 57 vs Sol 32, WebDev Arena Opus 1712 vs
Sol 1623, AA-Briefcase Opus 1720 vs Sol 1505, **Design Arena 1357 동률**.
→ "Claude가 UX 감각 우위"는 프론트 *구현*에선 맞고 *시각 취향*에선 안 맞는다.

### consult 2차 — 자기 정정 두 번

follow-up에서 consult가 스스로 정정했다. 신뢰도 신호로 기록해둔다.

1. > **앞 답변의 "Luna row는 어떤 공개 벤치에도 없다"는 틀렸어.** 2026년 7월
   > 29일 기준으로 Artificial Analysis에 `Luna xhigh`와 `Luna max`의 정확한
   > 설정별 row가 둘 다 존재해.

2. > `32.33 ± 5.49`는 **ASK-F1 그 자체가 아니라 `ask_human()`을 쓸 수 있는
   > 조건에서의 Combined Pass@3 계열 task outcome**이야. 앞 답변에서 이 숫자를
   > 단순히 "질문 능력 점수"처럼 읽힐 수 있게 쓴 건 정밀하지 않았어.

설정별 실측표 (디스패처 직접 검증):

| 설정 | Index | DeepSWE | Term-Bench | QnA | $/task | 시간 | 토큰 |
|---|---|---|---|---|---|---|---|
| `luna xhigh` | 55 | 57% | 76% | 31% | $1.26 | 6.6분 | 12.3M |
| **`luna max`** | **59** | **63%** | **80%** | 33% | $1.57 | 8.0분 | 15.5M |
| `sol medium` | 61 | 64% | 78% | **40%** | $2.99 | 5.2분 | 5.8M |

그리고 07-14 그 사건에 대한 consult의 판정:

> 딱 잘라 말하면, **"Luna는 판단 가능한 모델이다"라는 명제는 너무 약해.** 판단을
> 어느 정도 한다는 것과, 숨은 blocker 앞에서 멈추고 `QUESTION:`을 올린다는 건
> 전혀 다른 능력이야. 현재 공개 실측은 후자를 보증하지 않아.

## What Didn't Work

### ❌ 난이도를 워커 브레인 승급으로 받기 (Phase 2 → Phase 3에서 폐기)
- 시도: 어려우면 worker를 `sol medium` → `sol high`로 올리는 사다리.
- 문제: 난이도의 대부분은 **판단**에 있는데 워커 승급은 **실행** 축을 올린다.
  게다가 이 하네스는 이미 mate(설계) → worker(구현) 분리를 갖고 있어서, 사다리가
  그 구조를 흐렸다.
- 교훈: **막히면 같은 축에 힘을 더 주기 전에 축이 맞는지 본다.** 실행 자원을
  키우는 답이 나왔다면 대개 앞단이 부족한 것이다.

### ❌ "낭비다"라는 판단을 확인 게이트 붙인 선택지로 남기기 (Phase 5에서 교정)
- 시도: 사용자가 "sol high에게 코드 작업은 낭비"라고 했는데 "확인 1회 받으면
  가능"으로 문서화.
- 문제: 사용자가 같은 말을 두 번 하게 만들었다. 확인 게이트는 "비싸지만 가끔 맞는
  선택"을 신중하게 만들 뿐, "틀렸다"는 판단을 담지 못한다.
- 교훈: 사용자 판단이 "X는 값을 못 한다"면 X를 선택 가능한 상태로 두지 않는다.
  경로를 없애거나 다른 자리로 옮긴다.

### ❌ 스킬 문서에 폐지 이력 적기 (Phase 4에서 교정)
- 시도: `모델 라우팅에 하드 게이트 목록은 두지 않는다 — ... 미리 열거하지 않는
  건 열거가 판단을 대체하지 못하기 때문이다`
- 문제: 스킬은 읽는 에이전트의 **행동 문서**다. 부정형 이력은 없앤 개념을 도로
  상기시키고 컨텍스트 슬롯만 먹는다.
- 교훈: 행동 문서에는 남는 판단 기준만 긍정형으로. 변경 이력은 `decisions/`가
  담당한다. 두 문서의 독자가 다르다.

### ❌ 토큰 수를 쿼터 소모로 따로 계산 (사용자가 즉시 교정)
- 시도: "luna xhigh는 sol medium의 2.1배 토큰을 쓰니 구독 쿼터 기준으론 오히려
  비싸다"는 '반전'을 주장.
- 사용자: **"뭔 소리야 api 달러 = 구독 쿼터 사용량인데"**
- 문제: `$/task`가 이미 `단가 × 토큰량`이다. 토큰을 따로 센 건 이중 계산이었고,
  luna의 낮은 단가가 이미 반영돼 있었다.
- 교훈: 파생 지표를 원지표와 나란히 놓기 전에 정의를 확인한다. "반전을 찾았다"는
  느낌이 들 때가 특히 위험하다.

### ❌ 단위 모르는 숫자로 비교하기 (같은 맥락)
사용자가 준 `49/0.14`, `54/0.31`을 AA의 `$8.23`과 나란히 놨다가 정정.
consult follow-up에서 정체가 확인됐다 — **Intelligence Index v4.1과 그 평가
과제당 가중평균 API 비용(USD)**. Coding Agent Index의 태스크당 비용과 다른 축이다.

## Decision Rationale

### `luna max`를 고른 이유 (`sol medium`이 아니라)

한계수익. `xhigh → max`는 비용 +25%에 종합 +4점, DeepSWE +6%p. 거기서
`sol medium`까지는 비용이 다시 1.9배인데 종합은 +2점뿐이다. `sol medium`이 확실히
앞서는 자리는 레포 이해·탐색(QnA 40 대 33)인데, 그건 이미 사다리의 다음 칸
("판단이 걸리면 sol medium")이 커버한다.

consult는 전역 기본을 `sol medium`으로 되돌리길 권했으나, 사용자가 `luna max`를
택했다: "루나맥스 기본으로 하자. 쏠 미디엄도 필요할때 선택하면 될거같고."

### consult의 108회 A/B 제안을 받지 않은 이유

consult가 `Safe-pass`, `Harmful confident action rate`, `QUESTION precision`,
`Blocker recall`, `ASK-F1`, `False escalation rate`를 재는 36 시나리오 × 3설정
= 108회 A/B를 설계해줬다. 스스로도 "±18.6%p 오차의 screening이지 5%p를 증명하는
실험이 아니다"라고 했다. 방향이 이미 한쪽이라 실행 비용이 결정 가치를 넘는다고
판단해 받지 않았다. **설계 자체는 `docs/evidence/`에 남아 있으니, 나중에
`QUESTION:` 품질 baseline이 필요해지면 거기서 꺼내 쓴다.**

### `model: fable` 승격 규칙 폐기, 단 사용자 관측은 살림

실측은 Fable을 반박한다(1.4배 비용에 종합 66 대 67, 대부분 축에서 Opus 우위).
그런데 사용자 관측: "페이블이 오푸스보다 뭔가 창의적인 일이나 큰 그림을 잘 보는 거
같긴 했어 이건 내가 느낀거야."

→ **창의성·큰 그림은 어떤 공개 벤치도 재지 않는 축**이다. 실측이 반박하는 게
아니라 애초에 측정 대상이 아니다. 그래서 `tech-lead.md`에 이렇게 남겼다:

> the promotion needs a reason of its own: long-range implementation where it has
> earned the call, **or the creative and big-picture reads that no benchmark
> covers** — not the feeling that a task is hard.

근거 등급을 구분하면서 관측을 죽이지 않는 방식이다.

## Work Accomplished

### 1. Fast off (커밋 `f448d23`)
`MODE_START_DEFAULTS["worker"]["fast"]` True → False. `--fast`/`--no-fast`
플래그와 상속 로직은 유지. 테스트 `test_no_fast_overrides_worker_fast_default`를
`test_fast_overrides_worker_fast_default`로 뒤집었다(옵트인 검증).

### 2. 난이도 = 단계 추가, 하드게이트 목록 폐지 (커밋 `c7b83ec`)
- `sol` mate 플랜 → 동결 → `luna` 워커 구현이 기본이자 가장 싼 조합
- 모델 라우팅 하드게이트 열거(concurrency/security/공개 API 계약/마이그레이션/
  cross-cutting) 삭제 → 실패 비용 판단 하나
- **유지한 것**: 돈 경로 디스패처 sign-off, worker 스킬의 "혼자 결정 금지"
  에스컬레이션 목록. 이건 모델 라우팅이 아니라 **워커 소유권 경계**라 축이 다르다.
- `decisions/2026-07-29-difficulty-answered-with-a-stage.md`

### 3. 부정형 서술 제거 (커밋 `ec9c839`)
행동 문서 6곳에서 "~하지 않는다" 이력 서술을 걷고 판단 기준만 긍정형으로.

### 4. worker `sol` = `medium` 고정 (커밋 `71f1e01`)
`sol high`를 mate 전용으로 이동. `sol`의 effort 상한을 `high`로 확정(`xhigh` 제거).

### 5. consult 근거 문서화 (커밋 `7783c2c`, `c1a9cc2`)
- `docs/2026-07-29-model-routing-evidence.md` — 검증된 수치와 consult 인용만 있는
  수치를 **등급 구분**해 표기
- `docs/evidence/2026-07-29-consult-model-comparison.md` — 응답 242줄 원문
- `.gitignore`의 `*-evidence.md`가 근거 문서를 삼켜서 첫 커밋에서 누락됐다 →
  루트 한정(`/*-evidence.md`)으로 좁힘

### 6. worker 기본 `luna max` (커밋 `3a1e5d5`)
`MODE_START_DEFAULTS["worker"]["effort"]` `xhigh` → `max`. 테스트 3곳
(EXPECTED, start echo ×2). follow에서 명시적으로 `xhigh`를 주는 테스트는 오버라이드
검증이라 그대로 뒀다.

### 7. `~/.claude/tech-lead.md` (레포 밖)
- **Three rails**: Agent(Claude) / meight(Codex) / consult(GPT-5.6 Pro)
- consult ↔ 워커 경계 = **레포 접근이 필요한가** (사용자 표현이 내 "패킷에
  담기나"보다 판정이 즉시 돼서 채택)
- Codex ↔ Claude = **실행·수렴형 vs 이해·진단·종합형**
- `model: fable` 승격 규칙 폐기
- **이벤트 기반 보고** 추가 — 중요 발견·방향 전환·막힘·사용자 결정 필요·최종 결과.
  파일 단위 중계는 뉴스가 아니다. (사용자가 Opus 5 공식문서 발췌를 제시했는데,
  같이 제시된 "범위 규칙"은 시스템 프롬프트와 tech-lead.md에 이미 있어 넣지 않았다)
- 죽은 플래그 `meight --mode review` → `--mode mate --report decision --effort high`
  (`~/.claude/hooks/prompt-keyword-detector.sh:37`도 같이)

### 8. consult 스킬 게이트 개방 (레포 밖)
`scripts/run_agbrowse_code.py`의 "사용자가 명시할 때만" 게이트 제거, description을
최후수단 톤에서 적극 활용 톤으로, Workflow에 백그라운드 실행 안내 추가.

## Verification

- `python3 -m pytest tests/test_meight.py -q` → **68 passed, 1 failed**.
  실패는 `EffortTests::test_dynamic_efforts_are_accepted_by_installed_sdk_params`
  — `openai_codex` 모듈 미설치(ModuleNotFoundError)로, 이번 변경과 무관하며 세션
  내내 동일했다.
- `WebFetch`로 Artificial Analysis 페이지 **2회 직접 조회** — consult가 인용한
  수치가 원본과 일치함을 확인(전체 모델 비교 1회, 설정별 row 1회).
- `meight ping` → `pong (daemon pid 16587, capabilities=posture2)`.
- **안 한 것**: `luna max` 라이브 스모크. `max`는 `EFFORT_CHOICES`에 있고
  `allow_dynamic_sdk_effort`(meight.py:108)가 SDK 0.1.0b3의 닫힌 enum을 우회하는
  브리지를 start/follow 양쪽(1874, 2025)에 이미 걸어두고 있어 위험은 낮다고
  판단했다. 다음 세션의 첫 워커가 사실상 스모크가 된다.
- Fable/Opus 보조 지표(HiL-Bench, WebDev Arena, AA-Briefcase, Design Arena)는
  **consult 인용만 있고 원본 미검증** — 문서에 그렇게 표기했다.

## Architecture Impact

- **데몬 재시작 불필요**: 기본값 해소는 CLI의 `resolve_start_options`에서 일어나
  wire request에 실린다. 데몬은 받은 값을 쓸 뿐이고, `allow_dynamic_sdk_effort`는
  기존 코드라 구 데몬도 `max`를 처리한다.
- **`max`가 기본이 되면서 모든 워커가 dynamic-effort 브리지 경로를 탄다.** 첫
  호출에서 `TurnStartParams` 필드를 `str | None`으로 rebuild하는 방식이라
  idempotent하지만, SDK를 올릴 때 이 경로를 확인할 것.
- **`luna max`는 wall time이 제일 길다** (8.0분 / xhigh 6.6분 / sol medium 5.2분).
  백그라운드 dispatch라 대개 문제없지만 병렬 워커가 많으면 체감된다.
- **하드게이트 목록을 걷어낸 대가**: 07-14에 sol이 남긴 잔여 반론 — "라우팅은
  dispatcher가 acceptance-critical 의존을 사전 식별하는 데 의존한다" — 이 이제
  더 크게 걸린다. 백스톱이 얇아진 만큼 워커의 `QUESTION:` 품질에 더 기댄다.

## chatgpt2codex (백로그, 미테스트)

`github.com/ezBuilder/chatgpt2codex` — 로컬 데스크톱 앱이 MCP 서버로 뜨고 ChatGPT
웹이 커넥터로 붙어 레포를 읽고 패치·셸·테스트·스크린샷·`git commit/push`까지 한다.
파일 업로드가 아니라 `"ChatGPT thinks. Your computer acts."` 모델.

조사한 것:
- 도구: `code_search`, `file_read_slice`, `file_apply_patch`(해시 선조건 +
  트랜잭셔널), `local_shell_run`, `e2e_*`, `git_commit/push`, `computer_*`
- 보안 설계는 견고한 편 — 프로젝트 lease 권한, 시크릿 denylist(`.env`, `*.pem`,
  `id_rsa*`, `.aws/`, `.ssh/`), 셸의 파괴/네트워크 명령 차단, 심링크 탈출 금지,
  미확인 리스크 티어 fail-closed, 가드마다 vitest
- **주의**: `approvals.ts`에서 `write` 티어는 **무승인 통과**(lease만 있으면 패치·
  생성 자동). 레포가 2026-07-07 생성된 신생(스타 89), **라이선스 파일 없음**,
  설치가 서명 여부 불명인 `.pkg`

성립하면 `tech-lead.md`의 "레포 접근이 필요하면 워커, 아니면 consult" 경계가
무너진다 — consult가 레포 안으로 들어와 meight worker 자리를 잠식한다.
**검증 전에 문서를 먼저 고치지 말 것.** 격리 더미 레포 스모크가 먼저다.

## Files Changed

| File | Change |
|------|--------|
| `meight.py` | worker 기본값 `fast` True→False, `effort` xhigh→max |
| `tests/test_meight.py` | EXPECTED worker tier/effort, start echo 기대값, fast 오버라이드 테스트 방향 반전 |
| `skills/meight/SKILL.md` | 자세 기본값 표, 난이도=단계추가 문단, sol 행(깨진 파이프 복구 포함), 실측 근거 문단, 모델 보고 불릿 |
| `CLAUDE.md` / `AGENTS.md` | 운영 정책 표 3행 개편, 실패비용 문단 긍정형 재작성, 난이도 문단 |
| `ARCHITECTURE.md` | 기본값 표, 라우팅 표, 실패비용 불릿, mate/worker 모델 정렬 서술 |
| `README.md` / `docs/README.ko.md` | effort 경제학 문단, 기본값 표, 하드게이트 서술 |
| `docs/CONTEXT.md` | LAST UPDATED, 파이프라인, 난이도 대응, 모델 라우팅, effort 정책, 미결 2건 교체 |
| `docs/2026-07-29-model-routing-evidence.md` | **신규** — 검증 등급 구분한 근거표 |
| `docs/evidence/2026-07-29-consult-model-comparison*.md` | **신규** — consult 원문 + 패킷 |
| `decisions/2026-07-29-difficulty-answered-with-a-stage.md` | **신규** + luna max AMENDMENT |
| `.gitignore` | `*-evidence.md` → `/*-evidence.md` (루트 한정), `.consult/` 추가 |

## 미결

1. **`luna max` 라이브 스모크** — 다음 세션 첫 워커가 실질 스모크. 실패하면
   `allow_dynamic_sdk_effort` 경로부터 본다.
2. **`QUESTION:` 품질 baseline** — 어느 모델도 공개 실측이 없다(HiL-Bench에 luna
   row 없음, sol 수치도 ASK-F1이 아님). 하드게이트 목록을 걷어낸 지금 이 의존도가
   올라갔는데 품질을 모른다. consult가 준 A/B 설계가
   `docs/evidence/2026-07-29-consult-model-comparison.md` §6에 있다.
3. **chatgpt2codex 격리 스모크** — 위 섹션.
4. **보조 벤치마크 원본 미검증** — HiL-Bench, WebDev Arena, AA-Briefcase, Design
   Arena는 consult 인용만. Design Arena는 consult 자신이 "2차 static mirror"라고
   신뢰 등급을 낮춰 표기했다.
5. **`terra` 라우팅** — 07-10 A/B(n=1) 기반 잠정 강등 그대로. 변화 없음.

## Commit

refactor(routing): 모델 라우팅 정책 전면 개편 — 축을 영역에서 단계로

Co-Authored-By: Opus 5 <noreply@anthropic.com>
