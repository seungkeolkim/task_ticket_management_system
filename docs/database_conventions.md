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

## Migration verification

The test suite creates a temporary file-backed SQLite database, upgrades it to `head`, checks that model metadata matches the migration, and verifies downgrade behavior.

```powershell
alembic upgrade head
alembic check
alembic downgrade base
```
