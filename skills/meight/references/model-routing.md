# 모델·effort 라우팅 근거

SKILL.md의 기본값 표가 왜 그 자리에 있는지. 기본값만 쓸 거면 이 파일은 필요 없다.

## 사다리와 비용

Artificial Analysis Coding Agent Index v1.3 (종합 / DeepSWE / SWE-Atlas-QnA / 태스크당 비용):

- `luna xhigh` 55 / 57 / 31 / $1.26
- `luna max` **59 / 63 / 33 / $1.57**
- `sol medium` 61 / 64 / 40 / $2.99

`xhigh`→`max`는 25% 더 써서 종합 4점과 DeepSWE 6%p를 산다 — 그래서 worker 기본값이
`max`다. 거기서 `sol medium`까지는 비용이 1.9배인데 종합은 2점뿐이라 한계수익이
떨어진다. `sol medium`이 확실히 앞서는 자리는 레포 이해·탐색(QnA 40 대 33)이고,
그게 판단이 걸릴 때 `sol`로 올리는 이유다.

전문: [`docs/2026-07-29-model-routing-evidence.md`](../../../docs/2026-07-29-model-routing-evidence.md)

## 난이도가 올라갈 때

첫 대응은 워커 브레인 승급이 아니라 **단계 추가**다: `sol` mate에게 설계·플랜을
받아 동결하고, 그 플랜을 브리프로 받은 `luna` 워커가 구현한다. 판단이 어려운 것과
실행이 어려운 것은 다른 문제고 대부분의 어려움은 앞쪽에 있다 — 좋은 플랜을 쥔
`luna max`는 대부분의 구현을 해낸다. 이게 가장 싼 조합이다.

worker를 `sol`로 올리는 건 그 다음 — 설계를 앞에 붙일 수 없거나, 플랜이 있어도
구현 자체가 `sol` 브레인을 요구할 때. **worker의 `sol`은 `medium`이다**: `high`와의
실측 차이가 작아서 코드 작업에 `high`는 값을 못 한다. `medium`으로도 안 풀릴 것
같으면 브레인이 아니라 설계가 부족한 것이니 mate 한 판을 앞에 붙인다.

`sol high`는 mate 자리다. plan·적대 리뷰의 reviewer 기본값이고, 리뷰가 아닌
설계에서는 정말 어려울 때만 사용자 확인 후. worker에는 쓰지 않는다. `xhigh`는
`sol`에 없다.

## 승급 판단 축

**그 작업이 실패했을 때 무슨 일이 일어나는지**로 판단한다: 돈·데이터 손상, 비가역,
프로덕션 확산이면 올리고 나머지는 `luna`. 작업의 이름은 신호가 약하다 —
동시성이든 마이그레이션이든 계약 설계든 경계가 분명하고 검증 가능하면 `luna`나
`sol medium`이 해낸다.

## 측정에서 나온 주의점

`medium`은 적대적 리뷰에서 severity를 과대 승격하는 경향을 보였다. verdict가 걸린
리뷰는 `high`가 낫고, `medium`은 설계 사고·스코핑에 맞는다.

## terra

기본 소유 영역 없음. capability-specific 이유와 측정 근거가 있을 때 `luna`
에스컬레이션을 받을 수 있다. baseline 전에는 승급 규칙을 가정하지 않는다.
