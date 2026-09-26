# 다음 세션 Tiptap 구조화 본문 구현 가이드

## 목적

다음 작업 세션은 Markdown v1 본문 계약을 폐기하고 self-hosted Tiptap 기반 구조화 본문을 실제 코드·DB·화면에 연결하는 작업부터 시작한다. 이 문서는 빠른 진입을 위한 handoff이며 제품 요구사항과 반복 적용할 정책의 최종 기준은 `REQUIREMENTS.md`, `IMPLEMENTATION_ROADMAP.md`, `docs/decisions/`다.

## 시작 상태

- 기준 브랜치: `main`
- 기준 commit: `6666936` (`Merge pull request #9`)
- Alembic head: `20260923_0003`
- 마지막 기록 검증: pytest 233개와 Ruff 통과. PR #9는 문서만 변경했으며 로컬 테스트를 다시 실행하지 않았다.
- 현재 저장 schema는 `Ticket.description`과 `Comment.body`의 Markdown v1 Text다.
- 확인 당시 로컬 영속 DB의 `tickets`, `comments`, `ticket_history`는 모두 0건이다.
- 실제 구현 migration도 대상 DB에서 세 테이블의 row가 0건인지 다시 검사해야 한다. 이 문서의 과거 확인 결과만 신뢰하지 않는다.
- frontend package manager와 JavaScript build pipeline은 아직 없다.
- 화면은 FastAPI·Jinja2·Vanilla JavaScript 구조다.

## 세션 시작 시 필수 확인

저장소 `AGENTS.md`와 그 안의 규칙을 우선 적용하고 아래 문서를 다시 읽는다.

1. `REQUIREMENTS.md`
2. `IMPLEMENTATION_ROADMAP.md`
3. `docs/decisions/README.md`와 인덱스의 모든 결정 문서
4. `docs/database_conventions.md`
5. `docs/logging_conventions.md`
6. `REFERENCE_IMPLEMENTATION.md`

특히 다음 결정을 구현 기준으로 사용한다.

- `ARC-013`: Tiptap package exact version 고정과 self-hosted bundle
- `CNT-008`: Tiptap JSON body schema v2와 허용 기능
- `CNT-009`: Tiptap의 책임 제한과 서버 domain 책임
- `DB-018`: Markdown v1 비호환 폐기와 zero-row preflight
- `DB-019`: SQLite 유지와 PostgreSQL 재검토 조건
- `UI-015`: 초기 editor toolbar 범위

## 확정된 범위

### 본문 계약

- 티켓 설명과 각 댓글은 서로 독립된 Tiptap JSON document다.
- 애플리케이션 본문 계약은 `body_schema_version=2`다.
- Tiptap package 버전과 본문 schema version은 별개다.
- JSON 원본만 canonical data다.
- sanitized HTML과 plain text는 JSON에서 만든 파생 데이터다.
- 임의 HTML을 원본으로 저장하지 않는다.
- Markdown v1 dual-read, converter와 legacy 보존 컬럼은 만들지 않는다.
- 기존 Alembic revision을 수정하지 않고 새 revision을 추가한다.

### Tiptap 사용 범위

- Tiptap core와 필요한 open-source extension만 사용한다.
- Tiptap은 editor UI와 document structure에만 사용한다.
- Tiptap Cloud, CDN, collaboration, inline comment, comments service와 version history는 사용하지 않는다.
- 브라우저 undo/redo는 저장 전 편집 편의 기능이며 업무 변경 이력이 아니다.
- 티켓 댓글, Mention row, Attachment, optimistic locking, TicketHistory와 AuditLog는 Python application이 직접 관리한다.

### 초기 편집 기능

- 제목
- 굵게, 기울임, 밑줄, 취소선
- 제한된 글자 크기와 색상
- 중첩 bullet list와 ordered list
- task list와 checkbox
- 인용
- inline code와 code block
- 링크
- 표
- 내부 attachment image node

글꼴 선택과 표 셀 배경색은 초기 필수 범위가 아니다. image node의 저장 계약은 정의할 수 있지만 실제 삽입 UI는 첨부파일 API가 연결될 때 활성화한다.

