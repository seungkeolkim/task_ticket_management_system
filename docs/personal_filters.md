# 개인 저장 필터

## 사용과 공개 범위

- 프로젝트 티켓 목록·칸반에서 조건을 `적용`한 다음 이름을 입력하고 `개인 필터 저장`을 선택한다.
- `내 개인 필터 / 나만 보기`에서 저장한 조건을 적용하거나 이름 변경·현재 조건으로 덮어쓰기·삭제할 수 있다.
- `프로젝트 공유 필터 / 구성원 공용`은 구분된 영역이며 프로젝트 관리자가 관리한다. 구성원은 조회·적용할 수 있다. 상세 권한은 [공유 저장 필터](shared_filters.md)를 따른다.
- 마지막으로 적용한 조건·정렬·페이지 크기를 저장한다. 제출하지 않은 입력과 현재 페이지 번호는 저장하지 않는다.
- 날짜는 고정 날짜다. `이번 주` 같은 이름을 붙여도 날짜가 자동으로 이동하지 않는다.
- 칸반은 목록의 정렬·페이지 크기를 보존하되 보드에는 기존 순서와 전체 카드 표시를 유지한다(UI-029).

## 권한과 검증

- 본인 소유의 PERSONAL row와 현재 프로젝트 접근 권한을 모두 요구한다. 타인·다른 프로젝트·PROJECT row는 404다.
- 시스템 관리자도 타인 개인 필터에 접근할 수 없다. 비참여 프로젝트의 본인 필터 접근은 기존 관리자 override 감사를 따른다.
- 게스트와 비활성 프로젝트도 개인 조회 설정을 저장할 수 있다. 프로젝트·티켓 쓰기 권한에는 영향을 주지 않는다(IAM-017).
- 이름은 NFC·trim 후 1~200자, 제어 문자 금지다. 같은 사용자·프로젝트의 동일 이름을 거부하며 대소문자는 구분한다.
- TicketFilter v1의 허용 필드·연산자만 저장하며 owner·visibility를 client 입력으로 받지 않는다.
- 생성·조건 덮어쓰기·불러오기 때 Epic·parent는 현재 프로젝트의 활성 계층 후보, creator·assignee는 기존 목록의 사용자 후보인지 확인한다. 이력상 참조된 과거 담당자는 기존 후보 규칙을 따른다.
- 생성·수정 시각 조건은 UI와 왕복 가능한 Asia/Seoul 날짜 시작만 허용한다. 같은 시각의 UTC 표기도 허용하며 적용 URL은 한국 날짜로 변환한다.
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

- 기존 `saved_filters`를 사용하며 migration은 없다. application service가 쓰기 잠금·현재 권한 검사·저장·감사 transaction을 소유한다(DB-024).
- `updated_at` 비교로 stale 변경·삭제는 409 처리하고 실제 변경 시 시각이 단조 증가하도록 보장한다. no-op은 수정 시각과 변경 감사를 추가하지 않는다.
- 감사 action은 `personal_filter.created`, `.updated`, `.deleted`다. 개인 이름·검색 조건 대신 filter ID와 project ID만 기록한다. 시스템 로그는 성공 후 안정 식별자만 남긴다.
- 통합 테스트는 lifecycle, 날짜 왕복, 소유권·프로젝트 격리, 게스트·비활성 프로젝트, CSRF, schema·참조 검증, 동시 중복 생성, stale 변경, 감사 실패 rollback을 확인한다.
- 실제 Edge Browser 테스트는 개인/공유 구분, 저장·적용·이름 변경·덮어쓰기·삭제, 이름 XSS 방어와 화면 넘침을 확인한다. 실행 방법은 README의 Browser 테스트 절을 따른다.
