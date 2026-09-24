# TossInvest MCP 보완 작업 목록

이 문서는 보안 감사와 에이전트 사용성 검토에서 확인한 보완사항을 추적한다.
아래 항목은 2026-06-19 기준으로 완료했고, 이후 릴리즈와 소스 보강 내용을 반영했다.

## 2026-09-24 — OpenAPI와 패키지 업데이트

- [x] Toss OpenAPI manifest를 v1.2.17로 갱신하고 36개 operation과 기존 REST contract
  fingerprint가 유지됨을 확인했다.
- [x] FastMCP 4.0.8, Uvicorn 0.53.0, Ruff 0.16.8과 지원 범위 내 최신 의존성으로 `uv.lock`을 갱신했다.
- [x] uv 0.12.18, setup-uv 10.2.0, QEMU 4.4.0, Buildx 4.4.1과 build-push 7.4.0으로
  실행 환경과 SHA 고정 GitHub Actions를 갱신했다.

## 2026-09-09 — MCP 업데이트와 안정성 보강

- [x] FastMCP 4.0.3과 MCP Python SDK 2로 업데이트하고 의존성 lock을 갱신한다.
- [x] MCP annotation을 SDK 2 필드명으로 전환하고 기존·sessionless 연결을 함께 검사한다.
- [x] 공식 OpenAPI 1.2.15의 REST contract fingerprint와 36 operations가 이전과 같음을
  확인한 뒤 manifest를 갱신한다.
- [x] 도구 호출·preview 등록·사용자 컨텍스트 확보를 공통 처리로 묶는다.
- [x] 사용 중인 사용자 컨텍스트를 캐시 만료·용량 정리에서 보호하고 취소 시 반환한다.
- [x] 늦게 도착한 만료 토큰 응답이 새 토큰을 삭제하지 않도록 수정한다.
- [x] 잘못된 OAuth 응답을 거부하고 오류 코드·응답 메타데이터에도 비밀값 제거를 적용한다.
- [x] 주문 전송 뒤 서버 오류·통신 오류·잘못된 응답은 상태 미확인으로 처리하고 재시도를
  막는 회귀 테스트를 추가한다.
- [x] Retry-After 대기 시간을 제한하고 HTTP 날짜 형식을 지원한다.
- [x] 승인 시도 제한기를 별도 모듈로 옮기고 만료된 승인·접속자 기록을 정리한다.

검증: pytest 114개, Ruff, mypy strict, 문서·Skill·OpenAPI 검사, dependency audit,
wheel·source build, 기본·거래 Compose 검증과 가짜 API를 사용하는 Docker E2E를 통과했다.

## P0 — 실행 안전성과 설정 일관성

- [x] `TOSSINVEST_APPROVAL_TOKEN_SHA256` 설정 검증 오류를 수정하고 거래 모드 테스트를 복구한다.
- [x] 서버 `.env`와 컨테이너 환경에서 Toss 키와 계좌값을 제거한다.
- [x] 요청 헤더 기반 인증 컨텍스트와 자격 증명 fingerprint별 격리를 적용한다.
- [x] 승인 토큰은 원문이 아닌 SHA-256 해시만 MCP 클라이언트가 전달하도록 통일한다.
- [x] 시장가 주문과 주문 정정의 금액 제한을 보수적으로 계산한다.
- [x] 승인 후 주문 실행 직전에 가격·환율·잔고·주문 상태와 한도를 다시 검증한다.
- [x] 승인 페이지에 실패 횟수 제한과 요청 속도 제한을 적용한다.
- [x] 공개 평문 HTTP를 거부하고 HTTPS 응답에 HSTS와 `no-store`를 적용한다.
- [x] upstream 응답·오류·로그의 인증 및 계좌 필드를 redaction한다.

## P1 — MCP 에이전트 사용성

- [x] 모든 MCP 도구에 `readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint` annotation을 지정한다.
- [x] 도구 입력에 종목, 주문 수량·금액·가격, 날짜와 상태의 의미를 설명한다.
- [x] 공통 응답 메타데이터와 주문 미리보기·실행 결과의 구조화된 출력 스키마를 제공한다.
- [x] 서버 instructions에 조회 우선, 외부 승인, 쓰기 재시도 금지 규칙을 명시한다.
- [x] 조회 전용 Skill과 거래 Skill을 분리해 불필요한 거래 지침 노출을 줄인다.

## P1 — 문서와 배포

- [x] 한국어·영문 README와 `.env.example`의 변수명과 생성 절차를 일치시킨다.
- [x] `README.ko.md` 중복 파일을 명확한 언어 안내 파일로 정리한다.
- [x] `PLAN.md`를 구현 계획이 아닌 현재 상태와 향후 작업을 나타내는 문서로 정리한다.
- [x] `SECURITY.md`에 위협 모델, 지원 버전, 비밀정보 경계와 사고 대응 절차를 추가한다.
- [x] `CODE_OF_CONDUCT.md`를 표준 행동강령 수준으로 보강한다.
- [x] Semantic Versioning 기반 GitHub Release, 배포 파일 checksum과 multi-architecture GHCR
  이미지 게시를 자동화한다.
- [x] README에 안정 버전 고정 설치와 GHCR 이미지 사용법을 추가한다.

## P2 — 자동 검증

- [x] Skill frontmatter와 내용 검증을 CI에 추가한다.
- [x] Markdown 로컬 링크·anchor·code fence 검사를 CI에 추가한다.
- [x] README와 `.env.example`의 환경변수 드리프트 검사를 CI에 추가한다.
- [x] MCP annotation과 비밀정보 비노출 회귀 테스트를 추가한다.
- [x] 전체 pytest, Ruff, mypy, dependency audit, OpenAPI drift, Docker 구성을 검증한다.

## 완료 검증

- 전체 pytest 통과
- Ruff check 및 format 통과
- mypy strict 통과
- 알려진 Python dependency 취약점 없음
- OpenAPI v1.2.17, 36 operations fingerprint 일치
- 기본 모드 28개 도구와 쓰기 도구 0개 확인
- 거래 모드 34개 도구와 쓰기 도구 3개 확인
- 기본·거래 Compose 구성 검증
- production Docker image build 및 `/healthz` 실행 확인
- `v0.1.1` GitHub Release와 amd64/arm64 GHCR 이미지 게시
