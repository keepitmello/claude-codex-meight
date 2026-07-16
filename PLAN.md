# PLAN mode4-worker-delegate-split v2 (draft)

v1 → v2: plan-review-mode4 R1의 P1 4건 반영 (protocol epoch handshake, SSOT
경계 정정, 침묵 의미 변경 방지, 테스트 매트릭스/스모크 확장).

## Background

- 2026-07-14 mode-axis-collapse는 실사용 조합을 3개(mate+design, mate+review,
  worker+delegate)로 상정하고 단일 모드 축으로 접었다. 이때 worker 계약은
  전부 "위임"이라고 가정했다.
- 같은 날 계약 분리 커밋 f924c46이 구 worker 계약(e65173a)의 위임 격벽 —
  "decision surface, not a technical log" / "keep the dispatcher out of
  implementation and review ping-pong" / 내부 독립 리뷰어
  `multi_agent_v1.spawn_agent(agent_type="reviewer", fork_context=false)` —
  을 드랍했다. 결과적으로 delegate가 순수 구현자 계약으로 축소되고, 리뷰가
  디스패처 오케스트레이션 체인으로 일원화되어 "dispatcher를 기술 맥락에서
  분리한다"는 delegate의 존재 이유가 소실됐다.
- 사용자 확정 방향(2026-07-16): 분리 축은 작업 리스크가 아니라 **운영 상황**.
  Claude(dispatcher)가 기술 작업에 참여하는 축(design/review/worker)과 기술
  작업에서 완전히 빠지는 축(delegate)은 별개 운영 모드다. 누락됐던 4번째
  조합(worker 계약 + dispatcher 기술 참여)을 `worker` 모드로 신설하고,
  `delegate`를 원래의 전권 위임 계약으로 복원한다.

## Goal

`--mode design|review|worker|delegate` 4모드 체계.

- `worker` (신설): 현행 슬림 구현 계약(skills/meight-worker/SKILL.md)을 그대로
  사용. dispatcher가 리뷰 체인을 소유한다: 별도 `--mode review` sol 적대 리뷰
  세션 + dispatcher 풀 diff 읽기 + 최종 사인오프. plan-governed 및 하드게이트
  구현의 기본 모드.
- `delegate` (복원): 전권 위임 계약(skills/meight-delegate/SKILL.md 신설).
  e65173a의 Delegated Mode 섹션 + Implementation quality gate를
  meight-common/CONTRACT.md 위에 재기반(중복 normative 텍스트 0 원칙 유지):
  - 보고는 decision surface. 기술 로그/구현 추론을 dispatcher에게 보고하지
    않는다. 상세는 worker-unique evidence artifact로.
  - 기술 루프를 end-to-end로 소유. dispatcher를 구현·리뷰 핑퐁에서 배제.
  - 비자명(non-trivial) 작업은 구현 후 내부 독립 리뷰어를 기본으로 스폰:
    `multi_agent_v1.spawn_agent(agent_type="reviewer", fork_context=false)`
    (fresh context), read-only, 최대 2라운드, 수용된 P1 수정 후 관련 검증
    재실행. trivial 작업은 brief가 명시적으로 리뷰를 면제할 수 있다.
  - 금지 라우트 fail-closed: brief 자체가 하드게이트(보안/비가역/공개 계약/
    영속 마이그레이션) 또는 money-path/frozen dispatcher review chain을
    선언하면, 작업을 진행하지 않고 dispatcher-targeted reroute decision으로
    종료한다.
  - 구조적 `QUESTION:`은 소유권 밖 결정·진짜 블록에만.
- `design`/`review`: mate 프로토콜 변경 없음. 단, 문서/계약 내 stale 3모드
  라우팅 문장은 전파 대상(아래 Changes 3).

## Success Criteria

1. `--mode worker` start: preamble이 meight-worker 스킬 + 공통 계약을 주입,
   status.json / MODE 컬럼에 `worker` 기록.
2. `--mode delegate` start: preamble이 meight-delegate 스킬 + 공통 계약을
   주입. start의 운영자-가시 출력이 `mode=delegate contract=full-delegation`
   형태로 모드와 계약 자세를 함께 표시한다 (worker는
   `mode=worker contract=participatory`).
3. **Protocol epoch handshake**: 모든 `start`/`follow` 요청에 명시적 프로토콜/
   계약 epoch(`mode4`)가 실린다. 데몬은 import/상태 디렉터리 생성/레지스트리
   예약/SDK 기동/턴 시작 등 어떤 부작용보다 먼저 epoch를 검증하고, 성공
   응답은 normalized mode + epoch를 원자적으로 함께 에코한다. CLI는 둘 다
   검증하고 불일치 시 best-effort interrupt + 명확한 에러 + 비정상 종료.
   신 데몬은 `capabilities=mode4`만 광고 → 구 CLI는 preflight에서 fail-closed.
   같은 문자열 `delegate`로 성립하는 same-token downgrade가 swapped-daemon
   테스트로 커버된다.
4. follow/reply의 mode 상속이 4모드 전부에서 동작한다.
5. 문서 라우팅이 새 축을 반영한다: bounded 구현(디스패처 참여) → worker,
   전권 위임 → delegate. 저장된 기존 `--mode delegate` 예시/명령이 리포 전수
   인벤토리로 갱신된다.

## Changes

