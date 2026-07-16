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
버리는 일이다.** 그래서 meight는 세 가지 Codex 세션 계약을 네 운영 모드로
제공합니다.

- **메이트**(`--mode design` 또는 `--mode review`)는 독립적인 도전자입니다.
  진짜 판정이 걸린 plan 리뷰, 적대적 결함 사냥, blind design을 맡습니다 — 계약에 *디스패처에게
  도전하라, 동의가 목표가 아니다*라고 적혀 있습니다.
- **워커**(`--mode worker`)는 디스패처 참여형 bounded 구현자입니다.
  코드·테스트·검증·런타임 QA를 소유하고, 외부 리뷰의 필요성과 방식은
  디스패처가 판단합니다.
- **델리게이트**(`--mode delegate`)는 디스패처가 기술 맥락에서 빠진 상태로
  구현과 fresh-context 독립 리뷰를 끝까지 소유합니다. 하드게이트·money path·
  frozen dispatcher review chain 작업은 worker 모드로 fail-closed 합니다.

메이트·워커·델리게이트는 모델 정체성이 아니라 세션 계약의 이름입니다. 모드는 계약을,
`--model`은 두뇌를 고릅니다. 디스패처는 방향·중재·통합·최종 사인오프를
쥐고 있고, 메이트·워커·델리게이트의 말만으로 머지되는 것은 없습니다.

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

## 프로세스보다 판단

Meight가 제공하는 것은 의무 개발 파이프라인이 아니라 네 가지 세션
모드입니다. 과설계를 피하는 것이 최우선입니다. 디스패처는 작업의 실패 비용에
맞춰 필요한 설계·리뷰·구현·검증 게이트만 고르고, 그 선택을 한 줄로
기록합니다.

Blind/anchored design은 실제 방향 갈림길을 명확히 할 때 쓸 수 있습니다.
Plan 리뷰와 적대적 코드 리뷰도 필요할 때 꺼내는 판정 도구이지 기본 단계가
아닙니다. Worker 모드에서는 디스패처가 필요하다고 판단할 때 별도 review
세션을 띄우고, delegate 모드에서는 계약의 fresh-context 내부 리뷰를
사용합니다. 워커의 `done`은 여전히 주장일 뿐입니다. 리뷰한 작업의 사인오프는
리뷰 판정과 검증 근거를 함께 요구하고, 리뷰하지 않은 작업도 검증 근거는
필수입니다. diff 전문 읽기는 어떤 모드에서도 사인오프 게이트가 아닙니다.

포함된 operator-policy 템플릿은 bounded 작업을 `luna`에 라우팅하고,
acceptance-critical 동시성·보안·공개 API 계약 설계·데이터 마이그레이션·횡단
리팩터 또는 돈/데이터 손상과 비가역 피해 가능성이 있는 작업에 failure-cost
하드 게이트를 적용합니다. 이 모델 및 money-path 게이트는 조정 가능한 운영자
정책이지 meight 인터페이스 요구사항이 아닙니다.

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
| 세션 계약 | 없음 | 없음 | `--mode design\|review\|worker\|delegate`, 하네스가 주입 |

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
meight start impl-1 --mode worker \
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
meight start design-auth --mode design \
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

별도 감독 세션이 가치를 더하지 않을 때는 원샷 디스패치도 쓸 수 있습니다:

