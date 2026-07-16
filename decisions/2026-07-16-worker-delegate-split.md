# worker와 delegate를 참여형 구현/전권 위임 운영 모드로 분리할 것인가

DATE: 2026-07-16 · FORK: user-decided after anchored plan review

BACKGROUND: 2026-07-14 mode-axis collapse는 실사용 조합을 세 개로 보고 worker
계약을 delegate 단일 조합으로 접었다. 계약 분리 과정에서 구 delegate의
핵심이던 dispatcher 기술 맥락 배제와 내부 독립 리뷰도 함께 사라져, delegate와
일반 bounded 구현을 구분할 운영 의미가 없어졌다.

DECISION (PLAN mode4-worker-delegate-split v2,
SHA-256 `430b9f83d72855ba1befb97adb26fc40359bbb3893377e184a5d92234dccbfc3`):

1. 필수 단일 축을 `--mode design|review|worker|delegate` 네 모드로 확장한다.
   `collab`/`collaborative`는 design, `delegated`는 delegate 별칭으로 유지하고
   worker 별칭은 만들지 않는다.
2. `worker`는 현행 참여형 구현 계약이다. 디스패처가 별도 review 세션,
   full-diff 읽기, 최종 사인오프를 소유하며 plan-governed·hard-gated 구현의
   기본 모드다.
3. `delegate`는 디스패처가 기술 맥락에서 빠지는 전권 위임 계약이다. 구현과
   검증, fresh-context read-only 내부 리뷰(비자명 작업 기본, 최대 2라운드)를
   end-to-end로 소유한다. hard gate, money path, 공개 계약, 영속 마이그레이션,
   frozen dispatcher review chain은 진행하지 않고 worker reroute로 fail-closed
   한다.
4. start/follow 프로토콜 epoch를 `mode4`로 올린다. 요청은 epoch를 명시하고,
   데몬은 어떤 부작용보다 먼저 검증하며, 성공 응답은 normalized mode+epoch를
   원자적으로 에코한다. CLI는 둘 다 검증하고 불일치 시 best-effort interrupt
   후 비정상 종료한다.
5. `skills/meight-common/CONTRACT.md`는 공유 report/QUESTION/evidence/sandbox/
   git 규범의 단일 소스로 유지한다. mate, worker, delegate 스킬은 각 모드 고유
   규범만 소유한다.

SUPERSESSION: `2026-07-14-mode-axis-collapse.md`의 "worker 계약 = delegate 단일
조합" 및 3모드 열거를 대체한다. 그 기록의 단일 필수 mode 축, 별칭,
fail-closed 설계, mate/worker가 모델 정체성이 아니라는 결정은 유지한다.
`2026-07-14-mate-worker-role-split.md`의 계약/모델 직교와 공유 SSOT 분리도
유지하며, worker/delegate 운영 자세만 이 기록이 더 구체화한다.

OPERATOR GATE: running daemon 재시작과 non-trivial/trivial-waiver delegate
라이브 스모크는 구현 세션에서 실행하지 않는다. 전역 드레인, non-force
shutdown, LaunchAgent 로드 여부 분기, 새 PID/socket 및 mode4 확인 뒤 운영자가
수동 수행한다.

STATUS: adopted
