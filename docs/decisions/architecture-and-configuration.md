# Architecture and configuration decisions

| ID | 날짜 | 상태 | 결정 | 근거·영향 |
|---|---|---|---|---|
| ARC-001 | 2026-09-16 | DECIDED | 백엔드는 Python과 FastAPI를 사용하고 API, application service, domain, repository, adapter 계층을 분리한다. | 권한·FSM·저장소 규칙을 UI 및 DB 구현과 분리하여 재사용하고 테스트하기 위함이다. |
| ARC-002 | 2026-09-16 | DECIDED | 애플리케이션은 Docker Compose로 실행하고 영속 데이터는 하나의 외부 mount root 아래 `config`, `database`, `attachments`, `backups`로 나눈다. | 호스트 이전 시 mount root 전체를 복사할 수 있고 컨테이너 교체와 데이터를 분리할 수 있다. |
| ARC-003 | 2026-09-16 | DECIDED | 일반 운영 설정은 `<mounted-data>/config/application.toml`에서 읽으며 적용 우선순위는 환경 변수 → TOML → 기본값이다. | 이미지를 다시 만들지 않고 기동 시 운영값을 조정할 수 있다. 설정 변경은 재시작 후 적용한다. |
| ARC-004 | 2026-09-16 | DECIDED | 비밀번호와 서명 키 같은 비밀값은 TOML에 저장하지 않고 환경 변수 또는 container secret으로만 주입한다. | 마운트 데이터나 저장소를 복사할 때 비밀값이 함께 유출되는 것을 막는다. |
| ARC-005 | 2026-09-16 | DECIDED | 잘못되거나 알 수 없는 설정은 조용히 무시하지 않고 기동 시 검증 오류로 처리한다. | 오타나 잘못된 운영값으로 서비스가 예상과 다르게 동작하는 것을 방지한다. |
| ARC-006 | 2026-09-16 | DECIDED | 애플리케이션 경로 조합은 `os.path.join`을 사용하고 Windows 개발, Docker Linux, macOS 운영을 모두 검증 대상으로 둔다. | 호스트별 경로 구분자와 인코딩 차이를 애플리케이션 계층에 노출하지 않는다. |

## Open decisions

- 별도 프런트엔드 빌드 체계를 둘지, FastAPI의 server-rendered UI를 유지할지는 UI 구현 전에 확정한다.
- 정기 정리 작업을 별도 worker, scheduler container, 또는 외부 scheduler 중 어디에서 실행할지는 운영 준비 단계에서 확정한다.
