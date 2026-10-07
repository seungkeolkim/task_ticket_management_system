# 구현 로드맵 및 진척도

이 문서는 태스크·티켓 관리 시스템의 권장 구현 순서와 현재 진척도를 관리한다.

- 마지막 갱신일: 2026-10-05
- 상세 요구사항: [REQUIREMENTS.md](REQUIREMENTS.md)
- 기존 구현 차용 기준: [REFERENCE_IMPLEMENTATION.md](REFERENCE_IMPLEMENTATION.md)

## 진척도 관리 규칙

- `[x]`는 코드, 테스트 및 필요한 migration까지 검증된 완료 항목을 의미한다.
- `[ ]`는 미착수 또는 작업 중인 항목을 의미한다.
- 단계 제목은 하위 필수 항목이 모두 완료되었을 때만 `[x]`로 변경한다.
- 기능 정책이나 범위가 바뀌면 요구사항 문서를 먼저 수정한 뒤 이 문서를 갱신한다.
- 각 단계는 가능한 한 독립적으로 실행하고 검증할 수 있는 상태로 마무리한다.

## 전체 현황

- [x] 0단계 — 프로젝트 골격
- [x] 1단계 — 공통 DB 및 개발 기반
- [x] 데이터 선행 준비 — MVP·간트·보고서 모델, migration 및 버전별 데이터 계약
- [ ] 2단계 — 사용자·인증·감사 로그
- [x] 3단계 — 시스템 관리자 및 조직 관리
- [x] 4단계 — 프로젝트와 접근 권한
- [x] 5단계 — 티켓 핵심 도메인
- [ ] 6단계 — 티켓 관계·의존성·휴지통
- [x] 7단계 — 설명·댓글·멘션
- [ ] 8단계 — 첨부파일
- [x] 9단계 — 목록·검색·대시보드
- [ ] 10단계 — 칸반 및 웹 UI 완성
- [ ] 11단계 — 운영 준비 및 최종 검증

2026-10-05 현재 13개 구분 중 8개(0·1·데이터 선행 준비·3·4·5·7·9단계)가 완료됐다. 2단계는 감사 로그 정리 명령, 6단계는 티켓 영구 삭제, 8단계는 첨부파일 삭제·보존·영구 정리, 10단계는 주요 사용자 흐름 Browser 통합 테스트가 남아 있다. 11단계의 운영·보안·복구 검증도 완료 전이다. 간트·보고서 실행과 Label·Ad-hoc 필터는 별도 후속 범위이며, 데이터 구조만 준비된 상태를 기능 완료로 세지 않는다.

2026-10-05 공통 cron scheduler 기반: DB 일정·실행 이력 테이블과 전용 Compose service를 추가했다. 활성 일정은 기동 시 crontab으로 복원하고 변경 시 동기화한다. 실행 이력으로 트리거 시각을 계산하지 않으며 중단 중 실행을 소급하지 않는다. 현재 실제 job은 등록하지 않았고 휴지통 30일 영구 삭제도 계속 보류한다. 상세 구조는 [scheduler 문서](docs/scheduler.md)를 따른다.

## 데이터 선행 준비 및 화면별 진행 방식

기능별 단계는 누락 점검용으로 유지한다. 실제 구현은 데이터 기반 이후 아래 화면 순서로 작은 동작을 연결하고 반복 확장한다(ARC-009).
모델만 준비된 기능의 서비스·API·화면·보안 검증은 완료로 표시하지 않는다.

- [x] MVP 전체 테이블·관계·제약·주요 인덱스 준비
- [x] 간트용 계획 일정·진행률·마일스톤·의존 일정 필드 준비
- [x] 티켓 변경 전후 상태와 버전별 이벤트 저장 구조 준비
- [x] 보고서 요청·프로젝트 범위·동결 입력·실행 시도·출력 저장 구조 준비
- [x] 보고서 스킬과 버전별 지침·입출력 JSON Schema 저장 구조 준비
- [x] 필터·이벤트·보고서 in/out·스킬 DTO 및 JSON Schema·한글 예시 준비
- [x] 기존 identity 데이터 보존 upgrade, populated downgrade/re-upgrade, 모델·제약 일치 검증
- [x] [데이터 구조 명세](docs/mvp_data_model.md)와 [보고서 계약](docs/reporting_contracts.md) 작성
- [x] Markdown v1 본문 저장 구조를 Tiptap JSON body schema v2로 교체하는 모델·migration·계약 갱신

완료 기준: 실제 migration으로 생성한 DB에서 데이터 구조와 계약을 검증한다. 이력 수집기, 간트·보고서 실행 기능의 완료를 의미하지 않는다.

2026-09-17 검증: Windows Python 3.13 및 Docker Linux Python 3.12에서 각각 pytest 83개와 Ruff 검사를 통과했다. PostgreSQL과 macOS 실환경 검증은 후속이다.

2026-09-26 구조화 본문 정책 변경: 실제 ticket·comment·ticket_history 데이터가 없는 상태에서 Markdown v1 계약을 폐기하고 Tiptap JSON body schema v2로 전환하기로 했다. Tiptap은 exact version의 self-hosted editor bundle과 문서 구조에만 사용하며 댓글·멘션·첨부파일·변경 이력은 서버에서 직접 구현한다. 기존 migration은 유지하고 새 revision이 관련 row 0건을 preflight하며, v1 dual-read와 converter는 만들지 않는다. 데이터 선행 준비 단계는 새 모델·migration·계약 검증이 끝날 때까지 다시 진행 중으로 둔다.

2026-09-26 구조화 본문 전환 완료: Alembic head `20260926_0004`에서 ticket·comment·ticket_history zero-row preflight 후 Markdown v1 컬럼을 Tiptap JSON body schema v2로 교체했다. exact version의 self-hosted editor bundle, 서버 allowlist 검증, sanitized HTML·plain text 파생 경계, 티켓 생성·편집·상세·인라인 상세 round-trip과 변경 이력·감사·optimistic locking 회귀를 검증했다. 목록·대시보드는 plain text만 추출하고 칸반은 본문을 변환하지 않는다. Windows Python 환경에서 pytest 258개와 Ruff 검사를 통과했고 PR #10의 test·PowerShell runner도 통과했다. 댓글·멘션·첨부파일 서비스, 실제 브라우저 자동화, 현재 변경분의 Docker Linux 재검증과 배포용 standalone image 구성은 후속이다.

2026-09-27 댓글 관리 연결: 티켓 하위 댓글 조회·작성·수정·soft delete를 JSON API와 상세 화면에 연결하고, 게스트 읽기 전용·프로젝트 사용자 이상 전체 관리·시스템 관리자 override 감사·비활성 프로젝트와 휴지통 티켓 차단·종료 티켓 사후 기록을 적용했다. 빈 댓글 거부, 같은 티켓의 attachment image 참조 검사, optimistic locking, no-op 수정, 감사 실패 rollback과 작성자 join 기반 고정 query 수를 검증했다. 설명과 댓글은 공용 editor macro와 동일 renderer·sanitizer를 사용하며 editor별 label·placeholder와 form payload를 분리한다. Windows Python 3.13에서 pytest 270개와 Ruff 검사를 통과했고, Docker Linux Python 3.12에서는 플랫폼 전용 12개를 제외한 전체 테스트와 Ruff 검사 및 frontend bundle build를 통과했다. 멘션과 실제 첨부파일 service·UI는 후속이다.

| 순서 | 화면별 첫 연결 범위 | 상태 |
|---|---|---|
| 1 | 로그인·비밀번호 변경·초기 관리자 | 완료 |
| 2 | 사용자·조직의 기본 조회·생성 | 완료 |
| 3 | 프로젝트 생성·참여자 등록·내 프로젝트 | 완료 |
| 4 | 티켓 생성·목록·상세를 같은 DB 데이터로 연결 | 완료 |
| 5 | 내 작업 대시보드·칸반 조회 | 완료 |
| 6 | 티켓 편집·FSM·이력·충돌 처리·칸반 이동 | 완료 |
| 7 | 각 화면의 댓글·멘션·첨부·관계·휴지통·저장 필터·조직 JSON 확장 | 진행 중 |

