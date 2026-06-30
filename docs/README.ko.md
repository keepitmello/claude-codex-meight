# claude-codex-meight

<p align="center">
  <img src="./hero.jpg" alt="Claude Fable 5 + Codex" width="720">
</p>

[English](../README.md) | **한국어**

> **Claude × Codex를 위한 양방향 하네스.** 던지고 기다리기만 하는 게 아닙니다. Codex 워커가 도중에 질문을 던지고 더 나은 아이디어를 제안하고, Claude 오케스트레이터는 막히면 워커에게 상의하고, 양쪽이 서로의 작업을 리뷰합니다 — 한 모델이 다른 모델을 부리는 게 아니라 진짜 협업 루프입니다. 공식 `openai-codex` Python SDK 위에 구축했습니다. CLI: `meight`.

기존 Claude↔Codex 브릿지들은 *터미널을 지켜보는 사람*을 위해 만들어졌습니다 — 붙어서 타이핑할 tmux pane, 클릭할 대시보드. Meight는 에이전트 자신들을 위해 만들었습니다: Claude 오케스트레이터와 Codex 워커가 사람 없이 직접 협업합니다. 실제로는 이렇게 동작합니다:

- **양쪽 모두, 같은 스레드.** Codex는 단순 실행자가 아닙니다 — 워커는 막혔을 때뿐 아니라 더 나은 길이나 의심스러운 가정이 보일 때 턴 끝에 `QUESTION:`으로 짚고, 오케스트레이터는 답하거나 방향을 함께 조정합니다. 일 던지고 결과 받기가 아니라 진짜 주고받기입니다.
- **위임만 말고 상의도.** 설계가 막혔나요? 오케스트레이터가 읽기 전용 워커를 띄워 문제를 *함께* 풀어봅니다 — 코드 리뷰의 사촌인데, 결과물이 아니라 사고 과정에 적용하는 셈입니다.
- **서로가 서로를 검증.** Codex가 구현 → Claude 에이전트가 검증, Claude가 구현 → Codex 워커가 리뷰. 교차 모델 리뷰는 같은 모델끼리의 자기 리뷰가 놓치는 걸 잡습니다.
- **감독은 하되, 빈도는 판단.** `start`+`wait` 구조 덕에 오케스트레이터가 도는 중에도 `status`를 보고 `steer`할 수 있습니다 — 얼마나 자주, 아예 볼지 말지는 정해진 주기가 아니라 판단입니다. 진행 상황은 디스크의 작은 파일에 쌓여서 지켜보는 비용이 컨텍스트 ~0입니다.
- **맞을 때만 원샷.** `meight dispatch`는 여전히 짧고 단순하고 위험 낮은 작업의 fire-and-forget 용도로 쓸 수 있습니다.

```
   Claude 오케스트레이터   ⇄   Codex 워커
   (무엇을 · 왜)               (어떻게)
        │                          ▲
        ├──  start + 브리프  ──────┘
        │
        │◀──  QUESTION:  더 나은 아이디어 · 잘못된 가정 · 막힘 · 완료
        │──▶  답변 · steer · consult · 리뷰
        │            (어느 쪽이든 다음 턴을 열 수 있음, 같은 스레드)
        │
        ▼   오케스트레이터가 필요할 때만 디스크 다이제스트 pull — 컨텍스트 ~0, 스트리밍 없음
   전역 데몬 ── 공식 openai-codex SDK ── codex app-server (프로세스 1개, 스레드 N개)
        status.json · events.log · result.md
```

## 왜 두 모델이 함께 일하나

Anthropic의 새 Mythos급 모델(**Claude Fable 5**)은 기획과 판단에 매우 뛰어납니다 — 전체 그림을 보고, 일을 깔끔하게 쪼개고, 애매한 상황에서 옳은 결정을 내립니다. 대신 토큰이 비쌉니다. Codex(**GPT-5.5**)는 작업 단가가 훨씬 낮으면서 디테일에 강합니다: race condition, 타입 불일치, 빠뜨린 엣지 케이스, 계약 위반.

