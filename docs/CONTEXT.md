# CONTEXT — 이어받는 에이전트/세션을 위한 현재 상태 (living document)

> 목적: 이 레포를 처음 여는 에이전트가 **이 문서 하나로** 현재 상태, 문서
> 지도, 미결 사항을 파악하게 한다. 상태가 바뀌는 작업을 끝낸 세션은 이
> 문서를 갱신할 것. (역사적 경위는 decisions/를, 운영 프로토콜은 skills/를
> 신뢰 — 충돌 시 그쪽이 이긴다.)
>
> LAST UPDATED: 2026-08-02 (worker 기본 라우팅을 브리프 완결성 축으로 정렬)
> 이전: 2026-07-28 (posture2 — 2자세 통합, 샌드박스 강제 제거)

## 현재 상태 스냅샷

- **운영 모델 최종형**: 단일 필수 축 `--mode mate|worker`. mate = 생각·판단
  상대(설계·진단·verdict 리뷰, 프로토콜은 브리프가 선택), worker = 자기
  리뷰까지 소유하는 실행 팀원. 구 4모드 이름은 별칭으로 흡수
  (design/collab/collaborative/review → mate, delegate/delegated → worker).
  계약은 `skills/meight-mate`, `skills/meight-worker`, 공유 계약은
  `skills/meight-common/CONTRACT.md`다. 샌드박스는 강제하지 않는다 —
  read-only는 브리프 지시.
- **파이프라인**: blind design(방향 fork, mate) → plan-review 루프(mate
  일반 텍스트, 최대 3라운드, PLAN.md 동결) → worker 구현(sol medium 기본,
  계약·범위·증거가 완결된 브리프는 `--model luna`로 max+Fast 선택) → 적대
  리뷰(mate, 2라운드 캡) → dispatcher 사인오프. 게이트는 작업 크기에 비례해
  생략 가능하되 절대 조용히는 불가.
- **난이도 대응 = 모델 승급이 아니라 단계 추가**: 어려우면 `sol` mate 플랜 →
  동결 → 계약·범위·증거가 완결된 브리프 → `luna max`+Fast 워커 구현이
  실행에 강한 조합. worker `sol`은 항상 `medium`이고 브리프에 남은 판단을
  드러낸다. reviewer는 `sol high`가 기본이고, 비리뷰 설계에서의 `sol high`만
  정말 어려울 때 사용자 확인 1회. 세션을 띄우면 어떤 모델·effort로 띄웠는지
  사용자에게 한 줄 보고.
- **모델 라우팅**: 첫 축은 브리프 완결성이다 — 수용 기준·파일/디렉토리
  범위·검증 방법이 완결되면 디스패처가 `--model luna`를 선택하고, 그 밖의
  worker는 `sol medium`에서 레포 이해와 숨은 blocker 판단을 맡는다. 실패 비용은
  독립 축으로 유지해 돈·데이터 손상, 비가역, 프로덕션 확산이면 필요한 승급과
  게이트를 적용한다. 돈 경로 sign-off와 worker 스킬의 작업 전 에스컬레이션
  목록도 별도 축이다 (경위: `decisions/2026-07-29-difficulty-answered-with-a-stage.md`).
- **effort 정책**: worker `sol`은 `medium`, 완결 브리프에서 명시한 `luna`는
  `max`+Fast다. `luna max`는 `xhigh` 대비 비용 +25%에 Coding Agent Index
  +4점이고, `sol medium`은 SWE-Atlas-QnA 40 대 33으로 레포 이해·탐색에서
  앞선다. reviewer는 `sol high`; 비리뷰 mate의 `high`는 진짜 어려운 것만
  (dispatcher 판단 + 사용자 확인). sol에 xhigh는 쓰지 않는다. 근거:
  `skills/meight/references/model-routing.md`.
- **세션 저장 정책**: `thread_source=subagent`는 analytics 메타데이터일 뿐
  앱 숨김 기능이 아니다. 모든 start는 `thread_ephemeral=true`; follow/reply는
  새 ephemeral thread에 brief·result·recent events의 bounded handoff를
  주입한다.
- **fail-closed 기계**: 데몬 경계 epoch `ephemeral3` 검증이 모든 start/follow
  부작용보다 앞선다. start/follow 성공 응답의 normalized mode+epoch를 CLI가
  함께 검증하고 불일치 시 interrupt 클린업한다. 레거시 status 행은 계속
  무충돌 렌더한다.
- **디스패치 패턴**: 디스패처는 dispatch/reply를 백그라운드 셸로 던지고 태스크
  통지로 깨어난다 (포그라운드 wait는 사람용). plan 스텝 실시간 내레이션은
  `--narrate` 옵트인. steer는 디스패처→워커 턴 중 주입. tool-wait 15초 초과
  시 exit 3 표면화.
- **테스트**: `tests/test_meight.py` 전체 unittest 진입점이 2자세, legacy
  alias, preamble, status/legacy, 상속, epoch, tool-wait 분류와
  swapped-daemon 회귀를 커버.
- **하루 만에 세 사이클을 돈 날**: v3 파이프라인 채택 → mate/worker
  `--role` 분리 → 반나절 만에 `--mode` 단일 축으로 통합. 경위 전체는
  decisions/ 참조.

## 문서 지도 (뭘 보러 어디로 가나)

