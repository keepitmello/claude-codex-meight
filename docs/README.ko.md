# claude-codex-meight

<p align="center">
  <img src="./hero.jpg" alt="Claude Fable 5 + Codex" width="720">
</p>

[English](../README.md) | **한국어**

> **Codex mate가 당신의 계획에 반론을 던지고, Codex worker가 그걸 만들어내는
> 양방향 하네스.** meight는 협업으로 설계하고, 위임하고, 조향하고, 리뷰하고,
> 증거로 사인오프하는 LLM 에이전트를 위해 만들어졌다. 바닥에는 공식
> `openai-codex` Python SDK가 있다. CLI 이름은 `meight`.

대부분의 브리지는 터미널을 지켜보는 사람을 위해 만들어졌다 — tmux 패널,
대시보드, stdout 긁기. meight는 에이전트 자신을 위해 만들어졌다. 디스패처가
숨은 Codex 세션을 띄우고, 압축된 디스크 다이제스트를 읽고, 도는 턴을 조향하고,
구조화된 질문에 답하고, 최종 리포트를 구현 디테일에 파묻히지 않고 사용자
결정을 내릴 수 있을 만큼 작게 유지한다.

핵심 아이디어는 이거다: 프론티어 모델을 침묵하는 실행자로 쓰는 건 능력을
탁자에 버려두는 짓이다. 그래서 meight는 두 개의 자세 — 두 개의 Codex 세션
계약을 노출한다:

- **mate** (`--mode mate`)는 독립적인 생각 상대다. 블라인드/앵커드 설계에
  참여하고, 진단하고, 이름 붙은 아티팩트를 독립적으로 리뷰한다 — 계약이
  말하길 *디스패처에게 반론하라, 동의가 목표가 아니다*. 리뷰어는 근거에 따라
  material한 문제와 더 나은 방향을 모두 올릴 수 있다.
- **worker** (`--mode worker`)는 팀 구현자다. 코드, 테스트, 검증, 자기 리뷰를
  소유하고, 침묵 실행 대신 관찰과 더 나은 방향을 위로 올리며, 디스패처
  사인오프 게이트(보안 민감, 공개 API 계약, 데이터 마이그레이션, 돈 경로,
  동결된 리뷰 체인)를 만나면 작업 전에 에스컬레이션한다. 별도 외부 리뷰를
  돌릴지는 디스패처가 정한다.

mate와 worker는 세션 계약의 이름이지 모델의 이름이 아니다. 모드가 계약을
고르고 `--model`이 두뇌를 고른다. 방향, 중재, 통합, 최종 사인오프는 디스패처
몫이고, mate나 worker의 말만 믿고 머지되는 것은 없다.

```text
   dispatcher agent   <->   Codex mate(s) / worker(s)
   (what and why)           (challenge / implement)
        |                       ^
        |-- dispatch + brief ---|
        |
        |<- QUESTION / result
        |-- reply / steer / design / review
        |
        v
   global daemon -- official openai-codex SDK -- per-worker codex app-server
        status.json · events.log · result.md
```

## 프로세스보다 판단 먼저

meight가 주는 건 두 개의 세션 자세지, 의무적인 개발 파이프라인이 아니다.
오버엔지니어링 회피가 최우선이다: 디스패처는 작업의 실패 비용이 정당화하는
설계·리뷰·구현·검증 게이트만 고르고, 그 선택을 한 줄로 기록한다.

블라인드/앵커드 설계는 진짜 방향 분기를 정리할 때 쓴다. 아티팩트 리뷰는
부정·긍정 패스를 미리 나눈 절차가 아니라 독립 판단이다. 의도한 결과와 제약을
주면 리뷰어가 요청받지 않은 내용이라도 material한 문제와 더 나은 방향을 올릴
수 있다. 기본은 mate 하나고, 다른 fresh read가 실제 결정을 바꿀 수 있을 때만
하나를 더 병렬로 띄운다. worker의 `done`은 여전히 주장일 뿐이며 사인오프에는
검증 증거가 필요하다. acceptance gate로 선택한 리뷰만 verdict를 추가로 요구한다.

