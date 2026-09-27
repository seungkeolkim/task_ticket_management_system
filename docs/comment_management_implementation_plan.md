# 댓글 관리 기능 구현 계획

## 1. 목적

티켓 상세 화면에서 프로젝트 권한에 따라 구조화 댓글을 조회·작성·수정·soft delete할 수 있게 한다. 댓글은 티켓 설명과 동일한 Tiptap body schema v2 계약, HTML renderer와 sanitizer를 사용하며 댓글의 수명 주기와 감사 기록은 애플리케이션 service가 관리한다.

이번 작업은 댓글 관리 자체를 완결하는 데 집중한다. 멘션과 첨부파일의 실제 업로드·삭제 기능은 각각 후속 작업으로 분리하되, 댓글 본문과 기존 DB 관계가 후속 기능을 막지 않도록 경계를 유지한다.

## 2. 확정 정책

- 프로젝트 게스트는 삭제되지 않은 댓글을 읽을 수 있지만 작성·수정·삭제할 수 없다.
- 프로젝트 사용자와 프로젝트 관리자는 작성자와 무관하게 프로젝트 안의 모든 댓글을 작성·수정·soft delete할 수 있다.
- 시스템 관리자의 프로젝트 override 접근은 기존 프로젝트 권한 정책에 따라 감사 로그에 남긴다.
- 완료·취소 티켓에도 사후 기록을 위한 댓글 작성·수정·삭제를 허용한다.
- 비활성 프로젝트는 읽기 전용 보존 상태로 취급하여 댓글 쓰기를 차단한다.
- 휴지통 티켓은 일반 상세 조회 대상이 아니므로 댓글을 조회하거나 변경할 수 없다.
- 삭제는 `deleted_at`과 `deleted_by_id`를 기록하는 soft delete이며 삭제된 댓글 본문은 일반 조회에서 은폐하고 자리표시자로 반환한다.
- 원댓글에는 한 단계 대댓글을 등록할 수 있으며 대댓글 재중첩과 삭제된 원댓글에 대한 새 답글은 거부한다.
- 댓글 수정은 `expected_version`을 필수로 받고 SQLAlchemy optimistic locking과 함께 stale write를 차단한다.
- 댓글 생성·수정 요청에서 plain text가 공백이고 내부 attachment image도 없으면 빈 댓글로 판단하여 거부한다(CNT-011).
- 댓글 본문 원문이나 렌더링 HTML은 감사 로그와 시스템 로그에 기록하지 않는다.

## 3. 구현 범위

### 3.1 Schema와 DTO

- `CommentCreate`: `body_document`, 선택적 `parent_comment_id`
- `CommentUpdate`: `body_document`, `expected_version`
- `CommentDelete`: `expected_version`
- `CommentAuthorView`: 사용자 ID, 로그인 ID, 표시 이름
- `CommentView`: 댓글 ID, 부모 댓글 ID, depth, 삭제 여부, 작성자, 원문 document, sanitized HTML, schema version, version, 생성·수정 시각
- 상세 화면에서 필요한 댓글 목록은 원댓글 생성 순서와 각 원댓글의 대댓글 생성 순서로 안정 정렬한다.
- 모든 validation 함수와 DTO validator에는 역할을 설명하는 docstring을 작성한다.

### 3.2 Repository

- 프로젝트·티켓 scope와 membership 조건을 query 자체에 포함한다.
- 일반 조회는 삭제 댓글도 반환하되 service DTO에서 본문을 빈 document로 교체하고 삭제 자리표시자 상태를 제공한다.
- 단일 댓글 수정·삭제 조회는 `project_id`, `ticket_id`, `comment_id`를 모두 조건으로 사용한다.
- 작성자 정보를 batch 또는 join으로 조회하여 댓글 수에 비례하는 N+1 query를 만들지 않는다.
- repository 함수는 flush 또는 조회까지만 담당하고 commit하지 않는다.

### 3.3 Service