### 배포와 이관성

- `package.json`은 exact version을 사용하고 lock file을 commit한다.
- 공식 문서와 package metadata를 구현 시점에 다시 확인한 뒤 버전을 선택한다.
- build 단계에서 JavaScript·CSS bundle을 생성한다.
- 생성 bundle은 애플리케이션 image에 포함하고 FastAPI static 경로에서 제공한다.
- 운영 runtime에는 Node.js·npm을 포함하지 않는다.
- 운영 중 CDN이나 외부 Tiptap 서비스에 연결하지 않는다.
- SQLite를 MVP 기본 DB로 유지하고 이번 작업에서 PostgreSQL Compose service를 추가하지 않는다.

## 첫 구현 PR 권장 범위

첫 PR은 댓글까지 한 번에 확장하지 말고 **본문 기반과 티켓 설명 vertical slice**를 완성한다. PR이 merge된 뒤에도 기존 티켓 생성·편집·조회가 동작해야 한다.

1. frontend build 기반과 self-hosted Tiptap bundle을 구성한다.
2. 지원 node·mark·attribute의 versioned JSON 계약과 한국어 예시 fixture를 작성한다.
3. 서버의 JSON 구조·크기·깊이·node 수·text 길이·attribute·URL 검증을 구현한다.
4. Tiptap JSON에서 sanitized HTML과 plain text를 만드는 공통 service를 구현한다.
5. 새 Alembic revision에서 zero-row preflight 후 Ticket·Comment 본문 저장 구조를 v2 JSON으로 교체한다.
6. ORM, API DTO, TicketHistory snapshot 계약을 v2 document에 맞춘다.
7. 티켓 생성·편집 form에 Tiptap을 연결하고 hidden JSON payload로 서버에 전송한다.
8. 티켓 상세와 인라인 상세가 같은 renderer 결과를 표시하도록 연결한다.
9. no-op, optimistic locking, 변경 이력과 감사 로그의 기존 transaction 계약을 유지한다.
10. 관련 테스트와 문서를 갱신하고 실제 완료 항목만 로드맵에 체크한다.

댓글 작성·수정·soft delete, mention node 동기화와 첨부파일 upload는 후속 PR로 둔다. 다만 새 migration에서는 아직 비어 있는 Comment 본문 컬럼도 최종 v2 구조로 맞춰 다시 migration하지 않도록 한다.

## 데이터 모델 구현 지침

정확한 컬럼명은 기존 naming과 service DTO를 함께 보고 결정하되 이름만으로 원본과 파생값을 구분할 수 있어야 한다. 축약 이름은 사용하지 않는다.

권장 의미는 다음과 같다.

- 티켓 설명 원본: `description_document`
- 댓글 본문 원본: `body_document`
- 계약 버전: `body_schema_version`
- 필요 시 파생 HTML: `rendered_html`
- 필요 시 파생 평문: `plain_text`

파생값을 DB에 cache할지는 첫 PR에서 일관성 비용과 조회 성능을 비교해 결정한다. cache한다면 JSON 원본 저장과 같은 transaction에서만 갱신하고 원본 없이 독립 수정하지 않는다. cache하지 않는다면 목록·대시보드·보고서에서 반복 렌더링하지 않도록 plain text 추출 경계를 명확히 둔다.

초기 빈 document의 canonical JSON과 key 정렬·hash 규칙을 하나로 고정한다. JSON column에는 실행 가능한 code나 임의 HTML을 넣지 않는다. 전체 JSON을 교체하며 SQLAlchemy nested mutation 추적에 의존하지 않는다.

## migration 지침