2026-09-25 티켓 휴지통·복구 연결: Epic 또는 Task를 휴지통으로 이동할 때 현재 활성 하위 티켓을 하나의 deletion batch에 포함하고, 같은 batch 단위로 복구하도록 API와 실제 프로젝트 휴지통 화면을 연결했다. 다른 활성 티켓이 미완료 삭제 대상에 의존하면 이동을 차단하며, 일반 목록·칸반·상세 조회는 기존 soft-delete 제외 조건을 유지한다. 게스트와 비활성 프로젝트는 휴지통을 조회할 수 있지만 이동·복구는 할 수 없고, 각 티켓의 `DELETED`·`RESTORED` 이력과 감사 로그는 계층 작업별 같은 operation UUID로 기록한다. 기존 Alembic head `20260923_0003`을 유지한다. 기능 전용 통합 테스트 5개를 포함한 전체 pytest 233개와 Ruff 검사를 통과했다. 기존 테스트 도구 deprecation 경고 2건은 남아 있으며 영구 삭제 명령과 scheduler, 첨부파일 연계 정리는 후속이다.

2026-09-25 티켓 관계 연결: `Related` 대칭 관계와 `Depends on` 방향 관계의 조회·생성·삭제를 API, 전체 상세와 인라인 상세 화면에 연결했다. 자기 관계·완전 중복·다른 프로젝트 관계를 차단하고 게스트 읽기 전용, 비활성 프로젝트·종료 티켓 잠금, CSRF와 optimistic locking을 적용했다. 관계 변경은 양 끝 티켓의 version과 `RELATION_CHANGED` 이력을 같은 operation UUID로 갱신하며 감사 실패 시 전체 rollback한다. 기존 Alembic head `20260923_0003`을 유지한다. Windows Python 3.13에서 pytest 228개와 Ruff 검사를 통과했으며 기존 테스트 도구 deprecation 경고 2건은 남아 있다.

2026-09-24 문서 동기화 검증: 현재 `main`의 Alembic head는 `20260923_0003`이며 Windows Python 3.13 가상환경에서 pytest 212개와 Ruff 검사를 통과했다. 전체 테스트에는 migration upgrade·downgrade와 모델 일치 검증이 포함된다. 테스트 클라이언트 의존성의 deprecation 경고 2건과 macOS 실환경 검증은 남아 있다. 5단계는 모든 필수 하위 항목과 완료 기준을 충족하여 전체 현황도 완료로 맞췄다.

2026-09-19 프로젝트 연결: 생성·최초 관리자 지정·참여자 조회/추가·내 프로젝트를 HTML과 API에서 같은 서비스로 연결했다. 프로젝트 목록과 구성원 조회에 membership 조건을 적용하고 시스템 관리자 override, CSRF, 중복·동시 등록, 감사 실패 롤백, 권한 변경 재검사를 검증한다. 기존 head `20260917_0002`를 유지한다. 프로젝트 수정·비활성화·기존 참여자 역할 변경/제거는 미완료다. 실제 프로젝트의 미구현 업무 경로는 권한 검사 후 준비 중 안내를 제공한다.

2026-09-22 티켓 첫 연결: 프로젝트 구성원이 티켓을 생성하고 키·제목 검색 목록, 인라인 상세와 직접 상세에서 같은 DB 데이터를 조회하도록 HTML과 API를 연결했다. 프로젝트별 원자 번호 발급, Epic·Task·Subtask 생성 계층, 활성 구성원 담당자, 프로젝트 격리, 시스템 관리자 override 감사, CSRF, 생성 이력·감사 실패 rollback과 동시 생성을 검증한다. Windows Python 3.13에서 pytest 207개와 Ruff 검사를 통과했고 Docker Linux Python 3.12에서는 플랫폼 전용 12개를 제외한 테스트와 Ruff 검사를 통과했다. Markdown 렌더링, 편집·FSM·댓글·관계·첨부·이력 화면은 후속이다. 기존 head `20260917_0002`를 유지한다.

2026-09-22 대시보드·칸반 조회 연결: 내 티켓을 현재 담당 티켓 또는 담당자가 없는 내가 만든 티켓으로 정의하고, 참여 프로젝트만 대상으로 미완료·기한 초과·이번 주 마감·최근 수정 및 미확인 멘션을 HTML과 API에서 조회한다. 생성자 단독 조건은 전역 티켓 목록 필터로 제공한다. 칸반은 상태 열, Epic과 Epic 없음 그룹, 같은 상태 Subtask 중첩과 다른 상태 Subtask의 상위 Task 식별 그룹을 읽기 전용으로 연결했다. soft-delete 제외, 프로젝트 격리, 시스템 관리자 override 감사와 데이터 규모에 독립적인 조회 횟수를 검증했다. Windows Python 3.13에서 pytest 211개와 Ruff 검사를 통과했다. 멘션 읽음 처리, 칸반 필터·드래그와 상태 변경은 후속이다.

2026-09-23 티켓 편집·상태 전이 연결: 제목·설명 원문·중요도·담당자·마감일·상위 티켓 편집과 전용 FSM 상태 전이 API·HTML을 실제 데이터에 연결했다. 당시 권한 정책과 감사되는 시스템 관리자 override, 비활성·종료 티켓 쓰기 차단, 계층 이동·순환 방어, 의존 대상 완료 차단, Epic 미완료 Task 확인, 최초 착수·완료·취소 시각, 필수 expected_version과 stale 409를 적용했다. 한 버전당 전체 전후 snapshot 이력 한 건과 감사 로그를 같은 transaction에 기록하고 no-op·실패·충돌 rollback을 검증한다. Windows Python 3.13에서 pytest 221개와 Ruff 검사를 통과했다. 관계 생성·삭제와 칸반 드래그는 후속이었으며 당시 head `20260917_0002`를 유지했다. 이후 같은 날 프로젝트 권한 정책을 세 역할로 재정의하고 칸반 이동을 연결했다.

2026-09-23 칸반 상태 이동 연결: 브라우저 기본 drag-and-drop과 키보드용 상태 선택 control을 기존 전이 API에 연결했다. 카드별 수정 권한·FSM 허용 상태·버전과 미완료 의존성을 보드 조회에서 일괄 계산하고, 완료 drop을 사전 차단하되 서버에서 권한·FSM·의존성·optimistic locking을 최종 재검증한다. 성공과 stale 409 뒤에는 보드를 다시 읽어 Task·Subtask 계층 표시를 동기화한다. Windows Python 3.13에서 pytest 222개와 Ruff 검사를 통과했다. 같은 상태 안의 순서 변경과 실제 브라우저 자동화 검증은 후속이며 기존 head `20260917_0002`를 유지한다.

2026-09-23 프로젝트 권한 정책 재정의: 프로젝트 역할을 게스트·사용자·관리자로 통일하고 게스트는 읽기 전용, 사용자는 creator·assignee와 무관한 전체 티켓 업무, 관리자는 프로젝트·참여자 관리까지 담당하도록 확정했다. 시스템 관리자는 사용자·조직·전체 프로젝트와 보존·정리 작업을 관리하고 자동 작업은 별도 사용자 역할이 아닌 system actor로 기록한다.

2026-09-23 프로젝트 권한 정책 구현: `20260923_0003`에서 게스트 역할 CHECK를 추가하고 프로젝트·참여자 화면에 세 역할을 표시한다. 게스트의 프로젝트·티켓·보드 조회는 허용하되 생성·편집·상태 전이를 서버에서 차단하고 담당자 후보에서 제외했다. 프로젝트 사용자는 creator·assignee와 무관하게 모든 티켓을 편집·전이하며 시스템 관리자 write override는 감사한다. downgrade는 권한 상승을 피하기 위해 게스트 membership을 제거한다. 기존 참여자 역할 변경·제거와 마지막 관리자 보호는 후속이다. 현재 검증 결과는 위 2026-09-24 기록을 기준으로 한다.

