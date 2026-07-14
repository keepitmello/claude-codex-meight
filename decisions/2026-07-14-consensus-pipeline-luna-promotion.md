# meight 운영 모델을 plan-review loop + luna 기본 일꾼 체제로 확장할 것인가

DATE: 2026-07-14 · MODE: consensus (anchored plan-review loop, 3 rounds)

READ A (dispatcher, fable): 레딧 필드 리포트(fable plans → sol plan-review loop →
luna implements → fable full-diff read → sol code review)를 흡수하되, 07-03
anti-anchoring 교훈과 양립시키기 위해 방향 fork는 blind consult 유지, 방향 확정
후에만 anchored plan-review 루프 진입. 초안은 luna 라우팅을 "plan이 pseudo-code급
일 때"로 제한했고 루프는 "harness 변경 없이 persistent thread"로 가정.

READ B (worker sol, anchored, 3 rounds): R1 REVISE — persistent-loop 전제가 현
구현과 충돌(일반 완료 턴은 thread 해제, meight.py:978-993; REVISE는
dispatcher-targeted QUESTION으로 끝내야 보존), 루프 상한 부재, pseudo-code 기준
측정 불가, plan freeze 부재. R2 REVISE — "center of gravity" 게이트는 물량 기준이라
오라우팅(작지만 acceptance-critical한 auth/migration 조각이 luna로 감); 기준은
failure cost여야 함. luna 확대가 terra의 기존 테이블 소유권과 충돌. R3 APPROVE.

DISAGREEMENT: 라우팅 게이트 기준(물량 vs 실패비용), terra 처우(step-heavy 유지 vs
기본 담당 해제). 사용자 중간 수정(pseudo-code 요구 드롭, luna 판단 허용 + QUESTION
승격, luna xhigh+fast로 grunt work 전면 확대)이 R1 P1 하나를 대체.

RESOLUTION: evidence + user amendment — 사후 리뷰는 누락 동작/누락 테스트를 못
잡는다는 논증(리뷰 그물의 구조적 한계)이 failure-cost 게이트를 지지. terra 우위는
lessons.md의 07-10 A/B에서도 재현 안 됨 → 근거 없는 기본 소유권 제거.

DECISION (v3):
1. 방향 fork = blind consult(불변). 방향 확정 후에만 anchored plan-review 루프.
2. 루프 역학: dispatcher가 plan 저작 → sol high 리뷰 → REVISE는
   dispatcher-targeted QUESTION으로 종료(thread 보존, reply로 다음 라운드),
   APPROVE는 terminal. 최대 3라운드, 라운드마다 new-risks/resolved-risks 분리
   기록. 3라운드 미승인 시 자동 재진입 없이 dispatcher가 residual-risk 승인 /
   targeted evidence read / user escalation 중 택1.
3. 승인된 plan은 PLAN.md + 버전으로 동결 — 구현·최종 리뷰의 계약. 범위 변경 시
   재승인.
4. 라우팅 게이트(failure-cost 기준): acceptance-critical한 부분이 concurrency,
   security, 공개 schema/API 계약 설계, 영속 데이터 마이그레이션, cross-cutting
   리팩터에 materially 의존하거나 실패가 돈/데이터 손상·비가역·고임팩트 프로덕션
   피해를 낳으면 sol로 하드 라우팅. 그 외 전부 luna xhigh(+fast) 기본. 일반
   엔드포인트 구현 = luna, API 계약 설계/진화 = sol. 읽기 전용 프로덕션 로그
   조사 = luna, 프로덕션 변이/수습 = luna 금지(머니패스는 기존 dispatcher
   sign-off 게이트 유지). luna 내부의 애매함은 QUESTION 승격으로 처리.
5. 모델 테이블: luna xhigh+fast = bounded 구현·수정·테스트·검증·로그 파기·
   브라우저/런타임 QA·computer use·탐색 기본. sol high/xhigh = 방향·plan 리뷰·
   적대 리뷰·하드게이트 구현. terra = 기본 담당 없음, capability 폴백 전용,
   실측 근거(lessons.md) 시 재승격 가능.
6. 리뷰 체인: luna 구현 → sol 적대 리뷰(계약=동결 PLAN.md, 최대 2라운드) →
   dispatcher full-diff 정독 + 직접 수정 + 최종 사인오프. dispatcher 수정이
   plan 범위 이탈이면 재계획/재리뷰, P1-fix 수준이면 계약 유지. 하네스급 변경은
   plan 단계와 최종 diff 단계 모두 Claude context-holding 리뷰 추가.
7. 지표(lessons.md): plan 라운드 수·revise 원인·luna→sol 승격률(재라우팅/luna
   시작 태스크, 일반 QUESTION은 별도)·발화한 하드게이트 조항·사후 결함
   (false-approve, 동일 릴리스 윈도우 기준 — 릴리스 없는 레포는 시간 폴백 정의
   필요). v1은 독트린으로만 출시(양 SKILL.md + README/ARCHITECTURE 동시 전파,
   구 sol-default/terra-browser 문구 제거 + 전 문서 모순 검색), 측정 후 하드닝.

잔여 리스크(sol 최종 반론): 라우팅은 dispatcher가 acceptance-critical 의존을
디스패치 전에 식별하는 데 의존 — sol plan 리뷰가 발화 조항(또는 "none—luna
eligible")을 명시 검증하는 백스톱을 겸한다.

AMENDMENT (2026-07-14, 사용자 결정, 같은 날):
- luna 리포트 계약에 rationale 의무화 — decision surface에 "plan과의 편차 +
  근거 + 의도적으로 하지 않은 것"을 명시. 리뷰어(동결 plan + 전체 레포 문맥
  보유)가 누락 동작을 탐지할 단서를 제공. unknown-unknowns 한계는 하드게이트가
  계속 커버하되, 지표 축적 후 게이트 완화를 재검토.
- 승격 축은 luna→sol 단일이 아님 — luna→terra 승격도 열어둠. 승격 규칙
  정교화는 실측 기준선 확보 후로 defer.
- 하네스/코어 수술 라우팅 변경: Claude fork → Codex sol (fable 비용이 가장 큼;
  fable은 오케스트레이션·아비트레이션·최종 사인오프 전담). 07-03 preference를
  대체.

AMENDMENT 2 (2026-07-14 밤, 사용자 결정):
- sol effort 기본은 high — xhigh는 진짜 고난도(대형 하네스 수술, 극도로 얽힌
  디버깅, 최고난도 설계)에만 예약. luna xhigh는 유지(저비용).
- 게이트 비례 원칙: plan-review 루프·적대 리뷰 등 파이프라인 게이트는
  dispatcher 판단으로 소규모·저위험·가역 작업에서 생략/축소 가능. 단 생략은
  절대 조용히 하지 않는다 — 사소하면 사용자에게 알리고, 애매하면 먼저 묻는다.
  failure-cost 하드게이트와 머니패스 사인오프는 생략 불가. 생략은 지표로 기록
  (생략 후 결함이 비례 기준을 조이는 핵심 신호).

STATUS: adopted (문서 전파는 미실행 — 다음 작업)
