# TossInvest MCP 보완 작업 목록

이 문서는 보안 감사와 에이전트 사용성 검토에서 확인한 보완사항을 추적한다.
아래 항목은 2026-06-18 기준으로 완료했다.

## P0 — 실행 안전성과 설정 일관성

- [x] `TOSSINVEST_APPROVAL_TOKEN_SHA256` 설정 검증 오류를 수정하고 거래 모드 테스트를 복구한다.
- [x] `MCP_AUTH_TOKEN`과 `TOSSINVEST_CLIENT_SECRET`의 재사용을 서버 시작 단계에서 거부한다.
- [x] 승인 토큰은 원문이 아닌 SHA-256 해시만 서버에 저장하도록 예제와 문서를 통일한다.
- [x] 시장가 주문과 주문 정정의 금액 제한을 보수적으로 계산한다.
- [x] 승인 후 주문 실행 직전에 가격·환율·잔고·주문 상태와 한도를 다시 검증한다.
- [x] 승인 페이지에 실패 횟수 제한과 요청 속도 제한을 적용한다.

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

## P2 — 자동 검증

- [x] Skill frontmatter와 내용 검증을 CI에 추가한다.
- [x] Markdown 로컬 링크·anchor·code fence 검사를 CI에 추가한다.
- [x] README와 `.env.example`의 환경변수 드리프트 검사를 CI에 추가한다.
- [x] MCP annotation과 비밀정보 비노출 회귀 테스트를 추가한다.
- [x] 전체 pytest, Ruff, mypy, dependency audit, OpenAPI drift, Docker 구성을 검증한다.

## 완료 검증

- `43 passed`
- Ruff check 및 format 통과
- mypy strict 통과
- 알려진 Python dependency 취약점 없음
- OpenAPI v1.1.1, 21 operations fingerprint 일치
- 기본 모드 16개 도구와 쓰기 도구 0개 확인
- 거래 모드 22개 도구와 쓰기 도구 3개 확인
- 기본·거래 Compose 구성 검증
- production Docker image build 및 `/healthz` 실행 확인
