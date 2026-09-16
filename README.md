# Task Ticket Management System

FastAPI, SQLAlchemy, Alembic, and SQLite를 사용하는 사내용 태스크·티켓 관리 시스템입니다.

## 문서

- [요구사항](REQUIREMENTS.md)
- [구현 로드맵 및 진척도](IMPLEMENTATION_ROADMAP.md)
- [의사결정 기록](docs/decisions/README.md)
- [기존 프로젝트 참조 및 차용 가이드](REFERENCE_IMPLEMENTATION.md)
- [DB 설계 규칙](docs/database_conventions.md)

## Docker로 실행

```bash
docker compose up --build
```

- 웹 UI 목업: <http://localhost:8000>
- API 문서: <http://localhost:8000/docs>
- 상태 확인: <http://localhost:8000/health>
- DB 연결 확인: <http://localhost:8000/health/ready>

Docker Compose는 호스트의 `data` 디렉터리를 컨테이너의 `/app/data`에 마운트합니다. 설정은 `data/config/application.toml`에서 변경하고 컨테이너를 재시작하면 적용됩니다.

현재 루트 화면은 인증 및 실제 도메인 API가 연결되기 전의 탐색 가능한 UI 목업입니다. 로그인 없이 내 작업 대시보드가 열리며, 화면에 표시되는 데이터와 쓰기 버튼은 실제 데이터를 변경하지 않습니다.

## 로컬 개발

Python 3.11 이상이 필요합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
python -m app
```

테스트와 정적 검사는 다음 명령으로 실행합니다.

```powershell
pytest
ruff check .
```

## 설정

기본 설정 파일은 `data/config/application.toml`입니다. 다른 파일을 사용하려면 `APP_CONFIG_FILE` 환경 변수를 지정합니다.

설정 우선순위는 다음과 같습니다.

1. 환경 변수
2. 외부 TOML 설정 파일
3. 애플리케이션 기본값

중첩 설정은 `TTMS__섹션__필드` 형식의 환경 변수로 재정의할 수 있습니다. 예: `TTMS__AUDIT__RETENTION_DAYS=60`.

비밀번호와 서명 키 등의 비밀값은 TOML 파일에 저장하지 않고 환경 변수나 컨테이너 secret으로 주입합니다.