2026-09-19 최종 검증: Windows Python 3.13과 Docker Linux Python 3.12에서 각각 pytest 175개 및 Ruff 검사를 통과했다. migration 왕복·모델 일치 검증도 전체 테스트에 포함된다. 임시 DB의 브라우저에서 프로젝트 생성 → 참여자 등록 → 해당 사용자 재로그인 → 내 프로젝트 반영을 확인했다. 브라우저 화면 캡처가 시간 초과되어 정밀 배치 검증은 남아 있으며, 기존 테스트 도구 deprecation 경고 2건과 macOS 실환경 검증도 후속이다.

2026-09-19 PowerShell 래퍼 검증: Windows PowerShell 5.1에서 포트 검증기·래퍼 테스트 17개와 Ruff 검사를 통과했다. Docker 대역으로 실제 컨테이너를 변경하지 않고 start/stop 인자, 공백·한글 설정 경로, 잘못된 설정 차단, 종료 코드 전달과 호출 환경 복원을 검증했다. Windows CI에 설치된 PowerShell별 동일 검증을 추가했다.

2026-09-19 Compose 개발 mount 검증: Windows Docker Desktop에서 기본 이미지에 `app`·`migrations`·`alembic.ini`가 없고 Compose 실행 시에만 해당 경로가 bind mount되는 것을 확인했다. 설정 파일은 읽기 전용으로 mount된다. `down` 후 `start`를 반복해 의존성 설치 레이어가 `CACHED`로 유지되고 readiness가 성공하는지 검증했으며, pytest 187개와 Ruff 검사를 통과했다. macOS 실환경 검증은 후속이다.

2026-10-07 선택적 로컬 설정: `config/application.toml`을 Git 추적에서 제외하고 `config/application.toml.template`을 제공한다. 설정 파일이 없으면 앱과 Compose가 동일한 기본 설정으로 기동하며, 존재하는 잘못된 설정은 계속 거부한다. 호스트별 설정 변경이 pull과 충돌하지 않도록 설정 디렉터리를 읽기 전용으로 마운트한다. Windows 전체 pytest(선택 실행 Browser 2개 제외)와 Ruff를 통과했고 Docker에서 설정 파일 없는 기동·readiness 및 원래 설정 경로 복구를 확인했다.

2026-09-18 사용자·조직 연결 검증: Windows Python 3.13 및 Docker Linux Python 3.12에서 각각 pytest 149개와 Ruff 검사를 통과했다. 임시 DB와 Headless Edge에서 조직 생성 → 사용자 등록 → 실제 목록 갱신을 확인하고 1440px 화면의 배치·가로 넘침·브라우저 오류를 점검했다. 관리 기능 테스트는 관리자 권한·CSRF·중복·비활성 상위 조직·검색/페이지 이동·감사 실패 롤백과 새 사용자 로그인/비밀번호 변경을 검증한다. 조직 트리가 있는 DB의 base downgrade·재적용 회귀 테스트를 추가했다. 신규 revision 없이 head `20260917_0002`를 유지한다.

2026-09-17 인증 연결 검증: Windows Python 3.13 및 Docker Linux Python 3.12에서 각각 pytest 128개와 Ruff 검사를 통과했다. 임시 DB의 브라우저에서 최초 접근 → 로그인 → 초기 비밀번호 변경 화면 → 로그아웃을 확인했고, 변경·재로그인·원래 경로 복귀·전체 세션 폐기는 HTTP 통합 테스트로 검증했다. 인증용 migration은 추가하지 않았으며 당시 Alembic head는 `20260917_0002`였다. 당시 업무 화면은 예시 데이터로 남아 있었다. 테스트 도구의 deprecation 경고 2건과 macOS 실환경 검증은 후속이다.

각 쓰기 기능은 권한·입력 검증·감사 처리와 필요한 시스템 로그를 함께 구현한다. 티켓의 생성 이벤트부터 기록하며 후속 보고서 단계까지 이력 기록을 미루지 않는다.

## 0단계 — 프로젝트 골격

- [x] Python 패키지와 FastAPI 애플리케이션 진입점 구성
- [x] API, domain, service, repository, model, schema 및 web 계층 디렉터리 구성
- [x] `pyproject.toml` 의존성과 개발 도구 설정
- [x] 외부 `application.toml` 설정 파일 구성
- [x] 환경 변수 → 외부 설정 → 기본값 우선순위 적용
- [x] 설정값 타입·범위 및 알 수 없는 설정 검증
- [x] Dockerfile과 Docker Compose 구성
- [x] Compose 개발 소스 bind mount와 소스 변경에 독립적인 이미지 의존성 레이어 구성
- [x] DB·첨부파일·백업 데이터와 최상위 설정 디렉터리의 독립 volume mount 구성
- [x] 외부 설정의 서버 포트를 Compose 포트 매핑과 health check에 반영하는 실행 래퍼 구성
- [x] 동일한 start·stop을 제공하는 PowerShell 실행 래퍼와 명령·설정·종료 코드·호출 환경 복원 테스트 구성
- [x] SQLAlchemy engine과 SQLite 외래 키 활성화
- [x] Alembic 실행 환경 구성
- [x] `/health`와 `/health/ready` 제공
- [x] pytest와 Ruff 기본 검증 구성
- [x] 공통 시스템 로그 포맷과 외부 로그 레벨 설정 구성
- [x] Docker 이미지 빌드 및 컨테이너 health check 검증

완료 기준: Docker Compose로 애플리케이션이 기동되고 SQLite 연결을 포함한 readiness 응답이 성공한다.

## 1단계 — 공통 DB 및 개발 기반

- [x] UTC 기반 날짜·시간 공통 규칙 구현
- [x] ID, 생성일시 및 수정일시 공통 모델 또는 mixin 구현
- [x] 요청 단위 DB session과 transaction 경계 확정
- [x] 서비스 계층용 transaction context 구성
- [x] 단위 테스트용 DB fixture 구성
- [x] HTTP 통합 테스트용 애플리케이션 fixture 구성
- [x] 실제 migration을 사용한 upgrade 테스트 구성
- [x] migration downgrade 테스트 구성
- [x] SQLite와 향후 PostgreSQL을 고려한 공통 타입 규칙 문서화
- [x] CI에서 pytest, Ruff 및 migration 검증 실행

완료 기준: 빈 DB를 migration으로 생성하고 테스트 후 되돌릴 수 있으며, CI에서 동일한 검증이 반복 가능하다.

## 2단계 — 사용자·인증·감사 로그

- [x] `Organization` 최소 모델 설계
- [x] `User` 모델 및 시스템 역할 구현
- [x] `Session` 모델 구현
- [x] `AuditLog` 모델 구현
- [x] 최초 schema migration 작성
- [x] Argon2id 비밀번호 hash 및 verify 구현
- [x] 로그인 ID와 비밀번호 정책 구현
- [x] 로그인·로그아웃 API 구현
- [x] opaque 세션 토큰 생성과 서버 측 세션 검증 구현
- [x] 세션 쿠키 보안 설정 적용
- [x] 비활성 사용자의 로그인 및 기존 세션 차단
- [x] 비밀번호 변경 시 기존 세션 무효화
- [x] 최초 관리자 bootstrap 구현
- [x] 최초 로그인 및 비밀번호 초기화 후 변경 강제
- [x] 주요 인증 동작의 감사 로그 기록
- [ ] 30일 기본 보존 및 설정 가능한 감사 로그 정리 명령 구현
- [x] 인증 및 bootstrap 단위·통합 테스트 작성

완료 기준: 빈 DB에서 최초 관리자를 생성하고 로그인·로그아웃·비밀번호 변경을 수행할 수 있으며 관련 감사 로그가 남는다.

