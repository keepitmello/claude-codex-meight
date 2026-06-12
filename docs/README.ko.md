# claude-codex-meight

[English](../README.md) | **한국어**

> **Claude Code가 OpenAI Codex 워커를 네이티브 서브에이전트처럼 부리게 해주는 에이전트 우선(agent-first) 하네스** — 공식 `openai-codex` Python SDK 위에 직접 구축. CLI: `meight`.

기존 Claude↔Codex 브릿지들은 *터미널을 지켜보는 사람*을 위해 만들어졌어요: 붙어서 타이핑할 tmux pane, 클릭할 칸반 보드, 긁어올 stdout. **Meight는 오케스트레이터 에이전트 자신을 위해 설계됐습니다.** 설계 질문은 "터미널에서 뭐가 보기 좋은가"가 아니라 — *"Codex 워커를 디스패치하는 게 자기 서브에이전트 띄우는 것과 똑같이 느껴지려면 Claude에게 뭐가 필요한가?"* 였어요.

답: exit code 계약이 있는 원샷 디스패치, 컨텍스트 토큰을 거의 쓰지 않는 pull 방식 진행 다이제스트, 프로그래매틱 mid-turn 조향, 그리고 워커→오케스트레이터 질문 프로토콜. 전부 네이티브로 — tmux 없이, 스크린 스크래핑 없이, MCP 우회 없이.

```
Claude Code (오케스트레이터)
   │  백그라운드 Bash 호출 1번
   ▼
meight dispatch impl-1 --brief-file - --cwd ~/repo <<'EOF'
<작업 브리프>
EOF
   │                                  ▲
   ▼                                  │ 완료 알림
레포별 데몬 ──── 공식 openai-codex SDK ──── codex app-server (프로세스 1개, 스레드 N개)
   │
   └─ 디스크 다이제스트: status.json / events.log / result.md   ← 오케스트레이터가 필요할 때만 pull
```

## 왜 만들었나

2026년 6월 기준, 공개된 Claude↔Codex 오케스트레이션 프로젝트는 전부 Codex **CLI**를 감싸요 — `codex exec` 서브프로세스나 tmux `send-keys`. 그 세대 도구는 실행 중인 워커를 죽이지 않고는 조향할 수 없고, 모든 출력을 오케스트레이터 컨텍스트로 흘리지 않고는 진행을 관찰할 수 없고, 워커가 질문할 방법이 없어요.

OpenAI의 공식 **`openai-codex` Python SDK**(2026-05 릴리스)가 기반을 바꿨습니다: `codex app-server`와 JSON-RPC로 통신하며 `TurnHandle.steer()` / `.interrupt()` / `.stream()`을 공개 API로 노출하고, Codex 프로세스 1개가 N개 스레드를 동시 멀티플렉싱해요. **Meight는 — 우리가 아는 한 — 이 SDK 위에 구축된 최초의 공개 하네스입니다.** tmux 세대가 흉내내던 모든 것이 여기선 네이티브예요:

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

워커 디스패치 (아무 git 레포에서나 — 상태는 레포별 `.meight/`에 격리):

```bash
meight dispatch impl-1 --brief-file - --cwd ~/my-repo --sandbox ws <<'EOF'
src/foo.py에 X를 구현해. 기존 패턴: src/bar.py:42 참고.
검증: pytest tests/test_foo.py. 변경 파일 + 테스트 출력 보고.
EOF
# 데몬 자동 기동. 워커 완료까지 블로킹 후 결과 출력.
# exit 0=완료 · 2=실패/중단 · 3=워커 질문 · 4=데몬 사망 · 1=타임아웃
```

워커가 질문했다면(exit 3)? 질문은 출력된 결과에 들어있어요. 같은 스레드에서 원샷 답변:

```bash
meight reply impl-1 --brief "config-a.json 쓰고, legacy 필드는 유지해."
```

실행 중 관찰과 조향:

```bash
meight status            # 1줄 테이블: 상태, 경과, 변경 파일, 토큰, 현재 활동
meight status impl-1     # 상세: 현재 커맨드, 플랜, 마지막 사고 흐름
meight steer impl-1 "헬퍼 리팩토링은 멈추고 버그만 고쳐."   # mid-turn, 작업 손실 없음
meight interrupt impl-1
```