Meight는 이 둘을 묶어 비용은 낮추고 품질은 올립니다. Claude가 *무엇을, 왜*를 쥐고 Codex가 *어떻게*를 맡습니다. 하지만 이 분담이 값어치를 하는 건 둘이 **부리는 쪽과 도구가 아니라 동료로** 일하기 때문입니다 — 워커는 더 나은 길이 보이면 되받고, 오케스트레이터는 막히면 워커에게 상의하고, 서로의 결과물을 리뷰합니다(교차 모델 리뷰는 같은 모델끼리의 자기 리뷰가 놓치는 걸 잡습니다). 작업량이 두 구독으로 분산되는 것은 덤입니다. 전체 협업 정책은 [`CLAUDE.md`](../CLAUDE.md)로 동봉됩니다.

## 왜 만들었나

2026년 6월 기준, 공개된 Claude↔Codex 프로젝트는 전부 Codex를 **CLI로** 부립니다 — `codex exec` 서브프로세스를 띄우거나 tmux에 타이핑하는 방식입니다. 그렇게 만든 도구들은 같은 한계를 공유합니다: 실행 중인 워커의 방향을 바꾸려면 죽여야 하고(작업이 날아갑니다), 진행을 보려면 모든 출력을 오케스트레이터 컨텍스트로 부어야 하고, 막힌 워커는 도움을 청할 방법이 없습니다.

OpenAI의 공식 **`openai-codex` Python SDK**(2026년 5월 릴리스)가 이 한계를 없앴습니다. `codex app-server`와 직접 통신하면서 조향·중단·스트리밍을 정식 API로 제공하고, Codex 프로세스 하나가 여러 워커를 동시에 돌립니다. **Meight는 — 우리가 아는 한 — 이 SDK 위에 구축된 최초의 공개 하네스입니다.** 비교하면:

| | tmux/exec 브릿지 | MCP 래퍼 | **Meight** |
|---|---|---|---|
| 병렬 워커 | 워커당 프로세스 1개 | 블로킹 툴 콜 | 스레드 N개, codex 프로세스 1개 |
| mid-turn 조향 | 사람이 attach해서 타이핑, 또는 kill+resume(작업 손실) | ✗ | **`meight steer` — 프로그래매틱, 작업 손실 없음** |
| 진행 관찰 | stdout 스크래핑 / 컨텍스트로 스트리밍 | ✗ | **디스크 다이제스트, 필요할 때 pull (~토큰 0)** |
| 양방향 대화 | ✗ (추측하거나 멈춤) | ✗ | **워커가 `QUESTION:` 제기(막힘 *또는* 더 나은 아이디어) → exit 3 → `meight reply`; 오케스트레이터는 `consult`로 되물음** |
| 결과 전달 | 스크래핑 | 툴 반환값 | **exit code 계약 + stdout 결과 출력** |
| 세션 연속성 | 취약 | threadId | **같은 데몬 안의 `follow`/`reply` 턴** |

## 빠른 시작

