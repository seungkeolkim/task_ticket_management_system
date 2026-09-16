# Database and data lifecycle decisions

| ID | 날짜 | 상태 | 결정 | 근거·영향 |
|---|---|---|---|---|
| DB-001 | 2026-09-16 | DECIDED | 초기 DB는 SQLite이며 SQLAlchemy와 Alembic을 통해 PostgreSQL 등 다른 관계형 DB로 전환 가능한 경계를 유지한다. | 작은 규모로 시작하되 domain과 service가 SQLite 전용 SQL에 의존하지 않게 한다. |
| DB-002 | 2026-09-16 | DECIDED | SQLAlchemy metadata를 schema source of truth로 삼고 모든 변경은 upgrade·downgrade가 있는 Alembic revision으로 적용한다. 런타임 `create_all`은 사용하지 않는다. | 환경별 schema drift와 자동 baseline 추정을 방지한다. |
| DB-003 | 2026-09-16 | DECIDED | 내부 primary key는 SQLite 호환성이 좋은 auto-increment integer를 사용하고 외부 안정 식별자는 별도 unique key로 둔다. | 내부 관계와 외부 import·URL 식별자의 수명 주기를 분리한다. |
| DB-004 | 2026-09-16 | DECIDED | 애플리케이션 datetime은 timezone-aware UTC만 허용한다. SQLite에는 naive UTC로 저장하고 custom `UTCDateTime`이 읽을 때 UTC awareness를 복원한다. | SQLite의 timezone 정보 손실과 host timezone 오해석을 방지한다. |
| DB-005 | 2026-09-16 | DECIDED | 모든 SQLite connection에서 `PRAGMA foreign_keys=ON`을 실행하고 관계 무결성을 실제 FK와 constraint로 방어한다. | ORM 검증을 우회한 쓰기에서도 구조적 무결성을 유지한다. |
| DB-006 | 2026-09-16 | DECIDED | HTTP 요청은 한 session을 주입받고 application service가 write transaction 경계를 소유한다. 성공 시 한 번 commit하고 예외 시 rollback한다. | 계층별 숨은 commit과 서로 다른 session 사이 ORM 객체 전달 문제를 막는다. |
| DB-007 | 2026-09-16 | DECIDED | 최초 schema는 `organizations`, `users`, `user_sessions`, `audit_logs`이며 사용자는 하나의 조직을 필수 FK로 가진다. | 인증과 관리 기능의 최소 데이터 기반을 먼저 고정한다. 초기 관리자 조직 생성 방식은 IAM open decision으로 남긴다. |
| DB-008 | 2026-09-16 | DECIDED | session token은 SHA-256 hex hash를 저장할 수 있는 64자 unique column을 사용하고 사용자 삭제 시 session은 cascade 삭제한다. | 탈취 시 바로 사용할 수 있는 token 원문을 DB에 저장하지 않는다. |
| DB-009 | 2026-09-16 | DECIDED | 감사 로그 기본 보존 기간은 30일, 기본 정리 실행 주기는 24시간이며 둘 다 외부 설정으로 변경한다. 만료 로그는 영구 삭제한다. | MVP에서도 감사 데이터의 무기한 누적을 방지한다. |

## Open decisions

- PostgreSQL migration·repository 검증을 CI에서 언제 필수화할지는 실제 전환 필요성과 함께 확정한다.
- 대규모 데이터에서 keyset pagination으로 전환할 기준은 성능 측정 후 확정한다.
- audit cleanup의 다중 instance 중복 실행 방지 방식은 scheduler 구조를 정할 때 확정한다.
