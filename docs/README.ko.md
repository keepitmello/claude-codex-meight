# claude-codex-meight

<p align="center">
  <img src="./hero.jpg" alt="Claude Fable 5 + Codex" width="720">
</p>

[English](../README.md) | **한국어**

> **Codex 메이트와 워커를 오케스트레이션하기 위한 양방향 하네스.** Meight는
> 위임하고, 상의하고, 조향하고, 리뷰하고, 근거로 승인하는 LLM 에이전트를
> 위해 만들었습니다. 공식 `openai-codex` Python SDK 위에서 동작합니다.
> CLI: `meight`.

대부분의 브릿지는 터미널을 보는 사람을 기준으로 만들어졌습니다: tmux pane,
대시보드, stdout 스크래핑 같은 방식입니다. Meight는 에이전트를 기준으로
설계했습니다. 디스패처는 숨겨진 Codex 세션을 시작하고, 작은 디스크 요약을
읽고, 실행 중인 턴을 조향하고, 구조화된 질문에 답하고, 사용자에게 전달할
만큼 작은 최종 보고를 받을 수 있습니다.

- **명시적 역할.** `--role mate`는 독립 consult/리뷰 계약,
  `--role worker`는 구현/검증 계약을 선택합니다. 역할과 모델은 독립 축이고
  기본 역할은 없습니다.
- **명시적 모드.** `start`와 `dispatch`에는 `--mode collab|delegate`가
  필수입니다. 기본값은 없습니다. 소비자가 LLM 에이전트이므로 정책은 기억이
  아니라 하네스가 강제합니다.
- **기본은 감독형.** `start` + `wait`를 쓰면 실행 중에도 `status`와
  `steer`가 살아 있습니다. `dispatch`는 짧고 단순하고 위험 낮은 작업용으로
  남아 있습니다.
- **구조화된 질문.** 워커는 `QUESTION:`과 `TARGET: dispatcher|user`,
  `KIND`로 끝낼 수 있어서, 중간 에이전트가 직접 답할지 사람에게 올릴지
  판단할 수 있습니다.
- **결정 보고.** `--report decision`은 `decision.json`과 렌더링된
  `decision.md`를 씁니다. 원본 `result.md`는 감사 기록으로 남습니다. 이렇게
  기술 맥락을 격리합니다.
- **방향 갈림길은 blind consult.** 방향을 정하는 결정은 문제와 제약만 담은
  읽기 전용 consult로 독립 의견을 먼저 받습니다.
- **구현 전 plan review.** 방향이 정해지면 `mate/sol`의 최대 3라운드 리뷰가
  versioned `PLAN.md`를 승인·동결합니다.
- **worker/luna 구현, mate/sol 리뷰.** bounded 작업은 `worker/luna xhigh`가
  기본이고, failure-cost hard gate는 `worker/sol` 구현으로 올립니다. 구현 뒤
  `mate/sol`이 동결 plan을 기준으로 적대 리뷰합니다.
- **쓸수록 좋아집니다.** 방향 결정, 사용자 선호, 운영 교훈이 plain file로
  남고, 디스패처는 행동하기 전에 그것부터 읽습니다. 같은 질문이 사람에게 두 번
  가지 않고, 한번 정해진 방향은 정해진 채로 유지됩니다.

```text
   디스패처 에이전트   <->   Codex 메이트 / 워커
   (무엇과 왜)               (도전 / 구현)
        |                       ^
        |-- start + brief ------|
        |
        |<- QUESTION / decision report / result
        |-- reply / steer / consult / review
        |
        v
   전역 데몬 -- 공식 openai-codex SDK -- 워커별 codex app-server
        status.json · events.log · result.md · decision.json · decision.md
```

## 왜 만들었나

공식 `openai-codex` Python SDK는 `codex app-server`와 직접 통신하고,
조향, 중단, 스트리밍, output schema, thread 제어를 API로 제공합니다.
Meight는 활성 워커마다 SDK 런타임을 하나씩 사용하고, 워커가 끝나면 바로
해제해서 MCP subprocess와 파일 디스크립터가 남지 않게 합니다.

tmux/exec wrapper와 비교하면:

