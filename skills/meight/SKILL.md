---
name: meight
description: "Codex dispatch harness (global CLI: meight, repo: claude-codex-meight). Two postures: mate for design/diagnosis/verdict-first review, worker for team implementation with self-review; `--mode` is required and each task is dispatched supervised or one-shot. Use whenever a dispatcher routes work to Codex. TRIGGERS: -코덱스 -meight -메이트 -mate -코덱스위임"
---

# meight (claude-codex-meight)

오케스트레이팅 에이전트가 Codex 세션을 병렬로 굴리는 하네스. `meight` CLI로 어느 레포에서든 쓴다. 전역 데몬 하나를 레포들이 공유하고, 세션 상태는 호출 레포별로 `<daemon-home>/repos/<repo-key>/` 아래 격리된다.

기본 디스패처는 Claude Code 세션이다. Codex 앱/CLI 세션도 이 파일을 가리키는 얇은 `~/.codex/skills/meight` 바인딩으로 디스패처가 될 수 있다. 길고 다단계거나 방향이 민감한 작업은 Claude 디스패처가 낫다 — 교차 모델 디스패처는 감독하는 Codex 워커와 사각지대가 겹치지 않는다.

계약 상세는 [`meight-mate`](../meight-mate/SKILL.md), [`meight-worker`](../meight-worker/SKILL.md)에 있고, 공통 프로토콜은 [`meight-common/CONTRACT.md`](../meight-common/CONTRACT.md)다. 하네스 preamble이 자세에 맞는 스킬 + 공통 계약을 주입한다. 이 스킬은 디스패처 쪽 라우팅·감독의 SSOT다.

## 두 자세, --mode는 필수

`start`와 `dispatch`는 `--mode mate|worker`를 요구한다. 기본값은 없고, 플래그를 빼면 안내 메시지와 함께 에러다. 구 이름들(`design`/`collab`/`collaborative`/`review` → mate, `delegate`/`delegated` → worker)은 별칭으로 살아 있다.

- `--mode mate` — 생각·판단 상대. 블라인드/앵커드 설계, 진단, 방향, 그리고 verdict-first 플랜/디프/적대 리뷰까지. 어느 프로토콜을 적용할지는 브리프가 정한다 — 리뷰 브리프면 mate 스킬의 리뷰 섹션이 걸린다.
- `--mode worker` — 실행 팀원. how·구현·검증·자기 리뷰를 소유하고, 브리프 밖 관찰과 이견을 텍스트와 `QUESTION:`으로 올린다. 별도 외부 리뷰 세션을 띄울지는 디스패처가 판단한다.

샌드박스는 어느 자세도 강제하지 않는다 — read-only가 필요하면 브리프에 지시한다 (mate 스킬은 "브리프가 시키지 않으면 레포 파일을 고치지 않는다"를 기본으로 갖고 있다). `--sandbox`는 수동 선택용으로 남아 있다.

`follow`와 `reply`는 모드 플래그를 받지 않는다. 세션에 기록된 mode를 물려받고, 전체 preamble 대신 한 줄짜리 리마인더만 받는다. `--model`, `--effort`, `--fast`/`--no-fast`를 생략하면 model·effort·Fast tier도 상속하고, 명시하면 그 턴에 적용되며 이후 턴이 상속하는 값이 된다.

생략된 start/dispatch 설정은 wire request를 만들기 전에 CLI에서 자세로부터 해소된다:

| Mode | Model | Effort | Fast | Sandbox |
|---|---|---|---|---|
| `mate` | `sol` | `medium` | off | `full` |
| `worker` | `luna` | `max` | off | `full` |

표준은 조용하다 — 편차만 플래그로 주고, 명시한 플래그는 항상 기본값을 이긴다. 이 표는 의도적으로 `meight.py` 안의 코드 전용 운영 정책이다. config 파일이나 환경변수 오버라이드 레이어는 없다. start echo가 해소된 값 전부를 `(default)` / `(set)` 출처와 함께 보여준다.

mate 기본 effort는 `medium`이다 — 정말 어려운 문제만 `--effort high`로 올린다 (`sol`의 상한은 `high`다). 리뷰도 일반 텍스트로 판단을 반환하며, 외부 라우팅이 필요하면 마지막에 `QUESTION:`을 남긴다.

