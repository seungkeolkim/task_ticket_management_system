# System logging conventions

이 문서는 감사 로그가 아닌 개발·운영 진단용 시스템 로그의 공통 규약이다. 새 코드와 변경 코드는 이 규약을 따른다.

## 목적과 출력 위치

- 시스템 로그는 기동, 요청 처리, 외부 연동, 예외와 장애 원인을 개발자와 운영자가 진단하기 위한 기록이다.
- 사용자 행위와 중요 데이터 변경의 증적은 DB의 감사 로그에 기록하며 시스템 로그로 대체하지 않는다.
- 애플리케이션 로그는 표준 출력과 `<data_root>/logs/application.log`에 함께 기록한다. Docker에서는 표준 출력을 container runtime이 수집하고 로그 파일은 mount된 data 디렉터리에 보존한다.
- 로그 파일은 기본 100MB에 도달하면 회전하며 현재 파일 외에 백업 10개를 유지한다. 백업 파일명은 `application.log.1`부터 순서대로 생성된다.
- 기본 구현은 Python 표준 `logging`을 사용한다. 모듈마다 `logging.getLogger(__name__)`로 logger를 만든다.

## 포맷과 시간

기본 포맷은 다음과 같다.

```text
YYYY-MM-DDTHH:MM:SS.mmmZ LEVEL logger.name message
```

- 시간은 검색과 시간순 정렬이 쉽도록 항상 첫 필드에 둔다.
- 시간은 UTC ISO 8601 형식으로 기록하고 `Z`를 붙인다.
- 애플리케이션, Uvicorn, HTTP access log와 Alembic migration log는 동일한 handler와 포맷을 사용한다.
- 메시지는 짧고 안정적인 영문 event 이름을 먼저 쓰고 필요한 context를 `key=value`로 덧붙인다.

예시:

```text
2026-09-17T01:23:45.123Z INFO app.services.ticket ticket_created ticket_id=42 project_id=3
```

## 로그 레벨

- `DEBUG`: 개발 중 내부 흐름과 진단 정보. 정상 운영에서 대량으로 남길 필요가 없는 정보.
- `INFO`: 기동·종료, 중요한 작업의 정상 완료, 운영 상태 변화.
- `WARNING`: 요청은 처리할 수 있지만 확인이 필요한 비정상 조건이나 복구 가능한 실패.
- `ERROR`: 요청 또는 작업이 실패했고 운영자나 개발자의 확인이 필요한 경우.
- `CRITICAL`: 서비스 지속이나 데이터 안전성이 즉시 위협받는 경우.
- 예상 가능한 사용자 입력 오류와 일반적인 4xx 응답을 예외 stack trace와 함께 기록하지 않는다.
- 예외를 처리하면서 실패 원인을 기록할 때는 `logger.exception(...)`을 사용해 stack trace를 보존한다.

## 설정

- 로그 레벨은 `app.log_level`에서 읽으며 기본값은 `INFO`다.
- 허용값은 `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`이다.
- 외부 TOML의 `[app].log_level` 또는 `TTMS__APP__LOG_LEVEL` 환경 변수로 조정한다.
- 설정 우선순위는 환경 변수 → 외부 TOML → 애플리케이션 기본값이며 변경은 재기동 후 적용한다.
- `[storage].logs_dir`로 data root 아래 로그 디렉터리를 지정한다.
- `[logging].file_enabled`, `file_name`, `max_size_mb`, `backup_count`로 파일 출력과 회전 정책을 조정한다. `file_name`에는 경로가 없는 파일명만 허용한다.
- `backup_count`는 현재 로그 파일을 제외한 백업 개수다. 기본 설정의 최대 디스크 사용량은 대략 1.1GB다.
- 내장 파일 회전은 단일 프로세스 쓰기를 기준으로 한다. `server.workers`를 2 이상으로 운영할 때는 여러 프로세스가 같은 파일을 회전하지 않도록 파일 출력을 끄고 container runtime 등 외부 로그 수집기의 회전을 사용한다.
- SQL 문 진단은 별도의 `database.echo` 설정을 사용한다. SQL parameter에 민감정보가 포함될 수 있으므로 운영 환경에서는 기본적으로 비활성화한다.

## Context와 민감정보

- 관련 값이 있을 때 request ID, 사용자 ID, 프로젝트 ID, 티켓 ID처럼 검색 가능한 안정 식별자를 기록한다.
- 비밀번호, session token과 hash, cookie, authorization header, secret, 첨부파일 본문은 어떤 레벨에서도 기록하지 않는다.
- 이메일, IP, user agent, 사용자 입력 본문은 진단에 반드시 필요한 최소 범위에서만 기록한다.
- 같은 예외를 여러 계층에서 반복 기록하지 않는다. 처리하거나 외부 경계에서 최종 실패로 바꾸는 계층이 한 번 기록한다.

## 구현 및 검토 기준

- 새 service, background job, 외부 adapter와 관리 명령은 주요 시작·완료·실패 지점의 로그 필요성을 검토한다.
- 메시지 문자열 조합보다 logger의 인자 치환 방식(`logger.info("event id=%s", value)`)을 사용한다.
- 정상 동작에서 요청마다 과도한 `INFO` 로그를 추가하지 않고 HTTP access log와 중복을 피한다.
- 로그에 새 context를 추가할 때 민감정보 여부와 값의 크기를 검토한다.
- 로깅 설정이나 공통 포맷을 변경하면 단위 테스트와 이 문서를 함께 갱신한다.
