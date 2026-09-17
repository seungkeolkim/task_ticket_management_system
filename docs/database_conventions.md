# Database conventions

## Schema ownership

- SQLAlchemy model metadata is the application schema source of truth.
- Every schema change must be represented by an Alembic revision with both `upgrade` and `downgrade`.
- The application must not call `Base.metadata.create_all()` in production or during normal startup.
- Constraints and indexes use explicit, deterministic names through the shared naming convention.

## Identifiers and relationships

- Internal primary keys use auto-incrementing integers for SQLite compatibility.
- Stable external identifiers such as organization keys and ticket keys are separate unique columns.
- Relationships are protected by actual foreign keys, and SQLite enables `PRAGMA foreign_keys=ON` on every connection.
- Domain services validate business rules; database constraints remain the final defense for structural integrity and uniqueness.

## Date and time

- Application datetimes must be timezone-aware.
- Values are converted to UTC before binding.
- SQLite stores naive UTC because it does not preserve timezone metadata; the `UTCDateTime` type restores UTC awareness when values are read.
- Databases with timezone-aware timestamp support receive aware UTC values.
- Naive application datetime values are rejected instead of being interpreted using the host timezone.
- User-facing conversion to `Asia/Seoul` belongs in the presentation layer.

## Transactions and sessions

- HTTP requests receive one SQLAlchemy session through dependency injection.
- Application services define write transaction boundaries explicitly.
- `transaction_scope` owns a session, commits once on success, rolls back on any exception, and always closes the session.
- ORM entities should not be passed between independently created sessions; pass identifiers or DTOs across layer boundaries.
- Repository and service functions may flush but should not make hidden commits inside a larger use case.

## Portability

- Prefer SQLAlchemy generic column types and expressions.
- Keep database-specific connection options in the engine factory.
- Do not embed SQLite-only SQL in domain or service code.
- JSON fields contain data only and must never contain executable SQL or code.
- PostgreSQL support is considered verified only after migrations and repository tests run against PostgreSQL.
- Partial unique indexes currently have explicit SQLite and PostgreSQL predicates. Other engines require an equivalent uniqueness strategy before support is claimed.

## Migration verification

The test suite creates a temporary file-backed SQLite database, upgrades it to `head`, checks that model metadata matches the migration, and verifies downgrade behavior.

```powershell
alembic upgrade head
alembic check
alembic downgrade base
```

## MVP and reporting schema

- See [mvp_data_model.md](mvp_data_model.md) for the requirement/table mapping and service boundaries.
- Revision `20260917_0002` adds 15 work/reporting tables without rewriting the identity baseline.
- Validate upgrades with existing identity data as well as an empty database. Duplicate sibling organization names fail preflight before DDL; never silently rename or remove them.
- Downgrade destroys the new work/reporting rows. It is not a data-preserving application rollback and does not remove filesystem attachments. Use a consistent backup for recovery.
- SQLite DDL is not assumed to be fully transactional. Preserve a backup before applying migrations to a populated deployment.
- Composite foreign keys include project scope, and comment references also include their parent ticket. Authorization still belongs in services.
- Ticket and comment ORM writes use version columns. Bulk SQL must explicitly enforce version checks, increments and row counts; it must not bypass the application transaction/history contract.
- Validate JSON against the versioned contracts before persisting it. Replace whole JSON values instead of silently mutating nested objects.
- Ticket history is append-only at the service boundary and is retained for the ticket lifetime, independently of 30-day audit cleanup.
- Report input, published skill versions and completed attempts are immutable at the service boundary. Store a new version or attempt instead of overwriting evidence.
- Frozen report evidence has no FK to live tickets/history. Keep the report-project links and require current access to every source project on retrieval.

## 인증 쓰기 경계

주입된 session의 선행 조회를 포함한 쓰기는 `request_transaction`에서 한 번 commit하거나 rollback한다. 인증 실패 감사 기록은 commit한 뒤 사용자 오류를 반환한다. SQLite 인증 쓰기의 제한 판정과 bootstrap은 repository 잠금으로 직렬화한다(DB-013). DB backend 전환 시 이 경계의 동시성 검증을 먼저 구현한다. SQL parameter는 engine의 `hide_parameters=True`로 로그·예외에 출력하지 않는다.