CLI는 `start` 전에 capability handshake를 한다. 살아있는 데몬이 capability `posture2`를 광고하지 않으면 start는 fail closed. 모든 start/follow는 epoch `posture2`를 싣고, 성공 시 정규화 모드와 epoch를 원자적으로 echo해야 한다 — 아니면 CLI가 best-effort interrupt 후 nonzero 종료.

## 모델 선택 (GPT-5.6: sol / terra / luna)

`--model`을 생략하면 위 자세 기본값. 편차일 때만 명시한다. 짧은 이름은 실제 별칭이다: `sol`, `terra`, `luna`가 현재 ChatGPT 계정 슬러그 `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`로 해소된다. 전체/커스텀 모델 문자열은 그대로 통과한다.

라우팅 원리: **실패 비용이 모델을 고른다.** 기본값은 의도적으로 넓다 — bounded 작업은 `luna` `max`. Fast는 기본 off이고, 지연이 실제로 문제될 때만 `--fast`로 옵트인한다.

난이도가 올라갈 때 첫 대응은 워커 브레인 승급이 아니라 **단계 추가**다: `sol` mate에게 설계·플랜을 먼저 받아 동결하고, 그 플랜을 브리프로 받은 `luna` 워커가 구현한다. 판단이 어려운 것과 실행이 어려운 것은 다른 문제이고 대부분의 어려움은 앞쪽에 있다 — 좋은 플랜을 쥔 `luna max`는 대부분의 구현을 해낸다. 이게 이 하네스의 기본 구조이자 가장 싼 조합이다.

worker 자세를 `sol`로 올리는 건 그 다음이다 — 설계를 앞에 붙일 수 없거나, 플랜이 있어도 구현 자체가 `sol` 브레인을 요구할 때. **worker의 `sol`은 `medium`이다.** `medium`은 무겁게 들리는 작업도 해내고 `high`와의 실측 차이는 작아서, 코드 작업에 `high`를 태우면 값을 못 한다. 구현이 `medium`으로도 안 풀릴 것 같으면 브레인이 아니라 설계가 부족한 것이니 mate 한 판을 앞에 붙인다.

`sol high`는 mate 자리다. plan·적대 리뷰에서는 reviewer 기본값으로 쓰고, 리뷰가
아닌 설계에서는 정말 어려울 때만 사용자 확인을 한 번 받은 뒤 쓴다. worker에는
쓰지 않는다.

| Model | 쓸 곳 | 통상 effort |
|-------|------|---|
| `luna` | worker 자세 구현·수정·테스트·검증, read-only 로그 파기, 브라우저/런타임 QA, computer use, 탐색의 기본 모델 | `max` (Fast는 필요할 때 `--fast` 옵트인) |
| `sol` | mate 자세 방향·verdict 작업의 기본 모델. worker에는 예외 경로 — 설계 선행이 불가능하거나 구현 자체가 어려울 때 | worker는 언제나 `medium`. reviewer는 `high`; 비리뷰 설계의 `high`는 정말 어려울 때만 사용자 확인 후 사용. `xhigh`는 쓰지 않는다 |
| `terra` | 기본 소유 영역 없음. 측정 근거가 뒷받침될 때 capability-specific 폴백 | 작업별 |

실측이 이 사다리를 뒷받침한다 (Artificial Analysis Coding Agent Index v1.3, 종합 / DeepSWE / SWE-Atlas-QnA / 태스크당 비용):

- `luna xhigh` 55 / 57 / 31 / $1.26
- `luna max` **59 / 63 / 33 / $1.57**
- `sol medium` 61 / 64 / 40 / $2.99

`xhigh`에서 `max`로 올리는 건 25%로 종합 4점과 DeepSWE 6%p를 사는 거라 기본값이 거기 있다. 거기서 `sol medium`까지는 비용이 다시 1.9배인데 종합은 2점뿐 — 한계수익이 떨어진다. `sol medium`이 확실히 앞서는 자리는 레포 이해·탐색(QnA 40 대 33)이고, 그게 위 사다리에서 판단이 걸릴 때 `sol medium`으로 올리는 이유다. 근거 전문: [`docs/2026-07-29-model-routing-evidence.md`](../../docs/2026-07-29-model-routing-evidence.md).

