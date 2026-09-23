# MVP 데이터 구조

이 문서는 ORM·DB 제약·입출력 계약·migration을 중심으로 설명한다. 현재 인증, 사용자·조직 기본 관리, 프로젝트 권한, 티켓 생성·조회·편집·상태 전이, 대시보드와 칸반 이동은 서비스·API·화면까지 연결되어 있고 티켓 쓰기는 변경 이력을 같은 transaction에 기록한다. 관계·휴지통·댓글·멘션 쓰기·첨부파일·저장 필터와 간트·보고서 실행은 아직 연결하지 않았다.
원본은 `app/models/`, 데이터 계약은 `app/schemas/contracts.py`, 최신 추가 revision은 `20260923_0003`이다.

## 요구사항과 저장 구조

| 요구사항 | 테이블 | 주요 구조 |
|---|---|---|
| 사용자·조직·인증·감사 | 기존 organizations, users, user_sessions, audit_logs | 초기 revision 유지. 같은 위치 조직 이름 고유 인덱스 추가 |
| 프로젝트·참여자 | projects, project_members | 변경하지 않는 project key, (project, user) 고유 제약, next_ticket_number, 게스트·사용자·관리자 역할 |
| 티켓·계층·일정 | tickets | project별 번호, 전역 표시 key, 유형·상태·중요도, 부모, 담당자, Markdown, 날짜, 순서, version |
| 관계·간트 선후행 | ticket_relations | 동일 project의 source/target, Related 정규형, Depends on 방향, dependency_kind, lag_days |
| 휴지통·복구 | ticket_deletion_batches + tickets | root_ticket_key, 삭제자·시각·purge_after·복구자·시각, ticket의 batch FK |
| 기간별 변경 이력 | ticket_history | ticket version, event/operation UUID, actor, UTC, before/after 상태, changes, schema version |
| 댓글 | comments | project/ticket FK, 작성자, Markdown, version, soft delete |
| 멘션 | mentions | project/ticket/comment FK, 대상·작성자, read_at, removed_at, 원본별 중복 방지 |
| 첨부파일 | attachments | project/ticket/comment FK, storage backend/key, 원본명·MIME·크기·해시, 삭제·purge 시각 |
| 개인·공유 필터 | saved_filters | project, owner, visibility, 이름, versioned JSON definition |
| 보고서 스킬 | report_skills, report_skill_versions | 논리 key, 작성자, 활성 여부, 버전별 지침·입출력 JSON Schema·기본값·해시 |
| 보고서 요청·범위 | report_runs, report_run_projects | 요청자, 스킬 버전, 기간·시간대·조건, 입력 snapshot/hash, 프로젝트 목록 |
| 실제 LLM in/out | report_attempts | 시도 번호, 로컬 모델·실행 설정, 실제 요청·원응답·검증된 결과, 실패·시간·token 수 |

총 19개 애플리케이션 테이블: 기존 4개 + 신규 15개. Alembic 관리 테이블은 별도다.

## DB와 서비스의 책임

- DB는 FK, 고유 제약, 코드 범위, 양수 버전·번호, 일정 순서, 진행률 범위와 삭제 필드 조합을 강제한다.
- 프로젝트 부모·관계는 `(project_id, ticket_id)` 복합 FK를 사용한다.
- 댓글 원본은 `(project_id, ticket_id, comment_id)`로 검사한다. 같은 프로젝트의 다른 티켓 댓글을 참조해도 거부된다.
- FK는 연결 무결성을 보장하며 사용자 접근 권한은 보장하지 않는다. 참여 권한·활성 여부는 모든 서비스 조회와 쓰기에서 검사한다.
- 부모의 **유형**, 계층 순환, FSM, 종료 티켓 수정 제한, 의존성 완료 조건, 삭제·복구 가능 여부는 서비스에서 검사한다.
- projects.key와 tickets.key/number를 생성 이후 변경하지 않는 정책, 원자적인 번호 발급과 재사용 금지는 서비스 책임이다.
- 초기 번호 1부터 `projects.next_ticket_number`를 원자적으로 증가시키고 티켓 생성·최초 이력·감사 로그와 함께 commit한다. `MAX(number)`에서 계산하지 않는다. SQLite에서는 `BEGIN IMMEDIATE`로 동시 생성을 직렬화하며 통합 테스트에서 중복 발급과 rollback을 검증한다. PostgreSQL 전환 시 행 잠금 또는 동등한 원자 증가를 별도로 구현·검증한다.
- Ticket·Comment의 일반 ORM flush에는 SQLAlchemy version 검사를 적용한다. bulk UPDATE는 이를 우회하므로 서비스에서 금지하거나 version 조건·증가·영향 행 수 검사를 직접 적용해야 한다.
- 저장되는 JSON은 아래 계약으로 검증 후 쓰고 전체 값을 교체한다. 중첩 JSON을 제자리 수정해 dirty tracking에 의존하지 않는다.
- DB CHECK는 JSON 내부의 타입·버전·상태 간 일관성까지 검사하지 않는다. Pydantic 검증과 서비스 transaction 검증이 필요하다.

## 티켓과 간트 저장 규칙

