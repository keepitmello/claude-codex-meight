# claude-codex-meight

<p align="center">
  <img src="./hero.jpg" alt="Claude Fable 5 + Codex" width="720">
</p>

[English](../README.md) | **한국어**

> **Claude Code가 계획하고, Codex가 만듭니다.** Meight는 그 사이의 하네스입니다. Claude가 Codex 워커에게 일을 맡기고, 드문 체크포인트마다 상태를 확인하고, 필요할 때만 방향을 잡아주고, 끝나면 결과를 돌려받습니다 — 자기 서브에이전트를 감독하는 것과 비슷합니다. 공식 `openai-codex` Python SDK 위에 구축했습니다. CLI: `meight`.

기존 Claude↔Codex 브릿지들은 *터미널을 지켜보는 사람*을 위해 만들어졌습니다 — 붙어서 타이핑할 tmux pane, 클릭할 대시보드. Meight는 오케스트레이션을 하는 에이전트 자신을 위해 만들었습니다. 실제로는 이렇게 동작합니다:

- **감독은 하되, 빈도는 메인 판단.** 워커를 시작하면 `start`+`wait` 구조 덕에 도는 중에도 `meight status`를 보고 `steer`할 수 있습니다. 얼마나 자주 볼지, 조향할지 말지는 정해진 주기가 아니라 오케스트레이터의 판단입니다.
- **지켜보는 비용이 낮습니다.** 워커는 진행 상황을 디스크의 작은 파일에 기록합니다. Claude는 볼 필요가 있을 때만 봅니다. 컨텍스트 윈도우로 흘러드는 것은 없습니다.
- **달리는 중에 고치기.** 방향이 틀렸으면 `meight steer`로 실행 중인 워커에게 정정 지시를 보냅니다. 죽이지 않고, 지금까지의 작업도 잃지 않습니다.
- **맞을 때만 원샷.** `meight dispatch`는 여전히 짧고 단순하고 위험 낮은 작업의 fire-and-forget 용도로 쓸 수 있습니다.
- **부려먹는 일꾼이 아니라 동료.** Codex는 시키는 것만 하지 않습니다 — 막혔을 때뿐 아니라 더 나은 길이나 의심스러운 가정이 보이면 먼저 짚고, Claude도 자기 판단을 점검하려 워커에게 상의를 걸 수 있습니다. 질문과 답이 같은 스레드에서 양방향으로 오갑니다(`meight reply`, `meight follow`).

```
Claude Code (오케스트레이터)
   │  워커 시작 후 드문 체크포인트 대기
   ▼
meight start impl-1 --brief-file - --cwd ~/repo <<'EOF'
<작업 브리프>
EOF
   │
   ├─ background: meight wait impl-1 --timeout 300
   │                         ▲
   ├─ 체크포인트 timeout ────┘  meight status impl-1 → 다시 wait 또는 steer
   │
   ▼ terminal 알림
레포별 데몬 ──── 공식 openai-codex SDK ──── codex app-server (프로세스 1개, 스레드 N개)
   │
   └─ 디스크 다이제스트: status.json / events.log / result.md   ← 오케스트레이터가 필요할 때만 pull
```

## 왜 일을 이렇게 나누나

Anthropic의 새 Mythos급 모델(**Claude Fable 5**)은 기획과 판단에 매우 뛰어납니다 — 전체 그림을 보고, 일을 깔끔하게 쪼개고, 애매한 상황에서 옳은 결정을 내립니다. 대신 토큰이 비쌉니다. Codex(**GPT-5.5**)는 작업 단가가 훨씬 낮으면서 디테일에 강합니다: race condition, 타입 불일치, 빠뜨린 엣지 케이스, 계약 위반.

Meight는 이 둘을 묶어 비용은 낮추고 품질은 올립니다. Claude가 *무엇을, 왜*를 쥐고 Codex 워커가 *어떻게*를 맡되, 둘은 동료로 일합니다 — 서로의 결과물을 교차 리뷰하고, 어려운 결정은 함께 짚습니다(워커는 더 나은 길이 보이면 되받고, Claude는 막히면 워커에게 상의합니다). 교차 리뷰는 자기 리뷰가 놓치는 것을 잡아냅니다. 작업량이 두 구독으로 분산되는 것은 덤입니다. 전체 정책은 [`CLAUDE.md`](../CLAUDE.md)로 동봉됩니다.

## 왜 만들었나

2026년 6월 기준, 공개된 Claude↔Codex 프로젝트는 전부 Codex를 **CLI로** 부립니다 — `codex exec` 서브프로세스를 띄우거나 tmux에 타이핑하는 방식입니다. 그렇게 만든 도구들은 같은 한계를 공유합니다: 실행 중인 워커의 방향을 바꾸려면 죽여야 하고(작업이 날아갑니다), 진행을 보려면 모든 출력을 오케스트레이터 컨텍스트로 부어야 하고, 막힌 워커는 도움을 청할 방법이 없습니다.