요구사항: [Codex CLI](https://developers.openai.com/codex) 설치+로그인, Python ≥ 3.10.

```bash
git clone https://github.com/keepitmello/claude-codex-meight
cd claude-codex-meight && ./install.sh   # .venv 생성 + ~/.local/bin/meight
```

실질 작업은 감독형으로 디스패치합니다. Meight는 기본적으로 하나의 전역 데몬을 씁니다(`$MEIGHT_HOME`, `$XDG_STATE_HOME/meight`, 또는 `~/.meight`). 워커 상태는 전역 데몬 홈 아래 `repos/<repo-key>/`로 레포별 격리됩니다. `start`는 전역 데몬이 떠 있다고 가정합니다. 안 떠 있으면 `meight daemon`을 한 번 시작하거나, `dispatch`로 자동 시작하거나, `meight launchd install --load`로 선택적 LaunchAgent를 등록하세요.

```bash
meight start impl-1 --brief-file - --cwd ~/my-repo <<'EOF'
src/foo.py에 X를 구현해. 기존 패턴: src/bar.py:42 참고.
검증: pytest tests/test_foo.py. 변경 파일 + 테스트 출력 보고.
EOF

meight wait impl-1 --timeout 300
# exit 0=완료 · 2=실패/중단/runtime lost · 3=답장 가능한 워커 질문 · 4=데몬 사망 · 1=체크포인트 타임아웃
```

exit `1`이면 워커는 계속 실행 중입니다. 한 번만 상태를 보고, 다시 기다리거나 조향합니다:

```bash
meight status impl-1
meight steer impl-1 "헬퍼 리팩토링은 멈추고 버그만 고쳐."
meight wait impl-1 --timeout 300
```

exit `0`, `2`, `3`에서는 `wait`가 상태 요약만 출력합니다. 전체 메시지는 디스크에서 읽습니다:

```bash
meight result impl-1
```

워커가 답장 가능한 질문을 했다면(exit 3) 질문은 `meight status impl-1`의 `needs_input_detail`에서도 볼 수 있습니다. 같은 스레드에서 원샷으로 답합니다:

```bash
meight reply impl-1 --brief "config-a.json 쓰고, legacy 필드는 유지해."
```

반대로 *당신*이 막혔다면 루프를 반대 방향으로 돌리세요 — 읽기 전용 워커를 띄워 문제를 *함께* 풀어보고, `follow`로 방향을 같이 다듬습니다:

```bash
meight start consult-1 --sandbox ro --brief "내 계획은 X인데 Y가 미심쩍어. src/ 읽고 내가 놓친 거 짚어줘 — 더 나은 접근이 보이면 그것도."
meight wait consult-1 --timeout 300
meight follow consult-1 --brief "Y 지적 좋아. 그 방향으로 가면 Z는 어떻게 돼?"
```

짧고 단순하고 위험 낮은 작업에는 원샷 dispatch도 그대로 쓸 수 있습니다:

```bash
meight dispatch tiny-1 --brief "README에 LICENSE 언급이 있는지만 확인해." --sandbox ro
```

## Claude Code에서 쓰기

이것이 본래 용도입니다. 실질 작업에서는 `wait --timeout`을 **백그라운드 Bash**로 실행합니다. Claude는 체크포인트에서 깨어나 `status`를 한 번 읽고, 정상이면 다시 기다리고, 틀어졌으면 짧게 `steer`합니다:

```
Bash(command: "meight start review-1 --sandbox ro --effort high --brief-file - <<'EOF' ... EOF")
Bash(command: "meight wait review-1 --timeout 300",
     run_in_background: true)
→ ... Claude는 계속 다른 작업 ...
→ <task-notification> exit 1 체크포인트 타임아웃
→ meight status review-1
→ 정상이면 다시 wait · 틀어졌으면 meight steer review-1 "..."
```

워커가 terminal 상태에 도달하면 알림은 `0`(완료), `2`(실패/중단/runtime lost), `3`(아직 데몬에 붙어 있어서 답장 가능한 워커 질문)으로 옵니다. 전체 보고는 `meight result review-1`로 읽습니다. `0`이면 검증 후 받아들이고, `3`이면 `meight reply`로 답합니다. 데몬 재시작이나 GC 때문에 같은 스레드가 만료된 경우에는 `wait`가 `runtime_lost_detail`과 함께 `2`를 내므로, 답장하지 말고 새 워커를 시작합니다.

모든 브리프 앞에는 하네스 프리앰블이 자동으로 붙습니다: (a) 워커도 완료·검증한 작업은 `git commit`/`push`할 수 있지만, 통합과 최종 승인 책임은 오케스트레이터가 가짐 — (b) 워커를 teammate로 규정 — 추측하거나 묵묵히 따르는 대신, 막혔을 때는 물론 더 나은 접근·틀린 가정·방향을 바꿀 결정이 보이면 `QUESTION:` 문단으로 짚을 것. `--no-preamble`로 끌 수 있습니다.

바로 쓸 수 있는 오케스트레이터 프롬프트(역할 분담, 라우팅 테이블, 디스패치 프로토콜, 교차 리뷰 규칙)가 [`CLAUDE.md`](../CLAUDE.md)로 동봉됩니다 — 프로젝트나 글로벌 Claude Code 메모리에 복사해서 쓰면 됩니다. 디스패처용 Claude Code 스킬은 [`skills/meight/`](../skills/meight/SKILL.md)에 있고, 워커용 Codex 스킬은 [`skills/meight-worker/`](../skills/meight-worker/SKILL.md)에 있습니다. 워커용 스킬은 하네스 프리앰블이 위임된 Codex 워커에게 읽힙니다.

## "에이전트에게 편하다"는 것의 실제 의미

하네스 곳곳의 작은 결정들이 전부 "사용자는 터미널 앞의 사람이 아니라 LLM 에이전트"라는 전제 위에 있습니다:

- **exit code가 곧 API입니다.** `0`=완료, `2`=실패, `3`=질문, `4`=데몬 사망. 에이전트가 산문을 읽고 성공 여부를 추측하는 대신 숫자로 분기합니다. 알 수 없는 종료 상태는 *완료*가 아니라 *실패*로 처리됩니다 — exit 0은 믿어도 됩니다.
- **빽빽한 폴링이 아니라 드문 체크포인트.** `wait --timeout`을 작업의 예상 소요 시간쯤으로 잡으면, 그 안에 끝날 땐 오케스트레이터가 완료 푸시만 받고, 넘기면 타임아웃이 깨워서 `status`를 한 번 보게 합니다. 타임아웃은 exit `1`로 돌아오고 워커는 계속 실행됩니다. 정해진 주기도, 꼭 봐야 할 의무도 없습니다 — 턴을 태우는 촘촘한 폴링 없이도 `status`와 `steer`는 살아 있습니다.
- **세션 ID가 아니라 이름.** 워커는 `review-1`처럼 이름으로 부르고, 후속 지시도 마찬가지입니다. 틀릴 UUID 장부가 없습니다.
- **결과는 디스크에 남습니다.** `result.md`는 언제든 다시 읽을 수 있어서, 세션 도중 에이전트의 컨텍스트가 압축돼도 잃는 것이 없습니다.
- **status는 이미 요약본입니다.** raw 로그 대신 판단에 필요한 것만 돌려줍니다: 지금 뭘 하는 중인지, 어떤 파일이 바뀌었는지, 마지막 생각이 뭐였는지. 기다릴지, 조향할지, 끊을지 고르는 데 딱 그만큼.
- **규칙은 깜빡할 수 없습니다.** 워커 git 정책과 QUESTION 프로토콜은 에이전트가 기억하는 게 아니라 하네스가 모든 브리프에 자동 주입합니다.
- **브리프는 stdin으로 받습니다.** 긴 멀티라인 브리프가 쉘 쿼팅 함정을 아예 우회합니다.

## 커맨드 레퍼런스

| 커맨드 | 동작 |
|---|---|
| `meight start <name> [opts]` | 워커를 시작하고 thread id를 출력한 뒤 바로 반환. 감독형 워크플로우 시작점 |
| `meight wait <name> --timeout SEC` | 체크포인트 대기: terminal 상태, 답장 가능한 QUESTION, 데몬 사망, 타임아웃 중 하나에서 반환. 타임아웃은 워커를 계속 살려둠 |
| `meight dispatch <name> [opts]` | 원샷: 데몬 자동기동 → 워커 시작 → 대기 → 결과 출력. 짧고 단순하고 위험 낮은 작업용 |
| `meight reply <name> --brief ...` | 답장 가능한 워커 질문에 원샷 답변: follow + 대기 + 마지막 턴 결과 출력 |
| `meight status [name]` | 다이제스트 pull (테이블/상세). 디스크 직접 읽기 — 데몬 없이도 동작 |
| `meight steer <name> "text"` | 실행 중 턴에 지시 주입 (작업 손실 없음) |
| `meight interrupt <name>` | 실행 중 턴 취소 (idempotent) |
| `meight follow <name> --brief ...` | 저수준: 워커가 아직 데몬에 붙어 있을 때 같은 스레드에 새 턴 |
| `meight result / list / daemon / ping / shutdown / launchd` | 저수준 보조 커맨드 |

옵션: `--cwd`(워커 작업 디렉토리 — 파일 범위가 겹치면 git worktree로 분리), `--sandbox ws|ro|full`(기본 `full`=샌드박스 없음, 리뷰는 `ro`), `--effort low|medium|high|xhigh`(기본 `medium`, 복잡도에 따라 상향), `--model`, `--fast`/`--no-fast`(기본은 non-Fast이고, `--fast`를 넣은 워커만 codex Fast/priority tier 사용), `--timeout`. 워커는 기본적으로 hidden ephemeral Codex subagent thread로 시작해서 Codex Desktop의 메인 사용자 스레드 목록에 뜨지 않게 합니다. 보이는/main thread가 꼭 필요한 도구에서만 `--main-thread`를 쓰세요.

워커 상태는 `<daemon-home>/repos/<repo-key>/workers/<name>/`에 기록됩니다: `brief.md`, `status.json`(상태머신+토큰+변경 파일+현재 활동), `events.log`(의미 있는 이벤트당 1줄), `result.md`(턴별 최종 메시지). 전체 레포 상태는 `meight list --all-repos`로 볼 수 있습니다. 완료된 워커는 기본적으로 `MEIGHT_WORKER_GC_TTL_SEC` 동안 데몬 메모리에 남고, 그 동안만 같은 스레드 follow가 가능합니다. 데몬 재시작 또는 terminal-worker GC 뒤에는 디스크 산출물은 남지만 같은 스레드 follow는 만료되므로 새 워커를 시작해야 합니다. Foreground `meight daemon`은 기본적으로 활성 워커가 없으면 `MEIGHT_IDLE_TIMEOUT_SEC` 뒤 종료되며, `daemon --idle-timeout-sec 0`으로 명시 비활성화할 수 있습니다. 관리형 기동(`dispatch` auto-start와 LaunchAgent)은 env와 daemon 인자 둘 다로 idle 비활성을 전달하고, 오래 로드된 LaunchAgent job이 env를 빠뜨린 경우에도 `XPC_SERVICE_NAME`으로 관리형을 판별합니다. 실제 적용값은 `meight ping`의 `idle_timeout_sec`로 확인하세요.

## 알아두면 좋은 것

- Meight는 `~/.codex/config.toml`에서 모델, MCP 서버, 인증을 상속합니다 — 내부적으로 SDK가 표준 `codex app-server`를 띄우는 구조입니다. 터미널에서 `codex`가 되면 `meight`도 됩니다. 단, 워커 service tier는 기본 non-Fast로 명시 override하며, 특정 워커만 priority tier가 필요할 때 `--fast`를 씁니다.
- `openai-codex`는 베타라 버전을 고정했습니다(`0.1.0b3`). 올릴 때는 [`SPEC.md`](../SPEC.md)의 검증 스위트를 재실행하세요.
- 설계 상세 — 동시성 모델, 상태머신, 오케스트레이션 정책 — 는 [`ARCHITECTURE.md`](../ARCHITECTURE.md)에 있습니다.

## License

MIT