- 조회 service는 프로젝트 membership과 티켓 접근 가능 여부를 검증한다.
- 작성·수정·삭제 service는 프로젝트 사용자 이상의 write 권한과 프로젝트 활성 상태를 검증한다.
- Tiptap document는 기존 `validate_body_document`, `extract_body_document_text`, `iter_attachment_ids`, `render_body_document_html`을 재사용한다.
- attachment image가 있으면 같은 프로젝트·티켓에서 현재 사용할 수 있는 attachment인지 서버에서 다시 검증한다.
- 생성·수정·삭제와 감사 로그는 하나의 transaction으로 처리한다.
- 수정 요청이 현재 본문과 같으면 성공으로 처리하되 version과 감사 로그를 추가하지 않는다. 단, `expected_version` 충돌 검사는 no-op 판정보다 먼저 수행한다.
- `StaleDataError`와 무결성 오류는 기존 transaction context를 통해 사용자용 409 응답으로 변환한다.
- 주요 성공 지점은 안정적인 영문 event 이름과 댓글 ID·프로젝트 ID·티켓 ID만 INFO 수준으로 기록한다.
- 예상 가능한 권한·입력 오류는 stack trace를 남기지 않는다.

### 3.4 API와 Web UI

- API 경로는 티켓 하위 resource로 구성한다.
  - `GET /api/projects/{project_key}/tickets/{ticket_key}/comments`
  - `POST /api/projects/{project_key}/tickets/{ticket_key}/comments`
  - `PATCH /api/projects/{project_key}/tickets/{ticket_key}/comments/{comment_id}`
  - `DELETE /api/projects/{project_key}/tickets/{ticket_key}/comments/{comment_id}`
- 모든 쓰기 API와 HTML form은 기존 CSRF와 same-origin 검증을 적용한다.
- 티켓 상세의 임시 활동 안내를 댓글 목록과 작성 form으로 교체한다.
- 댓글 수정은 명시적인 편집 동작으로 editor를 열고 현재 version을 함께 제출한다.
- 삭제 성공 후 상세 화면으로 redirect하고 성공 메시지를 표시한다.
- 댓글 작성 API와 HTML form은 선택적 `parent_comment_id`로 원댓글에 한 단계 대댓글을 등록한다.
- 댓글·대댓글 등록, 댓글 수정과 삭제 HTML form은 공용 `data-confirm-message` 처리로 제출 전에 한 번 확인한다. 취소하면 요청을 전송하지 않는다.
- 입력 오류 시 사용자가 작성한 document를 form에 유지하되 오류 응답과 로그에는 본문 원문을 포함하지 않는다.

## 4. 공용 Tiptap editor 설정

현재 공용 editor의 `aria-label`은 `티켓 설명 편집기`로 고정되어 있다. 공용 editor가 설명과 댓글에서 같은 초기화 코드를 사용하도록 다음과 같이 일반화한다.

- editor container의 `data-rich-text-label` 값을 읽어 `aria-label`에 적용한다.
- 값이 없으면 `구조화 본문 편집기`를 기본값으로 사용한다.
- 티켓 설명 form은 `티켓 설명 편집기`를 명시한다.
- 댓글 작성 form은 `댓글 작성 편집기`를 명시한다.
- 댓글 수정 form은 `댓글 수정 편집기`를 명시한다.
- 필요한 경우 `data-rich-text-placeholder`도 같은 방식으로 받아 설명과 댓글의 안내 문구를 분리한다.
- `frontend/tiptap-editor.js`를 수정한 뒤 정적 bundle을 다시 생성하고 `app/web/static/tiptap-editor.js` 결과를 함께 검증한다.
- 한 페이지에 여러 editor가 존재해도 각 editor가 가장 가까운 form과 hidden payload만 갱신하는지 확인한다.

## 5. 빈 댓글 판정

빈 댓글 판정은 client UI가 아니라 service에서 최종 수행한다.

1. body schema v2 검증과 정규화를 수행한다.
2. `extract_body_document_text` 결과에서 공백을 제거한다.
3. `iter_attachment_ids`로 내부 attachment image 존재 여부를 확인한다.
4. plain text가 비어 있고 attachment ID도 없으면 `empty_comment` 오류로 거부한다.
5. 공백만 있는 paragraph, 빈 heading, 빈 list·table 구조는 모두 빈 댓글로 취급한다.
6. attachment image만 포함한 document는 유효한 댓글로 취급하되 attachment 권한 검증을 통과해야 한다.

