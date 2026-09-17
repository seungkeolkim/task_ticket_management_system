# 인증 화면과 초기 관리자

루트 `/`는 내 작업 대시보드 주소다. 미로그인 상태에서는 `/login?next=...`로 이동하고, 인증 후 원래 내부 경로와 query로 돌아간다. 외부 주소나 인증 화면으로의 반복 이동은 허용하지 않는다.

초기 관리자나 비밀번호 초기화 대상은 먼저 `/account/password`에서 현재 비밀번호와 새 비밀번호를 입력해야 한다. 변경 시 모든 기기의 기존 세션을 제거하고 새 비밀번호로 다시 로그인한다. 로그인·비밀번호 변경·로그아웃은 실제 DB에 연결되어 있다. 나머지 업무 화면은 로그인 후 접근하는 예시 데이터이며 프로젝트 권한과 업무 쓰기는 후속 작업이다. `/admin/*`는 시스템 관리자만 접근한다.

## 최초 관리자 생성

로컬 가상환경에서 다음 명령을 실행한다. migration 적용 후 비밀번호를 화면에 표시하지 않고 두 번 입력받는다.

```powershell
python -m app.cli bootstrap-admin --login-id admin --display-name "시스템 관리자"
python -m app
```

로그인 ID는 3~100자 영문 소문자·숫자·점·밑줄·하이픈이며 첫 글자는 영숫자다. 앞뒤 공백 제거와 소문자 정규화를 적용한다. 비밀번호는 12~128자이며 제어 문자와 공백만인 값은 거부한다.

자동 기동에서는 `BOOTSTRAP_ADMIN_LOGIN_ID`와 `BOOTSTRAP_ADMIN_PASSWORD` 또는 `BOOTSTRAP_ADMIN_PASSWORD_FILE` 중 하나를 주입한다. 표시명은 `BOOTSTRAP_ADMIN_DISPLAY_NAME`으로 지정할 수 있다. 파일 경로는 실행 프로세스 안에서 읽을 수 있는 UTF-8 secret 파일을 가리켜야 한다. 명령행 인자로 비밀번호를 전달하지 않는다.

Docker에서는 `.env.example`을 참고해 `.env`에 초기 관리자 환경 변수를 설정하고 `sh ./run_compose.sh start`로 실행한다. secret 파일 방식은 별도 volume/secret mount가 필요하다. 초기 생성 후에는 bootstrap 비밀값을 제거한다. 기존 사용자가 한 명이라도 있으면 재실행으로 관리자나 비밀번호를 덮어쓰지 않는다. 계정이 없는 로그인 화면에는 초기 설정 안내가 표시된다.

`[bootstrap]`의 `organization_key`와 `organization_name` 기본값은 `default`와 `기본 조직`이다. 같은 key의 활성 조직이 있으면 재사용하며 비활성 조직은 자동 활성화하지 않는다.

## API와 보호 규칙

| 경로 | 기능 |
|---|---|
| `GET /api/auth/csrf` | cookie와 함께 사용할 CSRF token 발급 |
| `GET /api/auth/me` | 현재 계정과 비밀번호 변경 필요 여부 |
| `POST /api/auth/login` | `login_id`, `password`, 선택적 `next` |
| `POST /api/auth/password` | `current_password`, `new_password`, `confirmation` |
| `POST /api/auth/logout` | 현재 세션 폐기 |

POST는 같은 origin의 `Origin`(없으면 `Referer`)과 `X-CSRF-Token` 헤더가 필요하다. HTML form은 같은 검증에 hidden token을 사용한다. API client는 cookie를 유지하고 로그인 후 CSRF token을 다시 조회한다. 업무 API에서는 `require_api_user`로 초기 비밀번호 변경도 강제해야 한다.

비밀번호는 Argon2id, 세션은 무작위 32바이트 token을 사용한다. DB에는 세션 SHA-256 hash만 저장하고 기본 480분 후 만료한다. 비활성화·세션 폐기는 다음 요청부터 적용된다. 로그인 실패와 현재 비밀번호 확인 실패는 감사 로그에 기록하며 기본 900초 동안 ID별 5회 또는 접속 IP별 30회 실패 시 `429`와 `Retry-After`를 반환한다. `[auth]`에서 조절한다.

세션 cookie는 host-only·HttpOnly이며 기본 SameSite=Lax다. HTTPS 운영에서는 `[session].cookie_secure=true`, HTTPS reverse proxy에서는 추가로 `[auth].public_origin`을 브라우저의 공개 origin으로 설정한다. 기본 실행은 forwarded header를 신뢰하지 않아 proxy 뒤의 IP 제한은 proxy 접속 IP를 공유한다. 실제 client IP 신뢰 정책은 운영 배포 시 확정해야 한다.

인증 실패 진단에는 비밀번호·cookie·token·SQL parameter를 남기지 않는다. 사용자 입력 검증 오류도 입력값을 응답에 복사하지 않는다. 인증 응답과 화면에는 `Cache-Control: no-store`를 적용한다.

이번 인증 연결은 기존 `users`, `user_sessions`, `organizations`, `audit_logs`를 사용하며 Alembic head `20260917_0002`를 유지한다. SQLite 인증 쓰기는 실패 횟수 판정과 기록을 직렬화한다. PostgreSQL 전환 시 동등한 잠금 구현과 동시성 검증이 필요하다(DB-013).
