---
name: meight
description: "Hand a whole workstream to a Codex session that owns it: takes a self-contained brief, runs many investigation/execution/verification cycles unsupervised, returns one result, and escalates via `QUESTION:`. Reach for it when work can leave this conversation — implementation, fixes, tests, verification, log digging, browser/runtime QA, computer use, exploration, diagnosis, and design or adversarial review — especially when it parallelizes with what you keep doing, since a Codex session draws a separate subscription. Two postures: worker implements with self-review, mate is a thinking partner for design/diagnosis/verdict-first review; `--mode` is required. Not for a single lookup or a judgment still bound to unspoken conversation context. TRIGGERS: -코덱스 -meight -메이트 -mate -코덱스위임 -위임 -delegate"
---

# meight (claude-codex-meight)

오케스트레이팅 에이전트가 Codex 세션을 병렬로 굴리는 하네스. `meight` CLI로 어느 레포에서든 쓴다. 전역 데몬 하나를 레포들이 공유하고, 세션 상태는 호출 레포별로 `<daemon-home>/repos/<repo-key>/` 아래 격리된다.

기본 디스패처는 Claude Code 세션이다. Codex 앱/CLI 세션도 이 파일을 가리키는 얇은 `~/.codex/skills/meight` 바인딩으로 디스패처가 될 수 있다. 길고 다단계거나 방향이 민감한 작업은 Claude 디스패처가 낫다 — 교차 모델 디스패처는 감독하는 Codex 워커와 사각지대가 겹치지 않는다.

계약 상세는 [`meight-mate`](../meight-mate/SKILL.md), [`meight-worker`](../meight-worker/SKILL.md)에 있고, 공통 프로토콜은 [`meight-common/CONTRACT.md`](../meight-common/CONTRACT.md)다. 하네스 preamble이 자세에 맞는 스킬 + 공통 계약을 주입한다. 이 스킬은 디스패처 쪽 라우팅·감독의 SSOT다.

## 두 자세, --mode는 필수

`dispatch`는 새 세션을 열 때 `--mode mate|worker`를 요구한다. 기본값은 없고, 플래그를 빼면 안내 메시지와 함께 에러다. 구 이름들(`design`/`collab`/`collaborative`/`review` → mate, `delegate`/`delegated` → worker)은 별칭으로 살아 있다.

- `--mode mate` — 생각·판단 상대. 블라인드/앵커드 설계, 진단, 방향, 그리고 verdict-first 플랜/디프/적대 리뷰까지. 어느 프로토콜을 적용할지는 브리프가 정한다 — 리뷰 브리프면 mate 스킬의 리뷰 섹션이 걸린다.
- `--mode worker` — 실행 팀원. how·구현·검증·자기 리뷰를 소유하고, 브리프 밖 관찰과 이견을 텍스트와 `QUESTION:`으로 올린다. 별도 외부 리뷰 세션을 띄울지는 디스패처가 판단한다.

생략된 설정은 자세에서 해소된다. `--effort` 없이 `--model`만 주면 그 모델의 effort 기본값을 다시 고르고, 명시한 `--effort`는 언제나 이긴다 — 표준은 조용하니 편차만 플래그로 준다. dispatch echo가 해소된 값 전부를 `(default)`/`(set)` 출처와 함께 보여준다.

| Mode | Model | Effort | Fast | Sandbox |
|---|---|---|---|---|
| `mate` | `sol` | `medium` | off | `full` |
| `worker` | `luna` | `max` | off | `full` |

이 표와 effort 기본값은 의도적으로 `meight.py` 안의 코드 전용 정책이다 — config 파일도 환경변수 오버라이드도 없다. 샌드박스는 어느 자세도 강제하지 않으니 read-only가 필요하면 브리프에 지시한다 (mate 스킬은 "브리프가 시키지 않으면 레포 파일을 고치지 않는다"를 이미 갖고 있다). `--sandbox`는 수동 선택용으로 남아 있다.

`follow`와 `reply`는 모드 플래그를 받지 않는다. 세션에 기록된 mode를 물려받고 전체 preamble 대신 한 줄 리마인더만 받으며, `--model`·`--effort`·`--fast`를 생략하면 그것도 상속한다 — 명시하면 그 턴부터 이후 턴이 상속하는 값이 된다.

