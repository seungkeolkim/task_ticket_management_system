# Content, comment, mention, and attachment decisions

| ID | 날짜 | 상태 | 결정 | 근거·영향 |
|---|---|---|---|---|
| CNT-001 | 2026-09-16 | SUPERSEDED | 티켓 설명과 댓글은 같은 Markdown 원문 저장 계약과 viewer를 사용한다. | CNT-008로 대체됨. 설명과 댓글이 같은 계약을 사용한다는 원칙은 유지한다. |
| CNT-002 | 2026-09-16 | SUPERSEDED | Markdown raw HTML은 비활성화하고 렌더링된 HTML에도 allowlist sanitizer를 적용한다. | CNT-008로 대체됨. 임의 HTML을 원본으로 저장하지 않고 파생 HTML을 sanitize하는 원칙은 유지한다. |
| CNT-003 | 2026-09-16 | DECIDED | 멘션은 본문의 표시 문자열만 신뢰하지 않고 원본과 대상 user ID를 가진 별도 row로 저장한다. | 표시 이름 변경 후에도 대상을 유지하고 같은 원본·대상의 미확인 멘션 중복을 막는다. |
| CNT-004 | 2026-09-16 | DECIDED | 첨부파일 메타데이터는 DB, 실제 blob은 storage interface 뒤의 mount directory에 저장한다. 다운로드는 공개 static 경로가 아니라 프로젝트 권한을 검사하는 endpoint를 통한다. | 파일 저장소 교체 가능성과 프로젝트 격리를 유지한다. |
| CNT-005 | 2026-09-16 | DECIDED | 기본 파일당 제한은 25MB이며 확장자와 MIME type을 함께 검증하고 실행·script 파일을 차단한다. 제한과 allowlist는 외부 설정으로 바꿀 수 있다. | 일반 문서 업무를 지원하면서 위험 파일과 무제한 업로드를 차단한다. |
| CNT-006 | 2026-09-16 | DECIDED | 댓글 삭제는 soft delete한다. 첨부파일 삭제는 즉시 접근을 차단하고 기본 30일 후 실제 blob을 영구 삭제하며 기간은 외부 설정으로 조정한다. | 감사 가능성과 실수 복구 기간을 확보한다. |
| CNT-007 | 2026-09-17 | DECIDED | 삭제된 댓글 본문은 원본 row에 유지하고 일반 조회에서 제외한다. 멘션 원본은 티켓 설명 또는 댓글 FK로 식별하고 제거된 멘션은 `removed_at`으로 구분한다. 첨부파일은 blob 삭제 성공 전 메타데이터가 사라지지 않도록 원본의 물리 삭제를 FK RESTRICT로 막는다. | NULL 댓글을 가진 설명 멘션에도 중복 방지를 적용한다. 티켓 purge는 파일 삭제·첨부 메타데이터 정리를 먼저 실행한 뒤 댓글과 티켓을 정리해야 한다. |
| CNT-008 | 2026-09-26 | DECIDED | 티켓 설명과 각 댓글은 동일한 `body_schema_version=2` 계약의 독립 Tiptap JSON document로 저장한다. 허용 범위는 제목, 굵게·기울임·밑줄·취소선, 제한된 글자 크기·색상, 중첩 bullet·ordered list, task list, 인용, 코드, 링크, 표와 내부 attachment image다. 글꼴과 표 셀 배경색은 초기 필수가 아니다. 임의 HTML은 원본으로 저장하지 않으며 sanitized HTML과 plain text는 파생 데이터다. | Confluence와 유사한 구조화 편집을 제공하면서 저장 포맷을 editor UI와 분리한다. 서버는 허용 node·mark·attribute, 크기·깊이, URL과 내부 참조를 검증하고 렌더링 결과에도 allowlist sanitizer를 적용한다. |
| CNT-009 | 2026-09-26 | DECIDED | Tiptap은 에디터와 문서 구조에만 사용한다. 티켓 댓글·멘션·첨부파일·optimistic locking·변경 이력·감사 로그는 기존 애플리케이션 domain에서 직접 구현한다. inline comment와 Tiptap Cloud·협업·댓글·version history는 사용하지 않는다. image node는 base64나 임의 외부 URL 대신 권한 검사를 거치는 내부 attachment ID를 참조한다. | 프로젝트 권한과 transaction·보존 정책을 서버의 단일 기준으로 유지하고 외부 서비스 종속성을 만들지 않는다. 브라우저 undo/redo는 저장 전 편집 편의 기능일 뿐 업무 이력이 아니다. |
| CNT-010 | 2026-09-26 | DECIDED | Tiptap JSON만 DB에 저장하고 파생 HTML과 plain text는 cache하지 않는다. 화면 DTO를 만드는 service에서 sanitized HTML을 생성하고, 목록·대시보드처럼 HTML이 필요 없는 경계에서는 plain text만 한 번 추출한다. | 원본과 cache의 transaction 일관성 및 재생성 migration 비용을 피한다. 실제 조회 부하가 확인되기 전에는 파생 저장소를 추가하지 않으며, 이후 cache가 필요하면 JSON과 같은 transaction에서만 갱신하는 별도 결정을 기록한다. |

## Open decisions

- 운영 환경의 전체 첨부파일 저장 용량과 최종 확장자·MIME allowlist는 첨부파일 구현 전에 확정한다.