1. **meight.py**: mode enum에 `worker` 추가, mode→skill 매핑
   (design/review→meight-mate, worker→meight-worker, delegate→meight-delegate).
   capability 토큰 `mode3`→`mode4` + **start/follow 요청 epoch 필드 + 데몬 측
   부작용-전 검증 + 응답 mode+epoch 원자 에코 + CLI 양쪽 검증**(role→mode3
   fail-closed 기계 확장). 티칭 에러 문구에 worker/delegate 구분 한 줄 포함.
   `cmd_start` 출력에 mode/contract posture 가시화.
2. **skills/meight-delegate/SKILL.md** 신설 (+ agents/openai.yaml): 위 Goal의
   delegate 계약. 전권-위임 고유 규범만 담는다: dispatcher 배제, decision
   surface 보고, 내부 fresh-context read-only 리뷰(≤2라운드, 수용 P1 수리 후
   재검증), trivial 면제 조건, 금지 라우트 fail-closed reroute, 소유권 밖
   escalation.
3. **SSOT 경계 정정**:
   - `skills/meight-common/CONTRACT.md`: 공유 harness-값 라우팅만 갱신 — 4모드
     열거, worker/delegate를 각 모드 스킬로 포인팅. decision 스키마·QUESTION
     라우팅·evidence·sandbox·git 규범은 이 파일에 단일 유지(변경 없음).
   - `skills/meight-worker/SKILL.md`: dispatcher-참여 구현 소유권 유지.
     description의 "delegate mode" 문구를 worker 모드로 갱신, "hard-gated
     implementation run by sol in worker mode"로 정정.
   - `skills/meight-mate/SKILL.md`: 하드게이트 sol 구현이 `--mode delegate`라는
     stale 문장 1건을 `--mode worker`로 정정(전파이며 mate 프로토콜 재설계
     아님).
4. **문서 전파 (전수 인벤토리)**: CLAUDE.md 라우팅 테이블, skills/meight/
   SKILL.md, README.md, docs/README.ko.md, docs/CONTEXT.md, SPEC.md,
   ARCHITECTURE.md, AGENTS.md. 모든 bounded-구현 예시를 delegate→worker로
   갱신하고, delegate 행을 "dispatcher가 기술 맥락에서 빠지는 전권 위임"으로
   재정의. `rg -n "mode delegate|--mode delegate|delegate mode"` 전수 스윕으로
   누락 0 확인.
5. **테스트**:
   - 단위 매트릭스: 4 canonical 모드 + alias 수용/거부, 데몬 측 부작용-전
     거부, 파서 티칭 에러, preamble/common 주입 경로, status 직렬화/렌더
     (레거시 행 무충돌 렌더 유지), start/follow/reply 상속, start 출력
     mode/contract posture 어서션.
   - epoch 요청/응답 검증 + **swapped-daemon 테스트**(normalized mode가 동일
     `delegate`인 케이스 포함) + 구 CLI×신 데몬 missing-epoch 부작용-전 거부.
   - 스킬 3+1종 리포 스킬 밸리데이터 통과.
   - 라이브 스모크 2건: (a) 의도적으로 non-trivial한 ro delegate brief —
     evidence에 내부 리뷰어 호출, fresh-context/read-only 자세, verdict,
     라운드 수, 최종 decision surface가 기록되는지 검증; (b) trivial brief +
     명시적 리뷰 면제 — 면제 경로 실증.
6. **마이그레이션**(운영자 수동): `meight list --all-repos --json`에서
   `starting`/`running`/`needs_input` 행 0 확인 → non-force `meight shutdown`
   → 재시작은 LaunchAgent 로드 여부로 분기: 로드됨 = `meight launchd install
   --load` 안전 이전 경로(bootout --wait, 신 PID/socket 소유권 검증), 미로드 =
   일반 기동 → `meight ping` `capabilities=mode4` + PID/socket identity 확인 →
   throwaway ro worker/delegate 스모크(위 5의 라이브 스모크) → 실제 디스패치.
7. **decision record**: `decisions/2026-07-16-worker-delegate-split.md`.
   2026-07-14-mode-axis-collapse.md의 "worker 계약 = delegate 단일 조합" 상정
   부분을 supersede (모드 축 자체와 fail-closed 설계는 존속). 구 기록에
   supersession 포인터 추가.
8. **완료 후**: 문서 전파 포함 전체를 커밋/푸시 (스킬 밸리데이터 + 테스트
   green 전제).

## Non-goals

- mode-파생 디폴트(model/effort/fast/sandbox/report) 도입 — 별도 워크스트림.
- 공유 report/QUESTION/evidence/sandbox/git 규범의 내용 변경 (라우팅 열거
  갱신만 허용).
- mate 프로토콜(design/review 계약 본문) 변경.
- `delegated` alias의 의미 변경(delegate에 유지). `worker` alias는 추가하지
  않음(정식 모드명).

## Risks / Mitigations

- 기존 저장된 `--mode delegate` 명령의 침묵 의미 변경: 전수 문서/예시
  인벤토리 갱신 + start 출력 contract posture 가시화 + delegate 계약의 금지
  라우트 fail-closed reroute. money-path dispatcher 사인오프 게이트는
  delegate에서도 불변.
- same-token downgrade(TOCTOU): epoch handshake + swapped-daemon 테스트로
  차단 (Success Criteria 3).
- best-effort interrupt는 소켓 연속 장애 시 클린업 미보장 — 단 silent
  success는 불가능(항상 비정상 종료). 잔여 리스크로 수용.
- 데몬 재시작 필요: 드레인 가드 + LaunchAgent 분기 절차 준수 (Changes 6).