- 타입: EPIC/TASK/SUBTASK. 상태: TODO/IN_PROGRESS/DONE/ON_HOLD/CANCELLED. 중요도: TRIVIAL/MINOR/MAJOR/CRITICAL/BLOCKER.
- UI의 한글 상태 표시명은 DB code가 아니다. 현재 서비스 변환 계층에서 저장 code와 화면 표시명을 분리한다.
- description/body는 Markdown 원문이고 body_schema_version=1이다. renderer·sanitizer는 후속이다.
- sort_order는 Numeric(20,6)이다. 같은 순서 값에서는 ticket ID로 안정적으로 정렬하고 간격 소진 시 재정렬은 서비스에서 처리한다.
- planned_start_date/planned_end_date는 달력 날짜이고 due_date와 독립이다. 둘 다 있으면 start <= end이며 미정 날짜도 허용한다.
- actual_started_at은 최초 착수, completed_at/cancelled_at은 현재 완료·취소 진입 시각이다. 재개 시 해당 종료 시각을 비우고 이전 값은 이력에 남긴다.
- progress_percent와 is_milestone은 후속 간트 UI를 위한 독립 필드다. 현재 상태 전이나 일정 자동 조정은 하지 않는다.
- source A가 target B에 의존한다. FS는 B 종료→A 시작, SS는 B 시작→A 시작, FF는 B 종료→A 종료, SF는 B 시작→A 종료다.
- lag_days는 signed 달력 일수다. 관계 생성 기능을 연결할 때 Depends on은 FS/0, Related는 dependency_kind=NULL/lag_days=0으로 저장한다.

## 삭제와 보존

- 삭제 시 활성 계층만 새 deletion batch에 연결하고 deleted_at을 설정한다. 이미 휴지통에 있는 자손은 원래 batch에 남긴다.
- 복구는 해당 batch의 티켓을 함께 복구하고 ticket의 batch/deleted_at을 비운다. batch의 restored_at/restored_by_id는 남긴다.
- batch의 root_ticket_key는 표시용 snapshot이며 순환 FK를 만들지 않는다. root가 속한 project와 당시 batch 집합의 일관성은 서비스가 검사한다.
- 댓글 본문은 soft delete 중 보존한다. 제거된 멘션은 일반 inbox에서 제외하고 재등장 시 같은 row를 사용한다. 읽음 상태 재설정 정책은 멘션 서비스에서 확정한다.
- 파일 영구 삭제 → Attachment 메타데이터 삭제 → 티켓 계층을 자식부터 물리 삭제한다. 파일이 없으면 삭제 성공으로 처리해 재시도 가능하게 한다.
- Attachment의 FK RESTRICT는 메타데이터보다 원본이 먼저 사라지는 것을 막는다. 파일 삭제·재시도와 동시 다운로드 조정은 저장소 서비스 책임이다.
- 티켓 물리 삭제 시 comments/mentions/relations/history는 FK cascade로 정리된다. 부모 삭제는 자식 FK RESTRICT 때문에 자식부터 처리해야 한다.
- 감사 로그는 기본 30일, 활동 이력은 티켓 수명, 보고서 입력·출력은 보고서 수명으로 구분한다. 보고서 snapshot은 원본 purge에 cascade되지 않는다.
- projects.history_complete_from은 완전한 이력을 보장할 수 있는 가장 이른 경계이며 NULL은 미검증이다. 프로젝트 생성 서비스가 기록 시작 시각으로 초기화하고, purge·이력 유실 시 해당 시각까지 전진시킨다. 그보다 이전에 시작하는 보고서는 보수적으로 PARTIAL로 분류한다.
- 원본을 지운 batch에는 purged_at을 남긴다. 이미 복구한 batch를 purge 상태로 바꿀 수 없다. watermark와 purge 기록은 티켓 삭제와 같은 transaction으로 저장한다.

## Migration 및 검증

- 기존 `20260916_0001`을 수정하지 않는다. 신규 revision은 기존 identity row를 변환·삭제하지 않는다.
- 같은 위치의 조직 이름 중복은 **DDL 전에** 검사하여 명확히 실패한다. 자동 이름 변경이나 데이터 삭제는 하지 않는다.
- SQLite DDL 전체의 원자성을 가정하지 않는다. 실제 적용 전 백업하고 다른 실패 시 revision·생성된 구조를 확인해 복구한다.
- downgrade는 신규 테이블과 데이터를 제거하고 기존 identity 및 이전 revision으로 되돌린다. populated hierarchy의 self-FK를 해제한 뒤 테이블을 제거한다.
- `20260923_0003` downgrade는 이전 schema에 읽기 전용 역할이 없으므로 게스트 membership을 제거한다. 쓰기 가능한 사용자로 자동 승격하지 않는다.
- downgrade는 blob 파일을 삭제하지 않는다. 파일과 DB를 동일 시점 백업으로 복구해야 하며 운영에서 downgrade를 데이터 보존 수단으로 사용하지 않는다.
- 테스트는 임시 SQLite DB에서 빈 DB upgrade, 기존 데이터 보존, populated downgrade/re-upgrade, CHECK/metadata 일치, 잘못된 FK·중복·일정·버전과 I/O 계약을 검사한다.
- Partial unique index는 SQLite와 PostgreSQL 문법을 함께 정의했다. PostgreSQL 실제 migration/repository 실행 검증은 아직 수행하지 않았다. 다른 DB의 지원을 보장하지 않는다.

## 연결 현황과 후속 순서

로그인·비밀번호 변경 → 사용자·조직 기본 관리 → 프로젝트·참여자 → 티켓 생성·목록·상세 → 대시보드·칸반 조회 → 편집·상태 전이·칸반 이동까지 연결했다. 다음 순서는 사용자·조직·프로젝트 관리 쓰기 확장과 관계·휴지통·댓글·멘션·첨부파일·저장 필터다.
각 화면에서 필요한 저장·조회와 권한 검증을 함께 연결한다. 간트와 보고서는 별도 후속 화면으로 둔다.

상세 보고서 계약은 [reporting_contracts.md](reporting_contracts.md), 의사결정 근거는 [planning-and-reporting.md](decisions/planning-and-reporting.md)를 참조한다.