## Claude Code에서 쓰기

이게 본래 용도예요. dispatch를 **백그라운드 Bash**로 실행하면 — 네이티브 서브에이전트가 끝났을 때처럼 완료 알림에 결과 전문이 실려 옵니다:

```
Bash(command: "meight dispatch review-1 --sandbox ro --effort high --brief-file - <<'EOF' ... EOF",
     run_in_background: true)
→ ... Claude는 계속 다른 작업 ...
→ <task-notification> exit 0, 출력에 워커의 전체 보고 포함
```

모든 브리프 앞에는 하네스 프리앰블이 자동으로 붙어요: (a) `git commit`/`push` 금지 — git은 오케스트레이터 소유 — (b) 막히면 추측하지 말고 `QUESTION:` 문단으로 턴을 끝내라. `--no-preamble`로 끌 수 있어요.

바로 쓸 수 있는 오케스트레이터 프롬프트(역할 분담, 라우팅 테이블, 디스패치 프로토콜, 교차 리뷰 규칙)가 [`CLAUDE.md`](../CLAUDE.md)로 동봉돼요 — 프로젝트나 글로벌 Claude Code 메모리에 복사해서 쓰세요. 자기완결형 Claude Code **스킬**도 [`skills/meight/`](../skills/meight/SKILL.md)로 들어있어요 — `~/.claude/skills/`에 복사하면 트리거 기반 JIT 로딩이 됩니다.

## 커맨드 레퍼런스

| 커맨드 | 동작 |
|---|---|
| `meight dispatch <name> [opts]` | 원샷: 데몬 자동기동 → 워커 시작 → 대기 → 결과 출력. 기본 워크플로우 |
| `meight reply <name> --brief ...` | 워커 질문에 원샷 답변: follow + 대기 + 마지막 턴 결과 출력 |
| `meight status [name]` | 다이제스트 pull (테이블/상세). 디스크 직접 읽기 — 데몬 없이도 동작 |
| `meight steer <name> "text"` | 실행 중 턴에 지시 주입 (작업 손실 없음) |
| `meight interrupt <name>` | 실행 중 턴 취소 (idempotent) |
| `meight follow <name> --brief ...` | 저수준: 같은 스레드에 새 턴 (컨텍스트 유지) |
| `meight start / wait / result / list / daemon / ping / shutdown` | dispatch를 구성하는 저수준 블록 |

옵션: `--cwd`(워커 작업 디렉토리 — 파일 범위가 겹치면 git worktree로 분리), `--sandbox ws|ro|full`(기본 `ws`=workspace-write, 리뷰는 `ro`), `--effort low|medium|high|xhigh`(기본 `medium`, 복잡도에 따라 상향), `--model`, `--timeout`.

워커 상태는 `<repo>/.meight/workers/<name>/`에: `brief.md`, `status.json`(상태머신+토큰+변경 파일+현재 활동), `events.log`(의미 있는 이벤트당 1줄), `result.md`(턴별 최종 메시지). `.meight/`는 글로벌 gitignore에 추가하세요.

## 견고성

동시성 레이어(flock+소켓 프로브 데몬 싱글톤, 워커별 컨트롤 락, stale 스트림 이벤트를 버리는 turn generation-id, tool 대기가 최종 상태로 둔갑하지 못하게 하는 `needs_input` source 구분)는 **Codex 자신의 어드버서리얼 리뷰 5라운드**를 통과했어요 — v1 전에 실결함 13건을 찾아 수정. 전체 결함 장부는 [`ARCHITECTURE.md`](../ARCHITECTURE.md#hardening-history)에. `~/.codex/config.toml`(모델, MCP 서버, 인증)을 그대로 상속합니다 — SDK가 표준 `codex app-server`를 띄우는 구조라서요.

> ⚠️ `openai-codex`는 베타라 버전 핀(`0.1.0b3`). 올릴 때는 [`SPEC.md`](../SPEC.md)의 검증 스위트를 재실행하세요.

## License

MIT
