---
date: 2026-07-28
scope: [meight.py, skills, posture2, dispatch-pattern]
type: refactor
---

## TL;DR
4모드(design/review/worker/delegate)를 mate/worker 2자세로 통합하고, 샌드박스 강제를 제거하고, 워커를 침묵 실행자에서 팀원 계약(자기 리뷰·반문·관찰 보고)으로 바꿨다. 디스패처의 포그라운드 wait를 폐기하고 "백그라운드 디스패치 + 하네스 통지" 패턴을 기본으로 명문화했다. 커밋 4개(`fe703e2`→`9a95d4a`) origin/main 푸시 완료, 테스트 69/69, 데몬 posture2 재시작 + mate/worker 스모크 라이브 통과.

## Keywords
`posture2` `mate` `worker` `MODE_START_DEFAULTS` `run_in_background` `--narrate` `TOOL_WAIT_GRACE_SEC` `classify_wait_state` `better-direction` `fe703e2` `b820496`

## Context
발단은 meight 자체가 아니라 같은 날 ~/.claude 쪽 작업이었다. Claude 5 공식 문서 2편(context engineering / Prompting Opus 5) 기준으로 tech-lead.md와 에이전트 구조를 "규칙 → 판단" 방향으로 정리했고(code-implementer/test-implementer → 범용 worker 에이전트 + refs/), 그 직후 우용이가 물었다: "meight의 design/worker/review 모드 분리 자체가 오버헤드 아닌가? 범용 하나를 능동적 팀원으로 굴리는 게 낫지 않나?"

중요한 프레임 교정이 하나 있었다. 나는 처음에 "GPT-5.6 프롬프트를 깎는 문제"로 받았는데, 우용이가 바로잡았다 — **meight 프로토콜은 Claude(디스패처)가 쓰는 인터페이스**고, 질문은 그 관점의 것이었다. 모드 분류는 디스패처가 디스패치마다 지불하는 세금이라는 프레임이 이 개편의 출발점이다.

## Investigation
Explore 에이전트로 레포 전수 조사부터 했다 (판단 전 사실 수집). 결정적 발견 세 개:

1. **"4모드"는 절반이 허상** — design과 review는 이미 같은 스킬 파일(meight-mate)을 공유했고 차이는 preamble 3줄뿐. 데몬 실행 경로에 모드 분기 0개. 모드는 CLI에서 "기본값 5개 + 스킬 경로 1개"로 해소된 뒤 라벨로만 흘렀다. → 통합 비용이 낮다는 근거.
2. **진짜 갈리는 축은 역할이 아니라 권한 자세(read-only vs write)** — 그런데 우용이가 이 축마저 걷어냈다: "read-only도 sandbox로 막는 건 불편, 지시만 하면 읽기 전용으로 돈다." 결국 남은 축은 mate(생각 상대)/worker(실행 팀원)라는 세션 계약 둘.
3. **팀원 계약은 텍스트로 이미 존재했으나 역할 경계가 죽이고 있었다** — `QUESTION:` 채널에 `better-direction` KIND까지 있는데, mate 스킬은 "구현하지 마"에, worker 스킬은 "리뷰하지 마"에 각 15줄을 쓰고 있었다. "기계적 작업자" 냄새의 출처.

부수 발견: `classify_wait_state`가 `needs_input_source=="tool"`을 무시해서 tool-wait가 타임아웃까지 invisible한 사각지대(수리됨), needs_input으로 잠든 워커 3개 방치, `~/.meight/notes/preferences.md`의 "하네스 수술 sol"과 상위 메모리 "하네스 수술 Claude" 모순.

## What Didn't Work
### ❌ plan 스텝 실시간 내레이션을 기본 on으로
- 시도: 1차 수술에서 "턴 도중 소통" 요구를 wait 루프의 스텝 전환 실시간 출력으로 구현했다.
- 문제: 우용이 지적 두 방 — (a) 디스패처 컨텍스트에 노이즈, (b) 애초에 디스패처가 포그라운드로 지켜보는 구조 자체가 틀렸다("foreground wait 나쁜 구조임").
- 교훈: "소통 개선"을 채널 추가로 풀기 전에 **그 채널을 누가 듣고 있는가**부터 물어야 한다. 듣는 주체가 없는 채널은 노이즈다. 결과: 내레이션은 `--narrate` 옵트인(사람 터미널용), 디스패처는 run_in_background + 하네스 태스크 통지로 전환 — 데몬 수정 없이 Claude Code 하네스의 기존 push 채널을 그대로 쓴 해법.

### ❌ (개편 전 프레임) GPT 프롬프팅 최적화 문제로 접근
- 시도: 모드 통합 질문을 "GPT-5.6은 명시 구조가 유효하니 모드별 스캐폴드가 필요할 수도"로 받았다.
- 문제: 질문의 주어가 틀렸다. 인터페이스는 Claude가 쓰고, 워커 본문만 GPT가 읽는다.
- 교훈: 프로토콜을 다듬을 땐 텍스트별로 **독자가 누구인지** 먼저 갈라라. 이 원칙이 실제 작업 분배가 됐다: skills/meight/SKILL.md(디스패처용)는 Claude 5 문법, meight-mate/-worker(워커용)는 GPT-5.6 문법.