- 기존 revision `20260917_0002`와 `20260923_0003`은 수정하지 않는다.
- 새 revision은 `tickets`, `comments`, `ticket_history` row 수를 먼저 확인한다.
- 하나라도 0이 아니면 자동 변환하거나 삭제하지 말고 명확한 오류로 중단한다.
- 사용자·조직·세션·감사·프로젝트·참여자 데이터는 보존한다.
- upgrade와 downgrade를 모두 구현한다.
- SQLite batch migration과 향후 PostgreSQL에서 같은 최종 metadata가 되도록 한다.
- downgrade는 v2 본문 row가 생긴 뒤 데이터 보존을 보장하지 않는 파괴적 rollback임을 명시하고 사전 백업을 요구한다.
- migration 이후 model metadata와 Alembic schema 일치를 검증한다.

## 보안 규칙

- client가 보낸 HTML을 신뢰하거나 그대로 `safe` 처리하지 않는다.
- 서버가 허용한 JSON node·mark·attribute만 받는다.
- 색상과 글자 크기는 제한된 allowlist를 사용하고 임의 CSS를 받지 않는다.
- 링크 scheme은 최소한 `http`, `https`와 필요한 내부 경로만 명시적으로 허용한다.
- event handler, script, iframe, 임의 style과 알 수 없는 data attribute를 제거한다.
- image node는 base64와 임의 외부 URL을 허용하지 않고 내부 attachment ID만 참조한다.
- attachment ID와 mention user ID는 저장할 때 현재 프로젝트 권한을 서버에서 다시 검사한다.
- serialized JSON 크기뿐 아니라 node 수, nesting depth와 전체 text 길이도 제한한다.
- 사용자 본문과 JSON payload를 시스템 로그에 남기지 않는다.

## 변경 이력 규칙

- 키 입력마다 TicketHistory를 만들지 않는다.
- 사용자가 저장한 서버 request 하나를 명시적인 변경 단위로 취급한다.
- `expected_version` 검사는 no-op 판단보다 먼저 수행한다.
- 본문이 실질적으로 같으면 ticket version, TicketHistory와 AuditLog를 추가하지 않는다.
- 변경된 본문은 기존 ticket field와 같은 transaction에서 before/after snapshot에 기록한다.
- Tiptap package의 internal transaction이나 undo stack을 업무 이력으로 저장하지 않는다.
- 본문 크기로 history가 과도하게 증가하는 문제가 확인되면 immutable content revision 분리를 별도 결정으로 기록하고 구현한다. 첫 PR에서 추측으로 추가하지 않는다.

## 첫 PR에서 제외할 항목

- 댓글 CRUD
- inline comment
- mention suggestion UI와 읽음 처리
- attachment upload·삭제·정리
- image paste·drop upload
- font family
- table cell background color
- Tiptap Cloud·collaboration·유료 extension
- PostgreSQL 전환과 Compose database service
- 보고서 Markdown 계약 변경

## 검증 항목

다음 세션의 구현은 문서 변경이 아니므로 테스트를 생략하지 않는다.

- 허용·금지 JSON node와 mark 검증
- 최대 크기·깊이·node 수·text 길이 경계
- 위험 URL, 임의 HTML·attribute와 XSS payload 제거
- JSON → HTML·plain text의 결정적 변환
- Tiptap editor 저장 → API → DB → 조회 → viewer round-trip
- 기존 티켓 권한, CSRF와 프로젝트 격리
- no-op과 stale `expected_version`
- TicketHistory와 AuditLog rollback
- zero-row migration 성공과 예상하지 못한 row가 있을 때 실패
- migration upgrade·downgrade와 model 일치
- Windows와 Docker Linux의 frontend build·Python test·Ruff

## 완료 기준

- 외부 네트워크 없이 애플리케이션이 editor bundle을 제공한다.
- 티켓 설명을 Tiptap에서 편집하고 v2 JSON으로 저장한 뒤 안전하게 조회할 수 있다.
- 서버가 허용하지 않은 문서 구조와 HTML·URL을 거부하거나 제거한다.
- 기존 티켓 권한·FSM·optimistic locking·이력·감사 transaction이 유지된다.
- Markdown v1 호환 code가 남지 않는다.
- 빈 DB와 기존 identity·project 데이터가 있는 DB에서 migration이 검증된다.
- 로드맵과 데이터 명세가 실제 구현 상태와 일치한다.
