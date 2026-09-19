# 사용자·조직 관리

비밀번호 변경까지 완료한 시스템 관리자는 사이드바의 **조직**에서 최상위·하위 조직을 추가하고, **사용자**에서 계정을 생성할 수 있다. 사용자 생성 시 조직·시스템 역할과 임시 비밀번호를 지정한다. 새 사용자는 첫 로그인에서 비밀번호를 변경한 뒤 다시 로그인한다.

- `/admin/organizations`: 실제 조직 트리와 직속 사용자 수 조회, 조직 생성. 조직 행을 펼치면 설명과 안정 식별 키를 확인한다.
- `/admin/users`: 실제 사용자 목록과 ID·이름·이메일 검색, 10·20·50개 페이지 이동, 사용자 생성. 기본 페이지 크기는 외부 pagination 설정을 따른다.
- JSON API는 `GET/POST /api/admin/organizations`, `GET/POST /api/admin/users`다. 사용자 조회는 `q`, `page`, `page_size`를 받는다.

생성 API의 조직 입력은 `name`, 선택적 `parent_id`, `description`이다. 사용자 입력은 `login_id`, `display_name`, `organization_id`, `password`, 선택적 `email`, `system_role`(기본 `USER`)이다. 생성 응답은 `201`과 새 `id`이며 비밀번호를 반환하지 않는다. 사용자 입력은 `app/schemas/administration.py`에서 HTML form과 API가 공유한다.

로그인 ID·비밀번호는 [인증 규칙](authentication.md)을 따른다. 이메일은 선택이며 앞뒤 공백 제거·소문자 정규화 후 고유하게 저장한다. 기본 형식 검사는 소유권이나 실제 수신 가능 여부를 보증하지 않는다. 조직명은 앞뒤 공백을 제거하고 같은 부모 안에서 중복을 거부한다. 비활성 조직 또는 비활성 상위 조직을 가진 조직은 신규 등록에 사용할 수 없다.

쓰기 요청은 인증·관리자 역할·초기 비밀번호 변경 여부·same-origin·CSRF를 검사한다. API는 같은 cookie를 유지하고 `GET /api/auth/csrf`의 값을 `X-CSRF-Token`으로 보낸다. JSON 입력 검증 오류는 `422`, 정책 오류는 `400`, 중복은 `409`로 반환한다. HTML 오류는 form에 표시하며 비밀번호는 다시 입력해야 한다.

생성과 `user.created` / `organization.created` 감사 기록은 같은 transaction으로 저장한다. 감사 실패는 생성을 되돌린다. 시스템 로그에는 작업 이름·관리자 ID·생성 ID·오류 코드만 기록한다.

기존 테이블을 사용하여 Alembic head는 `20260917_0002` 그대로다. 하위 조직이 있는 DB를 완전히 제거하는 `downgrade base`의 기존 FK 오류만 초기 revision의 downgrade에서 보완했다(DB-015). 이는 전체 데이터를 제거하는 운영 명령이며 화면 기능 사용을 위해 실행할 필요가 없다.

사용자 수정·비활성화·비밀번호 초기화, 조직 수정·이동·비활성화·JSON 입출력은 아직 연결하지 않았다. 프로젝트 생성·조회·참여자 추가는 [프로젝트 관리](projects.md)에 연결되어 있다. 티켓 업무 기능은 후속이다.