동봉된 오퍼레이터 정책 템플릿은 worker를 `grok high`로 시작한다. 레포 이해와
숨은 blocker 판단이 필요하면 디스패처가 `--model sol`을 명시한다. 작업 전체의
계약(수용 기준)·범위(파일/디렉토리 경계)·증거(검증 방법)를 브리프가 완결적으로
담으면 `--model luna`를 명시 선택할 수 있고, 실행·수렴을 위한 `luna max`와
Fast가 함께 해소된다. mate/review 기본은 `sol medium`이고, Grok 판단면은
`--model grok` 또는 `--model grok --effort xhigh`로 연다. 실패 비용은 별도
축으로 남아 브레인을 올리거나 리뷰를 붙이는 판단에 쓰인다. 어려운 작업은
워커를 키우는 대신 단계를 붙인다: `sol` mate의 플랜을 동결한 뒤 완결 브리프로
worker에 넘긴다. 이 모델·돈 경로 게이트는 명시적으로 조정 가능한 오퍼레이터
정책이지 meight 인터페이스 요구사항이 아니다.

effort도 같은 경제학을 따른다: 선택된 `luna`는 `max`로 돌린다 — `xhigh` 대비
25% 비용으로 종합 4점을 사기 때문이다. 선택된 `grok`는 `high`이고, `xhigh`는
명시 선택이자 카탈로그 상한이다. worker의 `sol`은 선택됐을 때 `medium`에
머문다. 형식적이거나 실패 비용이 큰 리뷰는 `sol high` 또는 `grok xhigh`를 쓸
수 있다. 설계의 높은 effort는 정말 어려울 때 디스패처가 판단하고 띄우기 전에
사용자 확인을 한 번 받는다. `sol`에 `xhigh`는 쓰지 않는다. Grok에는 Fast와
`max`/`ultra`가 없다.

## 왜 이게 존재하나

공식 `openai-codex` Python SDK는 `codex app-server`와 직접 대화하며 조향,
인터럽트, 스트리밍, output schema, 스레드 제어를 API로 노출한다. meight는
활성 워커당 SDK 런타임 하나를 쓰고, 워커가 끝나면 놓아준다 — MCP
서브프로세스와 파일 디스크립터가 늘어붙지 않게.

tmux/exec 래퍼들과 비교하면:

| | tmux/exec 브리지 | MCP 래퍼 | **meight** |
|---|---|---|---|
| 병렬 세션 | 워커당 프로세스 1개 | 블로킹 툴 콜 | 활성 워커당 SDK 런타임 1개 |
| 턴 중 조향 | attach해서 타이핑 or kill+resume | 불가 | `meight steer` |
| 진행 관찰 | stdout 긁기 | 불가 | 디스크 다이제스트, 필요할 때 pull |
| 양방향 대화 | 불가 | 불가 | 구조화된 `QUESTION:` → exit 3 → `reply` |
| 결과 전달 | 긁기 | 툴 리턴 | exit 코드 계약 + 결과 파일 |
| 결과 형식 | 불가 | 래퍼마다 다름 | 일반 텍스트 `result.md` |
| 세션 계약 | 없음 | 없음 | `--mode mate\|worker`, 하네스가 주입 |

그리고 모든 판단이 디스크에 남기 때문에 — 다이제스트, 결정 기록, 선호, 교훈 —
이 페어링은 쓸수록 개인화된다: 디스패처는 자기 사람이 어떤 질문을 보고 싶어
하는지, 어떤 질문은 스스로 답해도 되는 신뢰를 받았는지 배워간다.

## 빠른 시작