```bash
meight dispatch tiny-1 --mode worker --sandbox ro \
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
  기록에는 모드, 한 줄 게이트 선택, 재라우팅 이유, 사인오프 후 결함을 남길
  수 있습니다 — 측정 자체를 의식으로 만들지 않으면서 결과로 라우팅을
  튜닝하기에 충분합니다.

이 중 어느 것도 새 서브시스템이 아닙니다 — 파일과 독트린뿐이고, 정의는
[`skills/meight/SKILL.md`](../skills/meight/SKILL.md#learning-loop-decision-records-preferences-lessons)에
있습니다. 판단이 모델 기억이 아니라 디스크에 남으므로, 개인화는 컨텍스트
컴팩션과 새 세션, 심지어 모델 교체까지 살아남습니다.

## Claude Code / Codex에서 쓰기

실제 작업에서는 `wait --timeout`을 백그라운드 셸 호출로 돌리세요.
에이전트는 완료·질문·실패·데몬 사망·체크포인트 타임아웃에 깨어납니다.

```text
Bash(command: "meight start review-1 --mode review --brief-file - <<'EOF' ... EOF")
Bash(command: "meight wait review-1 --timeout 300", run_in_background: true)
-> 체크포인트 exit 1
-> meight status review-1
-> 정상: 다시 wait · 이탈: meight steer review-1 "..."
```

Claude 오케스트레이터용 드롭인 프롬프트는 [`CLAUDE.md`](../CLAUDE.md),
Codex-as-orchestrator 프롬프트는 [`AGENTS.md`](../AGENTS.md)로 제공됩니다.
디스패처용 전체 스킬은 [`skills/meight/`](../skills/meight/SKILL.md), 세션
계약은 [`skills/meight-mate/`](../skills/meight-mate/SKILL.md),
[`skills/meight-worker/`](../skills/meight-worker/SKILL.md),
[`skills/meight-delegate/`](../skills/meight-delegate/SKILL.md), 공유 프로토콜은
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
| `meight start <name> --mode design\|review\|worker\|delegate [opts]` | 세션을 시작하고 thread id와 해석된 mode/contract/model/effort/Fast/report/sandbox 값 및 default/set 출처를 출력한 뒤 즉시 반환. 감독형 워크플로우의 진입점. |
| `meight wait <name> --timeout SEC` | 체크포인트 대기: 터미널 상태, 답변 가능한 QUESTION, 데몬 사망, 타임아웃에 반환. 타임아웃은 워커를 살려둡니다. |
| `meight dispatch <name> --mode design\|review\|worker\|delegate [opts]` | 원샷: 데몬 자동 시작 -> capability 확인 -> start -> wait -> 선호 결과 출력. |
| `meight reply <name> --brief ... [--model M] [--effort E] [--fast\|--no-fast]` | 답변 가능한 질문에 원샷 응답. 모드/보고와 생략한 턴 설정을 상속하고, 명시한 설정은 새 턴부터 적용한 뒤 최신 결과를 출력. |
| `meight follow <name> --brief ... [--model M] [--effort E] [--fast\|--no-fast]` | 저수준: 같은 라이브 스레드에 새 턴. 모드/보고와 생략한 턴 설정을 상속하며, 명시한 설정은 이후 턴의 상속값이 됨. |
| `meight result <name> [--raw]` | `decision.md`가 있으면 그것을, `--raw`는 원본 `result.md`를 출력. |
| `meight status [name] [--json] [--all-repos]` | pull 요약. 테이블에 `MODE` 포함; 예전 role 필드나 긴 mode 값이 있는 레거시 행도 읽습니다. |
| `meight steer <name> "text"` | 실행 중인 턴에 지시 주입. |
| `meight interrupt <name>` | 턴 취소. 워커가 아직 시작 중이거나 reply 턴이 열리는 중에 도착한 인터럽트는 기록되고, 턴이 커밋되는 순간 중단시킵니다. |
| `meight list / daemon / ping / shutdown / launchd` | 저수준 지원 명령. |

공통 옵션:

- `--mode design|review|worker|delegate`는 `start`/`dispatch`에 필수입니다.
  `collab`, `collaborative`, `delegated`는 허용되는 별칭입니다. Design과
  review는 메이트 계약, worker는 디스패처가 리뷰 여부를 판단하는 참여형 구현,
  delegate는 내부 독립 리뷰까지 맡기는 전권 위임입니다. 금지 라우트는 worker로
  fail-closed 합니다.
- `--report text|decision`은 아래 모드 기본값을 사용하며, `decision`은
  `decision.json`/`decision.md`를 씁니다. 명시한 플래그는 항상 우선합니다.
- `--cwd`는 워커 작업 디렉토리. 파일 스코프가 겹치면 별도 git worktree를
  쓰세요.
- `--sandbox ws|ro|full`은 아래 모드 기본값을 사용합니다.
- `--model luna|sol|terra`는 짧은 별칭을 받고, 전체 모델 문자열은 그대로
  통과합니다.
- `--effort low|medium|high|xhigh|ultra|max`는 아래 모드 기본값을 사용합니다.
- `--fast`는 priority service tier를 선택하고, `--no-fast`는 끕니다.
  `follow`/`reply`에서 `--model`, `--effort`, Fast 플래그를 생략하면 현재
  워커 값을 상속합니다. 명시한 override는 그 새 턴부터 적용되고 이후 턴이
  상속할 값으로 기록됩니다.
- `--main-thread`는 보이는 메인 스레드가 필요한 도구를 위해 숨김 ephemeral
  subagent 스레드를 끕니다.

생략한 `start`/`dispatch` 설정은 요청을 보내기 전에 CLI에서 해석됩니다:

| 모드 | 모델 | Effort | Fast | Report | Sandbox |
|---|---|---|---|---|---|
| `design` | `sol` | `high` | 끔 | `text` | `ro` |
| `review` | `sol` | `high` | 끔 | `decision` | `ro` |
| `worker` | `luna` | `xhigh` | 켬 | `decision` | `full` |
| `delegate` | `sol` | `high` | 끔 | `decision` | `full` |

표준값은 조용히 쓰고, 편차만 명시합니다. 이 표는 단순성을 위해
`meight.py` 코드에만 있는 운영자 정책이며 config 파일이나 환경변수 override
계층은 없습니다. 시작 출력은 해석된 모든 값에 `(default)` 또는 `(set)`
출처를 붙여 보여 줍니다.

워커 상태는
`<daemon-home>/repos/<repo-key>/workers/<name>/`에 있습니다: `brief.md`,
`status.json`, `events.log`, `result.md`, decision 모드에서는 `decision.json`과
`decision.md`. 터미널 워커는 디스크 산출물을 남기고 SDK 런타임은 즉시
해제합니다. 최종 구조화 `QUESTION:`은 라이브 데몬에 붙어 있어 `reply`가 같은
스레드로 답할 수 있습니다. 데몬 재시작 후에는 디스크 산출물은 남지만
같은-스레드 reply는 만료됩니다; 새 워커를 시작하세요.

워커 이름은 영문자/숫자로 시작하는 1~128자의 ASCII 영문자, 숫자, `._-`만
허용하며 CLI와 데몬이 모두 경로 문법을 거부합니다. 데몬은 socket 요청의
repo 경로를 믿지 않고 repo key/state home을 직접 다시 계산해 검증합니다.
데몬 home, `repos/`, repo/worker 상태 디렉터리는 `0700`, `meight.sock`은
`0600`이고 worker 상태 경로의 symlink는 거부합니다. 요청 한 줄은 1 MiB로
제한합니다. 프로세스 전체 umask는 설정하지 않으므로 워커가 레포에 만드는
파일 모드는 바뀌지 않습니다.

터미널 산출물은 기본 30일 보존합니다. `MEIGHT_SESSION_RETENTION_SEC`로 초를
지정하고 `0`이면 디스크 정리를 끕니다. 정리는 accept loop 밖에서 최대 시간당
한 번 실행되며 active/replyable, malformed, symlink, 현재 registry에 등록된
워커는 건드리지 않습니다. 새 터미널 전이는 불변 `terminal_at`을 기록하고
레거시 행만 `updated_at`을 사용합니다. 데몬 crash/restart 뒤 orphan active 행은
증거를 보존한 채 `failed`/`runtime_lost_detail`로 바뀌며 숨김 ephemeral turn은
재개하지 않습니다.

## 구 데몬을 mode4 지원으로 업그레이드

새 CLI는 `meight ping`이 `capabilities=mode4`를 광고하지 않으면 `start` 전에
fail-closed로 멈춥니다. 모든 start/follow 요청은 epoch `mode4`를 싣고, 성공
응답은 정규화된 mode와 epoch를 원자적으로 함께 에코합니다. 그래서 같은
`delegate` 문자열을 쓰는 구 데몬으로 중간 교체되어도 침묵 다운그레이드는
불가능합니다. 수동으로 드레인 후 재시작하세요:

1. `meight list --all-repos --json` 확인; 어느 레포에도 `starting`, `running`,
   `needs_input` 세션이 없을 때까지 기다립니다.
2. non-force `meight shutdown` 실행. 거부되면 드레인을 마저 하세요; 이
   마이그레이션에 `--force`를 쓰면 안 됩니다.
3. LaunchAgent 로드 여부로 분기합니다. 로드됐으면 `meight launchd install
   --load`로 bounded `bootout --wait` 소유권 이전을 수행하고, 미로드면 데몬을
   정상 기동합니다.
4. `meight ping`이 `capabilities=mode4`를 보이는지, 새 PID와 socket identity가
   일치하는지 확인합니다.
5. 읽기 전용 throwaway `--mode worker` 스모크로 status mode와
   `meight-worker`+common 프리앰블 경로를 확인합니다.
6. 읽기 전용 delegate 스모크 두 개를 실행합니다. (a) 의도적으로 non-trivial한
   brief는 fresh-context/read-only 내부 리뷰어 호출, verdict, round 수, 최종
   decision surface를 evidence에 기록해야 합니다. (b) trivial brief는 리뷰
   면제를 명시하고 면제 근거를 기록해야 합니다. 둘 다 status `mode=delegate`와
   `meight-delegate`+common 프리앰블 경로를 확인합니다.
7. 모든 스모크 통과 뒤에만 실제 디스패치를 재개합니다.

## 알아두면 좋은 것

- Meight는 모델, MCP 서버, 인증에 `~/.codex/config.toml`을 그대로 물려받습니다.
  터미널에서 `codex`가 되면 `meight`도 됩니다.
- Meight는 SDK 번들 런타임이 아니라 현재 시스템의 `codex` 실행 파일을
  사용합니다. 명시적 오버라이드가 필요할 때만 `MEIGHT_CODEX_BIN`을 설정하세요.
- 세션은 기본으로 숨김 ephemeral Codex subagent 스레드로 시작합니다:
  `thread_source=subagent`, `thread_ephemeral=true`.
- 포그라운드 `meight daemon`은 활성 워커가 없으면 기본
  `MEIGHT_IDLE_TIMEOUT_SEC` 후 종료합니다. 관리형 `dispatch` 자동 시작과
  LaunchAgent 시작은 idle 종료를 끕니다; idle/retention 라이브 값은
  `meight ping`으로 확인하세요.
- LaunchAgent는 crash에만 재시작하는 `SuccessfulExit=false` supervision을
  씁니다. 정상 shutdown은 멈춘 채 유지됩니다. job이 load되어 있으면 auto-start는
  `launchctl kickstart`를 쓰고 `kickstart -k`는 쓰지 않습니다. detached 직접
  시작은 job이 없을 때만 사용합니다. `launchd install --load`는 non-force drain
  승인 뒤 기존 PID/socket 소멸을 기다리고, load된 job에 bounded
  `launchctl bootout --wait`를 실행한 다음
  bootstrap하여 새 PID와 socket identity를 확인하고 그 PID가 launchd가 보고한
  실행 PID와 같은지도 검증합니다. `launchctl` 결과가
  모호하거나 비정상 데몬이 singleton lock을 잡고 있으면 fail-closed로
  거부합니다. 공개 socket이 삭제되거나 교체되면 데몬은 0이 아닌 코드로
  종료되어 launchd가 다시 만들게 합니다.
- `openai-codex`는 핀 고정입니다(`0.1.0b3`, beta). SDK나 Codex CLI를 올릴
  때는 [`SPEC.md`](../SPEC.md)의 검증 스위트를 다시 돌리세요.
- 설계 디테일, 상태 머신, 하드닝 히스토리, 라이프사이클 주의사항은
  [`ARCHITECTURE.md`](../ARCHITECTURE.md)에, 전체 디스패처 프로토콜은
  [`skills/meight/SKILL.md`](../skills/meight/SKILL.md)에 있습니다. 이전
  파이프라인 설계 회고 — 자기 자신을 돌려서 설계된 그 날의 기록 — 는
  [`2026-07-14-v3-pipeline-retrospective.md`](./2026-07-14-v3-pipeline-retrospective.md)에
  있습니다.

## 라이선스

MIT