OpenAI의 공식 **`openai-codex` Python SDK**(2026년 5월 릴리스)가 이 한계를 없앴습니다. `codex app-server`와 직접 통신하면서 조향·중단·스트리밍을 정식 API로 제공하고, Codex 프로세스 하나가 여러 워커를 동시에 돌립니다. **Meight는 — 우리가 아는 한 — 이 SDK 위에 구축된 최초의 공개 하네스입니다.** 비교하면:

| | tmux/exec 브릿지 | MCP 래퍼 | **Meight** |
|---|---|---|---|
| 병렬 워커 | 워커당 프로세스 1개 | 블로킹 툴 콜 | 스레드 N개, codex 프로세스 1개 |
| mid-turn 조향 | 사람이 attach해서 타이핑, 또는 kill+resume(작업 손실) | ✗ | **`meight steer` — 프로그래매틱, 작업 손실 없음** |
| 진행 관찰 | stdout 스크래핑 / 컨텍스트로 스트리밍 | ✗ | **디스크 다이제스트, 필요할 때 pull (~토큰 0)** |
| 워커의 질문 | ✗ (추측하거나 멈춤) | ✗ | **`QUESTION:` 프로토콜 → exit 3 → `meight reply`** |
| 결과 전달 | 스크래핑 | 툴 반환값 | **exit code 계약 + stdout 결과 출력** |
| 세션 연속성 | 취약 | threadId | **같은 스레드 `follow`/`reply` 턴** |

## 빠른 시작