요구사항: [Codex CLI](https://developers.openai.com/codex) 설치·인증 완료,
Python >= 3.10.

```bash
git clone https://github.com/keepitmello/claude-codex-meight
cd claude-codex-meight
./install.sh   # .venv + ~/.local/bin/meight 생성
```

실제 작업은 아무 git 레포에서나 감독 디스패치로 한다. meight는 기본적으로
전역 데몬 하나를 쓰고(`$MEIGHT_HOME`, `$XDG_STATE_HOME/meight`, 또는
`~/.meight`), 워커 상태는 레포별로 `repos/<repo-key>/` 아래 격리한다.

```bash
meight dispatch impl-1 --mode worker --timeout 300 \
  --brief-file - --cwd ~/my-repo <<'EOF'
Implement X in src/foo.py. Existing pattern: see src/bar.py:42.
Verify with: pytest tests/test_foo.py.
Report changed files, verification, remaining P1s, risks, and evidence artifact.
EOF
# exit 0=완료 · 2=실패/인터럽트/런타임 유실 · 3=답할 수 있는 질문 · 4=데몬 사망 · 1=체크포인트 타임아웃
```

exit `1`이면 워커는 아직 돌고 있다. 한 번 들여다보고 조향한 뒤, 별도 대기
없이 같은 `dispatch`를 다시 실행해 재부착한다:

```bash
meight status impl-1
meight steer impl-1 "Stop refactoring the helper; only fix the bug."
meight dispatch impl-1 --mode worker --timeout 300
```

terminal exit이면 텍스트 결과를 읽는다:

```bash
meight result impl-1
```

워커가 답할 수 있는 질문을 남겼다면(exit `3`)? 같은 target/kind가
`status.json`과 `meight status`에도 보인다.

```bash
meight reply impl-1 --brief "Use config-a.json and keep the legacy field."
```

블라인드 설계는 mate에게 간다 — 조언과 협업:

```bash
meight dispatch design-auth --mode mate \
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

별도 감독 세션이 의미 없을 땐 원샷 디스패치:

```bash
meight dispatch tiny-1 --mode worker --sandbox ro \
  --brief "Check whether README mentions LICENSE."
```

Computer Use 앱 접근은 meight 세션마다 기본 허용된다. 그 외 MCP 승인은 원래
동작 그대로다.

## 구조화된 질문

세션은 추측하지 않고, 조용히 순응하지도 않는다. 막혔을 때 — 또는 더 나은
방향이 보일 때 — 구조화된 질문으로 턴을 끝내고, 데몬이 이를 exit `3`으로
승격한다:

```text
QUESTION:
TARGET: dispatcher | user
KIND: scope | ux | priority | risk | irreversible | acceptance | missing-info | better-direction | technical
<질문 + 선택지 + 권고>
```

`TARGET`은 누가 결정해야 하는지, `KIND`는 왜인지 말한다. 중간 레이어
에이전트는 디스패처 소유 질문에 `meight reply`로 답하고, 사용자 소유
질문(스코프, UX, 리스크 감내, 비가역 액션)은 그대로 올린다. 라우팅은
효과 기준이다: 답이 새 워커, 새 phase, 플랜/부록, 선승인된 재리뷰를 넘는 리뷰
정체성, 비싼 재실행, 실질적으로 다른 방법, campaign 캡 이후 추가 수리를
승인하는 것이라면 `technical`이라고 라벨돼 있어도 사용자 소유다. 워커 이름을
바꾸거나 리뷰 정체성을 새로 만들어도 캡은 리셋되지 않는다.

## 하네스는 배운다

평문 파일 원장 셋이 디스패치 루프를 쓸수록 좋게 만든다:

- **결정 기록** (`<repo>/decisions/`). 독립적인 두 설계로 정리된 방향 분기는
  기록을 남긴다: 양쪽 입장, 어디서 갈렸는지, 무엇이 정리했는지. 나중 세션이
  *왜*를 감사할 수 있고, 정리된 질문은 정리된 채로 남는다.
- **선호 원장** (`<daemon-home>/notes/preferences.md`). 사람이 `TARGET: user`
  질문에 답하면 그 답이 기록된다. 디스패처는 올리기 전에 원장을 확인하므로
  같은 부류의 질문은 사람에게 한 번만 간다 — 비가역·리스크 결정만 항상
  재확인한다.
- **교훈** (`<daemon-home>/notes/lessons.md`). 반복되는 리뷰 발견과 운영
  실수는 한 줄 교훈이 되고, 반복되면 브리프 템플릿으로 승격된다. 실행별
  기록에는 모드, 한 줄 게이트 선택, 재라우팅 사유, 사인오프 후 결함을 담을 수
  있다 — 측정을 의례로 만들지 않으면서 결과로부터 라우팅을 튜닝할 만큼만.

이 중 어떤 것도 새 서브시스템이 아니다 — 파일과 독트린뿐이고, 정의는
[`skills/meight/SKILL.md`](../skills/meight/SKILL.md)에 있다. 판단이 모델
기억이 아니라 디스크에 남기 때문에, 개인화는 컨텍스트 압축, 새 세션, 심지어
모델 교체도 넘어 살아남는다.

## Claude Code나 Codex에서 쓰기

실제 작업에서는 `dispatch --timeout`을 백그라운드 셸 호출로 건다. 에이전트는
완료, 질문, 실패, 데몬 사망, 체크포인트 타임아웃에 깨어난다. 체크포인트가
끝나도 워커는 계속 돌며 같은 `dispatch`를 다시 실행하면 재부착한다.

```text
Bash(command: "meight dispatch review-1 --mode mate --timeout 300 --brief-file - <<'EOF' ... EOF",
     run_in_background: true)
-> 체크포인트 exit 1
-> meight status review-1
-> 건강함: 같은 dispatch 다시 실행 · 방향 이탈: meight steer review-1 "..."
```

드롭인 Claude 오케스트레이터 프롬프트는 [`CLAUDE.md`](../CLAUDE.md), Codex를
오케스트레이터로 쓰는 프롬프트는 [`AGENTS.md`](../AGENTS.md)로 제공된다.
디스패처용 스킬 전문은 [`skills/meight/`](../skills/meight/SKILL.md), 세션
계약은 [`skills/meight-mate/`](../skills/meight-mate/SKILL.md)와
[`skills/meight-worker/`](../skills/meight-worker/SKILL.md), 공유 프로토콜은
[`skills/meight-common/`](../skills/meight-common/CONTRACT.md)에 있다.

런타임별 프롬프트 원본은 [`bindings/`](../bindings/)에 둔다. Claude는
[`bindings/claude/tech-lead.md`](../bindings/claude/tech-lead.md)에서 리뷰를
meight로 라우팅한다. Codex는 네이티브
[`meight`](../bindings/codex/skills/meight/SKILL.md),
[`codex-reviewer`](../bindings/codex/skills/codex-reviewer/SKILL.md),
[`codex-discusser`](../bindings/codex/skills/codex-discusser/SKILL.md) 스킬과
read-only [`reviewer`](../bindings/codex/agents/reviewer.toml) 에이전트 정의를
쓴다. 세 Codex 스킬 디렉터리는 `~/.codex/skills/`에 링크하고, 에이전트 정의는
`~/.codex/agents/reviewer.toml`에 링크하거나 복사한다. 로컬 Codex 설정에는
[`config-fragment.toml`](../bindings/codex/config-fragment.toml)의 reviewer
항목만 병합하고 인증·MCP 설정은 로컬에 남긴다.

기본 디스패처는 Claude Code 세션이다. Codex 앱은 네이티브 바인딩과 협업
도구를 쓰되 같은 meight 계약을 유지한다 — 프로토콜 하나, 디스패처 런타임 둘.
reviewer와 discusser는 공용 세션 계약이 아니라 Codex 전용 스킬이다.

## "에이전트에게 쉽다"의 의미

- **exit 코드가 API다.** `0` 완료, `2` 실패/인터럽트/런타임 유실, `3` 질문,
  `4` 데몬 사망, `1` 체크포인트 타임아웃.
- **세션 ID가 아니라 이름.** 세션은 `review-1`처럼 이름으로 부르고, 후속
  턴도 마찬가지다. 이름은 문자나 숫자로 시작하는 1-128자 ASCII
  문자/숫자/`._-`이고, CLI와 데몬 둘 다 경로 문법을 거부한다.
- **바쁜 폴링이 아니라 드문 체크포인트.** `dispatch --timeout`은 알람
  다이얼이지 워커를 죽이지 않으며, 같은 명령을 다시 실행하면 재부착한다.
- **status는 미리 소화돼 있다.** 모드, 리포트 타입, 현재 아이템, 변경 파일,
  needs-input target/kind, 마지막 메시지 꼬리를 돌려준다.
- **정책은 까먹을 수 없다.** 모드, 모드 스킬 로딩, 공유 계약, 리포트 형태는
  하네스가 주입한다 — `--mode`는 티칭 에러가 달린 필수 플래그고 데몬 경계에서
  재검증되므로, 낡은 CLI든 raw 소켓 클라이언트든 같은 계약을 받는다.
- **결과는 디스크에 남는다.** `result.md`는 감사용 원문 기록으로 남고,
  `result.md`에 워커의 텍스트 결과를 남긴다.
- **브리프는 stdin으로.** 여러 줄 브리프가 셸 인용 함정을 피한다.

## 커맨드 레퍼런스

| 커맨드 | 하는 일 |
|---|---|
| `meight dispatch <name> --mode mate\|worker [--target mac\|desktop] [opts]` | 원샷 실행. 기본 `mac`은 기존 로컬 경로를 그대로 쓴다. `desktop`은 clean commit과 repo mapping, `wy-server`를 요구하며 Mac으로 조용히 fallback하지 않는다. |
| `meight reply <name> --brief ... [--model M] [--effort E] [--fast\|--no-fast]` | 답할 수 있는 질문에 원샷으로 답한다. mode와 생략한 턴 설정은 상속, 명시한 오버라이드는 적용, 최신 결과 출력. |
| `meight follow <name> --brief ... [--model M] [--effort E] [--fast\|--no-fast]` | 저수준: 같은 라이브 스레드에 새 턴. mode와 생략 설정은 상속, 명시 오버라이드는 이후 턴의 기본값이 된다. |
| `meight result <name>` | `result.md`를 출력한다. |
| `meight status [name] [--json] [--all-repos]` | pull 다이제스트. 테이블에 `MODE` 포함, 구 role이나 장문 모드 값을 가진 레거시 행도 읽힌다. 디스크만 읽는다. |
| `meight steer <name> "text"` | 도는 턴에 지시를 주입한다. |
| `meight interrupt <name>` | 턴을 취소한다. 워커가 아직 시작 중이거나 reply 턴이 열리는 중에 도착한 인터럽트는 기록됐다가 턴이 커밋되는 순간 중단시킨다. |
| `meight list / daemon / ping / shutdown / launchd` | 저수준 지원 커맨드. |

공통 옵션:

- `--target mac|desktop`은 runtime 실행 위치다. desktop 변경은 해시 검증된
  worker artifact로만 회수하고 현재 checkout에 자동 적용하지 않는다.

- `--mode mate|worker`는 새 세션을 여는 `dispatch`에 필수다. 구 이름 `design`,
  `collab`, `collaborative`, `review`(→ mate)와 `delegate`, `delegated`
  (→ worker)는 별칭으로 받는다. mate는 생각 상대 계약, worker는 자기 리뷰를
  포함한 팀 구현 계약이고 외부 리뷰 선택은 디스패처 몫이다.
- `--cwd`는 워커 작업 디렉토리. 파일 스코프가 겹치는 병렬 워커는 별도 git
  worktree를 쓴다.
- `--sandbox ws|ro|full`은 아래 모드 기본값을 쓴다.
- `--model luna|sol|terra`는 짧은 별칭을 받고, 전체 모델 문자열은 그대로
  통과한다.
- `--effort low|medium|high|xhigh|ultra|max`는 `sol`/`luna`에서 선택 모델의
  기본값(`medium`/`max`)을 쓰고, 그 밖에는 아래 모드 기본값을 쓴다.
- `--fast`는 priority 서비스 티어를 고르고 `--no-fast`는 끈다. Fast를
  생략하면 선택한 모델의 Fast 기본을 다시 고르므로 `--model luna`는 Fast
  on이 되고, 명시한 Fast 플래그가 언제나 우선한다.
  `follow`/`reply`에서 `--model`, `--effort`, Fast 플래그를 생략하면 워커의
  현재 값을 상속하고, 명시하면 그 턴에 적용된 뒤 이후 턴이 상속하는 값이
  된다.
- 워커는 Codex 저장 쓰레드 목록에 추가되지 않는 ephemeral 스레드를 쓴다.
  `thread_source=subagent`는 source 메타데이터로만 유지한다.

생략된 `dispatch` 설정은 요청을 보내기 전에 CLI에서 해소된다:

| Mode | Model | Effort | Fast | Sandbox |
|---|---|---|---|---|
| `mate` | `sol` | `medium` | off | `full` |
| `worker` | `grok` | `high` | off | `full` |

`--effort` 없이 `--model sol|luna|grok`를 명시하면 해당 모델의 effort 기본값을
다시 고른다. Fast를 생략해도 선택한 모델의 Fast 기본을 다시 고른다. 따라서
`--model luna`는 `luna max`와 Fast를 함께 얻고, `--model grok`는 `grok high`에
Fast off다. 명시한 `--effort`와 `--fast`/`--no-fast`가 언제나 우선한다.

어느 자세도 샌드박스를 강제하지 않는다: read-only는 브리프가 정하는
정책이고(mate 계약은 브리프가 시키지 않는 한 레포 파일을 고치지 않는 게
기본이다), `--sandbox`는 수동 선택용으로 남아 있다.

표준은 조용하다: 편차만 명시한다. 이 표는 의도적으로 단순한 코드 전용
오퍼레이터 정책으로 `meight.py` 안에 살고, config 파일이나 환경변수
오버라이드 레이어는 없다. 새 세션의 dispatch 출력이 해소된 값 전부를 `(default)`/`(set)`
출처와 함께 보여준다.

워커 상태는 `<daemon-home>/repos/<repo-key>/workers/<name>/`에 산다:
`brief.md`, `status.json`, `events.log`, `result.md`. terminal 워커는 디스크
아티팩트를 남기고 SDK 런타임은 즉시 놓는다. 최종 구조화 `QUESTION:`도
런타임을 놓고 dormant 디스크 행으로 남는다. `reply`/`follow`는 새 ephemeral
스레드를 열고 저장된 brief·result·recent events의 bounded handoff를 주입한다.

데몬은 소켓 요청의 경로를 믿는 대신 repo key와 상태 홈을 스스로 도출·검증한다.
홈, `repos/`, 레포/워커 상태 디렉토리는 owner-only(`0700`)이고, 워커 상태
경로는 symlink일 수 없으며, `meight.sock`은 `0600`이다. 소켓 요청은 1 MiB로
제한된다. 프로세스 전역 umask는 설정하지 않아서 워커가 만드는 레포 파일은
워커 프로세스의 평소 모드를 유지한다.

terminal 아티팩트는 기본 30일 보존된다. `MEIGHT_SESSION_RETENTION_SEC`에 다른
비음수 초를 주거나 `0`으로 디스크 정리를 끈다. 정리는 accept 루프 밖에서
최대 시간당 한 번 돌고, 활성·답변 가능·malformed·symlink·현재 등록된 워커는
절대 지우지 않으며, 불변 `terminal_at`(레거시 행만 `updated_at`)을 쓴다. 데몬
크래시/재시작 후 고아가 된 활성 행은 `failed`/`runtime_lost_detail`이 된다.
최종 질문과 terminal 워커는 같은 bounded artifact handoff로 계속할 수 있다.

## 옛 데몬을 새 프로토콜 epoch로 올리기

살아있는 데몬이 현재 capability(`desktop1`)를 광고하지 않으면 CLI는 `dispatch`
전에 fail closed한다. 모든 wire start/follow 요청이 epoch를 싣고, 모든 성공 응답이
정규화된 mode, target, runtime, epoch를 원자적으로 에코하며 CLI가 모두 검증한다 —
핸드셰이크 중간에 바꿔치기된 same-token 데몬도 옛 계약을 조용히 쓸 수 없다.
드레인과 재시작은 수동으로 한다:

1. `meight list --all-repos --json`을 확인하고, 어느 레포에도 live turn
   (`starting`, `running`, tool-sourced `needs_input`)이 없어질 때까지 기다린다.
   최종 `QUESTION:` 행은 dormant라 마이그레이션을 막지 않는다.
2. 비강제 `meight shutdown`을 실행한다. 거부하면 드레인을 마저 한다 — 이
   마이그레이션에 `--force`는 쓰지 않는다.
3. LaunchAgent 상태로 분기한다. 로드돼 있으면 `meight launchd install
   --load`를 쓰고 bounded `bootout --wait` 이전이 새 데몬을 고르는지
   확인한다. 로드 안 돼 있으면 데몬을 평소대로 기동한다.
4. `meight ping`이 `capabilities=desktop1`를 보이는지 확인하고, 새 데몬 PID와
   소켓 정체성을 확인한다.
5. 버리는 `--mode worker` 스모크 하나(브리프로 read-only 지시)를 돌려 status
   mode와 `meight-worker` + common preamble 경로를 확인한다.
6. 버리는 `--mode mate` 스모크 하나를 돌려 `mode=mate`와 `meight-mate` +
   common preamble 경로를 확인한다.
7. 모든 스모크가 통과한 뒤에만 실제 디스패치를 재개한다.

## 알아두면 좋은 것

- meight는 모델, MCP 서버, 인증에 `~/.codex/config.toml`을 그대로 물려받는다.
  터미널에서 `codex`가 되면 `meight`도 된다.
- meight는 SDK에 번들된 런타임 대신 현재 시스템의 `codex` 실행 파일을 쓴다.
  명시적 오버라이드가 필요할 때만 `MEIGHT_CODEX_BIN`을 설정한다.
- 세션은 Codex 앱 기록에 남지 않는 ephemeral 스레드로 시작한다:
  `thread_source=subagent`, `thread_ephemeral=true`. source 값은 메타데이터이고,
  앱/세션 기록 누적을 막는 것은 `ephemeral=true`다.
- 포그라운드 `meight daemon`은 활성 워커가 없으면 기본
  `MEIGHT_IDLE_TIMEOUT_SEC`초 후 종료한다. 관리형 `dispatch` 자동 기동과
  LaunchAgent 기동은 idle 종료를 끈다. 실제 idle·보존 값은 `meight ping`으로
  확인한다.
- LaunchAgent는 crash-only 감독을 쓴다 (`SuccessfulExit=false`). 정상 종료는
  멈춘 채로 있는다. 자동 기동은 job이 로드돼 있을 때 `launchctl kickstart`를
  쓰고 `-k`는 절대 쓰지 않는다. 직접 detached 기동은 job이 없다는 명시적
  결과가 나왔을 때의 폴백일 뿐이다. `launchd install --load`는 옛 데몬을
  비강제로 드레인하고, 확인된 PID/소켓이 사라질 때까지 기다리고, 로드된
  job에는 bounded `launchctl bootout --wait`를 돌리고, plist를 bootstrap한
  뒤, launchd가 보고하는 running job PID와 일치하는 신선한 데몬 PID/소켓
  정체성을 요구한다. `launchctl` 결과가 모호하거나 unhealthy한 데몬이 싱글턴
  락을 쥐고 있으면 fail closed한다. 발행된 소켓이 삭제/교체되면 데몬은
  launchd가 재생성하도록 nonzero로 종료한다.
- `openai-codex`는 핀 고정이다 (`0.144.4`). SDK나 Codex CLI를 올릴 땐
  [`SPEC.md`](../SPEC.md)의 검증 스위트를 다시 돌린다.
- 설계 상세, 상태 머신, 하드닝 이력, 수명주기 caveat은
  [`ARCHITECTURE.md`](../ARCHITECTURE.md)에 있다. 디스패처 프로토콜 전문은
  [`skills/meight/SKILL.md`](../skills/meight/SKILL.md)에 있다. 초기
  파이프라인 설계 회고 — 스스로를 돌려서 스스로를 설계한 날의 기록 — 는
  [`docs/2026-07-14-v3-pipeline-retrospective.md`](./2026-07-14-v3-pipeline-retrospective.md)에
  있다.

## 라이선스

MIT
