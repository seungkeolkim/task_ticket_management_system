# Task Ticket Management System

FastAPI, SQLAlchemy, Alembic, and SQLite를 사용하는 사내용 태스크·티켓 관리 시스템입니다.

## 문서

- [요구사항](REQUIREMENTS.md)
- [구현 로드맵 및 진척도](IMPLEMENTATION_ROADMAP.md)
- [의사결정 기록](docs/decisions/README.md)
- [기존 프로젝트 참조 및 차용 가이드](REFERENCE_IMPLEMENTATION.md)
- [DB 설계 규칙](docs/database_conventions.md)
- [시스템 로깅 규약](docs/logging_conventions.md)
- [로그인·초기 관리자 설정](docs/authentication.md)
- [사용자·조직 관리](docs/administration.md)
- [프로젝트·참여자 관리](docs/projects.md)

## Docker로 실행

```bash
sh ./run_compose.sh start
```

중지는 다음 명령을 사용합니다.

```bash
sh ./run_compose.sh stop
```

Windows PowerShell에서는 저장소 루트의 동일한 실행 래퍼를 사용합니다.

```powershell
.\run_compose.ps1 start
.\run_compose.ps1 stop
```

`start`는 설정을 검증한 뒤 `docker compose up --build --detach`, `stop`은 `docker compose down`을 실행합니다. PowerShell 래퍼는 `.venv\Scripts\python.exe`, PATH의 `python`, `python3`, `py -3` 순으로 Python 3.11 이상을 찾습니다. 설정 파일이 없거나 잘못되어도 `stop`은 사용할 수 있으며, 호출 후 현재 폴더와 임시 환경 변수를 복원하고 Docker 종료 코드를 그대로 반환합니다.

다른 설정 파일은 다음과 같이 지정합니다. 상대 경로는 스크립트를 호출한 폴더 기준으로 해석합니다.

```powershell
$env:APP_CONFIG_FILE = 'C:\deployment\config\application.toml'
.\run_compose.ps1 start
```

- 웹 UI: <http://localhost:8000>
- API 문서: <http://localhost:8000/docs>
- 상태 확인: <http://localhost:8000/health>
- DB 연결 확인: <http://localhost:8000/health/ready>

Docker Compose는 개발 중인 `app`, `migrations`, `alembic.ini`를 컨테이너의 대응 경로에 bind mount합니다. Dockerfile은 이 경로들을 복사하지 않으며 런타임 라이브러리와 기동 스크립트만 이미지에 준비합니다. 따라서 Python 소스와 migration 변경 때문에 이미 설치한 라이브러리를 다시 설치하지 않습니다. 런타임 라이브러리는 `pyproject.toml`이 변경될 때만 이미지의 의존성 레이어에서 다시 설치됩니다. 소스를 포함하는 단독 배포 이미지는 릴리즈 구성을 도입할 때 별도로 구성합니다.

호스트의 `data` 디렉터리는 컨테이너의 `/app/data`에 마운트하고, `config/application.toml`은 `/app/config/application.toml`에 읽기 전용으로 별도 마운트합니다. `run_compose.sh start`는 `[server].port`를 읽어 애플리케이션 수신 포트, 호스트 공개 포트와 health check에 동일하게 적용합니다. 예를 들어 포트를 `9123`으로 바꾸고 다시 시작하면 `http://localhost:9123`으로 접속합니다.

Compose는 TOML을 직접 해석할 수 없으므로 직접 `docker compose up`을 실행하면 필수 포트 변수가 없다는 오류와 함께 중단됩니다. 항상 실행 래퍼를 사용하면 설정 변경과 포트 매핑이 어긋나지 않습니다. 다른 호스트 설정 파일을 사용하려면 절대 경로로 `APP_CONFIG_FILE=/path/to/application.toml sh ./run_compose.sh start`를 실행합니다.

루트 `/`는 내 작업 대시보드이며 로그인하지 않았다면 로그인 화면으로 이동합니다. 인증, 사용자·조직의 조회·생성, 프로젝트 생성·조회·참여자 등록은 실제 DB에 연결되어 있습니다. 내 작업 대시보드는 예시 데이터이며, 실제 프로젝트의 티켓·칸반·휴지통 경로는 준비 중 안내를 표시합니다. 최초 실행 전 [초기 관리자 설정](docs/authentication.md)에 따라 CLI 또는 bootstrap 환경 변수로 관리자를 생성하세요.

## 로컬 개발

Python 3.11 이상이 필요합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
python -m app.cli bootstrap-admin --login-id admin
python -m app
```

테스트와 정적 검사는 다음 명령으로 실행합니다.

```powershell
pytest
ruff check .
```

## 설정

기본 설정 파일은 `config/application.toml`입니다. 다른 파일을 사용하려면 `APP_CONFIG_FILE` 환경 변수를 지정합니다. 로컬 실행에서는 애플리케이션이 이 경로를 직접 읽고, Docker 실행에서는 래퍼가 같은 파일을 컨테이너 설정 경로에 마운트합니다.

설정 우선순위는 다음과 같습니다.

1. 환경 변수
2. 외부 TOML 설정 파일
3. 애플리케이션 기본값

중첩 설정은 `TTMS__섹션__필드` 형식의 환경 변수로 재정의할 수 있습니다. 예: `TTMS__AUDIT__RETENTION_DAYS=60`.

시스템 로그 레벨은 `[app].log_level` 또는 `TTMS__APP__LOG_LEVEL`로 조정합니다. 로그는 UTC 시간이 첫 필드인 공통 포맷으로 표준 출력과 `data/logs/application.log`에 함께 기록됩니다. 파일은 기본 100MB 단위로 회전하고 백업 10개를 유지하며 `[logging]` 설정이나 `TTMS__LOGGING__...` 환경 변수로 조정할 수 있습니다.

비밀번호와 서명 키 등의 비밀값은 TOML 파일에 저장하지 않고 환경 변수나 컨테이너 secret으로 주입합니다.