측정에서 나온 주의점 하나: `medium`은 적대적 리뷰에서 severity를 과대 승격하는 경향을 보였다. verdict가 걸린 리뷰는 `--effort high`로 올리는 게 낫고, medium은 설계 사고·스코핑 쪽에 맞는다.

브레인을 올릴지는 **그 작업이 실패했을 때 무슨 일이 일어나는지**로 판단한다: 돈·데이터가 손상되거나, 되돌릴 수 없거나, 프로덕션에 크게 번지면 올리고, 나머지는 `luna`다. 작업의 이름은 신호가 약하다 — 동시성이든 마이그레이션이든 계약 설계든 경계가 분명하고 검증이 가능하면 `luna`나 `sol medium`이 해낸다. 올렸으면 무엇을 보고 올렸는지 한 줄로 말한다.

돈 경로는 디스패처 sign-off를 유지한다. worker 스킬은 보안·비가역 구현, 공개 schema/API 계약, 영속 데이터 마이그레이션, 돈 경로, 동결 플랜을 만나면 작업 전에 에스컬레이션한다 — 워커가 혼자 결정하면 안 되는 것들이고, 모델 라우팅과는 다른 축이다. `luna` 작업 안의 모호함도 `QUESTION:`으로 올라온다.

`terra`는 capability-specific 이유와 측정 근거가 있을 때 `luna` 에스컬레이션을 받을 수 있다. 근거가 쌓이면 기본 소유로 승격 가능하지만 baseline 전에는 승격 규칙을 가정하지 않는다. UX와 사용자 눈에 보이는 동작 판단은 디스패처가 갖고, brief에 수용 UX 계약을 명시한다.

## 디스패치 패턴 — 백그라운드 + 통지

디스패처는 포그라운드에서 기다리지 않는다. `dispatch`(또는 `reply`)를 Bash의 `run_in_background`로 던지고 즉시 다른 일을 한다. 프로세스가 끝나면 — 완료든 실패든 exit 3(needs_input)이든 — 하네스가 태스크 통지로 디스패처를 깨운다. 통지 시점에 결과는 이미 디스크에 있다.

```text
Bash(command: "meight dispatch fix-auth --mode worker --cwd ~/repo --brief-file /tmp/brief.md",
     run_in_background: true)
→ 다른 작업 계속
→ 태스크 통지 도착 → meight result fix-auth
→ exit 3이면 → Bash(command: "meight reply fix-auth --brief '...'", run_in_background: true)
```

- **띄우면 한마디 한다**: 세션을 시작할 때 이름·자세와 함께 어떤 모델·effort로 띄웠는지 사용자에게 한 줄로 말한다 (`fix-auth 워커 띄웠어 — luna max`). 기본에서 벗어났으면 왜 올렸는지도 같은 줄에 붙인다. 백그라운드 세션은 사용자 눈에 안 보이니 이 한 줄이 어떤 브레인이 얼마짜리로 돌고 있는지 아는 유일한 창이다.
- `--timeout`(기본 1800)은 안전망 체크포인트다: 타임아웃으로 깨어나도 워커는 계속 돈다 — `status <name>` 보고 백그라운드 `wait`를 다시 건다.
- `--progress`(기본 300) heartbeat는 백그라운드에선 태스크 출력 파일에만 쌓인다 (한 줄/5분). 아주 긴 세션이면 `--progress 0`.
- 중간 개입 가능성이 있는 작업은 `start`로 열고 백그라운드 `wait <name> --timeout`을 별도로 건다 — 그 사이 `meight steer <name> "correction"`으로 도는 턴에 텍스트를 주입할 수 있다.
- **tool-wait 표면화**: 워커가 tool/approval 입력을 기다리며 15초 넘게 멈추면 wait가 exit 3으로 끝나 통지가 온다 (전에는 타임아웃까지 invisible). `status <name>`의 `needs_input_source`가 `tool`이면 답할 방법이 없는 대기다 — interrupt 후 브리프를 고쳐 재시작한다.

