# Content, comment, mention, and attachment decisions

| ID | 날짜 | 상태 | 결정 | 근거·영향 |
|---|---|---|---|---|
| CNT-001 | 2026-09-16 | DECIDED | 티켓 설명과 댓글은 같은 Markdown 원문 저장 계약과 viewer를 사용한다. | 특정 editor 구현과 저장 데이터를 분리하고 설명·댓글 표현 차이를 없앤다. |
| CNT-002 | 2026-09-16 | DECIDED | Markdown raw HTML은 비활성화하고 렌더링된 HTML에도 allowlist sanitizer를 적용한다. | Markdown parser 설정만 신뢰하지 않고 XSS에 이중 방어를 적용한다. |
| CNT-003 | 2026-09-16 | DECIDED | 멘션은 본문의 표시 문자열만 신뢰하지 않고 원본과 대상 user ID를 가진 별도 row로 저장한다. | 표시 이름 변경 후에도 대상을 유지하고 같은 원본·대상의 미확인 멘션 중복을 막는다. |
| CNT-004 | 2026-09-16 | DECIDED | 첨부파일 메타데이터는 DB, 실제 blob은 storage interface 뒤의 mount directory에 저장한다. 다운로드는 공개 static 경로가 아니라 프로젝트 권한을 검사하는 endpoint를 통한다. | 파일 저장소 교체 가능성과 프로젝트 격리를 유지한다. |
| CNT-005 | 2026-09-16 | DECIDED | 기본 파일당 제한은 25MB이며 확장자와 MIME type을 함께 검증하고 실행·script 파일을 차단한다. 제한과 allowlist는 외부 설정으로 바꿀 수 있다. | 일반 문서 업무를 지원하면서 위험 파일과 무제한 업로드를 차단한다. |
| CNT-006 | 2026-09-16 | DECIDED | 댓글 삭제는 soft delete한다. 첨부파일 삭제는 즉시 접근을 차단하고 기본 30일 후 실제 blob을 영구 삭제하며 기간은 외부 설정으로 조정한다. | 감사 가능성과 실수 복구 기간을 확보한다. |

## Open decisions

- Markdown editor library와 지원 확장 집합은 설명·댓글 구현 전에 확정한다.
- 운영 환경의 전체 첨부파일 저장 용량과 최종 확장자·MIME allowlist는 첨부파일 구현 전에 확정한다.
- 삭제된 댓글 본문을 DB에 그대로 보존할지 별도 감사 snapshot으로 이동할지는 댓글 구현 전에 확정한다.
