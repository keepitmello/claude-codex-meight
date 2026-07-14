# 계약 선택을 단일 모드 축(design|review|delegate)으로 접을 것인가

DATE: 2026-07-14 (심야) · FORK: user-decided (blind design은 사용자 지시로 중단)

BACKGROUND: 같은 날 도입된 --role mate|worker × --mode collab|delegate 2축이
"에이전트가 쉽게"라는 meight의 존재 이유와 긴장 (사용자 제기). 실사용 조합은
사실상 3개: mate+collab(설계), mate+delegate(리뷰), worker+delegate(구현).

DECISION (사용자 확정, 대화로 수렴):
1. 단일 필수 축 `--mode design|review|delegate`. --role 플래그 폐지 (수명 반나절).
   - design = mate와 같이 설계 (테크리드 느낌 — 사용자 프레이밍). blind
     design / anchored design이 구 blind/anchored consult를 대체 ("consult"는
     로컬 도구명과 충돌해 폐기, "read"안은 자명하지 않아 기각).
   - review = verdict-first 판정 (mate 계약 + 프리앰블에 리뷰 프로토콜 가이던스).
   - delegate = 순수 위임 (worker 계약, dispatcher는 PM/기획).
   - 별칭: collab/collaborative→design, delegated→delegate. "collab"은
     "design과 review는 협업 모드"라는 서사 형용사로만 생존.
2. mate/worker는 세션 계약명으로 존속 (모델 정체성 아님). 실무 정렬:
   mate≈sol, worker≈luna, sol은 하드게이트 구현 시 worker 계약으로. luna-mate
   조합은 구조상 가능하나 광고하지 않음 (사용자 결정).
3. role 시대의 fail-closed 기계 전부 개명 재사용: 데몬 경계 검증(부작용 전),
   capability 토큰 "role"→"mode3", start/follow 응답 mode echo 검증 + 불일치
   시 interrupt 클린업. 레거시 status 행(구 role 필드, collaborative/delegated
   값) 무충돌 렌더.
4. decision record 템플릿의 구 "MODE: consensus|delegation" 필드는 canonical
   모드 축과 충돌하는 제2 분류라 `FORK:` 필드로 개명 (mode3 적대 리뷰 지적).

VERIFICATION: 구현 sol worker(GO, 18 tests), 신체제 첫 --mode review 적대
리뷰 2라운드(NO-GO→NO-GO 1건 잔존→dispatcher 수정+사인오프로 종결 — 리뷰
캡 소진 시 자동 3라운드 금지 규칙의 첫 적용). review 모드 라이브 스모크
통과(mate 스킬+리뷰 가이던스 주입, pid 40593 데몬 capabilities=mode3).
드레인 가드가 이번에도 타 세션 워커(arcaea)를 보호 — 데몬은 타 세션의
dispatch auto-start로 이미 신 코드 전환돼 있었음.

STATUS: adopted. supersedes the flag portion of
2026-07-14-mate-worker-role-split.md (계약 내용·fail-closed 설계는 존속,
선택 축만 role→mode로).
