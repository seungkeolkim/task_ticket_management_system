# 프로젝트 공유 저장 필터

## 사용과 권한

- 프로젝트 목록·칸반의 `프로젝트 공유 필터 / 구성원 공용` 영역에서 조회·적용한다. `내 개인 필터 / 나만 보기`와 제목·badge·설명·구분선으로 나눈다.
- 활성 프로젝트의 프로젝트 관리자와 시스템 관리자는 이름을 입력해 생성하거나 이름 변경·현재 조건으로 덮어쓰기·삭제할 수 있다. 일반 사용자·게스트에게 관리 control은 표시하지 않고 API에서도 차단한다.
- 개인 필터와 같이 마지막으로 적용한 조건·정렬·페이지 크기를 저장한다. 미제출 입력과 페이지 번호는 저장하지 않는다. 날짜는 고정 날짜이며 목록·칸반의 기존 표시 규칙을 따른다.
- 모든 요청에서 현재 프로젝트 접근·관리 권한을 재검증한다. 비참여자는 404, 구성원의 관리 요청은 403, 비활성 프로젝트의 관리자 쓰기는 409다.
- 비활성 프로젝트도 조회·적용은 가능하다. 개인 필터의 비활성 프로젝트 저장 허용 정책은 변경하지 않는다.
- 최초 생성자가 탈퇴·비활성화되어도 공유 필터는 유지된다. owner_id는 최초 생성자 기록이고 현재 프로젝트 관리 권한을 제한하지 않는다. 시스템 관리자 override는 기존 프로젝트 감사 정책을 따른다(IAM-018).

## API

공통 경로: `/api/projects/{project_key}/shared-filters`

| 요청 | 동작 |
|---|---|
| GET | 해당 프로젝트 공유 필터 요약 목록 |
| POST | 관리자 `{name, definition}` 생성, 201 |
| GET `/{filter_id}` | 조건·프로젝트 권한 재검증 후 definition 반환 |
| PATCH `/{filter_id}` | 관리자 `{expected_updated_at, name?, definition?}` 변경 |
| DELETE `/{filter_id}` | 관리자 `{expected_updated_at}` 삭제, 204 |

- 공개 범위는 PROJECT로 고정하고 입력으로 owner·visibility를 받지 않는다. 개인 row·다른 프로젝트 row는 조회·수정·삭제 대상에 포함하지 않는다.
- 적용 주소는 `/projects/{project_key}/shared-filters/{filter_id}/apply?view=tickets` 또는 `view=board`다. 조건을 재검증한 뒤 기존 필터 URL로 303 이동한다.
- 이름은 NFC·trim 후 1~200자, 제어 문자 금지이며 프로젝트 공유 범위에서 대소문자를 구분해 중복을 거부한다. 개인 필터와 같은 이름은 허용한다.
- 개인·공유는 같은 입력 DTO 기반과 TicketFilter v1 참조·날짜 검증을 사용한다. 잘못된 저장 schema·현재 참조는 409로 안내하며 관리자가 유효한 조건으로 덮어쓰거나 삭제할 수 있다.
- 쓰기는 CSRF·same-origin을 검증한다. expected_updated_at이 오래되면 409, no-op은 수정 시각·변경 감사를 추가하지 않는다.

## 저장과 검증

- 기존 saved_filters를 사용하고 migration은 없다. 쓰기 잠금·중복 이름 확인·변경·감사 기록은 같은 transaction이며 실패 시 함께 rollback한다(DB-024).
- 감사 action은 shared_filter.created·shared_filter.updated·shared_filter.deleted다. 이름·조건 대신 filter ID·project ID를 기록하고 시스템 로그도 안정 식별자만 사용한다.
- 통합 테스트는 역할·공개 범위·프로젝트 격리, 생성자 이탈·권한 회수, 비활성 프로젝트, schema 복구, CSRF, stale 변경, 동시 중복 생성과 생성·수정·삭제 감사 실패 rollback을 확인한다.
- 실제 Edge Browser에서 관리자 lifecycle, 구성원·게스트의 적용과 관리 control 비노출, XSS 방어, 오래된 탭의 충돌 안내, 1440px 배치를 검증한다. README의 Browser 실행 방법을 따른다.