## 3단계 — 시스템 관리자 및 조직 관리

- [x] 시스템 관리자 인증 dependency 구현
- [x] 사용자 생성·조회 및 검색·페이지네이션 구현
- [x] 사용자 수정·비활성화 구현
- [x] 관리자 비밀번호 초기화 구현
- [x] 마지막 활성 시스템 관리자 보호
- [x] 비활성화된 사용자의 모든 세션 제거
- [x] 조직 self-referencing tree 조회 구현
- [x] 같은 부모 아래 조직명 DB 고유 제약(최상위 포함)
- [x] 조직명 중복 오류의 서비스·화면 처리
- [x] 자기 자신 또는 하위 조직으로의 이동 차단
- [x] 최상위·하위 조직 생성 및 비활성 상위 조직 검증
- [x] 조직 수정·이동·비활성화 구현
- [x] 사용자·조직 관리 화면의 실제 조회·생성 연결
- [x] 사용자·조직 관리 화면의 수정·비활성화·초기화·이동 확장
- [x] 조직 JSON export 구현
- [x] 조직 JSON import 형식 및 schema version 검증
- [x] 중복 키·형제 이름·순환 구조 검증
- [x] import 적용 전 추가·갱신·충돌 미리보기 구현
- [x] import 전체를 하나의 transaction으로 적용
- [x] 사용자·조직 조회·생성의 권한·CSRF·감사·중복·롤백 테스트 작성
- [x] 후속 관리 쓰기의 감사 로그와 권한 테스트 확장

완료 기준: 관리자가 사용자와 조직 트리를 안전하게 관리하고 조직 JSON을 비파괴 방식으로 왕복할 수 있다.

2026-09-28 사용자 계정 lifecycle 연결: 불변 로그인 ID를 제외한 표시 이름·이메일·소속 조직·시스템 역할·활성 상태 변경과 관리자 임시 비밀번호 초기화를 JSON API와 사용자 관리 화면에 연결했다. 마지막 활성 시스템 관리자의 동시 강등·비활성화를 SQLite 쓰기 잠금 안에서 차단하고, 사용자 비활성화와 비밀번호 초기화 시 기존 session을 모두 폐기한다. 변경·비활성화·재활성화·초기화 감사와 감사 실패 rollback을 검증했으며 Windows Python 환경에서 전체 pytest 321개와 Ruff 및 diff 검사를 통과했다. 조직 수정·이동·비활성화와 JSON 입출력이 남아 있어 3단계 전체는 진행 중이다.

2026-10-05 조직 관리 확장: 조직명·설명·상위 조직·활성 상태 변경을 관리자 API와 웹 화면에 연결했다. 이동 순환·형제 이름 중복·비활성 상위 계층을 차단하고 기존 사용자 로그인·프로젝트 참여는 보존한다. 변경과 감사는 같은 transaction에서 처리하며 no-op은 변경 감사를 남기지 않는다. Windows Python 전체 pytest와 관리 기능 통합 테스트, Ruff·diff 검사를 통과했다. 기존 dependency deprecation 경고 2개는 남아 있다. 조직 JSON 입출력은 다음 작업으로 남아 있어 3단계 전체는 진행 중이다.

2026-10-05 조직 JSON 입출력: 전체 조직 트리의 versioned JSON export, key 기반 추가·갱신, 미포함 조직 보존, 적용 전 변경·충돌 미리보기와 session·문서·현재 상태에 묶인 token 검증을 연결했다. 형식·중복 key/이름·순환·비활성 상위 정책, CSRF·관리자 권한·stale 차단, 부모·자식 위치 교환과 감사 실패 rollback을 검증했다. Windows Python 전체 pytest, 조직 전용 통합 테스트 14개와 Ruff·diff 검사를 통과했다. 새 DB migration은 없으며 3단계 완료 기준을 충족했다. 기존 dependency deprecation 경고 2개와 기본 실행 시 Browser·PowerShell 테스트의 조건부 skip 2개는 남아 있다.

## 4단계 — 프로젝트와 접근 권한

- [x] `Project` 모델과 고유 프로젝트 키 구현
- [x] `ProjectMember` 및 프로젝트 관리자·사용자 역할 저장 구조 구현
- [x] 프로젝트 게스트 역할을 추가하는 모델·CHECK constraint migration 구현
- [x] 프로젝트 생성·조회 및 내 프로젝트 화면 연결
- [x] 프로젝트 수정·비활성화 구현
- [x] 프로젝트 구성원 조회·추가 및 등록 시 역할 지정
- [x] 기존 프로젝트 구성원 역할 변경·제거 구현
- [x] 마지막 프로젝트 관리자 제거·하위 역할 변경 차단
- [x] `require_project_member` 구현
- [x] `require_project_user` 구현
- [x] `require_project_admin` 구현
- [x] 시스템 관리자 override 및 감사 로그 구현
- [x] repository 조회 조건에 membership 필터 적용
- [x] 접근 불가 프로젝트의 존재 여부 은폐
- [x] 조직 소속과 프로젝트 권한이 자동 연동되지 않는지 검증
- [x] 역할별 401·403 및 프로젝트 격리 테스트 작성
- [x] 게스트 읽기 전용·담당자 제외와 세 역할 권한 회귀 테스트 작성

완료 기준: 프로젝트마다 데이터와 권한이 격리되고 프로젝트 게스트·사용자·관리자의 역할 차이가 서버에서 강제된다.

2026-09-28 참여자 역할 변경·제거 연결: API·HTML form과 공통 service, 마지막 관리자·미완료 담당 티켓·비활성 상태 보호, 종료·휴지통 티켓 재활성화 시 담당자 적격성 검사를 연결했다. 같은 역할 요청은 membership 변경 기록을 만들지 않되 시스템 관리자 override 감사를 유지한다. Windows Python 환경에서 전체 pytest 311개와 Ruff 및 diff 검사를 통과했다. 프로젝트 수정·비활성화가 남아 있어 4단계 전체는 진행 중이다.

2026-09-28 프로젝트 수정·활성 상태 관리 연결: 불변 key를 제외한 이름·설명·활성 상태 변경과 재활성화를 JSON API와 설정 화면에 연결했다. 비활성화는 데이터를 보존하면서 기존 읽기 전용 제약을 즉시 적용하고, no-op·시스템 관리자 override·감사 실패 rollback을 검증한다. Windows Python 환경에서 전체 pytest 313개와 Ruff 및 diff 검사를 통과했으며, 4단계의 필수 하위 항목과 완료 기준을 모두 충족했다.

## 5단계 — 티켓 핵심 도메인

- [x] `Ticket` 모델과 Epic·Task·Subtask 유형 저장 구조 구현
- [x] 프로젝트별 단조 증가 티켓 번호 발급
- [x] 표시 키 생성 및 번호 재사용 방지
- [x] 제목, 설명, 중요도, 담당자 및 마감일 필드 구현
- [x] Epic → Task → Subtask 계층 규칙 구현
- [x] 다른 프로젝트 부모 지정 차단
- [x] 계층 순환 참조 차단
- [x] Task 이동 시 Subtask 유지 정책 구현
- [x] 등록·진행중·완료·보류·취소 FSM 구현
- [x] 완료일시와 취소일시 처리
- [x] 완료·취소 티켓 업무 필드 수정 차단
- [x] creator·assignee 수정 제한 제거 및 프로젝트 사용자 이상의 전체 티켓 수정·상태 전이 권한 구현
- [x] Ticket ORM 버전 번호 및 stale write 차단 검증
- [x] 서비스·API의 optimistic locking 충돌 처리
- [x] `TicketHistory` 모델과 변경 전후 상태·이벤트 계약 구현
- [x] 주요 필드 변경 이력의 서비스 기록 구현
- [x] 티켓 생성·상세·수정·상태 전이 API 구현
- [x] 게스트·사용자·관리자 기준 계층·FSM·권한·동시 수정 테스트 갱신

