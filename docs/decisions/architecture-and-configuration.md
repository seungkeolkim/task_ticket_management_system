# Architecture and configuration decisions

| ID | 날짜 | 상태 | 결정 | 근거·영향 |
|---|---|---|---|---|
| ARC-001 | 2026-09-16 | DECIDED | 백엔드는 Python과 FastAPI를 사용하고 API, application service, domain, repository, adapter 계층을 분리한다. | 권한·FSM·저장소 규칙을 UI 및 DB 구현과 분리하여 재사용하고 테스트하기 위함이다. |
| ARC-002 | 2026-09-16 | SUPERSEDED | 애플리케이션은 Docker Compose로 실행하고 영속 데이터는 하나의 외부 mount root 아래 `config`, `database`, `attachments`, `backups`로 나눈다. | ARC-008로 대체됨. 설정과 영속 데이터의 수명 주기 및 Compose 적용 책임을 분리한다. |
| ARC-003 | 2026-09-16 | SUPERSEDED | 일반 운영 설정은 `<mounted-data>/config/application.toml`에서 읽으며 적용 우선순위는 환경 변수 → TOML → 기본값이다. | ARC-008로 대체됨. 설정 우선순위는 유지하되 기본 위치와 Compose 기동 방식을 변경한다. |
| ARC-004 | 2026-09-16 | DECIDED | 비밀번호와 서명 키 같은 비밀값은 TOML에 저장하지 않고 환경 변수 또는 container secret으로만 주입한다. | 마운트 데이터나 저장소를 복사할 때 비밀값이 함께 유출되는 것을 막는다. |
| ARC-005 | 2026-09-16 | DECIDED | 잘못되거나 알 수 없는 설정은 조용히 무시하지 않고 기동 시 검증 오류로 처리한다. | 오타나 잘못된 운영값으로 서비스가 예상과 다르게 동작하는 것을 방지한다. |
| ARC-006 | 2026-09-16 | DECIDED | 애플리케이션 경로 조합은 `os.path.join`을 사용하고 Windows 개발, Docker Linux, macOS 운영을 모두 검증 대상으로 둔다. | 호스트별 경로 구분자와 인코딩 차이를 애플리케이션 계층에 노출하지 않는다. |
| ARC-007 | 2026-09-17 | DECIDED | 감사 로그와 별도로 Python 표준 `logging` 기반의 시스템 진단 로그를 표준 출력과 data root 아래 회전 파일에 함께 기록한다. UTC ISO 8601 시간을 첫 필드에 두고 애플리케이션과 Uvicorn 로그에 공통 포맷을 적용하며, 로그 레벨·파일명·파일 활성화·회전 크기·백업 개수는 외부 설정으로 조정한다. 세부 작성 규약은 `docs/logging_conventions.md`를 따른다. | Docker와 로컬 개발에서 같은 방식으로 시간순 검색하고 재기동 이후에도 진단 로그를 보존하며, 실행 환경별 로그 양과 디스크 사용량을 재빌드 없이 조절하면서 감사 증적과 장애 진단의 책임을 분리한다. |
| ARC-008 | 2026-09-17 | DECIDED | 일반 운영 설정은 최상위 `config/application.toml`, 영속 데이터는 `data/`에 분리하고 컨테이너에 각각 `/app/config/application.toml`과 `/app/data`로 마운트한다. 설정 우선순위는 환경 변수 → TOML → 기본값을 유지한다. Docker Compose는 `run_compose.sh`가 TOML의 `server.port`를 검증한 뒤 호스트·컨테이너 포트와 health check에 같은 값으로 주입하며, 래퍼 없는 Compose 기동은 필수 변수가 없어 실패하게 한다. | 설정 변경이 애플리케이션 수신 포트에만 적용되어 호스트 공개 포트와 어긋나는 장애를 막고, 운영 설정과 생성되는 영속 데이터의 수명 주기를 분리한다. `stop`은 설정 파일 오류와 무관하게 실행할 수 있다. |
| ARC-009 | 2026-09-17 | DECIDED | 확정된 MVP 저장 구조를 선행 준비한 뒤 화면별 작은 기능을 UI·서비스·DB까지 연결하고 전체 화면을 순환하며 확장한다. 기존 기능별 로드맵은 누락 점검에 유지한다. | 한 영역을 완성할 때까지 다른 화면이 목업으로 남는 기간을 줄인다. 연결한 기능의 권한·무결성·감사 처리는 같은 작업에서 검증한다. |
| ARC-010 | 2026-09-17 | DECIDED | 최초 화면별 연결은 기존 FastAPI·Jinja2 렌더링을 유지하며 HTML form과 JSON API가 같은 인증 서비스를 사용한다. | 목업 레이아웃을 재사용하면서 로그인부터 실제 데이터 흐름을 연결한다. 인라인 상세와 칸반의 클라이언트 상호작용 방식은 해당 화면 구현 시 정한다. |
| ARC-011 | 2026-09-19 | DECIDED | Windows용 `run_compose.ps1`을 추가하고 기존 셸 래퍼와 `scripts/read-compose-port.py`를 공유한다. start는 up --build --detach, stop은 down이며 종료 코드를 전달한다. PowerShell은 저장소 가상환경·python·python3·py -3 순으로 Python 3.11 이상을 찾고 stop에는 Python이나 유효한 설정 파일을 요구하지 않는다. | 운영 포트 규칙을 중복 구현하지 않는다. 상대 설정 경로는 호출 폴더 기준으로 절대화하며 실행 후 호출자의 위치·임시 환경 변수를 복원한다. |
| ARC-012 | 2026-09-19 | DECIDED | Compose 개발 실행은 `app`, `migrations`, `alembic.ini`를 호스트에서 bind mount하고 Dockerfile에서는 해당 경로를 복사하지 않는다. 개발 이미지는 런타임 의존성과 기동 스크립트만 포함하며 소스를 포함하는 단독 배포 이미지는 릴리즈 구성을 도입할 때 별도로 만든다. | 개발 소스의 공급 경로를 bind mount 하나로 통일하고 반복 기동·빌드에서 소스 복사와 라이브러리 재설치를 피한다. `pyproject.toml`이 변경된 경우에만 의존성 레이어를 갱신한다. |

## Open decisions

- 정기 정리 작업을 별도 worker, scheduler container, 또는 외부 scheduler 중 어디에서 실행할지는 운영 준비 단계에서 확정한다.
