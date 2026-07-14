# CONTEXT — 이어받는 에이전트/세션을 위한 현재 상태 (living document)

> 목적: 이 레포를 처음 여는 에이전트가 **이 문서 하나로** 현재 상태, 문서
> 지도, 미결 사항을 파악하게 한다. 상태가 바뀌는 작업을 끝낸 세션은 이
> 문서를 갱신할 것. (역사적 경위는 decisions/를, 운영 프로토콜은 skills/를
> 신뢰 — 충돌 시 그쪽이 이긴다.)
>
> LAST UPDATED: 2026-07-15 (mode-axis collapse 직후)

## 현재 상태 스냅샷

- **운영 모델 최종형**: 단일 필수 축 `--mode design|review|delegate`.
  design/review 세션 = mate 계약(`skills/meight-mate/SKILL.md`), delegate
  세션 = worker 계약(`skills/meight-worker/SKILL.md`), 공유 계약은
  `skills/meight-common/CONTRACT.md`. 프리앰블이 모드별 스킬+공유 계약을
  주입하고, review 모드에는 리뷰 프로토콜 가이던스가 추가로 붙는다.
- **파이프라인**: blind design(방향 fork) → plan-review 루프(최대 3라운드,
  PLAN.md 동결) → worker 구현(luna xhigh+fast 기본, failure-cost 하드게이트만
  sol) → 적대 리뷰(2라운드 캡) → dispatcher full-diff 사인오프. 게이트는
  작업 크기에 비례해 생략 가능하되 절대 조용히는 불가.
- **effort 정책**: luna=xhigh(+fast), sol=high 기본(재량 medium, xhigh는
  진짜 어려운 것만 — dispatcher 판단).
- **fail-closed 기계**: 데몬 경계 mode 검증(모든 부작용 앞), capability
  토큰 `mode3`, start/follow 응답 mode echo 검증 + 불일치 시 interrupt
  클린업. 레거시 status 행(구 role 필드/구 mode 값) 무충돌 렌더.
- **테스트**: `tests/test_meight.py` 18개 (mode 라이프사이클 매트릭스 +
  decision 라우팅 + echo/티칭에러 회귀).
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
| 개별 결정의 양쪽 입장과 근거 | `decisions/` — mode-flag-required(07-03), consensus-pipeline-luna-promotion(+사용자 AMENDMENT 2건), mate-worker-role-split, mode-axis-collapse |
| 하네스 내부 설계·상태머신·하드닝 이력 | `ARCHITECTURE.md`, `SPEC.md` |
| 드롭인 오케스트레이터 프롬프트 | `CLAUDE.md`(Claude용), `AGENTS.md`(Codex용) |
| 운영 원장 (레포 **밖**, 글로벌) | `~/.meight/notes/lessons.md`(사이클 지표·교훈), `~/.meight/notes/preferences.md`(사용자 결정 적립 — 에스컬레이션 전 필독) |

## 설계 철칙 (짧은 판본 — 전문은 skills/meight/SKILL.md)

1. 소비자는 LLM 에이전트 — 정책은 기억이 아니라 하네스가 강제한다 (필수
   플래그 + 티칭 에러 + 데몬 경계 재검증).
2. failure cost가 모델을 고른다. 리뷰는 확률 필터지 보장이 아니다 — 누락형
   결함(동시성·보안·비가역)은 사후 리뷰로 못 잡으니 사전 라우팅으로 막는다.
3. 방향 fork는 blind로 (앵커링 방지), 방향 확정 후에만 anchored 루프.
4. verdict는 자신이 리뷰한 대상을 명시한다 — stale verdict는 폐기.
5. 게이트는 비례하되 생략은 절대 조용히 하지 않는다. 하드게이트·머니패스는
   생략 불가.
6. 자동 학습보다 scorecard 먼저 — 지표 없이 규칙을 조이거나 풀지 않는다.
7. mate/worker는 세션 계약명이지 모델 정체성이 아니다. 실무 정렬: mate≈sol,
   worker≈luna, sol은 하드게이트 구현 시 worker로.

## 미결 사항 (다음 의사결정 대기)

- **terra 라우팅 — 결정 보류 중.** 현재 "기본 담당 없음, capability 폴백"은
  07-10 A/B(n=1, 적대리뷰 단일 표본)에 근거한 잠정 강등이다. 실전 데이터
  (luna→terra 승격 사례, capability별 성패)가 lessons.md에 쌓인 뒤 재결정할
  것 — 지금의 표는 확정이 아니다. 승격 규칙(luna→sol, luna→terra) 정교화도
  같은 이유로 defer.
- **luna 게이트 튜닝**: 하드게이트 조항의 적정선은 미검증 가정. luna 결함률·
  승격률·false-approve·게이트 생략 후 결함 지표가 기준선.
- **NEEDS_REWORK 3단 verdict**: plan-review 조기 탈출 신호 후보 — 도입 시
  plan 재승인 필요 (백로그).
- **verdict 인코딩의 스키마 1급 필드화**: 현재는 문서 규약(APPROVE⇒done/GO,
  REVISE⇒needs_decision/NO-GO). 측정 후 하드닝 후보.
- **P3 잔여**: best-effort interrupt는 데몬/소켓 연속 장애 시 클린업 미보장
  (silent success는 불가). 알려진 외부 버그: consult 스킬(로컬 도구)의
  packet builder가 첨부를 떨굼 — 리서치 패킷은 본문 인라인으로.

## 운영 메모

- 데몬은 meight.py 수정 후 재시작해야 새 코드 반영. 재시작 절차(드레인 →
  non-force shutdown → capability 확인 → 스모크)는 README "Upgrading" 섹션.
  non-force 가드가 타 세션 워커를 두 번 실제로 보호했다 — `--force` 금지.
- 스킬/독 파일은 프리앰블이 읽는 공유 자원 — 워커가 수정 중일 때 새 워커
  시작 금지.
- 하네스급 변경의 적대 리뷰 브리프에는 "meight.py 런타임과 대조"를 반드시
  포함 — 문서 간 정합 스윕만으로는 문서↔런타임 drift를 못 잡는다 (실증 2회).