완료 기준: API에서 티켓을 생성하고 계층과 권한을 지키며 상태를 변경할 수 있고 모든 주요 변경이 추적된다.

## MVP 확장 — 자유 Label·Ad-hoc Text 필드

범위 검토 A02·A20과 TKT-014·DB-023을 구현한다. 기존 5단계의 계층·권한 정책은 유지하며, [상세 계약](docs/ticket_properties.md)을 따른다.

- [x] 자유 입력 복수 Label 및 ticket-local 이름·타입·값 계약
- [x] 타입 확장 가능한 JSON 저장 구조와 기존 데이터 보존 migration
- [x] Text 필드 생성·수정·제거 및 전체·인라인 상세 표시
- [x] Label 생성·편집 및 목록·칸반 chip 표시
- [x] 생략된 속성 보존, 명시적 제거, no-op·version 충돌·변경 이력 연결
- [x] 입력 검증·XSS·프로젝트 권한·종료 잠금·감사 실패 rollback·휴지통 복구 검증
- [x] 기존 데이터가 있는 migration upgrade·downgrade·re-upgrade 검증
- [x] 실제 Browser에서 Text 필드 추가·수정·제거 component 검증
- [x] 최종 전체 회귀 검증 결과 기록

2026-10-03 구현 검증: Windows Python 환경의 전체 pytest 364개가 통과했다. 이후 Unicode 정규화 후 길이 초과 회귀 2개를 추가하고 속성·계약 검증 21개를 재실행해 통과했다. 실제 Edge의 편집 component 테스트 2개, Ruff·JavaScript 문법·diff 검사도 통과했다. 검증은 임시 SQLite DB를 사용했으며 기존 업무 DB에는 migration을 실행하지 않았다. 기존 FastAPI/Starlette dependency deprecation 경고 2개는 남아 있다. 전체 배포 E2E·macOS·PostgreSQL 검증은 이 완료 범위에 포함하지 않는다.

별도 후속: Text 이외 타입과 전용 입력 도구, 시스템 제공 선택형 확장 필드. Label·추가 필드의 필터 연계는 별도 후속 필터 작업에서 논의한다.

2026-10-03 사용자 요청에 따른 로컬 DB 적용: SQLite online backup 후 `20260929_0006`에서 `20261003_0007`로 upgrade했다. `alembic check`, DB integrity·FK 검사와 백업 대비 기존 테이블의 모든 기존 컬럼 값 보존을 확인했다. 업무 DB·백업 파일은 Git에 포함하지 않는다.

## 6단계 — 티켓 관계·의존성·휴지통

- [x] `Related` 대칭 관계 구현
- [x] `Depends on` 방향 관계 구현
- [x] 자기 관계와 완전 중복 관계 차단
- [x] 다른 프로젝트 티켓 간 관계 차단
- [x] 관계의 정방향·역방향 표시 DTO 구현
- [x] 미완료 의존 대상이 있을 때 완료 전이 차단
- [x] Epic과 Task의 하위 티켓 포함 휴지통 이동 구현
- [x] 활성 티켓의 의존 대상 삭제 차단
- [x] 계층 단위 티켓 복구 구현
- [x] 휴지통 항목의 일반 조회와 수정 차단
- [ ] 기본 30일 후 영구 삭제 명령 구현
- [x] 게스트 읽기 전용과 프로젝트 사용자 이상의 관계·휴지통·복구 권한 테스트 작성
- [ ] 영구 삭제와 관리자 수동 실행·system actor 자동 실행 테스트 작성

완료 기준: 관계 규칙과 완료 차단이 모든 상태 변경 경로에서 동일하게 적용되고 삭제된 계층을 안전하게 복구할 수 있다.

## 7단계 — 설명·댓글·멘션

에디터와 저장 계약은 CNT-008·CNT-009, 배포 방식은 ARC-013, v1 폐기 방식은 DB-018을 따른다.

- [x] Tiptap core·extension exact version과 lock file 및 self-hosted 정적 bundle build 구성
- [x] 허용 node·mark·attribute와 `body_schema_version=2` JSON 계약 작성
- [x] Markdown v1 컬럼을 교체하는 zero-row preflight migration과 ORM·DTO 갱신
- [x] JSON 크기·깊이·node·attribute·URL·내부 참조 서버 검증 구현
- [x] Tiptap JSON 기반 HTML renderer·allowlist sanitizer·plain text 추출 구현
- [x] 제목·강조·밑줄·취소선·색상·크기·목록·들여쓰기·체크박스·인용·코드·링크·표 toolbar 구현
- [x] 링크 URL scheme과 렌더링 allowlist 보안 테스트 작성
- [x] 티켓 설명 편집·저장·조회 round-trip 구현
- [x] `Comment` 모델을 Tiptap document 계약과 ORM version 검사에 맞게 갱신
- [x] 댓글 작성·수정 서비스 구현
- [x] 프로젝트 사용자 이상의 프로젝트 내 전체 댓글 수정·soft delete 구현
- [x] 한 단계 대댓글과 삭제 댓글 자리표시자 조회 구현
- [x] 댓글 등록·수정·삭제 전 사용자 확인 적용
- [x] 티켓 생성·수정·상태 변경·관계·첨부·휴지통 변경 전 사용자 확인 적용
- [x] 설명과 댓글이 동일한 renderer를 사용하도록 구성
- [x] 현재 프로젝트 구성원 대상 멘션 후보 조회
- [x] 서버에서 멘션 대상의 프로젝트 접근 권한 재검증
- [x] `Mention` 모델과 원본·대상 DB 중복 방지 구현
- [x] 본문 수정 시 멘션 추가·삭제 차이 반영
- [x] 개별·전체 멘션 읽음 처리 구현
- [x] 접근 권한 상실 시 멘션 내용 은폐

완료 기준: 애플리케이션 서버가 제공하는 고정 버전 editor에서 설명과 댓글을 같은 구조화 문서 계약으로 안전하게 편집·렌더링하고, 권한이 있는 사용자만 멘션하여 확인할 수 있다. 댓글·멘션·이력은 Tiptap 외부 서비스 없이 서버 transaction에서 관리한다.

2026-09-27 댓글 thread 확장: 같은 프로젝트·티켓의 삭제되지 않은 원댓글에 한 단계 대댓글을 등록하도록 comment self-reference와 API·상세 화면을 연결했다. 삭제된 댓글은 저장 원문을 유지하되 일반 응답에서는 빈 document로 은폐하고 `삭제된 댓글입니다.` 자리표시자로 남겨 기존 대댓글의 맥락을 보존한다. 대댓글 재중첩과 삭제 댓글에 대한 새 답글은 거부한다. SQLite migration은 기존 멘션·첨부의 댓글 참조를 보존하는 upgrade·downgrade를 검증했으며 Windows Python 3.13에서 pytest 273개와 Ruff 검사를 통과했다.

2026-09-27 댓글 제출 확인: 댓글·대댓글 등록, 댓글 수정과 삭제 HTML form에 공용 `data-confirm-message` 확인 처리를 적용했다. 사용자가 확인을 취소하면 browser가 form 요청을 전송하지 않으며 JSON API 계약은 변경하지 않는다. frontend bundle build, Windows Python 3.13 전체 pytest 274개와 Ruff 검사를 통과했다.

2026-09-28 TaskItem editor checkbox 정렬 보정: `.field input`의 공용 100% 너비·42px 최소 높이 규칙이 Tiptap이 생성한 checkbox에도 적용되던 충돌을 editor 전용 CSS로 차단했다. checkbox를 16px로 고정하고 label·첫 문단 margin을 정렬해 편집 중 checkbox와 같은 줄의 텍스트가 어긋나지 않게 했다. frontend bundle build, Windows Python 환경 전체 pytest 323개와 Ruff 및 diff 검사를 통과했다.

