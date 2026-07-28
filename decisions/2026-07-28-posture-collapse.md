# 4모드를 mate/worker 2자세로 접고 샌드박스 강제를 걷어낼 것인가

DATE: 2026-07-28 · FORK: user-decided after dispatcher-side analysis

BACKGROUND: 07-16 worker/delegate split 이후 축은
`--mode design|review|worker|delegate` 네 모드였다. 사용자가 디스패처 관점의
비용을 제기했다: 디스패치마다 4분류를 강제하는 것 자체가 인터페이스 세금이고,
역할 경계 지시("구현 금지"/"리뷰 금지")가 워커를 침묵 실행자로 만든다. 코드
조사 결과 데몬 실행 경로에 모드 분기는 0개였고(모드 = CLI 기본값 5개 + 스킬
경로 1개), design/review는 이미 같은 스킬 파일을 공유했다. 진짜 축은 역할이
아니라 "생각/판단 vs 실행" 둘뿐이었다.

DECISION:

1. 축을 `--mode mate|worker` 2자세로 접는다. `--mode` 필수 정책(07-03)은
   유지. 구 이름 `design`/`collab`/`collaborative`/`review` → mate,
   `delegate`/`delegated` → worker 별칭으로 흡수 — 손가락 관습과 기록된
   status 행이 그대로 동작한다.
2. 기본값: mate = `sol medium, text, no-fast`; worker = `luna xhigh, decision,
   fast`. mate effort는 medium이 기본이고 어려운 문제만 high/xhigh로 올린다.
   verdict 인코딩이 필요한 플랜 리뷰는 `--report decision`을 명시한다.
3. 샌드박스 강제를 걷어낸다 — 두 자세 다 기본 `full`. read-only는 브리프
   지시로 대체한다(사용자 결정: 지시만으로 read-only가 지켜지고, 샌드박스
   강제가 검증 작업을 불편하게 한다). `--sandbox` 플래그는 수동 선택용으로
   남는다.
4. worker 계약을 팀원으로 재작성한다: 자기 리뷰 소유(비자명 작업은 내부
   fresh-context 리뷰어 스폰 가능, 2라운드 캡), `QUESTION:`/`better-direction`
   반문, `risks[]` 관찰 보고. 구 delegate의 Forbidden Routes는 "작업 전
   에스컬레이션 게이트" 목록으로 worker 계약에 흡수된다.
5. 턴 도중 소통: (a) 워커 plan 스텝 전환의 실시간 출력 — 단, 같은 날
   AMENDMENT로 `--narrate` 옵트인으로 강등 (사용자 결정: 디스패처 컨텍스트에
   노이즈고, 배경 실행+통지 패턴에선 포그라운드로 지켜보는 주체가 없다 —
   사람이 터미널에서 지켜볼 때만 의미). (b) tool/approval 대기가
   15초(`TOOL_WAIT_GRACE_SEC`)를 넘으면 exit 3으로 표면화한다 — 전에는
   needs_input_source="tool"이 wait 루프에서 invisible해 타임아웃까지 걸렸다.
7. (AMENDMENT 2026-07-28) 디스패처 기본 패턴은 백그라운드 dispatch + 태스크
   통지다: `dispatch`/`reply`를 run_in_background로 던지고, 프로세스 종료
   (완료·실패·exit 3)가 통지로 디스패처를 깨우면 `result`를 읽고 필요시
   `reply`. 포그라운드 wait 서술은 사람용 터미널 사용법으로 강등.
   `--timeout 1800`은 안전망 체크포인트로, `--progress 300`은 파일 전용
   heartbeat로 유지 (긴 세션은 `--progress 0`).
6. epoch를 `posture2`로 올린다. 검증·에코 메커니즘은 mode4와 동일.

REVISIT WHEN: 브리프 지시만으로 read-only가 지켜지지 않는 실측 사례가
lessons.md에 쌓이면 3을 재검토한다. 플랜 리뷰에서 `--report decision` 명시
누락이 반복되면 2의 mate report 기본값을 재검토한다.

STATUS: adopted. Supersedes the four-mode axis of
`2026-07-16-worker-delegate-split.md` (그 문서의 계약 내용 중 내부 리뷰어와
게이트 목록은 worker 스킬로 이전되어 살아 있다).
