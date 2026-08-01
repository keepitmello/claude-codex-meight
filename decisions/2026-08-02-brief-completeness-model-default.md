# worker 기본 모델을 브리프 완결성 축으로 선택할 것인가

DATE: 2026-08-02 · FORK: user-decided during dispatcher-side policy edit

REFERENCE: `decisions/2026-07-29-difficulty-answered-with-a-stage.md`는 난이도에
단계를 추가하고 worker `sol`을 `medium`에 고정한다는 결정을 담고 있으며,
그 기록은 수정하지 않는다.

BACKGROUND: 07-29의 기본축은 실행 비용을 우선해 worker를 `luna max`로 두는
방향이었다. 이번 결정은 작업 전체의 계약·범위·증거가 명확한지에 따라 모델을
고르는 새 축을 추가하고 기본 선택을 반대로 정렬한다.

DECISION:

1. worker 기본은 `sol medium`, Fast off다. 코드 기본값과 dispatch echo가 이
   선택을 반영한다.
2. 브리프가 작업 전체의 계약(수용 기준)·범위(파일/디렉토리 경계)·증거(검증
   방법)를 완결적으로 담으면 디스패처가 `--model luna`를 명시 선택한다.
   CLI는 명시 모델에 맞춰 `luna max`와 Fast를 함께 해소한다.
3. Fast와 effort를 명시한 플래그는 언제나 모델별 재선택보다 우선한다. `--model`
   생략 또는 불완전 브리프의 worker는 `sol medium`에서 레포 이해·탐색과 숨은
   blocker 판단을 맡는다.
4. 난이도 대응은 `sol` mate 플랜 → 동결 → 완결 브리프 → worker 구현이라는
   단계 추가를 유지한다. worker `sol`은 `medium`에 고정하고 `sol high`는 mate
   자리로 둔다. 실패 비용 승급과 돈 경로 sign-off·작업 전 에스컬레이션 게이트는
   새 기본 선택과 독립된 축으로 유지한다.

EVIDENCE: `sol medium`은 SWE-Atlas-QnA 40 대 `luna max` 33으로 레포 이해·탐색과
숨은 blocker 판단에 강하다. `luna max`는 종합 59 / DeepSWE 63 / QnA 33 / $1.57로
실행·수렴을 제공하고 `sol medium`의 $2.99 대비 비용이 1/1.9다. 근거 수치는
`skills/meight/references/model-routing.md`에 고정한다.

REVISIT WHEN: (a) `sol medium` 기본 운용에서 비용이 체감 문제로 확인되거나,
(b) 완결 브리프에서 선택한 `luna`의 `QUESTION:` 품질에 대한 실측이 생기거나,
(c) 브리프 완결성 판정이 반복적으로 잘못 라우팅된다는 운영 증거가 쌓일 때.

STATUS: adopted.