2026-10-04 멘션 연결: 설명·댓글·대댓글에서 @ 후보 선택, 서버의 활성 membership 재검증, 원본·대상별 동기화와 대시보드 개별·전체 읽음 및 댓글 anchor 이동을 연결했다. 유지된 멘션의 읽음은 보존하고 제거 후 재추가는 미확인으로 갱신한다. v3 mention node와 v2 dual-read, 기존 데이터 보존 migration `20261004_0008`을 추가했으며 상세 정책은 [멘션 계약](docs/mentions.md)에 기록했다. 실제 Edge에서 입력·저장·수신자 확인을 검증했다. Windows 전체 pytest 429개(실제 Edge Browser 시나리오 4개 포함)를 통과했다. 이후 읽음 감사 rollback·휴지통 은폐와 canonical 멘션 이름 크기 제한 회귀 3개를 추가하고 본문·멘션 테스트 51개를 재실행해 통과했다(현재 수집 432개). Ruff·JavaScript 문법·frontend bundle build·diff 검사를 통과했고 7단계 필수 항목을 완료했다. 기존 dependency deprecation 경고 2개는 남아 있다. 기존 업무 DB에는 migration을 적용하지 않았으며 이 변경의 Docker Linux·macOS·PostgreSQL 검증은 후속이다.

## 8단계 — 첨부파일

운영 배포 전 전체 저장 용량과 최종 허용 확장자·MIME type 목록을 확인한다.
일반 첨부파일 기반과 본문 이미지 연결은 완료했으며, 삭제·접근 차단과 30일 후 영구 정리는 의도적으로 후순위 TODO로 미뤘다. 현재 저장 구조와 권한 정책은 [첨부파일 저장과 권한](docs/attachments.md)에 유지한다.

- [x] 첨부파일 저장소 interface 정의
- [x] 로컬 마운트 디렉터리 adapter 구현
- [x] `Attachment` 메타데이터 모델 구현
- [x] UUID 기반 내부 저장 키 생성
- [x] 경로 조작과 파일명 충돌 방지
- [x] 기본 25MB 크기 제한 및 외부 설정 적용
- [x] 확장자와 MIME type 동시 검증
- [x] 실행 파일과 스크립트 파일 차단
- [x] 게스트 다운로드와 프로젝트 사용자 이상 업로드 권한을 검사하는 API 구현
- [ ] 후순위: 프로젝트 사용자 이상의 첨부파일 삭제 권한을 검사하는 API 구현
- [x] 이미지 미리보기와 일반 파일 정보 제공
- [x] 본문 image node와 내부 attachment ID의 업로드·삽입·권한 검증 연결
- [ ] 후순위: 삭제 즉시 접근 차단 및 기본 30일 보존 구현
- [ ] 후순위: 실제 파일 영구 삭제 명령 구현
- [x] 파일 시스템과 DB 실패 시 보상 처리 테스트 작성

완료 기준: 마운트된 파일 저장소에서 권한·크기·형식을 검증하며 파일을 안전하게 제공하고 삭제할 수 있다.

2026-09-27 일반 첨부파일 기반 연결: 프로젝트 key와 전역 ticket ID를 사람이 찾을 수 있는 상위 경로로 사용하고 UUID 앞 4자를 두 단계 shard로 나눈 local storage adapter를 구현했다. 업로드는 mount root의 staging 영역에서 최대 크기·확장자별 MIME type·실제 signature 또는 OOXML container를 검증한 뒤 최종 경로로 원자 이동한다. 프로젝트 사용자 이상은 활성 프로젝트의 티켓에 일반 파일을 등록하고 게스트를 포함한 프로젝트 구성원은 권한 endpoint로 목록 조회·다운로드할 수 있다. 업로드는 티켓 version·CONTENT_CHANGED 이력·감사 로그를 같은 DB transaction에서 갱신하며 실패 시 blob을 보상 삭제한다. 전용 단위·통합 테스트 12개와 allowlist 설정 테스트 2개를 포함한 전체 pytest 290개 및 Ruff 검사를 통과했다. 첨부파일 삭제·30일 보존·영구 삭제는 후속이다.

2026-09-27 본문 이미지 연결: 기존 티켓의 설명·댓글 editor에서 raster image를 일반 첨부파일로 즉시 업로드하고 반환된 attachment ID를 Tiptap image node에 삽입한다. renderer의 `/attachments/{id}` 요청은 활성 attachment와 프로젝트·티켓 접근 권한을 검사한 뒤 `inline`으로 제공한다. image만 있는 설명도 상세 화면에서 표시하며 다른 티켓의 attachment 참조를 차단한다. 새 티켓은 생성 후 편집 화면에서 이미지를 추가하고, 본문 저장을 취소한 업로드도 일반 첨부파일로 유지한다. Windows Python 3.13 전체 pytest 294개와 Ruff 및 frontend bundle build를 통과했다. 참조 중인 image를 포함한 삭제 정책과 삭제 API는 후순위로 미뤘으며, 30일 후 blob 정리와 scheduler도 착수하지 않은 명시적 TODO로 유지한다.

## 9단계 — 목록·검색·대시보드

- [x] typed ticket filter DTO 구현
- [x] 칸반의 공통 필터·URL 보존·필터 제외 부모 식별 표시 연결
- [x] 유형·상태·중요도·계층·사용자·날짜 필터 구현
- [x] 생성일·수정일·마감일·중요도·번호 정렬 구현
- [x] 항상 안정적인 보조 정렬 적용
- [x] 10·20·50 서버 사이드 페이지네이션 구현
- [x] 목록과 count에 동일한 권한·필터 조건 적용
- [x] 현재 페이지 연관 데이터 batch 조회 및 N+1 방지
- [x] URL query parameter에 필터·정렬·페이지 상태 보존
- [x] 티켓 키와 제목 대상 단순 검색 구현
- [x] 개인 저장 필터 생성·불러오기·이름 변경·덮어쓰기·삭제 및 개인/공유 구분 UI 구현
- [x] 프로젝트 공유 필터 구현
- [x] 저장 필터 JSON schema version과 DTO 검증 구현
- [x] 개인 저장 필터의 입력·소유권·프로젝트 권한·참조 재검증 연결
- [x] 프로젝트 공유 저장 필터의 입력·관리·조회 권한 재검증 연결
- [x] 내 티켓·기한 초과·임박 티켓 집계와 생성자 단독 목록 필터
- [x] 최근 수정 티켓과 미확인 멘션 대시보드 구현
- [x] 목록·검색·대시보드 프로젝트 격리 테스트 작성

완료 기준: 접근 가능한 티켓만 안정적으로 필터링·검색·페이지 이동할 수 있고 내 작업 현황을 한 화면에서 확인할 수 있다.

2026-09-28 프로젝트 티켓 목록 filter·sort 연결: 기존 `TicketFilter` v1 계약을 프로젝트 목록 API와 화면에 적용해 유형·상태·중요도, Epic·직접 상위, 생성자·담당자·미지정 담당자, 생성·수정·마감일 범위를 조합하고 생성일·수정일·마감일·중요도·티켓 번호의 양방향 정렬을 제공한다. Epic 조건은 Epic 자체와 하위 Task·Subtask를 포함하며, 날짜 화면 값은 Asia/Seoul 날짜 경계로 변환한다. 목록과 count는 같은 권한·filter query를 사용하고 안정적인 ID 보조 정렬과 due date NULL 후순위를 유지한다. filter·정렬·페이지 크기·현재 페이지는 pagination과 inline 상세 link의 URL query에 보존한다. Windows Python 환경에서 전체 pytest 327개와 Ruff 및 diff 검사를 통과했다.

