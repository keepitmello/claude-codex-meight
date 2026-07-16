# claude-codex-meight

<p align="center">
  <img src="./hero.jpg" alt="Claude Fable 5 + Codex" width="720">
</p>

[English](../README.md) | **한국어**

> **Codex 메이트가 계획에 도전하고, Codex 워커가 그것을 구현하는 양방향
> 하네스.** Meight는 함께 설계하고, 위임하고, 조향하고, 리뷰하고, 근거로 승인하는
> LLM 에이전트를 위해 만들었습니다. 공식 `openai-codex` Python SDK 위에서
> 동작합니다. CLI: `meight`.

대부분의 브릿지는 터미널을 보는 사람을 기준으로 만들어졌습니다: tmux pane,
대시보드, stdout 스크래핑. Meight는 에이전트 자신을 기준으로 설계했습니다 —
디스패처는 숨겨진 Codex 세션을 시작하고, 작은 디스크 요약을 읽고, 실행 중인
턴을 조향하고, 구조화된 질문에 답하고, 구현 디테일에 빠지지 않을 만큼 작은
최종 보고만 받아 사용자 대면 결정을 내립니다.

핵심 아이디어는 이것입니다: **프론티어 모델을 말 없는 실행자로 쓰는 건 능력을
버리는 일이다.** 그래서 meight는 Codex 세션 계약 두 가지를 제공합니다.

- **메이트**(`--mode design` 또는 `--mode review`)는 독립적인 도전자입니다.
  진짜 판정이 걸린 plan 리뷰, 적대적 결함 사냥, blind design을 맡습니다 — 계약에 *디스패처에게
  도전하라, 동의가 목표가 아니다*라고 적혀 있습니다.
- **워커**(`--mode delegate`)는 bounded 구현자입니다. 코드·테스트·검증·런타임
  QA라는 기술 루프를 소유하고 decision surface로 보고하며, 진짜 애매함은
  추측하는 대신 승격시킵니다.

메이트와 워커는 모델 정체성이 아니라 세션 계약의 이름입니다. 모드는 계약을,
`--model`은 두뇌를 고릅니다. 디스패처는 방향·중재·통합·최종 사인오프를
쥐고 있고, 메이트나 워커의 말만으로 머지되는 것은 없습니다.

```text
   디스패처 에이전트   <->   Codex 메이트 / 워커
   (무엇과 왜)               (도전 / 구현)
        |                       ^
        |-- start + brief ------|
        |
        |<- QUESTION / decision report / result
        |-- reply / steer / design / review
        |
        v
   글로벌 데몬 -- 공식 openai-codex SDK -- 워커별 codex app-server
        status.json · events.log · result.md · decision.json · decision.md
```

## 파이프라인

Meight에는 자기 자신을 개조하며 다듬은, 의견이 있는 개발 루프가 실려
있습니다. 모든 단계는 프레임워크 코드가 아니라 독트린(하네스가 주입하는
파일)입니다:

1. **방향 갈림길은 blind design.** 방향을 정하는 결정 전에, 읽기 전용
   메이트에게 문제와 제약만 줍니다 — 앵커링될 디스패처의 의견 없이 — 그리고
   가장 근거 있는 설계와 그에 대한 가장 강한 반론을 돌려받습니다.
2. **Plan-review 루프.** 방향이 정해지면 디스패처가 계획을 쓰고 `mate/sol`이
   리뷰합니다: verdict-first `APPROVE`/`REVISE`, 최대 3라운드, 이전 지적의
   증분 재리뷰, 노이즈 억제(스타일 트집·비현실 엣지케이스 금지). `REVISE`는
   구조화된 질문으로 같은 스레드를 살려두므로 수정이 한 대화 안에서
   이어집니다. 승인된 계획은 versioned `PLAN.md`로 동결됩니다 — 이후 모든
   것이 이 계약을 기준으로 판정됩니다.
3. **워커가 구현합니다.** bounded 작업의 기본은 `worker/luna` `xhigh`(가능하면
   `--fast`) — 싸고 유능합니다. failure-cost 하드 게이트는 acceptance-critical
   작업 — 동시성, 보안, 공개 API 계약 설계, 데이터 마이그레이션, 횡단
   리팩터, 돈/데이터 손상이나 비가역 피해가 가능한 모든 것 — 을
   `worker/sol`로 올립니다. 구현 보고는 계획과의 편차, 그 이유, 의도적으로
   하지 않은 것을 반드시 명시합니다.
