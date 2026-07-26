---
name: meight
description: "Codex dispatch harness (global CLI: meight, repo: claude-codex-meight). Route blind and anchored design to design, verdict-first plan/diff review to review, participatory bounded implementation to worker, and dispatcher-free full delegation to delegate; `--mode` is required and each task is dispatched supervised or one-shot. Use whenever a dispatcher routes work to Codex. TRIGGERS: -코덱스 -meight -메이트 -mate -코덱스위임"
---

# meight (claude-codex-meight)

오케스트레이팅 에이전트가 Codex 세션을 병렬로 굴리는 하네스. `meight` CLI로 어느 레포에서든 쓴다. 전역 데몬 하나를 레포들이 공유하고, 세션 상태는 호출 레포별로 `<daemon-home>/repos/<repo-key>/` 아래 격리된다.

기본 디스패처는 Claude Code 세션이다. Codex 앱/CLI 세션도 이 파일을 가리키는 얇은 `~/.codex/skills/meight` 바인딩으로 디스패처가 될 수 있다. 길고 다단계거나 방향이 민감한 작업은 Claude 디스패처가 낫다 — 교차 모델 디스패처는 감독하는 Codex 워커와 사각지대가 겹치지 않는다.

계약 상세는 [`meight-mate`](../meight-mate/SKILL.md), [`meight-worker`](../meight-worker/SKILL.md), [`meight-delegate`](../meight-delegate/SKILL.md)에 있고, 셋의 공통 프로토콜은 [`meight-common/CONTRACT.md`](../meight-common/CONTRACT.md)다. 하네스 preamble이 모드에 맞는 스킬 + 공통 계약을 주입한다. 이 스킬은 디스패처 쪽 라우팅·감독의 SSOT다.

## 모드는 필수

`start`와 `dispatch`는 `--mode design|review|worker|delegate`를 요구한다. `collab`, `collaborative`, `delegated`는 별칭. 기본값은 없고, 플래그를 빼면 안내 메시지와 함께 에러다.

- `--mode design` — 블라인드/앵커드 설계, 진단, 아키텍처, 대안, 트레이드오프, 계획, 방향 설정. 세션은 mate이고 선택지와 근거를 펼친다.
- `--mode review` — verdict-first 플랜/디프/적대적/독트린 리뷰. 리뷰 의무가 명시된 mate.
- `--mode worker` — bounded 구현, 수정, 테스트, 검증, 런타임/브라우저 QA, computer use, 탐색. 별도 리뷰 세션이 필요한지는 디스패처가 판단.
- `--mode delegate` — 디스패처가 기술 컨텍스트에서 빠지는 완전 위임. delegate가 내부 fresh-context read-only 리뷰를 소유하며, 하드 게이트·돈 경로·동결된 디스패처 리뷰 체인은 worker로 fail-closed.

design/review는 mate 계약, worker는 참여형 구현, delegate는 완전 위임이다. 정규화된 모드는 `status.json`에 기록되고 `MODE` 컬럼에 뜬다.

`follow`와 `reply`는 모드 플래그를 받지 않는다. 세션에 기록된 mode/report를 물려받고, 전체 preamble 대신 한 줄짜리 하네스 리마인더만 받는다. `--model`, `--effort`, `--fast`/`--no-fast`를 생략하면 model·effort·Fast tier도 상속하고, 명시하면 그 턴에 적용되며 이후 턴이 상속하는 값이 된다.

생략된 start/dispatch 설정은 wire request를 만들기 전에 CLI에서 모드로부터 해소된다:

| Mode | Model | Effort | Fast | Report | Sandbox |
|---|---|---|---|---|---|
| `design` | `sol` | `high` | off | `text` | `ro` |
| `review` | `sol` | `high` | off | `decision` | `ro` |
| `worker` | `luna` | `xhigh` | on | `decision` | `full` |
| `delegate` | `sol` | `high` | off | `decision` | `full` |

표준은 조용하다 — 편차만 플래그로 주고, 명시한 플래그는 항상 모드 기본값을 이긴다. 이 표는 의도적으로 `meight.py` 안의 코드 전용 운영 정책이다. config 파일이나 환경변수 오버라이드 레이어는 없다. start echo가 해소된 값 전부를 `(default)` / `(set)` 출처와 함께 보여준다.

