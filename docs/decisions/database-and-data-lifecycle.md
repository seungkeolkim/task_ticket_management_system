# Database and data lifecycle decisions

| ID | 날짜 | 상태 | 결정 | 근거·영향 |
|---|---|---|---|---|
| DB-001 | 2026-09-16 | DECIDED | 초기 DB는 SQLite이며 SQLAlchemy와 Alembic을 통해 PostgreSQL 등 다른 관계형 DB로 전환 가능한 경계를 유지한다. | 작은 규모로 시작하되 domain과 service가 SQLite 전용 SQL에 의존하지 않게 한다. |
| DB-002 | 2026-09-16 | DECIDED | SQLAlchemy metadata를 schema source of truth로 삼고 모든 변경은 upgrade·downgrade가 있는 Alembic revision으로 적용한다. 런타임 `create_all`은 사용하지 않는다. | 환경별 schema drift와 자동 baseline 추정을 방지한다. |
| DB-003 | 2026-09-16 | DECIDED | 내부 primary key는 SQLite 호환성이 좋은 auto-increment integer를 사용하고 외부 안정 식별자는 별도 unique key로 둔다. | 내부 관계와 외부 import·URL 식별자의 수명 주기를 분리한다. |
| DB-004 | 2026-09-16 | DECIDED | 애플리케이션 datetime은 timezone-aware UTC만 허용한다. SQLite에는 naive UTC로 저장하고 custom `UTCDateTime`이 읽을 때 UTC awareness를 복원한다. | SQLite의 timezone 정보 손실과 host timezone 오해석을 방지한다. |
| DB-005 | 2026-09-16 | DECIDED | 모든 SQLite connection에서 `PRAGMA foreign_keys=ON`을 실행하고 관계 무결성을 실제 FK와 constraint로 방어한다. | ORM 검증을 우회한 쓰기에서도 구조적 무결성을 유지한다. |
| DB-006 | 2026-09-16 | DECIDED | HTTP 요청은 한 session을 주입받고 application service가 write transaction 경계를 소유한다. 성공 시 한 번 commit하고 예외 시 rollback한다. | 계층별 숨은 commit과 서로 다른 session 사이 ORM 객체 전달 문제를 막는다. |
| DB-007 | 2026-09-16 | DECIDED | 최초 schema는 `organizations`, `users`, `user_sessions`, `audit_logs`이며 사용자는 하나의 조직을 필수 FK로 가진다. | 인증과 관리 기능의 최소 데이터 기반을 먼저 고정한다. 초기 관리자 조직 생성 방식은 IAM-010을 따른다. |
| DB-008 | 2026-09-16 | DECIDED | session token은 SHA-256 hex hash를 저장할 수 있는 64자 unique column을 사용하고 사용자 삭제 시 session은 cascade 삭제한다. | 탈취 시 바로 사용할 수 있는 token 원문을 DB에 저장하지 않는다. |
| DB-009 | 2026-09-16 | DECIDED | 감사 로그 기본 보존 기간은 30일, 기본 정리 실행 주기는 24시간이며 둘 다 외부 설정으로 변경한다. 만료 로그는 영구 삭제한다. | MVP에서도 감사 데이터의 무기한 누적을 방지한다. |
| DB-010 | 2026-09-17 | DECIDED | 기존 identity revision은 유지하고 `20260917_0002`에 확정된 MVP 및 간트·보고서 기반을 추가한다. upgrade는 기존 identity 데이터를 보존하고 downgrade는 신규 업무 데이터를 제거하는 파괴적 작업으로 명시한다. | revision 재작성·stamp·운영 DB 초기화를 피한다. 빈 DB 및 데이터가 있는 이전 revision에서 왕복을 검증한다. |
| DB-011 | 2026-09-17 | DECIDED | 프로젝트 경계는 복합 FK로, 댓글 원본 일치는 project·ticket·comment 복합 FK로 보호한다. Related는 작은 내부 ticket ID가 source인 정규형만 저장한다. 조직 최상위 이름과 설명 멘션 중복은 SQLite·PostgreSQL partial unique index로 보호한다. | 서비스 우회 쓰기에서도 잘못된 연결을 차단한다. MySQL 등 partial index 미지원 DB로 전환할 때는 동등한 제약 설계가 필요하다. |
| DB-012 | 2026-09-17 | DECIDED | 휴지통 이동마다 batch를 생성하고 당시 활성 하위 티켓만 연결한다. 복구 후 ticket의 삭제 필드를 비우고 batch 복구 이력을 남긴다. 이미 다른 batch로 삭제된 자손은 새 batch에 흡수하지 않는다. | 삭제·복구 대상을 재귀 조회만으로 추측하지 않고 실제 함께 이동한 집합을 보존한다. 부모가 삭제 상태인 자손만 독립 복구하는 동작은 서비스가 거부한다. |
| DB-013 | 2026-09-17 | DECIDED | SQLite 인증 쓰기는 repository의 `BEGIN IMMEDIATE`로 실패 제한 판정·감사 기록과 bootstrap을 직렬화한다. 비밀번호 교체와 로그인은 기존 hash 조건으로 경합을 검사한다. | 기존 테이블만 사용하여 migration을 추가하지 않는다. 잠금 동안 hash 검증으로 쓰기 처리량이 제한되며 PostgreSQL 전환 전 동등한 잠금 구현·검증을 요구한다. |
| DB-014 | 2026-09-18 | DECIDED | 사용자·조직 생성도 DB-013의 SQLite 쓰기 잠금을 재사용하고 잠금 후 관리자 상태·조직 상태·중복을 확인한다. 생성과 감사 기록을 한 transaction으로 commit한다. | 동시 생성 및 역할 변경 경합에 대비하고 무결성 오류는 rollback 후 안전한 409로 반환한다. backend 전환 시 관리 쓰기도 동시성 검증 대상이다. |
| DB-015 | 2026-09-18 | DECIDED | 최초 revision의 upgrade·식별자는 유지하며 downgrade의 조직 테이블 제거 직전에 parent 연결을 해제한다. 새 revision은 추가하지 않는다. | SQLite가 하위 조직이 있는 self-RESTRICT 테이블의 DROP을 거부하는 기존 결함을 수정한다. 의도적으로 전체 DB를 제거하는 base rollback에만 적용되며 head→0001 downgrade와 정상 실행 데이터에는 영향을 주지 않는다. |

## Open decisions

- PostgreSQL migration·repository 검증을 CI에서 언제 필수화할지는 실제 전환 필요성과 함께 확정한다.
- 대규모 데이터에서 keyset pagination으로 전환할 기준은 성능 측정 후 확정한다.
- audit cleanup의 다중 instance 중복 실행 방지 방식은 scheduler 구조를 정할 때 확정한다.