## 6. 감사 로그와 시스템 로그

감사 action은 다음 이름을 사용한다.

- `comment.created`
- `comment.updated`
- `comment.deleted`

감사 detail에는 `project_id`, `ticket_id`, `comment_id`, 변경 전후 version을 기록한다. 본문 document, plain text와 HTML은 기록하지 않는다.

시스템 로그는 다음 event를 사용한다.

- `comment_created`
- `comment_updated`
- `comment_deleted`

정상 목록 조회는 HTTP access log와 중복되므로 별도 INFO 로그를 추가하지 않는다. 실패 stack trace는 예상하지 못한 예외를 service 경계에서 처리할 때 한 번만 남긴다.

## 7. 테스트 계획

### 7.1 단위 테스트

- 빈 document와 공백만 있는 document 거부
- attachment image만 있는 document 허용 및 attachment 검증
- 설명과 댓글의 동일 renderer·sanitizer 결과
- 댓글 DTO의 schema version, extra field와 version 검증
- 공용 editor label 기본값과 화면별 label 설정

### 7.2 통합 테스트

- 프로젝트 게스트의 댓글 목록 조회와 쓰기 거부
- 프로젝트 사용자·관리자의 작성자 무관 수정·삭제
- 시스템 관리자 override 조회·쓰기 감사 기록
- 다른 프로젝트 댓글 존재 은폐
- 완료·취소 티켓 댓글 작성 허용
- 비활성 프로젝트와 휴지통 티켓 댓글 쓰기 차단
- 삭제 댓글 원문 은폐·자리표시자 조회와 원본 row 유지
- 한 단계 대댓글의 프로젝트·티켓 scope, thread 정렬과 재중첩 거부
- stale `expected_version` 409 및 본문·감사 로그 rollback
- no-op 수정 시 version과 감사 로그 미증가
- 감사 저장 실패 시 댓글 변경 전체 rollback
- CSRF 누락·불일치 요청 차단
- HTML form 입력 오류 시 본문 유지와 민감한 진단 정보 은폐
- 댓글 수가 늘어도 정해진 범위 안에서 query 수가 유지되는지 검증

## 8. 제외 범위

- 멘션 후보 검색, 멘션 차이 반영과 읽음 처리
- 첨부파일 업로드·다운로드·삭제 service
- 댓글 영구 삭제 전용 명령
- 실시간 push, toast와 이메일 알림
- inline comment와 외부 Tiptap 협업 기능
- 댓글 변경을 별도 `TicketHistory` event로 기록하는 기능

## 9. 작업 순서

1. 공용 editor label·placeholder 설정 일반화와 frontend bundle 검증
2. 댓글 DTO와 repository 구현
3. 댓글 조회·작성·수정·soft delete service와 감사·시스템 로그 구현
4. API route와 CSRF 검증 연결
5. 티켓 상세 댓글 목록·작성·편집·삭제 UI 연결
6. 단위·통합 테스트와 Ruff 실행
7. Windows 전체 테스트와 Docker Linux 회귀 검증
8. 완료된 로드맵 항목과 관련 문서 갱신

## 10. 완료 기준

- 프로젝트 게스트·사용자·관리자와 시스템 관리자 override 정책이 서버에서 강제된다.
- 댓글이 티켓 설명과 같은 body schema v2로 안전하게 저장·렌더링된다.
- 빈 댓글, 다른 프로젝트 접근, stale write와 감사 실패가 데이터 변경 없이 거부된다.
- 삭제된 댓글은 일반 조회에서 원문이 은폐된 자리표시자로 남고 DB 원본과 삭제 주체·시각은 유지된다.
- 원댓글 아래 한 단계 대댓글을 등록할 수 있고 원댓글 삭제 후에도 기존 대댓글을 조회할 수 있다.
- 티켓 상세 화면에서 댓글 조회·작성·수정·삭제를 수행할 수 있다.
- 관련 단위·통합 테스트, 전체 pytest와 Ruff 검사가 통과한다.
- 실제 완료된 항목만 `IMPLEMENTATION_ROADMAP.md`에 반영한다.