### 사람용 터미널 사용법

포그라운드 `wait`/`dispatch`는 사람이 터미널에서 직접 지켜볼 때의 사용법이다. `--narrate`를 주면 워커의 plan 스텝 전환이 실시간으로 출력된다 (`[HH:MM:SS] name ▶ <step>`) — 디스패처 세션에서는 노이즈라 기본 off다.

```bash
meight start <name> --mode worker --brief-file - --cwd <dir> <<'EOF'
## Goal       <what this enables + success criteria>
## Decision   <the user decision this phase must close>
## Approval   <approved phase/method/cost envelope; campaign + round number>
## Scope      <file/dir boundary; do not exceed>
## Existing patterns  <file:line pointers; required for good review>
## Constraints <domain rules only; mode/QUESTION policy is injected>
## Stop / Escalate <failed gate, cap, or phase-change conditions>
## Verification <commands to run + expected outcome>
## Verification <commands to run + expected outcome>
EOF
```

mode/QUESTION 정책은 preamble이 주입하므로 brief에 붙이지 않는다. brief에는 도메인 규칙과 작업별 제약만 넣는다.

```bash
meight status                # 이 레포의 한 줄 테이블, MODE 포함
meight list --all-repos      # 레포 네임스페이스 전역 테이블
meight status <name>         # 상세 — mode/needs_input target+kind 포함
meight steer <name> "correction"
meight interrupt <name>
meight result <name>         # result.md 출력
meight reply <name> --brief "Use config-a.json and keep the legacy field."
meight follow <name> --effort xhigh --fast --brief "Continue with more reasoning."
```

`status`는 pull-only이고 디스크를 읽는다. `steer`, `interrupt`, `follow`와 런타임 동작은 살아있는 데몬이 필요하다. 최종 질문과 terminal 결과는 app-server를 살려두지 않는다 — `reply`/`follow`는 데몬 재시작이나 registry GC 이후에도 영속된 `thread_id`를 새 런타임에서 재개한다.

멈춘 백그라운드 셸은 워커 실패가 아니라 셸 라이프사이클 이벤트로 취급한다 — `status`가 진실이다.

`dispatch`는 데몬 자동 기동 → start → wait → `result.md` 출력까지 한 번에 하는 블로킹 원샷이다 — 위 패턴대로 백그라운드로 던진다. terminal 결과 후 다른 워커가 없을 때 데몬이 종료하길 원하면 `--shutdown-when-idle`.

## 결과

모든 세션은 일반 텍스트 결과를 `result.md`에 남긴다. 외부 결정이나 진짜 블로커가
있을 때만 마지막 문단에 공통 계약의 `QUESTION:` 형식을 사용한다.

## Codex 워커 능력

brief에서 모달리티를 명시적으로 요구하고, 실제로 썼다는 증거를 요구한다: 브라우저 사용(localhost 앱 클릭스루, 반응형 플로우, 스모크, 스크린샷) / computer use(데스크톱 앱·OS UI 조작) / 비전·스크린샷(레이아웃, 텍스트 잘림, 렌더링, 목업, Figma, 프로덕션 캡처) / 에셋·문서 작업(이미지, PDF, 문서, CSV/XLSX) / 리서치(현행 문서, API, 릴리스 노트, 가격, 정책 — 브라우징 가능할 때) / 커넥터 기반 작업(GitHub, Google Drive, Figma, Canva, Hugging Face, Sentry 등 활성화된 것).

## 참조

- 소유권 경계, phase 승인과 campaign identity, `QUESTION:` 라우팅, 학습 루프 원장(decisions/, preferences.md, lessons.md): [`references/ownership-and-escalation.md`](references/ownership-and-escalation.md)
- 블라인드/앵커드 설계 브리프 예시, 플랜 리뷰 APPROVE/REVISE 인코딩, mate 리뷰, fresh-eyes UI 리뷰, 이견 처리: [`references/design-and-review.md`](references/design-and-review.md)
- 데몬 재시작·epoch 마이그레이션 체크리스트, launchd, 상태 경로, 환경변수, 수명주기 caveat: [`references/daemon-ops.md`](references/daemon-ops.md)
