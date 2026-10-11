# 개인 저장 필터

현재 계약은 TicketFilter v4다. 복합 조건과 필드 추가형 편집기, URL·NULL·규모 제한은 [필터 설계](ticket_filter_design.md), UI-034·UI-036·UI-037을 따른다. 날짜·현재 사용자의 동적 값은 [동적 기준값](dynamic_filter_criteria.md)을 따른다.

## 사용과 공개 범위

- 목록·칸반에서 `필터 추가`로 필드를 선택하고 연산자·값을 입력한다. `그룹 추가`로 중첩 AND/OR와 그룹 NOT을 구성하고 `적용`한다.
- `필터 저장`에서 이름과 `내 개인 필터 · 나만 보기`를 선택한다. 저장 필터 선택창은 개인/공유를 구분하며 `불러오기`가 조건을 편집기에 복원한다.
- 개인 조건은 본인만 사용한다. 공유 범위의 관리 권한은 [공유 저장 필터](shared_filters.md)를 따른다.
- 마지막으로 적용한 조건·정렬·페이지 크기만 저장한다. 미적용 편집 중에는 생성·덮어쓰기를 비활성화하고 이름 변경·삭제는 유지한다. 현재 페이지 번호는 저장하지 않는다.
- 불러온 이름·공개 범위를 표시하고 이름 변경·현재 조건으로 덮어쓰기·삭제는 선택한 필터에 적용한다.
- 날짜는 고정 Date다. `이번 주`라는 이름도 자동으로 이동하지 않는다. 2단계의 동적 규칙은 아직 없다.
- 칸반은 목록 정렬·페이지 크기를 보존하되 기존 보드 순서·전체 카드 표시를 유지한다(UI-029).

## 권한과 검증

- 본인 소유의 PERSONAL row와 현재 프로젝트 접근 권한을 모두 요구한다. 타인·다른 프로젝트·PROJECT row는 404다.
- 시스템 관리자도 타인 개인 필터에 접근할 수 없다. 비참여 프로젝트의 본인 필터 접근은 기존 관리자 override 감사를 따른다.
- 게스트와 비활성 프로젝트도 개인 조회 설정을 저장할 수 있다. 프로젝트·티켓 쓰기 권한에는 영향을 주지 않는다(IAM-017).
- 이름은 NFC·trim 후 1~200자, 제어 문자 금지다. 같은 사용자·프로젝트의 동일 이름을 거부하며 대소문자는 구분한다.
- TicketFilter v4의 허용 필드·연산자만 저장하며 owner·visibility를 client 입력으로 받지 않는다.
- 생성·조건 덮어쓰기·불러오기 때 Epic·parent는 현재 프로젝트의 활성 계층 후보, creator·assignee는 기존 목록의 사용자 후보인지 확인한다. 이력상 참조된 과거 담당자는 기존 후보 규칙을 따른다.
- 생성·수정·마감일은 YYYY-MM-DD 고정 날짜다. on/between은 날짜 전체를 포함하고 before/after는 선택일을 제외한다. 중첩 NOT 안의 참조도 재검증한다.
- 불러올 수 없는 schema·참조는 409로 안내하고 조건을 임의 제거하지 않는다. 요약 목록·이름 변경·삭제와 유효한 조건으로 덮어쓰기는 가능하다.

## API

공통 경로: `/api/projects/{project_key}/personal-filters`

| 요청 | 동작 |
|---|---|
| GET | 본인 필터의 id·name·visibility·updated_at 목록 |
| POST | `{name, definition}`으로 생성 |
| GET `/{filter_id}` | schema·권한·참조 검증 후 definition 포함 반환 |
| PATCH `/{filter_id}` | `{expected_updated_at, name?, definition?}`으로 변경 |
| DELETE `/{filter_id}` | `{expected_updated_at}`으로 삭제 |

쓰기 요청은 session CSRF와 same-origin 검증을 통과해야 한다. 공개 범위는 서버가 PERSONAL로 고정한다.
화면 적용 주소는 `/projects/{project_key}/personal-filters/{filter_id}/apply?view=tickets` 또는 `view=board`이며 검증 후 기존 필터 URL로 303 이동한다.

## 저장·감사·검증

- 기존 `saved_filters`를 사용한다. Alembic `20261011_0010`이 v1 row만 삭제하고 schema_version 기본값을 2로 바꾼다(DB-028). 서비스가 쓰기 잠금·권한·저장·감사 transaction을 소유한다(DB-024).
- `updated_at` 비교로 stale 변경·삭제는 409 처리하고 실제 변경 시 시각이 단조 증가하도록 보장한다. no-op은 수정 시각과 변경 감사를 추가하지 않는다.
- 감사 action은 `personal_filter.created`, `.updated`, `.deleted`다. 개인 이름·검색 조건 대신 filter ID와 project ID만 기록한다. 시스템 로그는 성공 후 안정 식별자만 남긴다.
- 통합 테스트는 lifecycle, 날짜 왕복, 소유권·프로젝트 격리, 게스트·비활성 프로젝트, CSRF, schema·참조 검증, 동시 중복 생성, stale 변경, 감사 실패 rollback을 확인한다.
- 실제 Edge Browser 테스트는 개인/공유 구분, 저장·적용·이름 변경·덮어쓰기·삭제, 이름 XSS 방어와 화면 넘침을 확인한다. 실행 방법은 README의 Browser 테스트 절을 따른다.
