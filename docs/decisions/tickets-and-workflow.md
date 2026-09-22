# Ticket and workflow decisions

| ID | 날짜 | 상태 | 결정 | 근거·영향 |
|---|---|---|---|---|
| TKT-001 | 2026-09-16 | DECIDED | 티켓 계층은 Epic → Task → Subtask이며 Task는 Epic 없이 존재할 수 있지만 Subtask는 반드시 Task를 부모로 가진다. | 초기 Jira 유사 업무 구조를 제한된 규칙으로 명확히 표현한다. 다른 프로젝트 부모와 순환은 금지한다. |
| TKT-002 | 2026-09-16 | DECIDED | 상태는 등록·진행중·완료·보류·취소이며 명시된 FSM 전이만 서버에서 허용한다. | UI, API, 칸반 drag가 동일한 업무 규칙을 사용하고 모든 전이를 추적한다. |
| TKT-003 | 2026-09-16 | DECIDED | 중요도는 Trivial·Minor·Major·Critical·Blocker의 영문 code로 저장하고 기본값은 Major로 한다. | 저장값을 화면 번역과 분리하고 표시명 변경에 안전하게 한다. |
| TKT-004 | 2026-09-16 | DECIDED | 관계는 대칭인 Related와 방향이 있는 Depends on을 지원한다. 미완료 의존 대상이 하나라도 있으면 의존하는 티켓의 완료 전이를 차단한다. | 관계의 역방향 표현은 조회 시 계산하고 별도 관계 row로 중복 저장하지 않는다. |
| TKT-005 | 2026-09-16 | DECIDED | Task를 같은 프로젝트의 다른 Epic으로 이동하거나 Epic에서 분리해도 Subtask는 Task 아래 그대로 유지하고 상태·담당자·순서를 바꾸지 않는다. | Task와 Subtask의 업무 단위를 보존한다. 프로젝트 간 이동은 허용하지 않는다. |
| TKT-006 | 2026-09-16 | DECIDED | Epic과 하위 Task 상태는 자동 연동하지 않는다. Epic 완료 시 미완료 Task를 경고하지만 초기 버전에서는 완료를 차단하지 않는다. | 암묵적인 일괄 상태 변경으로 개별 Task 이력이 훼손되는 것을 막는다. |
| TKT-007 | 2026-09-16 | DECIDED | 티켓 삭제는 계층 단위 soft delete이며 기본 30일 후 영구 삭제한다. 활성 티켓이 삭제 대상에 의존하면 먼저 관계를 해제하거나 대상을 완료해야 한다. | 실수 복구와 의존성 무결성을 함께 보장한다. |
| TKT-008 | 2026-09-16 | DECIDED | 발급된 프로젝트별 티켓 번호는 복구나 영구 삭제 이후에도 재사용하지 않는다. | 외부 링크와 감사 이력에서 하나의 표시 키가 다른 티켓을 가리키지 않게 한다. |
| TKT-009 | 2026-09-22 | DECIDED | SQLite 티켓 생성은 DB-013의 `BEGIN IMMEDIATE` 쓰기 직렬화 안에서 프로젝트의 `next_ticket_number`를 원자적으로 1 증가시키고 증가 전 값을 번호로 사용한다. 티켓·최초 CREATED 이력·감사 로그와 카운터 증가는 한 transaction에서 commit한다. | `MAX(ticket.number)+1`의 동시 생성 중복과 삭제 후 번호 재사용을 피한다. 실패한 transaction은 카운터까지 rollback하며 PostgreSQL 등으로 전환할 때는 행 잠금 또는 동등한 원자 증가를 별도로 검증한다. |

## Open decisions

- Epic 완료 경고를 확인만 받는지 별도 사유 입력까지 요구할지는 UI 구현 시 결정한다.