2026-10-04 칸반 기본 필터 연결: 목록과 칸반이 같은 query 검증·repository 필터·HTML form을 공유하도록 연결했다. 키·제목, 유형·상태·중요도, Epic·직접 상위, 생성자·담당자·미지정과 날짜 조건을 지원하고, 미일치 상위 티켓은 그룹 식별에만 사용해 일치하는 Subtask를 보존한다. 모든 상태 열·필터 밖 의존성 검사·기존 카드 순서를 유지하며 목록 전환과 drag 재조회에서 URL 조건을 보존한다. Windows Python 전체 pytest 379개(실제 Edge Browser 테스트 포함), Ruff·JavaScript 문법·diff 검사를 통과했다. Browser에서 form 제출·초기화·목록 왕복·drag 취소/성공·재조회와 1440px 배치를 확인했다. 기존 dependency deprecation 경고 2개는 남아 있으며 DB migration과 기존 업무 DB 변경은 없다. Label·Ad-hoc 필터, 개인·공유 저장 필터와 macOS 실환경 검증은 후속이다.

2026-10-04 개인 저장 필터: 목록·칸반에서 현재 적용된 조건·정렬·페이지 크기의 생성·불러오기·이름 변경·덮어쓰기·삭제를 구현했다. 개인 영역은 `나만 보기`, 공유 영역은 `구성원 공용 · 준비 중`으로 구분한다. 본인 소유권·현재 프로젝트 권한·schema·참조를 재검증하고 CSRF·동시 수정·중복 이름을 차단하며 감사 기록을 같은 transaction에 저장한다. Windows Python 전체 pytest 395개(실제 Edge Browser 시나리오 2개 포함), 개인 필터 통합 테스트 16개와 Ruff·JavaScript 문법·diff 검사를 통과했다. 날짜 경계 오류 방어 보완 후 개인 필터 테스트를 재검증했다. 기존 dependency deprecation 경고 2개는 남아 있다. DB migration은 없으며 프로젝트 공유 필터의 실제 생성·관리는 후속이다.

2026-10-04 프로젝트 공유 저장 필터: 프로젝트 관리자·시스템 관리자의 생성·이름 변경·덮어쓰기·삭제와 구성원·게스트의 목록·칸반 적용을 연결했다. 개인·공유 영역을 명시적으로 구분하며 공유 관리 control은 활성 프로젝트 관리자에게만 표시한다. 생성자 이탈 후 현재 관리자 관리, 비활성 프로젝트 읽기 전용, 공개 범위·프로젝트 격리, 입력·참조 재검증, CSRF·stale·동시 중복 방어와 감사 rollback을 검증했다. 공통 입력 DTO·조건 검증·UI script를 재사용하고 DB migration은 추가하지 않았다. Windows Python 전체 pytest 412개(실제 Edge Browser 시나리오 3개 포함), 개인·공유 통합 테스트 33개와 Ruff·JavaScript 문법·diff 검사를 통과했다. 기존 dependency deprecation 경고 2개는 남아 있다. 9단계의 모든 필수 항목과 완료 기준을 충족했으며 Label·Ad-hoc 필터 연계는 별도 후속 범위다.

## 10단계 — 칸반 및 웹 UI 완성

- [x] 화면 인벤토리 기반 탐색 가능한 비동작 UI 목업 구성
- [x] 공통 레이아웃과 디자인 토큰 구성
- [x] 로그인 및 비밀번호 변경 화면 구현
- [x] 사용자·조직·프로젝트 관리 화면 구현
- [x] 티켓 목록과 인라인 상세 패널 구현
- [x] 직접 접근 가능한 전체 티켓 상세 페이지 구현
- [x] Task·Subtask 상세의 상위·하위·같은 Task 계층 탐색과 상태 표시 구현
- [x] 상태별 칸반 열 구현
- [x] Epic 그룹 접기·펼치기 구현
- [x] Epic 없는 Task 그룹 구현
- [x] 같은 상태의 Task·Subtask 계층 표시
- [x] 다른 상태의 Subtask 부모 식별 그룹 표시
- [x] Subtask 카드의 배경색 구분과 왼쪽 들여쓰기 적용
- [x] 카드에 키·제목·중요도·담당자·마감일 표시
- [x] 드래그 대상의 FSM 허용 여부 표시
- [x] 카드별 상태 선택 control 제거 및 drag-only 상태 변경 UI 적용
- [x] 완료 의존성이 남은 카드의 완료 drop 차단
- [x] 서버에서 권한·FSM·의존성 재검증
- [x] optimistic locking 충돌 시 보드 새로고침 안내
- [x] 티켓 목록·상세·칸반·대시보드의 업무 정보 글꼴 가독성 기준 적용
- [x] 내 프로젝트 즐겨찾기 별표와 공통 내비게이션 고정 목록 구현
- [x] 새 티켓 유형별 상위 티켓 후보 동적 제한 구현
- [x] 칸반 카드 중요도 색상을 티켓 목록과 동일하게 표시
- [x] 공통 왼쪽 navigation sidebar 접기·펼치기와 상태 유지 구현
- [ ] 주요 사용자 흐름 브라우저 통합 테스트 작성

완료 기준: 관리 기능과 티켓 업무 흐름을 웹 UI에서 수행할 수 있고 칸반 드래그가 API 규칙과 일치한다.

2026-09-27 업무 화면 typography 보정: `body`의 14px 상속을 8~10px 고정 규칙이 덮던 티켓 목록·인라인 상세·칸반·대시보드 핵심 정보를 본문 14px, 보조 정보 13px, metadata 12px design token으로 정리했다. 구조화 본문 viewer도 같은 본문 token을 사용한다.

2026-09-28 티켓 계층 탐색 연결: Task 상세의 `Subtask 목록`과 Subtask 상세의 `상위 Task & 같은 Task의 Subtask`를 전체·인라인 상세와 API에 연결했다. 각 항목은 키·제목·상태·담당자와 상세 링크를 제공하고 현재 Subtask를 강조하며, 완료·취소 티켓은 유지하고 휴지통 티켓은 제외한다. 진행률·완료 비율은 계산하지 않는다. 기존 `(project_id, parent_id)` index를 사용해 상세당 한 번의 계층 query로 조회하며 Windows Python 환경에서 전체 pytest 322개와 Ruff 및 diff 검사를 통과했다.

2026-09-28 칸반 카드 상태 control 제거: 카드마다 표시하던 상태 select와 해당 JavaScript event 경로·CSS를 제거하고 상태 변경을 drag-and-drop으로 단일화했다. 카드의 FSM 허용 상태·의존성·version metadata와 서버 전이 API, 오류 feedback과 성공·stale 이후 보드 재조회는 유지한다. Windows Python 환경에서 전체 pytest 322개와 Ruff 및 diff 검사를 통과했다.

2026-09-28 칸반 Subtask 카드 구분: 모든 Subtask 카드에 유형 전용 class를 부여하고 공통 design token 기반의 옅은 배경색과 8px 왼쪽 margin을 적용했다. 같은 상태 Task 아래와 다른 상태 열의 상위 Task 식별 group에서 동일하게 표시되며 카드 정보와 drag 동작은 변경하지 않았다. Windows Python 환경에서 전체 pytest 322개와 Ruff 및 diff 검사를 통과했다.

2026-09-29 프로젝트 즐겨찾기: 내 프로젝트 카드의 회색·노란색 별표로 사용자별 즐겨찾기를 설정·해제하고, 선택한 프로젝트를 검색·페이지네이션과 무관하게 공통 내비게이션의 `내 프로젝트` 아래에 이름순으로 고정 표시한다. 즐겨찾기는 명시적 `ProjectMember`에 저장되어 비참여 시스템 관리자 override에는 허용하지 않고 참여 제거 시 함께 정리된다. Alembic `20260929_0006`에서 기존 참여 정보를 보존하며 기본값 false로 추가했다. Windows Python 환경 전체 pytest 329개와 Ruff 및 diff 검사를 통과했다.

2026-09-29 새 티켓 상위 후보 제한: 새 티켓 유형을 바꾸면 Epic은 상위 선택을 비활성화하고, Task는 Epic만, Subtask는 Task만 표시하면서 필수 입력으로 전환한다. 초기 서버 렌더링도 같은 후보 제한을 적용하고 기존 서버 계층 검증을 최종 방어로 유지한다. Windows Python 환경 전체 pytest 330개와 Ruff·JavaScript 문법 및 diff 검사를 통과했다.