CLI는 `start` 전에 capability handshake를 한다. 살아있는 데몬이 capability `mode4`를 광고하지 않으면 start는 fail closed. 모든 start/follow는 epoch `mode4`를 싣고, 성공 시 정규화 모드와 epoch를 원자적으로 echo해야 한다 — 아니면 CLI가 best-effort interrupt 후 nonzero 종료.

## 모델 선택 (GPT-5.6: sol / terra / luna)

`--model`을 생략하면 위 모드 기본값. 편차일 때만 명시한다. 짧은 이름은 실제 별칭이다: `sol`, `terra`, `luna`가 현재 ChatGPT 계정 슬러그 `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`로 해소된다. 전체/커스텀 모델 문자열은 그대로 통과한다.

라우팅 원리: **실패 비용이 모델을 고른다.** 기본값은 의도적으로 넓다 — bounded 작업은 `luna` `xhigh`, 계정과 서비스가 Fast를 지원하면 `--fast`.

| Model | 쓸 곳 | 통상 effort |
|-------|------|---|
| `luna` | worker 모드 구현·수정·테스트·검증, read-only 로그 파기, 브라우저/런타임 QA, computer use, 탐색의 기본 모델 | `xhigh` + 가능하면 `--fast` |
| `sol` | design/review 방향·verdict 작업의 기본 모델, 그리고 하드 게이트 걸린 worker 구현 | `high`; `xhigh`는 정말 어려운 문제에만 |
| `terra` | 기본 소유 영역 없음. 측정 근거가 뒷받침될 때 capability-specific 폴백 | 작업별 |

`high`는 sol의 기본값이지 바닥이 아니다 — `high`가 과사고할 수 있어서 가벼운 mate 작업은 `medium`으로 내려도 된다. 다만 측정에서 나온 주의점: `medium`은 적대적 리뷰에서 severity를 과대 승격하는 경향을 보였다. 그래서 medium 강등은 verdict를 내는 리뷰보다 설계 사고·스코핑 쪽에 쓰는 게 낫다.

하드 게이트 (계약 문구 그대로): **acceptance-critical한 부분이 concurrency, security, 공개 schema/API 계약 설계, 영속 데이터 마이그레이션, cross-cutting 리팩터에 materially 의존하거나 실패가 돈/데이터 손상·비가역·고임팩트 프로덕션 피해를 낳으면 sol로 하드 라우팅.** 일반 엔드포인트 구현은 `luna`, API 계약 설계·진화는 `sol`. read-only 프로덕션 로그 조사는 `luna`, 프로덕션 mutation이나 인시던트 remediation은 `luna` 작업이 아니고, 돈 경로는 기존 디스패처 sign-off 게이트를 유지한다. `luna` 작업 안의 모호함은 `QUESTION:` 에스컬레이션으로 처리한다.

`terra`는 capability-specific 이유와 측정 근거가 있을 때 `luna` 에스컬레이션을 받을 수 있다. 근거가 쌓이면 기본 소유로 승격 가능하지만 baseline 전에는 승격 규칙을 가정하지 않는다. UX와 사용자 눈에 보이는 동작 판단은 디스패처가 갖고, brief에 수용 UX 계약을 명시한다.

## 감독 인터페이스

`start`가 감독 세션을 연다. `status`, `steer`, `result`, `reply`로 다시 들여다본다 — 얼마나 자주 볼지는 정해두지 않는다.

```bash
meight start <name> --mode worker --brief-file - --cwd <dir> <<'EOF'
## Goal       <what this enables + success criteria>
## Decision   <the user decision this phase must close>
## Approval   <approved phase/method/cost envelope; campaign + round number>
## Scope      <file/dir boundary; do not exceed>
## Existing patterns  <file:line pointers; required for good review>
## Constraints <domain rules only; mode/QUESTION/report policy is injected>
## Stop / Escalate <failed gate, cap, or phase-change conditions>
## Verification <commands to run + expected outcome>
## Report     <decision surface; details in a worker-unique evidence artifact>
EOF
```