| | tmux/exec 브릿지 | MCP 래퍼 | **Meight** |
|---|---|---|---|
| 병렬 워커 | 워커당 프로세스 1개 | 블로킹 툴 콜 | 활성 워커당 SDK 런타임 1개 |
| 실행 중 조향 | attach/type 또는 kill+resume | 없음 | `meight steer` |
| 진행 관찰 | stdout 스크래핑 | 없음 | 디스크 요약, 필요할 때 pull |
| 양방향 대화 | 없음 | 없음 | 구조화된 `QUESTION:` -> exit 3 -> `reply` |
| 결과 전달 | 스크래핑 | 툴 반환값 | exit code 계약 + 결과 파일 |
| 기계 판독 보고 | 없음 | wrapper마다 다름 | `--report decision` via `output_schema` |

그리고 모든 판단이 디스크에 남기 때문에 — 요약, 결정, 선호, 교훈 —
이 페어링은 시간이 갈수록 더 개인적이 됩니다. 디스패처는 자신의 사람이
어떤 질문은 직접 보고 싶어하고, 어떤 질문은 자신에게 믿고 맡기는지를
배워갑니다.

## 빠른 시작

요구사항: [Codex CLI](https://developers.openai.com/codex) 설치와 로그인,
Python >= 3.10.

```bash
git clone https://github.com/keepitmello/claude-codex-meight
cd claude-codex-meight
./install.sh   # .venv 생성 + ~/.local/bin/meight
```

실제 작업은 어느 git repo에서든 감독형으로 시작합니다. Meight는 기본적으로
하나의 전역 데몬을 씁니다(`$MEIGHT_HOME`, `$XDG_STATE_HOME/meight`, 또는
`~/.meight`). 워커 상태는 `repos/<repo-key>/` 아래 repo별로 격리됩니다.

```bash
meight start impl-1 --role worker --mode delegate --report decision --brief-file - --cwd ~/my-repo <<'EOF'
src/foo.py에 X를 구현해. 기존 패턴: src/bar.py:42 참고.
검증: pytest tests/test_foo.py.
변경 파일, 검증, 남은 P1, 리스크, 증거 artifact를 보고해.
EOF

meight wait impl-1 --timeout 300
# exit 0=완료 · 2=실패/중단/runtime-lost · 3=답장 가능한 질문 · 4=데몬 사망 · 1=체크포인트 타임아웃
```

exit `1`이면 워커는 계속 실행 중입니다. 한 번 상태를 보고, 다시 기다리거나
조향합니다:

```bash
meight status impl-1
meight steer impl-1 "헬퍼 리팩토링은 멈추고 버그만 고쳐."
meight wait impl-1 --timeout 300
```

terminal exit에서는 선호 보고서를 읽습니다. 감사용 원본이 필요할 때만
`--raw`를 씁니다:

```bash
meight result impl-1
meight result impl-1 --raw
```

워커가 답장 가능한 질문을 했다면(exit `3`) 같은 target/kind가
`status.json`과 `meight status`에도 보입니다.

```bash
meight reply impl-1 --brief "config-a.json을 쓰고 legacy 필드는 유지해."
```

짧고 단순하고 위험 낮은 작업에는 one-shot dispatch를 쓸 수 있습니다:

```bash
meight dispatch tiny-1 --role worker --mode delegate --report decision --sandbox ro \
  --brief "README에 LICENSE 언급이 있는지만 확인해."
```

meight 워커의 Computer Use 앱 접근은 기본으로 켜져 있습니다. 다른 MCP 승인
동작은 바꾸지 않습니다.

```bash
meight dispatch desktop-qa --role worker --mode delegate --sandbox ro \
  --brief "Computer Use로 Calculator를 확인해. UI 상태는 바꾸지 마."
```

## 운영 모델

| 역할 / 모델 | 기본 소유권 | Effort |
|---|---|---|
| `worker` / `luna` | bounded 구현, 수정, 테스트, 검증, read-only 로그 조사, browser/runtime QA, computer use, 탐색 | `xhigh`, 가능하면 `--fast` |
| `mate` / `sol` | 방향, plan review, adversarial review | `high` 또는 `xhigh` |
| `worker` / `sol` | failure-cost hard gate가 발화한 구현 | `xhigh` |
| 어느 역할이든 / `terra` | 실측 근거가 있는 capability fallback | 작업별 |

Acceptance-critical 동작이 concurrency, security, 공개 schema/API 계약 설계,
영속 데이터 migration, cross-cutting refactor에 materially 의존하거나 실패가
돈/데이터 손상·비가역·고임팩트 production 피해를 만들면 `sol`로 hard
route합니다. 모델이 `sol`이어도 구현은 `--role worker`입니다.

구현 체인은 `worker/luna` → `mate/sol` adversarial review(최대 2라운드) →
dispatcher의 frozen `PLAN.md` + full diff 정독과 최종 sign-off입니다. Scope를
바꾸는 수정은 plan 승인을 다시 열고, P1-fix 수준 수정은 기존 계약을 유지합니다.

## Consult

방향을 정하는 갈림길에서는 blind consult가 기본입니다. 먼저 자신의 분석을
작성하되 브리프에는 넣지 말고, 읽기 전용 메이트에게 가장 근거가 좋은 설계와
그 설계에 대한 가장 강한 반론을 묻습니다.

```bash
meight start consult-auth --role mate --mode collab --sandbox ro --model sol --effort high --cwd ~/my-repo --brief-file - <<'EOF'
auth token refresh 설계를 골라야 한다.

제약:
- 사용자에게 보이는 logout 회귀는 없어야 한다.
- 기존 token storage는 src/auth/store.ts에 있다.
- 기존 request retry 코드는 src/api/client.ts에 있다.

옵션:
- Option A: protected request 전에 만료가 가까우면 refresh한다.
- Option B: API client에서 401을 받을 때 refresh를 중앙화한다.

가장 근거가 좋은 설계, 그 설계에 대한 가장 강한 반론, 남은 불확실성을
해소할 증거를 알려줘. 코드 변경은 하지 마.
EOF
```

이미 방향이 정해진 뒤에는 anchored consult도 유효합니다:

```bash
meight start consult-refine --role mate --mode collab --sandbox ro --model sol --brief \
  "방향은 Option B야. 놓친 점과 edge case를 압박해서 봐줘."
```

두 의견이 갈리면 evidence question과 value judgment를 나눕니다. Evidence는
targeted verification 세션 하나로 확인합니다. Scope, UX, priority, risk
appetite, irreversible action, acceptance criteria 같은 user-owned 판단은
사람에게 올립니다. 최대 두 라운드 뒤에는 되돌리기 쉽고 위험 낮은 쪽을
택하거나 escalation합니다.

방향이 정해진 뒤 plan review는 별도의 anchored loop입니다. Dispatcher가 plan을
쓰고 `--role mate --model sol --mode delegate --report decision`으로 보냅니다.
`APPROVE`는 종료하고, `REVISE`는 dispatcher-targeted decision으로 같은 thread를
살려 `reply`로 다음 라운드를 받습니다. 최대 3라운드이며 매 라운드
`new-risks`와 `resolved-risks`를 분리합니다. 승인된 versioned `PLAN.md`가 구현과
최종 리뷰 계약이고, scope 변경은 승인을 다시 엽니다.

## 하네스는 배웁니다

세 가지 plain-file ledger가 디스패치 루프를 쓸수록 좋아지게 만듭니다:

- **결정 기록** (`<repo>/decisions/`). 두 독립 분석으로 결론이 난 방향
  갈림길마다 기록이 남습니다: 양쪽 입장, 갈린 지점, 무엇이 결론을 냈는지.
  이후 세션은 *왜*를 감사할 수 있고, 한번 정리된 질문은 정리된 채로
  유지됩니다.
- **선호 원장** (`<daemon-home>/notes/preferences.md`). 사람이 `TARGET: user`
  질문에 답할 때마다 그 답이 기록됩니다. 디스패처는 escalation 전에 원장을
  먼저 확인하므로, 같은 부류의 질문은 사람에게 한 번만 도달합니다 — 단,
  irreversible과 risk 결정만은 항상 다시 확인합니다.
- **교훈** (`<daemon-home>/notes/lessons.md`). 반복되는 리뷰 발견과 운영
  실수는 한 줄 교훈이 되고, 재발하면 brief template으로 승격됩니다. Run
  record마다 `mate|worker` 역할도 기록합니다.

이 중 무엇도 새 서브시스템이 아닙니다 — 파일과 doctrine뿐이며, 정의는
[`skills/meight/SKILL.md`](../skills/meight/SKILL.md#learning-loop-decision-records-preferences-lessons)에
있습니다. 판단이 model memory가 아니라 디스크에 남기 때문에, 이 개인화는
컨텍스트 압축과 새 세션, 심지어 모델 교체까지 살아남습니다.

## Claude Code 또는 Codex에서 쓰기

실제 작업에서는 `wait --timeout`을 background shell call로 실행합니다.
에이전트는 완료, 질문, 실패, 데몬 사망, 체크포인트 타임아웃에서 깨어납니다.

```text
Bash(command: "meight start review-1 --role mate --mode delegate --report decision --sandbox ro --model sol --effort high --brief-file - <<'EOF' ... EOF")
Bash(command: "meight wait review-1 --timeout 300", run_in_background: true)
-> checkpoint exit 1
-> meight status review-1
-> 정상이면 다시 wait · 틀어졌으면 meight steer review-1 "..."
```

Claude 오케스트레이터용 drop-in prompt는 [`CLAUDE.md`](../CLAUDE.md)에
있습니다. Codex-as-orchestrator prompt는 [`AGENTS.md`](../AGENTS.md)에
있습니다. 전체 dispatcher-facing skill은
[`skills/meight/`](../skills/meight/SKILL.md)에 있고, 역할 계약은
[`skills/meight-mate/`](../skills/meight-mate/SKILL.md)와
[`skills/meight-worker/`](../skills/meight-worker/SKILL.md), 공유 계약은
[`skills/meight-common/`](../skills/meight-common/CONTRACT.md)에 있습니다.

## "에이전트에게 편하다"는 뜻

- **Exit code가 API입니다.** `0` 완료, `2` 실패/중단/runtime-lost, `3` 질문,
  `4` 데몬 사망, `1` 체크포인트 타임아웃입니다.
- **세션 ID가 아니라 이름.** 워커는 후속 턴까지 `review-1` 같은 이름으로
  다룹니다.
- **촘촘한 폴링이 아니라 드문 체크포인트.** `wait --timeout`은 깨우는
  다이얼이지 워커를 죽이는 시간이 아닙니다.
- **Status는 이미 요약본입니다.** role, mode, report type, current item,
  changed files, needs-input target/kind, last-message tail을 보여줍니다.
- **정책은 잊힐 수 없습니다.** Role, mode, role skill, shared contract,
  report shape은 하네스가 주입합니다.
- **결과는 디스크에 남습니다.** `result.md`는 원본 감사 기록이고,
  decision report는 `decision.json`과 `decision.md`를 추가합니다.
- **브리프는 stdin으로 받습니다.** 긴 멀티라인 브리프가 shell quoting
  함정을 피합니다.

## 커맨드 레퍼런스

| 커맨드 | 동작 |
|---|---|
| `meight start <name> --role mate\|worker --mode collab\|delegate [opts]` | 세션을 시작하고 thread id를 출력한 뒤 바로 반환. 감독형 워크플로우 시작점 |
| `meight wait <name> --timeout SEC` | terminal 상태, 답장 가능한 QUESTION, 데몬 사망, 타임아웃 중 하나에서 반환. 타임아웃은 워커를 계속 살려둠 |
| `meight dispatch <name> --role mate\|worker --mode collab\|delegate [opts]` | one-shot: 데몬 자동 시작 -> capability 확인 -> 시작 -> 대기 -> 선호 결과 출력 |
| `meight reply <name> --brief ...` | 답장 가능한 질문에 one-shot 답변. role/mode/report를 상속 |
| `meight follow <name> --brief ...` | 저수준: 같은 live thread에 새 턴. role/mode/report 상속 |
| `meight result <name> [--raw]` | 있으면 `decision.md` 출력. `--raw`는 원본 `result.md` 출력 |
| `meight status [name] [--json] [--all-repos]` | digest pull. 테이블에는 `ROLE`과 `MODE`; legacy row의 role은 `-` |
| `meight steer <name> "text"` | 실행 중 턴에 지시 주입 |
| `meight interrupt <name>` | 턴 취소. 워커가 아직 시작 중이거나 답변 턴을 여는 중에 도착한 interrupt는 기록되었다가, 시작이 완료되는 순간 턴을 중단시킵니다 |
| `meight list / daemon / ping / shutdown / launchd` | 저수준 보조 커맨드 |

자주 쓰는 옵션:

- `--role mate|worker`는 `start`와 `dispatch`에 필수이며 기본값이 없습니다.
  Consult/review는 `mate`, 구현/검증은 `worker`입니다.
- `--mode collab|delegate`는 `start`와 `dispatch`에 필수입니다
  (`collaborative`/`delegated` alias 허용).
- `--report text|decision`은 기본 `text`입니다. `decision`은
  `decision.json`/`decision.md`를 씁니다.
- `--cwd`는 워커 작업 디렉토리입니다. 파일 범위가 겹치면 별도 git
  worktree를 쓰세요.
- `--sandbox ws|ro|full`은 기본 `full`입니다. 리뷰와 consult는 보통 `ro`를
  씁니다.
- `--effort low|medium|high|xhigh`는 기본 `medium`입니다.
- `--fast`는 특정 워커만 priority service tier로 보냅니다. 생략하거나
  `--no-fast`면 non-Fast입니다.
- `--main-thread`는 visible main thread가 필요한 도구에서만 씁니다.

워커 상태는 `<daemon-home>/repos/<repo-key>/workers/<name>/`에 있습니다:
`brief.md`, `status.json`, `events.log`, `result.md`, decision mode에서는
`decision.json`과 `decision.md`도 있습니다. Terminal worker는 디스크
artifact를 남기지만 SDK runtime은 즉시 해제합니다. 마지막 structured
`QUESTION:`만 live daemon에 붙어 있어서 같은 thread로 `reply`할 수
있습니다. 데몬 재시작 뒤에는 디스크 artifact는 남지만 same-thread reply는
만료되므로 새 워커를 시작하세요.

## 구 데몬을 role 지원 버전으로 바꾸기

새 CLI는 live daemon이 `role` capability를 광고하지 않으면 start request를
보내기 전에 `daemon predates --role; restart required`로 fail-closed합니다.
마이그레이션은 운영자가 다음 체크리스트로 수행합니다:

1. `meight list --all-repos --json`으로 모든 repo namespace를 확인하고
   `starting`, `running`, `needs_input` 세션을 전부 drain합니다.
2. non-force `meight shutdown`을 실행합니다. 거부되면 drain을 마저 하고,
   이 마이그레이션에서는 `--force`를 쓰지 않습니다.
3. 정상 설치 경로로 새 데몬을 시작한 뒤 `meight ping`의
   `capabilities=role`을 확인합니다.
4. read-only throwaway 세션을 `--role mate --mode delegate`로 시작합니다.
5. status에 `role=mate`가 기록되고 saved `brief.md` preamble에
   `skills/meight-mate/SKILL.md`와 `skills/meight-common/CONTRACT.md`가 모두
   들어가는지 확인한 뒤 실제 dispatch를 재개합니다.

## 알아두면 좋은 것

- Meight는 model, MCP server, auth를 `~/.codex/config.toml`에서 상속합니다.
  터미널에서 `codex`가 되면 `meight`도 됩니다.
- Meight는 SDK에 포함된 runtime 대신 현재 시스템의 `codex` 실행 파일을
  사용합니다. 특정 실행 파일을 강제로 쓸 때만 `MEIGHT_CODEX_BIN`을 설정하세요.
- 워커는 기본적으로 hidden ephemeral Codex subagent thread로 시작합니다:
  `thread_source=subagent`, `thread_ephemeral=true`.
- Foreground `meight daemon`은 기본적으로 활성 워커가 없으면
  `MEIGHT_IDLE_TIMEOUT_SEC` 뒤 종료됩니다. Managed `dispatch` auto-start와
  LaunchAgent 시작은 idle shutdown을 끕니다. 실제 값은 `meight ping`으로
  확인하세요.
- `openai-codex`는 베타라 버전을 고정했습니다(`0.1.0b3`). SDK나 Codex CLI를 올릴 때는
  [`SPEC.md`](../SPEC.md)의 검증 스위트를 재실행하세요.
- 설계 상세, state machine, hardening history, lifecycle caveat는
  [`ARCHITECTURE.md`](../ARCHITECTURE.md)에 있습니다. 전체 dispatcher
  protocol은 [`skills/meight/SKILL.md`](../skills/meight/SKILL.md)에 있습니다.

## License

MIT