요구사항: [Codex CLI](https://developers.openai.com/codex) 설치+로그인, Python ≥ 3.10.

```bash
git clone https://github.com/keepitmello/claude-codex-meight
cd claude-codex-meight && ./install.sh   # .venv 생성 + ~/.local/bin/meight
```

실질 작업은 감독형으로 디스패치합니다(아무 git 레포에서나 가능 — 상태는 레포별 `.meight/`에 격리됩니다). `start`는 레포별 데몬이 떠 있다고 가정합니다. 안 떠 있으면 `meight daemon`을 별도로 한 번 시작하세요.

```bash
meight start impl-1 --brief-file - --cwd ~/my-repo --sandbox ws <<'EOF'
src/foo.py에 X를 구현해. 기존 패턴: src/bar.py:42 참고.
검증: pytest tests/test_foo.py. 변경 파일 + 테스트 출력 보고.
EOF

meight wait impl-1 --timeout 300
# exit 0=완료 · 2=실패/중단 · 3=워커 질문 · 4=데몬 사망 · 1=체크포인트 타임아웃
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

워커가 질문했다면(exit 3) 질문은 `meight status impl-1`의 `needs_input_detail`에서도 볼 수 있습니다. 같은 스레드에서 원샷으로 답합니다:

```bash
meight reply impl-1 --brief "config-a.json 쓰고, legacy 필드는 유지해."
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

워커가 terminal 상태에 도달하면 알림은 `0`(완료), `2`(실패/중단), `3`(워커 질문)으로 옵니다. 전체 보고는 `meight result review-1`로 읽습니다. `0`이면 검증 후 받아들이고, `3`이면 `meight reply`로 답합니다.

모든 브리프 앞에는 하네스 프리앰블이 자동으로 붙습니다: (a) `git commit`/`push` 금지 — git은 오케스트레이터 소유 — (b) 워커를 teammate로 규정 — 추측하거나 묵묵히 따르는 대신, 막혔을 때는 물론 더 나은 접근·틀린 가정·방향을 바꿀 결정이 보이면 `QUESTION:` 문단으로 짚을 것. `--no-preamble`로 끌 수 있습니다.

바로 쓸 수 있는 오케스트레이터 프롬프트(역할 분담, 라우팅 테이블, 디스패치 프로토콜, 교차 리뷰 규칙)가 [`CLAUDE.md`](../CLAUDE.md)로 동봉됩니다 — 프로젝트나 글로벌 Claude Code 메모리에 복사해서 쓰면 됩니다. 자기완결형 Claude Code **스킬**도 [`skills/meight/`](../skills/meight/SKILL.md)에 들어 있습니다 — `~/.claude/skills/`에 복사하면 트리거 기반 JIT 로딩이 됩니다.

## "에이전트에게 편하다"는 것의 실제 의미

하네스 곳곳의 작은 결정들이 전부 "사용자는 터미널 앞의 사람이 아니라 LLM 에이전트"라는 전제 위에 있습니다:

- **exit code가 곧 API입니다.** `0`=완료, `2`=실패, `3`=질문, `4`=데몬 사망. 에이전트가 산문을 읽고 성공 여부를 추측하는 대신 숫자로 분기합니다. 알 수 없는 종료 상태는 *완료*가 아니라 *실패*로 처리됩니다 — exit 0은 믿어도 됩니다.
- **빽빽한 폴링이 아니라 드문 체크포인트.** `wait --timeout`을 작업의 예상 소요 시간쯤으로 잡으면, 그 안에 끝날 땐 오케스트레이터가 완료 푸시만 받고, 넘기면 타임아웃이 깨워서 `status`를 한 번 보게 합니다. 타임아웃은 exit `1`로 돌아오고 워커는 계속 실행됩니다. 정해진 주기도, 꼭 봐야 할 의무도 없습니다 — 턴을 태우는 촘촘한 폴링 없이도 `status`와 `steer`는 살아 있습니다.
- **세션 ID가 아니라 이름.** 워커는 `review-1`처럼 이름으로 부르고, 후속 지시도 마찬가지입니다. 틀릴 UUID 장부가 없습니다.
- **결과는 디스크에 남습니다.** `result.md`는 언제든 다시 읽을 수 있어서, 세션 도중 에이전트의 컨텍스트가 압축돼도 잃는 것이 없습니다.
- **status는 이미 요약본입니다.** raw 로그 대신 판단에 필요한 것만 돌려줍니다: 지금 뭘 하는 중인지, 어떤 파일이 바뀌었는지, 마지막 생각이 뭐였는지. 기다릴지, 조향할지, 끊을지 고르는 데 딱 그만큼.
- **규칙은 깜빡할 수 없습니다.** 커밋 금지와 QUESTION 프로토콜은 에이전트가 기억하는 게 아니라 하네스가 모든 브리프에 자동 주입합니다.
- **브리프는 stdin으로 받습니다.** 긴 멀티라인 브리프가 쉘 쿼팅 함정을 아예 우회합니다.

## 커맨드 레퍼런스

| 커맨드 | 동작 |
|---|---|
| `meight start <name> [opts]` | 워커를 시작하고 thread id를 출력한 뒤 바로 반환. 감독형 워크플로우 시작점 |
| `meight wait <name> --timeout SEC` | 체크포인트 대기: terminal 상태, QUESTION, 데몬 사망, 타임아웃 중 하나에서 반환. 타임아웃은 워커를 계속 살려둠 |
| `meight dispatch <name> [opts]` | 원샷: 데몬 자동기동 → 워커 시작 → 대기 → 결과 출력. 짧고 단순하고 위험 낮은 작업용 |
| `meight reply <name> --brief ...` | 워커 질문에 원샷 답변: follow + 대기 + 마지막 턴 결과 출력 |
| `meight status [name]` | 다이제스트 pull (테이블/상세). 디스크 직접 읽기 — 데몬 없이도 동작 |
| `meight steer <name> "text"` | 실행 중 턴에 지시 주입 (작업 손실 없음) |
| `meight interrupt <name>` | 실행 중 턴 취소 (idempotent) |
| `meight follow <name> --brief ...` | 저수준: 같은 스레드에 새 턴 (컨텍스트 유지) |
| `meight result / list / daemon / ping / shutdown` | 저수준 보조 커맨드 |

옵션: `--cwd`(워커 작업 디렉토리 — 파일 범위가 겹치면 git worktree로 분리), `--sandbox ws|ro|full`(기본 `ws`=workspace-write, 리뷰는 `ro`), `--effort low|medium|high|xhigh`(기본 `medium`, 복잡도에 따라 상향), `--model`, `--timeout`.

워커 상태는 `<repo>/.meight/workers/<name>/`에 기록됩니다: `brief.md`, `status.json`(상태머신+토큰+변경 파일+현재 활동), `events.log`(의미 있는 이벤트당 1줄), `result.md`(턴별 최종 메시지). `.meight/`는 글로벌 gitignore에 추가하세요.

## 알아두면 좋은 것

- Meight는 `~/.codex/config.toml`(모델, MCP 서버, 인증)을 그대로 상속합니다 — 내부적으로 SDK가 표준 `codex app-server`를 띄우는 구조입니다. 터미널에서 `codex`가 되면 `meight`도 됩니다.
- `openai-codex`는 베타라 버전을 고정했습니다(`0.1.0b3`). 올릴 때는 [`SPEC.md`](../SPEC.md)의 검증 스위트를 재실행하세요.
- 설계 상세 — 동시성 모델, 상태머신, 오케스트레이션 정책 — 는 [`ARCHITECTURE.md`](../ARCHITECTURE.md)에 있습니다.

## License

MIT
