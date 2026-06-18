# TossInvest MCP Server 구현 계획

## 기본 결정

- 토스증권 공식 Open API를 Hermes Agent에서 사용하는 오픈소스 MCP 서버로 구현한다.
- 라이선스는 MIT이며 저작권자는 `cha2hyun`이다.
- Python 3.12, FastMCP 3.4.x, httpx, Pydantic, uv를 사용한다.
- Streamable HTTP와 Docker Compose로 배포한다.
- 기본 주소는 `http://127.0.0.1:8000/mcp`이다.
- 기본 동작은 조회 전용이며 기준 명세는 토스증권 Open API v1.1.1이다.

## 구현

- OAuth2 토큰 자동 발급·캐시, 계좌 헤더 적용, Decimal 기반 금액 처리, API 그룹별 rate limit,
  조회 429 재시도, requestId 보존, 비밀정보 마스킹을 구현한다.
- 공식 시세·종목·시장·계좌·자산·주문 조회 API를 MCP 도구로 제공한다.
- 주문은 기본 비활성화하며 미리보기와 일회용 확인을 거쳐 생성·정정·취소한다.
- 주문 한도, 1억원 이상 차단, clientOrderId 멱등성, 계좌별 직렬 실행, 불명확한 네트워크
  실패의 재시도 금지를 서버가 강제한다.

## 배포 및 Hermes

- `/mcp`, `/healthz`, `/readyz`를 제공한다.
- MCP Bearer 인증, Origin 검사, non-root/read-only Docker 실행을 적용한다.
- Hermes 조회 도구 allowlist 예제와 거래 안전 절차를 설명하는 Skill을 제공한다.

## 오픈소스와 검증

- 영문·한글 README, MIT 라이선스, 기여·보안·행동강령 문서를 포함한다.
- Ruff, mypy, pytest, secret scan, OpenAPI 계약 검사, Docker build CI를 실행한다.
- SemVer 태그에서 `linux/amd64`, `linux/arm64` GHCR 이미지를 배포한다.
- CI에서는 실제 주문을 실행하지 않는다.

## Git 정책

- Author와 Committer는 `cha2hyun <cha2hyun.dev@gmail.com>`만 사용한다.
- 공동 작성자 또는 별도 작성자 목록을 추가하지 않는다.