2026-09-29 칸반 중요도 색상 보정: 칸반 카드 상단의 일반 span selector가 공용 중요도 badge 색상을 회색으로 덮던 specificity 충돌을 제거했다. 회색 metadata 규칙은 티켓 키 전용 class에만 적용하고 중요도는 목록과 같은 `priority-critical`·`priority-major` 등 공용 class 색상을 유지한다. Windows Python 환경 전체 pytest 330개와 Ruff 및 diff 검사를 통과했다.

2026-09-29 티켓 변경 확인 확장: 댓글에만 적용하던 제출 확인을 공용 정적 script로 분리하고 티켓 생성·수정·상태 전이·관계 추가/삭제·첨부파일 등록·휴지통 이동/복구에 확대했다. form을 거치지 않는 본문 image 첨부와 칸반 drag 상태 변경도 요청 직전에 확인하며, 취소 시 서버 요청을 전송하지 않는다. frontend bundle build, Windows Python 환경 전체 pytest 331개와 Ruff·JavaScript 문법 및 diff 검사를 통과했다.

2026-09-29 link mark 호환성 보정: Tiptap 3이 수동 link에도 생성하는 `title` 속성을 서버가 호환 입력으로 검증한 뒤 canonical document에서 제거하도록 editor와 저장 계약을 일치시켰다. 외부 주소는 명시적인 HTTP(S) scheme을 요구하며 scheme 없는 입력을 임의로 변경하지 않고 editor에서 안내한다. frontend bundle build, Windows Python 환경 전체 pytest 335개와 Ruff·JavaScript 문법 및 diff 검사를 통과했다.

2026-09-29 link 편집·식별 개선: editor의 단일 link toolbar button에서 추가·URL 수정·명시적 삭제를 제공하는 dialog를 연결했다. editor와 viewer의 link text에 공통 blue 색상·밑줄을 적용하고 hover와 viewer keyboard focus를 강조했다. frontend bundle build, Windows Python 환경 전체 pytest 337개와 Ruff·JavaScript 문법 및 diff 검사를 통과했다.

2026-09-29 프로젝트 업무 진입점 변경: 내 프로젝트 카드의 `프로젝트 열기`와 공통 내비게이션의 즐겨찾기 프로젝트를 해당 프로젝트의 티켓 목록에 연결했다. 시스템 관리자의 전체 프로젝트 관리 목록은 설정·구성원 관리 목적의 프로젝트 root 연결을 유지한다. Windows Python 환경 전체 pytest 337개와 Ruff 및 diff 검사를 통과했다.

2026-09-29 하위 티켓 빠른 생성: Epic·Task의 전체 상세와 티켓 목록 inline 상세에 각각 `Task 만들기`·`Subtask 만들기`를 추가했다. 새 티켓 화면은 검증된 query parameter로 티켓 유형과 상위 티켓을 자동 선택하며, 계층이 맞지 않는 조작된 요청은 거부한다. guest와 비활성 프로젝트에는 생성 동작을 노출하지 않는다. Windows Python 환경 전체 pytest 338개와 Ruff 및 diff 검사를 통과했다.

2026-10-02 공통 navigation 접기·펼치기: topbar의 항상 접근 가능한 toggle button으로 왼쪽 sidebar를 완전히 숨기고 main workspace와 page content가 확보된 전체 너비를 사용하게 했다. 선택 상태를 browser `localStorage`에 유지하고 숨겨진 navigation을 `inert`와 `aria-hidden`으로 keyboard focus 및 접근성 tree에서 제외한다. reduced motion 환경에서는 transition을 제거한다. Windows Python 환경 전체 pytest 339개와 Ruff·JavaScript 문법 및 diff 검사를 통과했다.

2026-10-02 사용성 개선 브랜치 문서 정합성 점검: 현재 Alembic head `20260929_0006`을 인증·관리·MVP 데이터 문서에 동기화하고 migration 목록에 프로젝트 즐겨찾기 revision을 보완했다. Tiptap 본문 계약에 link `title` 호환 입력과 canonical 제거 규칙을 명시하고, 프로젝트 전문 문서에 일반 사용자·관리자별 진입 경로와 접이식 navigation을 반영했으며 README에 주요 데이터 계약 문서를 연결했다. 실제 공통 app shell과 design token 적용 상태에 맞춰 10단계 checklist도 완료 처리했다. 과거 roadmap의 당시 test 수와 migration head는 시점별 검증 이력으로 유지했다. decision ID와 로컬 Markdown link 검사를 통과했으며 Windows Python 환경 전체 pytest 339개와 Ruff 및 diff 검사를 다시 통과했다.

2026-10-07 프로젝트 기본 진입점 변경: 내 프로젝트와 전체 프로젝트 관리 카드의 `프로젝트 열기`, 즐겨찾기 프로젝트를 해당 프로젝트의 칸반보드에 연결했다. 전체 프로젝트 관리 카드에는 별도의 프로젝트 설정 링크를 둔다. 프로젝트 통합 테스트와 Ruff·diff 검사를 통과했다.

## 11단계 — 운영 준비 및 최종 검증

- [x] 공통 cron scheduler의 DB 일정·실행 이력 구조와 기동 시 복원 구현
- [x] 웹과 분리된 Docker Compose scheduler service 구성
- [ ] 감사 로그·휴지통·첨부파일 정리용 전용 명령 구성
- [ ] 시스템 관리자 수동 실행과 내부 system actor 자동 실행의 감사·시스템 로그 구분
- [ ] 정리 작업 실행 주기와 중복 실행 방지 방식 검증
- [x] Docker Compose에 전용 scheduler 추가
- [ ] 운영 HTTPS와 `Secure` 세션 쿠키 설정 검증
- [x] 인증 화면·API의 CSRF와 same-origin 방어 검증
- [ ] 후속 업무 쓰기 전체의 CSRF 적용 누락 점검
- [x] 로그인 실패 제한 또는 지연 정책 구현
- [ ] 관리자 주요 작업 감사 로그 누락 점검
- [x] 현재 구현 범위의 Windows 개발 환경 전체 테스트
- [x] 현재 구현 범위의 Docker Linux 환경 전체 테스트
- [ ] macOS Docker volume mount 검증
- [ ] 첨부파일 이동·삭제·복구 운영 테스트
- [ ] DB 및 첨부파일 백업·복구 절차 문서화
- [ ] health check와 장애 로그 점검
- [ ] 초기 운영 배포 체크리스트 작성

완료 기준: 지원 환경에서 동일한 테스트를 통과하고 데이터 이동·정리·복구 및 보안 설정을 운영자가 문서에 따라 수행할 수 있다.

## 후속 범위

- [ ] 간트차트·일정 편집·진행률 및 일정 의존 정책 연결
- [ ] 기간별 이력 수집·경계 상태 복원·근거 누락 감지
- [ ] 로컬 LLM adapter·작업 실행기·재시도·출력 검증
- [ ] 보고서 요청·조회·Markdown 내보내기 화면과 프로젝트 권한 검증
- [ ] 보고서 스킬 생성·버전 관리·SKILL.md export
- [ ] 보고서 입력·출력의 보존 기간·정리·입력량 제한 확정
- [ ] Sprint와 백로그
- [ ] 한국어 전문 검색
- [ ] 관리자용 DB·첨부파일 백업 ZIP
- [ ] 사용자 정의 상태와 workflow
- [ ] Text 이외 Ad-hoc 필드 타입·입력 도구(시점 별도 확정)
- [ ] 시스템 제공 선택형 확장 필드
- [ ] 프로젝트 및 업무 통계
- [ ] 외부 인증 연동
- [ ] 오브젝트 스토리지 첨부파일 adapter
- [ ] 필요 시 다크 모드