CLI는 `dispatch` 전에 capability handshake를 하고, 살아있는 데몬이 `ephemeral3`를 광고하지 않으면 fail closed한다. 내부 wire `start`/`follow`는 그 epoch를 싣고 성공 시 정규화 모드와 epoch를 원자적으로 echo해야 한다 — 아니면 CLI가 best-effort interrupt 후 nonzero 종료.

## 모델 (GPT-5.6: sol / terra / luna)

`sol`, `terra`, `luna`는 계정 슬러그 `gpt-5.6-*`로 해소되는 실제 별칭이고, 전체/커스텀 문자열도 그대로 통과한다. `--model`을 생략하면 자세 기본값 — 편차일 때만 명시한다.

기본값에서 벗어날 축은 **실패 비용**이다: 돈·데이터 손상, 비가역, 프로덕션 확산이면 올리고 나머지는 `luna`. 난이도가 올라갈 때 첫 대응은 워커 승급이 아니라 단계 추가다 — `sol` mate에게 플랜을 받아 동결하고 `luna` 워커가 구현하는 게 가장 싼 조합이다. worker의 `sol`은 `medium`이고, `sol high`는 mate 자리다 (`sol`에 `xhigh`는 없다). 올렸으면 무엇을 보고 올렸는지 한 줄로 말한다.

사다리 근거·비용 수치·승급 경로 상세: [`references/model-routing.md`](references/model-routing.md)

돈 경로는 디스패처 sign-off를 유지한다. worker 스킬은 보안·비가역 구현, 공개 schema/API 계약, 영속 데이터 마이그레이션, 돈 경로, 동결 플랜을 만나면 작업 전에 에스컬레이션한다 — 모델 라우팅과는 다른 축이다. UX와 사용자 눈에 보이는 동작 판단은 디스패처가 갖고, brief에 수용 UX 계약을 명시한다.

## 디스패치 패턴 — 백그라운드 + 통지

`dispatch`는 데몬 자동 기동 → (새 이름이면 내부 wire start, 활성 이름이면 재부착) → `status.json` 폴링 → `result.md` 출력까지 하는 블로킹 원샷이다. Bash `run_in_background`로 던지면 그 셸의 종료가 태스크 통지를 만들고, 통지 시점에 결과는 이미 디스크에 있다. 그래서 관찰 표면은 `dispatch`·`status`·`result` 셋이고, 백그라운드 `dispatch` 위에 얹는 폴링은 같은 대기를 한 번 더 도는 것 외에 아무것도 알려주지 않는다.

```text
Bash(command: "meight dispatch fix-auth --mode worker --cwd ~/repo --brief-file /tmp/brief.md",
     run_in_background: true)
→ 다른 작업 계속
→ 태스크 통지 도착 → meight result fix-auth
→ exit 3이면 → Bash(command: "meight reply fix-auth --brief '...'", run_in_background: true)
```

새 세션을 열 때는 이름·자세와 모델·effort를 한 줄로 말한다 (`fix-auth 워커 띄웠어 — luna max`) — 백그라운드 세션은 사용자 눈에 안 보이니 그 한 줄이 유일한 창이다. 재부착이면 CLI가 `reattached to worker '<name>'`을 낸다.

- `--timeout`(기본 1800)은 안전망 체크포인트다. 타임아웃으로 셸이 끝나도 워커는 계속 도니, 같은 `dispatch <name> --mode ...`를 다시 실행하면 재부착해 통지를 다시 만든다. terminal 행은 재부착 대상이 아니다. 멈춘 백그라운드 셸은 워커 실패가 아니라 셸 라이프사이클 이벤트고, `status`가 진실이다.
- `--progress`(기본 300) heartbeat는 백그라운드에선 태스크 출력 파일에만 쌓인다 (한 줄/5분). 아주 긴 세션이면 `--progress 0`.
- `steer`는 세션을 어떻게 열었는지 보지 않아서 `dispatch`로 연 세션에도 꽂힌다. 도는 턴이 없는 틈이면 `no active turn to steer`로 떨어지고, terminal 뒤에 같은 내용을 넣으려면 `follow`를 쓴다.
- 세션을 끝내는 도구는 `meight interrupt <name>`이다. `pkill`은 프로세스 이름 매칭이라 `<name>`만으로 잡으면 살려두려던 셸까지 함께 죽는다.
- 워커가 tool/approval 입력을 기다리며 15초 넘게 멈추면 `dispatch`가 exit 3으로 끝나 통지가 온다. `status <name>`의 `needs_input_source`가 `tool`이면 답할 방법이 없는 대기다 — interrupt 후 브리프를 고쳐 재시작한다.
- **capacity 재시도**: provider가 `Selected model is at capacity`로 턴을 끝내면 같은 model·effort·tier·thread에서 5초 시작 60초 상한의 지수 백오프로 재시도한다. 예산은 시간 상한이고 기본 15분, `--timeout`이 더 짧으면 그 시간이다. Fast 승격이나 모델 교체는 하지 않는다 — provider 사정이니 브리프도 모델도 바꿀 게 아니다. 진행은 `status`의 `capacity_retry`와 heartbeat에 보이고, 포기 결과에 횟수·경과가 남는다.