4. **리뷰 체인.** `mate/sol`이 동결된 plan을 계약으로 적대 리뷰(최대 2라운드,
   런타임 대조, verdict는 자신이 리뷰한 대상을 정확히 명시 — stale verdict는
   폐기됨) → 디스패처가 plan과 레포 문맥을 들고 diff 전문을 정독, 유효한
   결함은 직접 수정, 최종 사인오프를 소유합니다.

**게이트는 작업 크기에 비례합니다.** plan이 지배하는 작업에는 전체 체인이
기본이지만, 작고 위험 낮고 가역적인 작업에서는 디스패처가 게이트를
생략/축소할 수 있습니다 — 단 절대 조용히는 아닙니다: 어떤 게이트를 왜
건너뛰었는지 사용자에게 알리거나, 애매하면 먼저 묻습니다. failure-cost 하드
게이트와 머니패스 사인오프는 절대 생략할 수 없고, 생략은 지표로 기록됩니다.

Effort도 같은 경제학을 따릅니다: `luna`는 싸니까 `xhigh`로 돌리고, `sol`은
`high`가 기본(overthink할 수 있어 가벼운 메이트 작업은 디스패처 재량으로
`medium`까지), `xhigh`는 진짜 어려운 문제에만 예약합니다 — 무엇이 그에
해당하는지는 디스패처가 판단합니다.

## 왜 만들었나

공식 `openai-codex` Python SDK는 `codex app-server`와 직접 통신하며 조향,
인터럽트, 스트리밍, output schema, 스레드 제어를 API로 노출합니다. Meight는
활성 워커당 SDK 런타임 하나를 쓰고, 워커가 끝나면 즉시 해제해서 MCP
서브프로세스와 파일 디스크립터가 남지 않게 합니다.

tmux/exec 래퍼와 비교하면:

| | tmux/exec 브릿지 | MCP 래퍼 | **Meight** |
|---|---|---|---|
| 병렬 세션 | 워커당 프로세스 1개 | 블로킹 툴 호출 | 활성 워커당 SDK 런타임 1개 |
| 턴 중간 조향 | attach/type 또는 kill+resume | 불가 | `meight steer` |
| 진행 관찰 | stdout 스크래핑 | 불가 | 디스크 요약, 필요할 때 pull |
| 양방향 대화 | 불가 | 불가 | 구조화 `QUESTION:` -> exit 3 -> `reply` |
| 결과 전달 | 스크래핑 | 툴 반환값 | exit code 계약 + 결과 파일 |
| 기계가 읽는 보고 | 불가 | 래퍼마다 다름 | `output_schema` 기반 `--report decision` |
| 세션 계약 | 없음 | 없음 | `--mode design\|review\|delegate`, 하네스가 주입 |

그리고 모든 판단이 디스크에 남기 때문에 — 요약, 결정, 선호, 교훈 — 쓸수록
페어링이 개인화됩니다: 디스패처는 어떤 질문을 사람이 보고 싶어하는지, 어떤
질문은 스스로 답해도 되는지 배워 갑니다.

## 빠른 시작