mode/report/QUESTION 정책은 preamble이 주입하므로 brief에 붙이지 않는다. brief에는 도메인 규칙과 작업별 제약만 넣는다.

```bash
meight status                # 이 레포의 한 줄 테이블, MODE 포함
meight list --all-repos      # 레포 네임스페이스 전역 테이블
meight status <name>         # 상세 — mode/report/needs_input target+kind 포함
meight steer <name> "correction"
meight interrupt <name>
meight result <name>         # decision.md가 있으면 그걸 우선
meight result <name> --raw   # raw result.md 감사 기록
meight reply <name> --brief "Use config-a.json and keep the legacy field."
meight follow <name> --effort xhigh --fast --brief "Continue with more reasoning."
meight reply <name> --effort high --no-fast --brief "Use the approved option."
```

`status`는 pull-only이고 디스크를 읽는다. `steer`, `interrupt`, `follow`와 런타임 동작은 살아있는 데몬이 필요하다. 최종 질문과 terminal 결과는 app-server를 살려두지 않는다 — `reply`/`follow`는 데몬 재시작이나 registry GC 이후에도 영속된 `thread_id`를 새 런타임에서 재개한다.

장기 실행 체크포인트 셸은 기본 오케스트레이션 경로가 아니다. 멈춘 백그라운드 셸은 워커 실패가 아니라 셸 라이프사이클 이벤트로 취급한다.

## 원샷 디스패치

`dispatch`는 별도 감독 세션이 필요 없을 때 쓰는 블로킹 원샷이다.

```bash
meight dispatch tiny-1 --mode worker --sandbox ro \
  --brief "Check whether README mentions LICENSE."
```

필요하면 데몬을 자동 기동하고, 워커를 시작해 기다렸다가 선호 결과(`decision.md` 있으면 그것, 없으면 `result.md`)를 출력한다. terminal 결과 후 다른 워커가 없을 때 데몬이 종료하길 원하면 `--shutdown-when-idle`.

## 리포트 모드

모드별 기본값: design은 `text`, review/worker/delegate는 `decision`. `--report`가 항상 이긴다. text 리포트는 최종 메시지를 `result.md`에 쓴다.

`--report decision`일 때:
- SDK 턴이 `output_schema`를 쓴다.
- 데몬이 턴마다 `decision.json`과 렌더된 `decision.md`를 쓴다.
- `meight result`, `dispatch`, `reply`는 `decision.md`를 우선한다. `meight result --raw`는 raw `result.md`.
- `result.md`는 감사 기록으로 남는다.
- `outcome=needs_decision`은 `needs_input` / exit `3`으로 라우팅되며 첫 user-targeted 항목을 우선한다.

정확한 스키마와 필드 의미는 [공통 계약](../meight-common/CONTRACT.md)에만 있다.

## Codex 워커 능력

brief에서 모달리티를 명시적으로 요구하고, 실제로 썼다는 증거를 요구한다: 브라우저 사용(localhost 앱 클릭스루, 반응형 플로우, 스모크, 스크린샷) / computer use(데스크톱 앱·OS UI 조작) / 비전·스크린샷(레이아웃, 텍스트 잘림, 렌더링, 목업, Figma, 프로덕션 캡처) / 에셋·문서 작업(이미지, PDF, 문서, CSV/XLSX) / 리서치(현행 문서, API, 릴리스 노트, 가격, 정책 — 브라우징 가능할 때) / 커넥터 기반 작업(GitHub, Google Drive, Figma, Canva, Hugging Face, Sentry 등 활성화된 것).

## 참조

- 소유권 경계, phase 승인과 campaign identity, `QUESTION:` 라우팅, 학습 루프 원장(decisions/, preferences.md, lessons.md): [`references/ownership-and-escalation.md`](references/ownership-and-escalation.md)
- 블라인드/앵커드 설계 브리프 예시, 플랜 리뷰 APPROVE/REVISE 인코딩, mate 리뷰, fresh-eyes UI 리뷰, 이견 처리: [`references/design-and-review.md`](references/design-and-review.md)
- 데몬 재시작·mode4 마이그레이션 체크리스트, launchd, 상태 경로, 환경변수, 수명주기 caveat: [`references/daemon-ops.md`](references/daemon-ops.md)