| 알고 싶은 것 | 문서 |
|---|---|
| 운영 프로토콜 (dispatcher가 따를 규칙 SSOT) | `skills/meight/SKILL.md` |
| 세션 계약 (mate / worker / 공유) | `skills/meight-mate/SKILL.md`, `skills/meight-worker/SKILL.md`, `skills/meight-common/CONTRACT.md` |
| 왜 이 파이프라인인가 — 설계 경위·리서치·검증 기록 | `docs/2026-07-14-v3-pipeline-retrospective.md` (v3 채택 시점 기준; 이후 델타는 decisions/) |
| 외부 리서치 요약 (TRIP-workflow/jinn/codex-plugin-cc/aimee/clideck 채택·기각) | 회고 문서 §4 |
| 개별 결정의 양쪽 입장과 근거 | `decisions/` — mode-flag-required(07-03), consensus-pipeline-luna-promotion(+사용자 AMENDMENT 2건), mate-worker-role-split, mode-axis-collapse, brief-completeness-model-default(08-02) |
| 하네스 내부 설계·상태머신·하드닝 이력 | `ARCHITECTURE.md`, `SPEC.md` |
| 드롭인 오케스트레이터 프롬프트 | `CLAUDE.md`(Claude용), `AGENTS.md`(Codex용) |
| 운영 원장 (레포 **밖**, 글로벌) | `~/.meight/notes/lessons.md`(사이클 지표·교훈), `~/.meight/notes/preferences.md`(사용자 결정 적립 — 에스컬레이션 전 필독) |

## 설계 철칙 (짧은 판본 — 전문은 skills/meight/SKILL.md)

1. 소비자는 LLM 에이전트 — 정책은 기억이 아니라 하네스가 강제한다 (필수
   플래그 + 티칭 에러 + 데몬 경계 재검증).
2. 브리프 완결성이 worker의 기본 모델을 고른다. 실패 비용은 독립 축으로
   유지하며, 누락형 결함(동시성·보안·비가역)은 사후 리뷰보다 사전 라우팅과
   명시한 증거 계약으로 막는다.
3. 방향 fork는 blind로 (앵커링 방지), 방향 확정 후에만 anchored 루프.
4. verdict는 자신이 리뷰한 대상을 명시한다 — stale verdict는 폐기.
5. 게이트는 비례하되 생략은 절대 조용히 하지 않는다. 머니패스와 worker
   에스컬레이션 목록은 생략 불가.
6. 자동 학습보다 scorecard 먼저 — 지표 없이 규칙을 조이거나 풀지 않는다.
7. mate/worker는 세션 계약(자세)명이지 모델 정체성이 아니다. 실무 정렬:
   mate≈sol, worker 기본≈sol medium, 완결 브리프의 worker는 `luna max`+Fast를
   명시 선택할 수 있다. 완전 위임은 별도 모드가 아니라 worker 계약의 자기 리뷰
   + 브리프 스코프로 표현한다.

## 미결 사항 (다음 의사결정 대기)

- **terra 라우팅 — 결정 보류 중.** 현재 "기본 담당 없음, capability 폴백"은
  07-10 A/B(n=1, 적대리뷰 단일 표본)에 근거한 잠정 강등이다. 실전 데이터
  (luna→terra 승격 사례, capability별 성패)가 lessons.md에 쌓인 뒤 재결정할
  것 — 지금의 표는 확정이 아니다. 승격 규칙(luna→sol, luna→terra) 정교화도
  같은 이유로 defer.
- **`QUESTION:` 품질 baseline**: 어느 모델도 공개 실측이 없다 (HiL-Bench에
  luna row 없음, sol 수치도 ASK-F1이 아님). 하드게이트 목록을 걷어낸 지금
  워커 에스컬레이션에 더 의존하는데 그 품질을 모른다 — 로컬 관측 필요.
- **브리프 완결성 라우팅 튜닝**: 완결 브리프의 `luna` 선택과 불완전 브리프의
  `sol medium` 판단이 비용·품질 면에서 맞는지는 계속 측정한다. sol의 hidden-
  blocker 발견률, luna의 결함률·승격률·false-approve 지표가 기준선이다.
- **NEEDS_REWORK 3단 verdict**: plan-review 조기 탈출 신호 후보 — 도입 시
  plan 재승인 필요 (백로그).
- **verdict 인코딩의 스키마 1급 필드화**: 현재는 문서 규약(APPROVE⇒done/GO,
  REVISE⇒needs_decision/NO-GO). 측정 후 하드닝 후보.
- **P3 잔여**: best-effort interrupt는 데몬/소켓 연속 장애 시 클린업 미보장
  (silent success는 불가). 알려진 외부 버그: consult 스킬(로컬 도구)의
  packet builder가 첨부를 떨굼 — 리서치 패킷은 본문 인라인으로.

## 운영 메모

- 데몬은 meight.py 수정 후 재시작해야 새 코드 반영. epoch 재시작 절차(전역
  드레인 → non-force shutdown → LaunchAgent 로드 여부 분기 → 새 PID/socket 및
  capability(`ephemeral3`) 확인 → worker와 mate 2종 라이브 스모크)는 README
  "Upgrading" 섹션.
  non-force 가드가 타 세션 워커를 두 번 실제로 보호했다 — `--force` 금지.
- 스킬/독 파일은 프리앰블이 읽는 공유 자원 — 워커가 수정 중일 때 새 워커
  시작 금지.
- 하네스급 변경의 적대 리뷰 브리프에는 "meight.py 런타임과 대조"를 반드시
  포함 — 문서 간 정합 스윕만으로는 문서↔런타임 drift를 못 잡는다 (실증 2회).