요구사항: [Codex CLI](https://developers.openai.com/codex) 설치·인증,
Python >= 3.10.

```bash
git clone https://github.com/keepitmello/claude-codex-meight
cd claude-codex-meight
./install.sh   # .venv + ~/.local/bin/meight 생성
```

실제 작업에는 아무 git 레포에서나 감독형 디스패치를 쓰세요. Meight는 기본으로
글로벌 데몬 하나를 쓰고(`$MEIGHT_HOME`, `$XDG_STATE_HOME/meight`, 또는
`~/.meight`), 워커 상태는 `repos/<repo-key>/` 아래에 레포별로 격리합니다.

```bash
meight start impl-1 --mode delegate --report decision --model luna --effort xhigh --fast \
  --brief-file - --cwd ~/my-repo <<'EOF'
Implement X in src/foo.py. Existing pattern: see src/bar.py:42.
Verify with: pytest tests/test_foo.py.
Report changed files, verification, remaining P1s, risks, and evidence artifact.
EOF

meight wait impl-1 --timeout 300
# exit 0=완료 · 2=실패/인터럽트/런타임소실 · 3=답변 가능한 질문 · 4=데몬 사망 · 1=체크포인트 타임아웃
```

exit `1`이면 워커는 아직 실행 중입니다. 한 번 들여다보고, 다시 기다리거나
조향하세요:

```bash
meight status impl-1
meight steer impl-1 "Stop refactoring the helper; only fix the bug."
meight wait impl-1 --timeout 300
```

터미널 상태에서는 선호 보고를 읽습니다. 감사 기록이 필요할 때만 `--raw`를
쓰세요:

```bash
meight result impl-1
meight result impl-1 --raw
```

워커가 답변 가능한 질문을 남겼다면(exit `3`)? 같은 target/kind가
`status.json`과 `meight status`에도 보입니다.

```bash
meight reply impl-1 --brief "Use config-a.json and keep the legacy field."
```

Blind design은 메이트에게 갑니다 — 읽기 전용, 협업 모드:

```bash
meight start design-auth --mode design --sandbox ro --model sol --effort high \
  --cwd ~/my-repo --brief-file - <<'EOF'
We need to choose an auth-token refresh design.

Constraints:
- No user-visible logout regression.
- Existing token storage is in src/auth/store.ts.

Options:
- Option A: refresh before each protected request when expiry is near.
- Option B: centralize refresh in the API client on 401.

Give the best-supported design, the strongest case against it, and the evidence
that would settle remaining uncertainty. No code changes.
EOF
```

짧고 단순하고 위험 낮은 작업에는 원샷 디스패치도 있습니다:

```bash
meight dispatch tiny-1 --mode delegate --report decision --sandbox ro \
  --brief "Check whether README mentions LICENSE."
```

Computer Use 앱 접근은 meight 세션마다 기본 활성화되어 있습니다. 그 외 MCP
승인은 그대로입니다.

## 구조화된 질문

세션은 추측하지 않고, 조용히 순응하지도 않습니다. 막혔을 때 — 또는 더 나은
방향이 보일 때 — 구조화된 질문으로 턴을 끝내고, 데몬이 그것을 exit `3`으로
승격시킵니다:

```text
QUESTION:
TARGET: dispatcher | user
KIND: scope | ux | priority | risk | irreversible | acceptance | missing-info | better-direction | technical
<질문 + 옵션 + 추천>
```

`TARGET`은 누가 결정해야 하는지, `KIND`는 왜 올라왔는지를 말합니다. 중간
레이어 에이전트는 디스패처 소유 질문은 `meight reply`로 답하고, 사용자 소유
질문(스코프, UX, 리스크 성향, 비가역 행동)은 그대로 사람에게 올립니다.
decision-report 모드에서는 같은 라우팅이 스키마의 `outcome=needs_decision`으로
흐릅니다.

## 하네스는 배웁니다

plain file 원장 세 개가 디스패치 루프를 쓸수록 좋게 만듭니다:

- **결정 기록** (`<repo>/decisions/`). 두 독립 설계로 해소된 모든 방향
  갈림길이 기록을 남깁니다: 양쪽 입장, 갈린 지점, 무엇이 결론을 냈는지.
  나중 세션이 *왜*를 감사할 수 있고, 정해진 질문은 정해진 채로 유지됩니다.
- **선호 원장** (`<daemon-home>/notes/preferences.md`). 사람이 `TARGET: user`
  질문에 답하면 그 답이 기록됩니다. 디스패처는 에스컬레이션 전에 원장을
  먼저 확인하므로, 같은 부류의 질문은 사람에게 한 번만 갑니다 — 비가역·
  리스크 판단만은 매칭돼도 항상 재확인합니다.
- **교훈** (`<daemon-home>/notes/lessons.md`). 반복되는 리뷰 지적과 운영
  실수가 한 줄 교훈이 되고, 재발하면 브리프 템플릿으로 승격됩니다. 실행
  기록에는 모드, plan-review 라운드 수와 revise 원인, 승격률과 발화한
  하드게이트 조항, 게이트 생략, 사인오프 후 결함이 담깁니다 — 라우팅
  게이트를 감이 아니라 실측으로 튜닝하는 기준선입니다.

이 중 어느 것도 새 서브시스템이 아닙니다 — 파일과 독트린뿐이고, 정의는
[`skills/meight/SKILL.md`](../skills/meight/SKILL.md#learning-loop-decision-records-preferences-lessons)에
있습니다. 판단이 모델 기억이 아니라 디스크에 남으므로, 개인화는 컨텍스트
컴팩션과 새 세션, 심지어 모델 교체까지 살아남습니다.

## Claude Code / Codex에서 쓰기

실제 작업에서는 `wait --timeout`을 백그라운드 셸 호출로 돌리세요.
에이전트는 완료·질문·실패·데몬 사망·체크포인트 타임아웃에 깨어납니다.

```text
Bash(command: "meight start review-1 --mode review --report decision --sandbox ro --model sol --effort high --brief-file - <<'EOF' ... EOF")
Bash(command: "meight wait review-1 --timeout 300", run_in_background: true)
-> 체크포인트 exit 1
-> meight status review-1
-> 정상: 다시 wait · 이탈: meight steer review-1 "..."
```

Claude 오케스트레이터용 드롭인 프롬프트는 [`CLAUDE.md`](../CLAUDE.md),
Codex-as-orchestrator 프롬프트는 [`AGENTS.md`](../AGENTS.md)로 제공됩니다.
디스패처용 전체 스킬은 [`skills/meight/`](../skills/meight/SKILL.md), 세션
계약은 [`skills/meight-mate/`](../skills/meight-mate/SKILL.md)와
[`skills/meight-worker/`](../skills/meight-worker/SKILL.md), 공유 프로토콜은
[`skills/meight-common/`](../skills/meight-common/CONTRACT.md)입니다.

기본 디스패처는 Claude Code 세션입니다. Codex 앱/CLI 세션도
`~/.codex/skills/meight` 얇은 바인딩(이 레포의
[`skills/meight/SKILL.md`](../skills/meight/SKILL.md)를 그대로 참조)을 통해
같은 프로토콜로 디스패치할 수 있습니다 — 프로토콜은 하나, 디스패처 런타임은
둘입니다.

## "에이전트에게 쉽다"의 의미

- **Exit code가 API입니다.** `0` 완료, `2` 실패/인터럽트/런타임 소실, `3`
  질문, `4` 데몬 사망, `1` 체크포인트 타임아웃.
- **세션 ID가 아니라 이름.** 세션은 후속 턴까지 `review-1`처럼 이름으로
  부릅니다.
- **바쁜 폴링이 아니라 드문 체크포인트.** `wait --timeout`은 깨어날 시점을
  정하는 다이얼이지, 워커를 죽이지 않습니다.
- **status는 미리 소화되어 있습니다.** 모드, 보고 형식, 현재 항목,
  변경 파일, needs-input target/kind, 마지막 메시지 꼬리를 돌려줍니다.
- **정책은 잊을 수 없습니다.** 모드, 모드별 스킬 로딩, 공유 계약, 보고
  형식은 하네스가 주입합니다 — `--mode`는 티칭 에러가 있는 필수 플래그이고
  데몬 경계에서도 검증되므로, 오래된 CLI나 raw 소켓 클라이언트도
  같은 계약을 받습니다.
- **결과는 디스크에 살아남습니다.** `result.md`는 원본 감사 기록으로 남고,
  decision 보고는 `decision.json`과 `decision.md`를 더합니다.
- **브리프는 stdin으로.** 여러 줄 브리프가 셸 인용 함정을 피합니다.

## 명령 레퍼런스

| 명령 | 하는 일 |
|---|---|
| `meight start <name> --mode design\|review\|delegate [opts]` | 세션을 시작하고 thread id와 함께 즉시 반환. 감독형 워크플로우의 진입점. |
| `meight wait <name> --timeout SEC` | 체크포인트 대기: 터미널 상태, 답변 가능한 QUESTION, 데몬 사망, 타임아웃에 반환. 타임아웃은 워커를 살려둡니다. |
| `meight dispatch <name> --mode design\|review\|delegate [opts]` | 원샷: 데몬 자동 시작 -> capability 확인 -> start -> wait -> 선호 결과 출력. 짧고 단순하고 위험 낮은 작업 전용. |
| `meight reply <name> --brief ...` | 답변 가능한 질문에 원샷 응답. 모드/보고를 상속하고 최신 결과를 출력. |
| `meight follow <name> --brief ...` | 저수준: 같은 라이브 스레드에 새 턴. 모드/보고 상속. |
| `meight result <name> [--raw]` | `decision.md`가 있으면 그것을, `--raw`는 원본 `result.md`를 출력. |
| `meight status [name] [--json] [--all-repos]` | pull 요약. 테이블에 `MODE` 포함; 예전 role 필드나 긴 mode 값이 있는 레거시 행도 읽습니다. |
| `meight steer <name> "text"` | 실행 중인 턴에 지시 주입. |
| `meight interrupt <name>` | 턴 취소. 워커가 아직 시작 중이거나 reply 턴이 열리는 중에 도착한 인터럽트는 기록되고, 턴이 커밋되는 순간 중단시킵니다. |
| `meight list / daemon / ping / shutdown / launchd` | 저수준 지원 명령. |

공통 옵션:

- `--mode design|review|delegate`는 `start`/`dispatch`에 필수입니다.
  `collab`, `collaborative`, `delegated`는 허용되는 별칭입니다. Design과
  review는 메이트 계약을 쓰는 두 협업 모드이고, delegate는 워커 계약을 쓰는
  위임 모드입니다. Design은 blind/anchored design, review는 verdict-first
  plan/diff 리뷰, delegate는 구현에 씁니다.
- `--report text|decision` 기본은 `text`; `decision`은
  `decision.json`/`decision.md`를 씁니다.
- `--cwd`는 워커 작업 디렉토리. 파일 스코프가 겹치면 별도 git worktree를
  쓰세요.
- `--sandbox ws|ro|full` 기본은 `full`; 읽기와 리뷰는 보통 `ro`.
- `--model luna|sol|terra`는 짧은 별칭을 받고, 전체 모델 문자열은 그대로
  통과합니다.
- `--effort low|medium|high|xhigh` 기본은 `medium`.
- `--fast`는 해당 워커를 priority service tier로 올립니다; 생략 또는
  `--no-fast`는 비Fast 유지.
- `--main-thread`는 보이는 메인 스레드가 필요한 도구를 위해 숨김 ephemeral
  subagent 스레드를 끕니다.

워커 상태는
`<daemon-home>/repos/<repo-key>/workers/<name>/`에 있습니다: `brief.md`,
`status.json`, `events.log`, `result.md`, decision 모드에서는 `decision.json`과
`decision.md`. 터미널 워커는 디스크 산출물을 남기고 SDK 런타임은 즉시
해제합니다. 최종 구조화 `QUESTION:`은 라이브 데몬에 붙어 있어 `reply`가 같은
스레드로 답할 수 있습니다. 데몬 재시작 후에는 디스크 산출물은 남지만
같은-스레드 reply는 만료됩니다; 새 워커를 시작하세요.

## 구 데몬을 mode3 지원으로 업그레이드

새 CLI는 `meight ping`이 `capabilities=mode3`을 광고하지 않으면 `start` 전에
fail-closed로 멈춥니다 — 그리고 start/follow 응답의 정규화된 mode echo까지
검증하므로, 핸드셰이크 중간에 데몬이 바뀌어도 잘못된 세션 계약을 조용히
사용하지 않습니다. 수동으로 드레인 후 재시작하세요:

1. `meight list --all-repos --json` 확인; 어느 레포에도 `starting`, `running`,
   `needs_input` 세션이 없을 때까지 기다립니다.
2. non-force `meight shutdown` 실행. 거부되면 드레인을 마저 하세요; 이
   마이그레이션에 `--force`를 쓰면 안 됩니다.
3. 데몬을 정상 시작하고 `meight ping`이 `capabilities=mode3`을 보이는지
   확인합니다.
4. 읽기 전용 throwaway `--mode review` 세션을 하나 띄웁니다. status에
   `mode=review`가 기록되고 저장된 프리앰블이
   `skills/meight-mate/SKILL.md`와 `skills/meight-common/CONTRACT.md`를 모두
   참조하는지 확인합니다.
5. 그 스모크가 통과한 뒤에만 실제 디스패치를 재개합니다.

## 알아두면 좋은 것

- Meight는 모델, MCP 서버, 인증에 `~/.codex/config.toml`을 그대로 물려받습니다.
  터미널에서 `codex`가 되면 `meight`도 됩니다.
- Meight는 SDK 번들 런타임이 아니라 현재 시스템의 `codex` 실행 파일을
  사용합니다. 명시적 오버라이드가 필요할 때만 `MEIGHT_CODEX_BIN`을 설정하세요.
- 세션은 기본으로 숨김 ephemeral Codex subagent 스레드로 시작합니다:
  `thread_source=subagent`, `thread_ephemeral=true`.
- 포그라운드 `meight daemon`은 활성 워커가 없으면 기본
  `MEIGHT_IDLE_TIMEOUT_SEC` 후 종료합니다. 관리형 `dispatch` 자동 시작과
  LaunchAgent 시작은 idle 종료를 끕니다; 라이브 값은 `meight ping`으로
  확인하세요.
- `openai-codex`는 핀 고정입니다(`0.1.0b3`, beta). SDK나 Codex CLI를 올릴
  때는 [`SPEC.md`](../SPEC.md)의 검증 스위트를 다시 돌리세요.
- 설계 디테일, 상태 머신, 하드닝 히스토리, 라이프사이클 주의사항은
  [`ARCHITECTURE.md`](../ARCHITECTURE.md)에, 전체 디스패처 프로토콜은
  [`skills/meight/SKILL.md`](../skills/meight/SKILL.md)에 있습니다. 이
  파이프라인이 왜 이런 모양인지 — 자기 자신을 돌려서 설계된 그 날의 기록 —
  은 [`2026-07-14-v3-pipeline-retrospective.md`](./2026-07-14-v3-pipeline-retrospective.md)에
  있습니다.

## 라이선스

MIT
