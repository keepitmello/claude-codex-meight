# sol의 역할 명칭과 Codex-측 스킬을 mate/worker로 분리할 것인가

DATE: 2026-07-14 (저녁) · MODE: consensus (plan-review loop 3 rounds → impl →
adversarial review 2 rounds)

READ A (dispatcher): v3 체제에서 sol은 공동설계자·승인권 리뷰어인데 "worker"
명칭이 실제 자리와 어긋남 (사용자 방향 제시). 제안: sol 역할 = mate(meight
어원), 스킬 3분할(meight-mate 신설/meight-worker 슬림화/공통은
meight-common/CONTRACT.md), 선택은 --role mate|worker required 플래그(모델과
직교 — sol도 하드게이트 구현 시 worker로 돎).

READ B (mate, plan-review 3라운드): R1 REVISE — 신 CLI vs 구 장기실행 데몬
경계에 fail-closed 부재(silent degrade), drain 없는 재시작이 needs_input
스레드 파괴, SPEC/README.ko 전파 누락, e2e 검증 매트릭스 부재. R2 REVISE —
drain은 repo-scoped list가 아니라 `list --all-repos` + non-force shutdown이어야
(전역 데몬), capability handshake 양방향 회귀 테스트 명시. R3 APPROVE.

구현(sol worker, xhigh): meight.py role 라이프사이클(경계 검증이 모든 부작용
앞, capabilities 광고, ROLE 컬럼, follow/reply 상속), 스킬 3분할(중복 normative
텍스트 0), 문서 8종 전파, 테스트 14개.

적대 리뷰(mate, 신체제 첫 mate 디스패치): R1 NO-GO — **ping-check와 start가
별개 요청이라 사이에 데몬이 구버전으로 교체되면 silent degrade (TOCTOU,
시뮬레이션으로 실증)** + precedence/SPEC/테스트 정밀도 P3 3건. 수정(sol
worker): start 응답의 role echo를 CLI가 검증, 불일치 시 best-effort interrupt
클린업 + 명확한 에러 + 비정상 종료; role 티칭 에러가 mode보다 우선(양 경계);
SPEC user-priority 정정; ROLE 셀 정밀 assertion. R2 GO (17 tests).

DECISION:
1. 역할 명칭: mate(도전·리뷰·컨설트) / worker(구현·검증). terra는 역할 아님.
   역할과 모델은 직교.
2. 스킬: skills/meight-mate/SKILL.md + skills/meight-worker/SKILL.md +
   skills/meight-common/CONTRACT.md (공유 계약 단일 소스). 프리앰블은 역할
   스킬 + 공통 계약을 함께 주입.
3. --role mate|worker required (티칭 에러, --mode와 동일 철학). 데몬 경계에서
   재검증(모든 부작용 앞), ping/runtime_status가 capabilities=["role"] 광고,
   CLI는 start 전 capability 확인 + start 응답 role echo 검증(fail-closed).
4. 마이그레이션 절차: `meight list --all-repos --json` 드레인 확인 → non-force
   `meight shutdown`(전역 활성 워커 가드) → 재시작 → ping capabilities 확인 →
   throwaway mate 스모크. (첫 적용에서 가드가 타 레포 활성 워커를 실제로
   막아냄 — 절차의 실효성 실증.)

잔여(비차단): best-effort interrupt는 데몬/소켓 연속 장애 시 클린업 미보장
(단 silent success는 불가능, 항상 비정상 종료). fix 코드의 데몬 측 반영은
다음 재시작 시(현 데몬은 role-aware, 신 CLI와 호환) — 재시작+스모크는
운영자 pending gate.

STATUS: adopted; flag mechanism superseded by 2026-07-14-mode-axis-collapse.md
(--role 폐지, --mode design|review|delegate로 통합 — 계약 내용과 fail-closed
설계는 존속)
