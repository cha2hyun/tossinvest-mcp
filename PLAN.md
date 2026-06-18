# TossInvest MCP 프로젝트 상태

## 목표

토스증권 공식 Open API를 Hermes Agent 같은 MCP 클라이언트에서 안전하게 사용할 수 있도록
조회 기능을 기본 제공하고, 주문 기능은 명시적 활성화와 별도 사람 승인 뒤에만 제공한다.

## 현재 구현

- Python 3.12, FastMCP, httpx, Pydantic과 uv 기반 Streamable HTTP 서버
- 토스증권 Open API v1.1.1의 전체 조회 operation
- OAuth2 client-credentials 발급, 메모리 캐시와 동시 갱신 방지
- 계좌 헤더 주입과 MCP 응답의 계좌 식별 정보 제거
- API 그룹별 rate limit과 조회 요청에 한정된 안전한 재시도
- 기본 조회 전용 실행과 명시적 `--dangerously-enable-trading` 거래 활성화
- 미리보기, 별도 사람 승인, 실행 직전 상태 재검증과 일회용 쓰기
- KRW/USD 설정 한도, 1억원 hard block과 보수적인 시장가 정책
- 주문 쓰기 자동 재시도 금지와 `order-state-unknown` 복구 지침
- MCP 인증, Origin 검사, Tool annotation과 구조화된 output schema
- non-root, read-only filesystem, capability 제거가 적용된 Docker Compose
- 조회·거래 workflow를 분리한 Hermes Skill
- Ruff, mypy, pytest, dependency audit, secret scan, OpenAPI drift와 Docker build CI

## 설계 경계

- 단일 worker와 단일 인스턴스를 전제로 preview 상태를 메모리에 저장한다.
- 서버 재시작 시 preview와 승인 상태는 모두 무효화된다.
- 호스트 관리자와 Docker daemon 접근자는 process 환경과 memory를 볼 수 있는 신뢰
  경계에 포함된다.
- 공식 sandbox가 보장되지 않으므로 CI와 자동 검증은 실제 주문을 실행하지 않는다.

## 유지보수

- 공식 OpenAPI 변경은 `scripts/update_openapi.py --check`로 감지하고 검토 후 manifest를
  갱신한다.
- 문서, 환경변수 예제와 Skill은 CI에서 의미적 드리프트를 검사한다.
- 보안과 에이전트 사용성 개선 내역은 [IMPROVEMENTS.md](IMPROVEMENTS.md)에서 추적한다.
- 라이브 주문과 관련된 변경은 인증, 승인, 한도, 재검증과 재시도 금지 회귀 테스트를 반드시
  포함한다.