## Decision Rationale
- **2자세 유지 (완전 단일화 거부)**: mate/worker까지 합치지 않은 건 컨텍스트 격리가 실질 가치라서다 — 리뷰·블라인드 설계의 힘은 디스패처 프레임을 물려받지 않는 데서 온다. 이건 자세가 아니라 브리프로도 되지만, 기본값 묶음(sol/medium vs luna/xhigh/fast)의 앵커로서 2행 테이블은 남길 가치가 있었다.
- **mate 기본 sol/medium**: 우용이 결정. "어려울 때만 high 수동 승급." 측정 주의점(medium은 적대 리뷰에서 severity 과대 승격)은 스킬에 남김 — verdict 리뷰는 `--effort high` 권장.
- **delegate 삭제**: worker와의 차이가 "리뷰 루프 소유권"뿐이었고, 워커가 자기 리뷰 재량(내부 리뷰어 스폰 포함, 2라운드 캡)을 가지면 존재 이유가 사라진다. Forbidden Routes 중 유효한 것은 worker의 작업 전 에스컬레이션 게이트로 이전.
- **별칭 유지**: 우용이의 UserPromptSubmit 훅이 `--mode review`를 주입하고 있어 제거하면 훅이 깨진다. 기록된 세션 호환도 겸함.
- **--timeout 1800 유지**: 백그라운드 패턴에서 타임아웃 종료는 실패가 아니라 안전망 체크포인트 통지가 된다 (워커는 계속 돈다).

## Work Accomplished
### 1. posture2 본 개편 (커밋 `fe703e2`)
mode 축 4→2, epoch mode4→posture2(fail-closed handshake), 샌드박스 기본 full(no enforcement), 스킬 4→3종(delegate 삭제), 역할 경계 지시 제거 + 팀원 계약 전면화, tool-wait 15s grace 후 exit 3 표면화, 문서(CLAUDE/AGENTS/README/ARCHITECTURE/SPEC/CONTEXT) 갱신, `decisions/2026-07-28-posture-collapse.md`.
### 2. 디스패치 패턴 전환 (커밋 `b820496`)
`wait_for_worker(narrate=False)` + `--narrate` 3개 파서, skills/meight/SKILL.md "백그라운드 + 통지" 패턴 명문화(실커맨드 예시), WaitNarrationTests.
### 3. 문서 마무리 (커밋 `e20de31`, `9a95d4a`)
openai.yaml 메타데이터, README.ko.md 전면 재작성(한다체 통일). 번역 중 영문 README의 posture2 잔재 2곳("four session modes", sol effort high) 발견·수정 — Noticed 채널이 번역 작업에서 실제로 값을 냈다.

## Verification
- `.venv/bin/python -m unittest discover -s tests` → 69/69 OK (주의: 시스템 python3으로 돌리면 `openai_codex` 미설치로 1개 실패 — 환경 문제지 회귀 아님)
- 데몬: `meight shutdown` → launchd kickstart → `pong ... capabilities=posture2`
- 스모크 (새 패턴 그대로 run_in_background 디스패치): mate 15s 완료(기본값 sol/medium/text 해소 확인), worker 51s 완료 — 리포트에 시키지 않은 "Self-review" 검증 라인이 들어옴(새 계약 작동 증거). smoke-ok.txt 내용 확인.
- 푸시: `origin/main = 9a95d4a`, gh 활성 계정 mysubb01 복구 확인.

## Architecture Impact
- 이 레포를 아는 다른 디스패처 세션들은 재시작 전까지 구 스킬 스냅샷을 들고 있다 — 다음 세션부터 새 로스터.
- `MODE_START_DEFAULTS`가 코드 내 유일한 운영 정책이라는 원칙은 유지 (config 레이어 없음).
- 포그라운드 `wait`/`--narrate`는 이제 "사람용"으로 분류된다. 디스패처 플로우에 wait를 쓰는 스킬·문서를 새로 쓸 때 이 구분을 지켜라.

## Files Changed
| File | Change |
|------|--------|
| `meight.py` | mode 축 2행, epoch posture2, tool-wait grace, narrate 게이트 |
| `tests/test_meight.py` | 모드 고정 테스트 갱신 + WaitNarrationTests + tool-wait 회귀 (65→69) |
| `skills/meight-{mate,worker,common}/` | 팀원 계약 재작성, delegate 삭제·흡수 |
| `skills/meight/SKILL.md` + `references/` | 디스패처 SSOT — 백그라운드+통지 패턴 |
| `README.md` / `docs/README.ko.md` | posture2 기준 재작성 / 전면 완역 |
| `decisions/2026-07-28-posture-collapse.md` | 결정 기록 + AMENDMENT 2건 |

## 미결
- needs_input으로 잠든 워커 3개 (`tn-migrate-review`, `tn-p1-review`, `tn-p1-verify`) — reply 또는 정리 필요.
- `~/.meight/notes/preferences.md` "하네스 수술 sol" vs 메모리 "하네스 수술 Claude" 모순 — 우용이 판정 대기 (이번 수술은 Claude fork로 진행, 결과 깨끗).
- verdict 인코딩의 스키마 1급 필드화 백로그는 여전히 열려 있음 (docs/CONTEXT.md).

## Commit
docs(cycles): posture2 개편 세션 wrap

Co-Authored-By: Fable 5 <noreply@anthropic.com>