```bash
meight status                # 이 레포 테이블, MODE 포함 / --all-repos, <name> 상세
meight result <name>         # result.md
meight reply <name> --brief "Use config-a.json and keep the legacy field."
meight follow <name> --effort xhigh --fast --brief "Continue with more reasoning."
meight steer <name> "correction"   /   meight interrupt <name>
```

`status`는 pull-only로 디스크를 읽는다. `steer`·`interrupt`·`follow`와 런타임 동작은 살아있는 데몬이 필요하다. 최종 질문과 terminal 결과는 app-server를 살려두지 않지만, `reply`/`follow`는 데몬 재시작이나 registry GC 이후에도 영속된 `thread_id`를 새 런타임에서 재개한다. terminal 결과 후 다른 워커가 없을 때 데몬이 종료하길 원하면 `--shutdown-when-idle`.

### 브리프 골격

`--narrate`는 워커 plan 스텝 전환을 실시간 출력한다 (`[HH:MM:SS] name ▶ <step>`) — 사람이 터미널에서 볼 때만 쓰고 디스패처 세션에서는 노이즈다.

```bash
meight dispatch <name> --mode worker --brief-file - --cwd <dir> <<'EOF'
## Goal       <what this enables + success criteria>
## Decision   <the user decision this phase must close>
## Approval   <approved phase/method/cost envelope; campaign + round number>
## Scope      <file/dir boundary; do not exceed>
## Existing patterns  <file:line pointers; required for good review>
## Constraints <domain rules only; mode/QUESTION policy is injected>
## Stop / Escalate <failed gate, cap, or phase-change conditions>
## Verification <commands to run + expected outcome>
EOF
```

mode/QUESTION 정책은 preamble이 주입하므로 brief에 붙이지 않는다 — 도메인 규칙과 작업별 제약만 넣는다.

## 결과

모든 세션은 일반 텍스트 결과를 `result.md`에 남긴다. 외부 결정이나 진짜 블로커가
있을 때만 마지막 문단에 공통 계약의 `QUESTION:` 형식을 사용한다.

## Codex 워커 능력

brief에서 모달리티를 명시적으로 요구하고, 실제로 썼다는 증거를 요구한다: 브라우저 사용(localhost 앱 클릭스루, 반응형 플로우, 스모크, 스크린샷) / computer use(데스크톱 앱·OS UI 조작) / 비전·스크린샷(레이아웃, 텍스트 잘림, 렌더링, 목업, Figma, 프로덕션 캡처) / 에셋·문서 작업(이미지, PDF, 문서, CSV/XLSX) / 리서치(현행 문서, API, 릴리스 노트, 가격, 정책 — 브라우징 가능할 때) / 커넥터 기반 작업(GitHub, Google Drive, Figma, Canva, Hugging Face, Sentry 등 활성화된 것).

## 참조

- 소유권 경계, phase 승인과 campaign identity, `QUESTION:` 라우팅, 학습 루프 원장(decisions/, preferences.md, lessons.md): [`references/ownership-and-escalation.md`](references/ownership-and-escalation.md)
- 블라인드/앵커드 설계 브리프 예시, 플랜 리뷰 APPROVE/REVISE 인코딩, mate 리뷰, fresh-eyes UI 리뷰, 이견 처리: [`references/design-and-review.md`](references/design-and-review.md)
- 데몬 재시작·epoch 마이그레이션 체크리스트, launchd, 상태 경로, 환경변수, 수명주기 caveat: [`references/daemon-ops.md`](references/daemon-ops.md)
- 모델 사다리 비용 근거, 승급 경로, terra 조건: [`references/model-routing.md`](references/model-routing.md)
