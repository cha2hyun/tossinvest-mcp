# TossInvest MCP

[English](README.md)

[토스증권 공식 Open API](https://developers.tossinvest.com/docs)를 Hermes Agent 등의 MCP
클라이언트에서 안전하게 사용할 수 있도록 만든 Docker 기반 MCP 서버입니다.

국내·미국 주식 시세, 종목 정보, 계좌, 보유 종목, 주문 내역을 조회할 수 있으며, 명시적으로
활성화한 경우에만 안전장치가 적용된 주문 도구가 노출됩니다.

> 토스증권의 공식 제품이 아닌 독립 오픈소스 프로젝트입니다. 투자 조언을 제공하지 않으며,
> 실행된 모든 주문의 책임은 사용자에게 있습니다.

## 주요 기능

- OAuth 2.0 Client Credentials 토큰 자동 발급 및 메모리 캐시
- 공식 Open API v1.1.1의 모든 조회 operation 지원
- API 그룹별 rate limit 및 조회 요청의 안전한 `429` 재시도
- 계좌번호를 모델에 노출하지 않는 고정 계좌 헤더 적용
- 기본적으로 주문 도구를 등록하지 않는 조회 전용 모드
- 생성·정정·취소의 2단계 미리보기와 2분짜리 일회용 확인
- KRW/USD 주문 한도와 1억원 이상 주문의 강제 차단
- 국내 시장가 주문을 공식 상한가 기준으로 보수적으로 검사
- Bearer 인증 및 Origin 검사가 적용된 Streamable HTTP MCP
- 보안 설정을 적용한 Docker Compose
- Hermes Agent 설정 예제와 거래 안전 Skill

## 빠른 시작

준비물:

- 토스증권 Open API `client_id`, `client_secret`
- Docker 및 Docker Compose

```bash
cp .env.example .env
openssl rand -hex 32
```

생성된 토큰과 토스증권 인증 정보를 `.env`에 입력하고 서버를 실행합니다.

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/healthz
```

MCP 주소는 `http://127.0.0.1:8000/mcp`입니다.

[`examples/hermes-config.yaml`](examples/hermes-config.yaml)의 설정을
`~/.hermes/config.yaml`에 추가하고, `~/.hermes/.env`에
`TOSSINVEST_MCP_AUTH_TOKEN`을 설정한 다음 확인합니다.

```bash
hermes mcp test tossinvest
```

함께 제공되는 Hermes Skill을 설치합니다.

```bash
mkdir -p ~/.hermes/skills/tossinvest
cp skills/tossinvest/SKILL.md ~/.hermes/skills/tossinvest/SKILL.md
hermes skills list | grep tossinvest
```

Skill 설치 후에는 새 Hermes 세션을 시작하세요.

## 환경변수

| 변수 | 필수 조건 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `TOSSINVEST_CLIENT_ID` | 항상 | — | 토스증권 Open API 클라이언트 ID |
| `TOSSINVEST_CLIENT_SECRET` | 항상 | — | 토스증권 Open API 클라이언트 secret |
| `TOSSINVEST_ACCOUNT_SEQ` | 계좌 도구 | — | 서버가 사용할 고정 계좌 sequence |
| `TOSSINVEST_ENABLE_TRADING` | 선택 | `false` | 주문 도구 등록 여부 |
| `TOSSINVEST_MAX_ORDER_KRW` | 주문 활성화 | — | 원화 주문 최대 금액 |
| `TOSSINVEST_MAX_ORDER_USD` | 주문 활성화 | — | 달러 주문 최대 금액 |
| `MCP_AUTH_TOKEN` | 항상 | — | MCP 연결용 Bearer 토큰 |
| `MCP_ALLOWED_ORIGINS` | 선택 | 빈 값 | 허용할 브라우저 Origin 목록 |
| `MCP_HOST` | 선택 | `0.0.0.0` | Compose 외 직접 실행 시 listen 주소 |
| `MCP_PORT` | 선택 | `8000` | Compose 외 직접 실행 시 listen 포트 |
| `MCP_PUBLISHED_PORT` | 선택 | `8000` | Docker Compose가 호스트에 공개할 포트 |
| `LOG_LEVEL` | 선택 | `INFO` | 서버 로그 레벨 |

`.env`는 절대 커밋하지 마세요. 인증 정보, 계좌번호, access token, 실제 API 응답도 저장소에
올리면 안 됩니다.

## 제공 도구

조회 도구:

- `get_stock_info`, `get_stock_warnings`
- `get_prices`, `get_orderbook`, `get_recent_trades`, `get_price_limits`, `get_candles`
- `get_exchange_rate`, `get_market_calendar`
- `list_accounts`, `get_holdings`
- `list_orders`, `get_order`
- `get_buying_power`, `get_sellable_quantity`, `get_commissions`

`list_accounts`는 원본 계좌번호와 account sequence를 제거하고 계좌 유형 및 서버에 설정된
계좌인지 여부만 반환합니다.

`TOSSINVEST_ENABLE_TRADING=true`일 때만 다음 도구가 추가됩니다.

- `preview_order` → `place_order`
- `preview_order_modification` → `modify_order`
- `preview_order_cancellation` → `cancel_order`

주문 실행에는 미리보기에서 반환된 `preview_id`와 정확한 확인 문구가 필요합니다. 미리보기는
2분 후 만료되며 한 번만 사용할 수 있습니다.

주문 전송 후 네트워크 연결이 끊겨 상태를 확정할 수 없으면 `order-state-unknown`을 반환합니다.
이 경우 자동으로 재주문하지 말고 주문 내역부터 확인해야 합니다.

## 개발

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run python scripts/update_openapi.py --check
```

## 보안

기본 Compose 설정은 `127.0.0.1`에만 포트를 공개합니다. 외부에 배포하려면 반드시 HTTPS
reverse proxy와 네트워크 접근 제한을 적용하세요. 주문 기능을 켜기 전에
[SECURITY.md](SECURITY.md)를 확인하세요.

## 라이선스

[MIT](LICENSE) — Copyright (c) 2026 cha2hyun
