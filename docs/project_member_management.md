# 프로젝트 참여자 역할 변경·제거 구현 가이드

## 1. 목적

현재 프로젝트 참여자 기능은 프로젝트 생성 시 최초 관리자 지정, 참여자 조회, 활성 사용자 검색과 신규 참여자 등록까지 연결되어 있다. 다음 작업에서는 기존 참여자의 역할 변경과 참여 제거를 구현하고, 모든 경로에서 프로젝트에 최소 한 명의 관리자가 남도록 보장한다.

이 문서는 `main` 브랜치의 현재 구현을 기준으로 작업 범위, 정책 확인 사항, 계층별 변경 위치와 검증 기준을 정리한다. 제품 요구사항은 `REQUIREMENTS.md`, 완료 여부는 `IMPLEMENTATION_ROADMAP.md`, 확정된 정책은 `docs/decisions/organizations-and-projects.md`와 `docs/decisions/users-auth-and-permissions.md`를 최종 기준으로 삼는다.

## 2. 현재 구현 상태

완료된 기능은 다음과 같다.

- 시스템 관리자의 프로젝트 생성과 최초 프로젝트 관리자 지정
- 프로젝트 참여자 목록 조회
- 로그인 ID·표시 이름 기반의 미참여 활성 사용자 검색
- 프로젝트 게스트·사용자·관리자 역할을 지정한 신규 참여자 등록
- 프로젝트 관리자와 시스템 관리자 override의 관리 권한 검사
- 비참여 일반 사용자에 대한 프로젝트 존재 은폐
- CSRF·same-origin 검사
- SQLite write lock 이후 사용자·프로젝트 권한·중복 상태 재검증
- 프로젝트 생성·참여자 등록과 감사 로그의 단일 transaction 처리

현재 제공되는 경로는 다음과 같다.

| 구분 | 경로 | 상태 |
|---|---|---|
| API | `GET /api/projects/{project_key}/members` | 완료 |
| API | `GET /api/projects/{project_key}/candidates` | 완료 |
| API | `POST /api/projects/{project_key}/members` | 완료 |
| Web | `GET /projects/{project_key}/members` | 완료 |
| Web | `POST /projects/{project_key}/members` | 완료 |
| API·Web | 기존 참여자 역할 변경 | 완료 |
| API·Web | 기존 참여자 제거 | 완료 |
| Service | 마지막 프로젝트 관리자 보호 | 완료 |

`ProjectMember`에는 `project_id`, `user_id`, `role`과 공통 생성·수정 시각이 있으며 별도의 version column은 없다. 현재 SQLite 쓰기는 `project_operation_context(..., write_operation=True)`가 `BEGIN IMMEDIATE` 계열 잠금을 획득한 후 권한과 상태를 다시 조회한다.

## 3. 이번 작업 범위

이번 작업은 다음 항목을 하나의 vertical slice로 완성한다.

1. 기존 참여자의 역할 변경
2. 기존 참여자의 프로젝트 참여 제거
3. 마지막 프로젝트 관리자의 하위 역할 변경·제거 차단
4. 프로젝트 관리자와 시스템 관리자 override 권한 적용
5. JSON API와 HTML form을 동일한 service에 연결
6. 변경과 감사 로그를 하나의 transaction으로 처리
7. 권한 변경 직후 모든 프로젝트 접근 경로에 새 역할이 반영되는지 검증
8. 동시 요청에서도 관리자가 0명이 되는 상태 방지

이번 작업에서 제외하는 항목은 다음과 같다.

- 프로젝트 기본 정보 수정과 활성·비활성 전환
- 사용자 계정 비활성화
- 조직 단위 프로젝트 권한
- 참여자 일괄 등록·변경·제거
- 사용자 그룹 또는 팀 역할
- 초대 메일과 승인 workflow
- 역할 변경 이력 전용 화면

## 4. 확정 정책

기존 요구사항과 결정 기록에 따라 아래 정책을 그대로 적용한다.

- 프로젝트 관리자와 시스템 관리자만 참여자의 역할을 변경하거나 참여에서 제거할 수 있다.
- 프로젝트 게스트·사용자·관리자 사이의 역할 변경을 허용한다.
- 조직 소속은 프로젝트 참여와 역할에 영향을 주지 않는다.
- 시스템 관리자가 명시적 프로젝트 관리자 권한 없이 관리하면 `project.override_access` 감사 로그를 남긴다.
- 마지막 프로젝트 관리자는 제거하거나 `PROJECT_USER`·`PROJECT_GUEST`로 변경할 수 없다.
- 일반 사용자가 접근할 수 없는 프로젝트와 참여자는 존재하지 않는 것과 같은 404로 응답한다.
- 역할 변경·제거 요청은 DB write lock 이후 actor 상태, 프로젝트 관리 권한, 대상 참여 상태와 관리자 수를 다시 확인한다.
- 감사 로그 저장에 실패하면 역할 변경·제거도 rollback한다.

같은 역할로 변경을 요청한 경우 성공으로 처리하되 `updated_at`, membership 변경 감사와 성공 시스템 로그를 추가하지 않는 no-op으로 처리한다. 단, 시스템 관리자 override로 관리 경로에 접근했다면 필수 `project.override_access` 감사 로그는 유지한다.

## 5. 확정한 추가 정책

### 5.1 담당 티켓이 있는 참여자

프로젝트 게스트는 담당자가 될 수 없으므로 `PROJECT_GUEST`로 변경하거나 참여에서 제거할 때 기존 담당 티켓과 충돌할 수 있다. 자동으로 담당자를 해제하면 다수 티켓의 version·이력·감사 로그를 함께 갱신해야 하고 사용자의 의도와 다르게 업무 담당자가 사라질 수 있다.

적용 정책은 다음과 같다.

- 휴지통 밖의 미완료 티켓을 담당 중인 사용자는 게스트로 변경하거나 프로젝트에서 제거하지 못하게 한다.
- 먼저 해당 티켓을 다른 사용자에게 재배정하거나 담당자 미지정으로 변경하도록 409 오류로 안내한다.
- 완료·취소 티켓의 담당자는 과거 기록으로 유지하고 역할 변경·제거를 차단하지 않는다.
- 휴지통 티켓의 담당자도 과거 기록으로 유지한다.
- 완료·취소 티켓을 재개하거나 휴지통 티켓을 복구할 때 현재 담당자가 활성 프로젝트 사용자 또는 관리자인지 다시 검사하고, 적격하지 않으면 409로 차단한다.
- 프로젝트 사용자와 프로젝트 관리자 사이의 역할 변경은 담당 티켓과 무관하게 허용한다.

이 정책은 `PRJ-009`에 기록한다.

### 5.2 비활성 프로젝트의 참여자 관리

현재 확정 정책은 비활성 프로젝트의 신규 참여자 등록을 차단하지만 기존 참여자의 역할 변경·제거는 명시하지 않는다.

적용 정책은 다음과 같다.

- 접근 회수 목적의 참여자 제거와 관리자·사용자의 게스트 하향은 허용한다.
- 게스트를 사용자·관리자로 올리거나 사용자를 관리자로 올리는 권한 확대는 차단한다.
- 마지막 관리자 보호는 프로젝트 활성 여부와 관계없이 적용한다.

기존 참여자가 비활성 사용자인 경우에도 동일 역할 no-op·역할 하향·제거는 허용하지만 권한 확대는 차단한다. 이 정책은 `PRJ-009`에 기록한다.

## 6. 권장 API 계약

대상은 사용자 ID가 아니라 프로젝트 안에서 유일한 membership ID로 식별한다.

### 6.1 역할 변경

```http
PATCH /api/projects/{project_key}/members/{member_id}
Content-Type: application/json
X-CSRF-Token: ...

{
  "role": "PROJECT_USER"
}
```

- 성공: 변경된 `MemberView`와 `200 OK`
- 같은 역할: 현재 `MemberView`와 `200 OK`, 데이터 변경 없음
- 대상 없음 또는 다른 프로젝트 membership: `404 member_not_found`
- 관리 권한 부족: 기존 프로젝트 노출 정책에 따른 `403` 또는 `404`
- 마지막 관리자 보호: `409 last_project_administrator`
- 미완료 담당 티켓 존재: `409 member_has_active_assignments`
- 비활성 프로젝트의 권한 확대: `409 project_inactive_role_expansion`
- 비활성 참여자의 권한 확대: `409 inactive_member_role_expansion`

### 6.2 참여 제거

```http
DELETE /api/projects/{project_key}/members/{member_id}
X-CSRF-Token: ...
```

- 성공: body 없는 `204 No Content`
- 대상 없음 또는 다른 프로젝트 membership: `404 member_not_found`
- 마지막 관리자 보호: `409 last_project_administrator`
- 미완료 담당 티켓 존재: `409 member_has_active_assignments`

`PATCH`와 `DELETE` 모두 현재 API write와 같은 CSRF·same-origin 검사를 적용한다.

## 7. 계층별 구현 계획

### 7.1 Schema

`app/schemas/projects.py`에 역할 변경 입력 DTO를 추가한다.

```python
class MemberRoleUpdate(BaseModel):
    """프로젝트 참여자 역할 변경 입력을 검증한다."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["PROJECT_ADMIN", "PROJECT_USER", "PROJECT_GUEST"]
```

모든 신규 함수와 validator에는 역할을 설명하는 docstring을 작성한다.

### 7.2 Repository

`app/repositories/projects.py`에 다음 조회를 추가한다.

- 프로젝트 ID와 membership ID로 대상 `ProjectMember` 조회
- 해당 프로젝트의 관리자 수 조회
- 동시 변경 방지를 위한 프로젝트 row 잠금 조회
- 대상 사용자가 담당 중인 휴지통 밖 미완료 티켓 수 조회
- 역할 변경 후 반환할 단일 `MemberView` row 조회

조회 조건에는 항상 `project_id`를 포함하여 다른 프로젝트의 membership ID를 전달해도 존재를 노출하지 않는다. repository는 조회·flush만 담당하며 commit하지 않는다.

SQLite에서는 기존 write lock이 쓰기를 직렬화한다. PostgreSQL 전환을 고려하여 모든 membership 변경이 관리자 수 판정 전에 해당 프로젝트 row 하나를 `SELECT ... FOR UPDATE`로 잠그는 repository 경계를 둔다. 현재 비 SQLite backend는 별도 검증 전까지 지원하지 않는다.

### 7.3 Service

`app/services/projects.py`에 다음 함수를 추가한다.

- `update_project_member_role(...)`
- `remove_project_member(...)`

역할 변경 순서는 다음과 같다.

1. `project_operation_context(..., write_operation=True)` 시작
2. actor의 현재 활성 상태와 프로젝트 관리 권한 재검증
3. 대상 membership을 프로젝트 범위로 조회
4. 프로젝트 row 잠금
5. 요청 역할이 현재 역할과 같으면 현재 DTO 반환
6. 비활성 프로젝트·비활성 참여자의 권한 확대 차단
7. 관리자 하향이면 현재 관리자 수를 확인하고 마지막 관리자 차단
8. 게스트 하향이면 미완료 담당 티켓 검사
9. 역할 변경과 `updated_at` 반영
10. `project.member_role_changed` 감사 로그 기록
11. transaction commit 후 성공 시스템 로그 기록

참여 제거도 같은 흐름을 사용하되 마지막 관리자와 미완료 담당 티켓 검사를 통과한 뒤 membership row를 삭제한다.

본인이 자신의 역할을 낮추거나 참여에서 나가는 동작은 다른 관리자가 남아 있다면 허용하는 것을 권장한다. 권한은 transaction 시작 시점에 확인하고, 성공 응답 이후 다음 요청부터 변경된 역할을 적용한다.

### 7.4 감사 로그와 시스템 로그

권장 감사 action은 다음과 같다.

- `project.member_role_changed`
- `project.member_removed`

역할 변경 감사 detail:

```json
{
  "user_id": 42,
  "before_role": "PROJECT_USER",
  "after_role": "PROJECT_ADMIN"
}
```

참여 제거 감사 detail:

```json
{
  "user_id": 42,
  "role": "PROJECT_USER"
}
```

시스템 로그 event는 `project_member_role_changed`, `project_member_removed`를 사용하고 `actor_id`, `project_id`, `user_id`만 기록한다. 표시 이름·로그인 ID·이메일은 기록하지 않는다. 예상 가능한 4xx는 stack trace 없이 처리하고 예상하지 못한 실패만 기존 `project_operation_context`에서 한 번 기록한다.

### 7.5 API와 Web route

`app/api/routes/projects.py`에 `PATCH`와 `DELETE` route를 추가하고 `app/web/projects.py`에는 HTML form용 POST route를 추가한다.

권장 HTML 경로:

- `POST /projects/{project_key}/members/{member_id}/role`
- `POST /projects/{project_key}/members/{member_id}/remove`

HTML form도 API와 같은 DTO와 service를 사용한다. 성공 후에는 Post/Redirect/Get 방식으로 `/projects/{project_key}/members`로 이동하고 역할 변경·제거 성공 메시지를 구분한다.

### 7.6 화면

`app/web/templates/project_members.html`의 참여자 행을 다음과 같이 확장한다.

- 관리 권한이 있으면 각 참여자의 역할 select와 변경 버튼 표시
- 제거 버튼에 명확한 browser 확인 메시지 적용
- 마지막 관리자 한 명만 남은 경우 역할 하향과 제거 control 비활성화
- 자기 자신을 변경할 때 접근 권한을 잃을 수 있다는 안내 표시
- 프로젝트가 비활성인 경우 확정된 정책에 따라 허용 동작만 노출
- 서버가 최종 권한·관리자 수·담당 티켓을 재검증

UI의 비활성화는 편의 기능이며 보안 기준으로 사용하지 않는다.

## 8. 동시성 및 rollback

다음 경쟁 조건을 반드시 방어한다.

- 두 명의 관리자를 동시에 하향하여 관리자가 0명이 되는 요청
- 같은 참여자에 대한 동시 역할 변경
- 역할 변경과 참여 제거의 동시 요청
- actor의 관리 권한이 다른 transaction에서 먼저 하향된 상태
- 감사 로그 저장 실패

현재 SQLite에서는 write lock 획득 후 actor와 대상 상태를 다시 읽어 직렬화한다. 같은 transaction 안에서 관리자 수를 확인하고 변경해야 한다. `ProjectMember`에 version column을 추가하는 migration은 이번 범위에 필수로 두지 않지만, 향후 다중 worker·PostgreSQL 전환 시 row lock 동작을 별도로 검증한다.

감사 로그 저장 실패, `IntegrityError` 또는 예상하지 못한 예외가 발생하면 membership과 감사 로그가 모두 rollback되어야 한다.

## 9. 테스트 계획

`tests/integration/test_projects.py`를 중심으로 다음 사례를 추가한다.

### 9.1 역할 변경

- 프로젝트 관리자가 게스트·사용자·관리자 사이의 역할을 변경
- 시스템 관리자 override 변경과 `project.override_access` 감사
- 프로젝트 사용자·게스트·외부 사용자의 변경 거부
- 다른 프로젝트의 membership ID 존재 은폐
- 잘못된 역할과 extra field 거부
- 같은 역할 요청의 no-op과 감사 로그 미생성
- 시스템 관리자 no-op 요청의 membership 변경 감사 미생성과 override 감사 유지
- 역할 변경 직후 티켓 쓰기·담당자 후보·프로젝트 관리 권한 반영
- 다른 관리자가 있을 때 자기 역할 하향 허용 및 다음 요청 차단

### 9.2 참여 제거

- 프로젝트 관리자의 일반 참여자 제거
- 제거된 사용자의 내 프로젝트·티켓·댓글·첨부파일 접근 차단
- 시스템 관리자 override 제거와 감사 기록
- 다른 프로젝트 membership 제거 시도 존재 은폐
- 이미 제거된 membership 재요청의 404
- 다른 관리자가 있을 때 자기 참여 제거 허용

### 9.3 안전 규칙

- 마지막 관리자 역할 하향 거부
- 마지막 관리자 제거 거부
- 두 관리자 동시 하향·제거 시 최소 한 명 유지
- 미완료 티켓 담당자의 게스트 하향·제거 거부
- 완료·취소·휴지통 티켓만 담당하는 사용자의 변경 허용
- 완료·취소 티켓 재개와 휴지통 복구 시 부적격 담당자 차단
- 비활성 프로젝트·비활성 참여자의 역할 하향·제거 허용과 권한 확대 차단
- actor의 권한이 lock 전에 변경된 경우 쓰기 거부
- 감사 기록 실패 시 역할·삭제 rollback
- API와 HTML form의 CSRF·same-origin 검증
- HTML 성공 redirect와 오류 시 최신 참여자 목록 표시

기존 프로젝트·티켓·대시보드·칸반 테스트도 함께 실행하여 권한 변경에 따른 회귀를 확인한다.

## 10. 권장 작업 순서

1. `main`에서 `feature/project-member-management` 브랜치 생성
2. 담당 티켓과 비활성 프로젝트 정책 확정 및 decision log 갱신
3. DTO와 repository 조회·잠금 함수 구현
4. 역할 변경 service와 단위·통합 테스트 구현
5. 참여 제거 service와 단위·통합 테스트 구현
6. JSON API route와 CSRF 검증 연결
7. HTML form·화면 control·확인 메시지 연결
8. 권한 변경 후 티켓·대시보드·댓글·첨부파일 접근 회귀 검증
9. 전체 pytest, Ruff와 `git diff --check` 실행
10. 완료된 항목만 `IMPLEMENTATION_ROADMAP.md`와 `docs/projects.md`에 반영

## 11. 완료 기준

- 프로젝트 관리자와 시스템 관리자가 기존 참여자의 역할을 변경하고 참여에서 제거할 수 있다.
- 프로젝트 사용자·게스트와 비참여 사용자는 관리 동작을 수행할 수 없다.
- 어떤 동시 요청에서도 프로젝트 관리자가 0명이 되지 않는다.
- 담당 티켓 정책이 API·HTML에서 동일하게 적용된다.
- 변경 즉시 프로젝트·티켓·댓글·첨부파일 권한에 새 역할이 적용된다.
- 감사 로그와 membership 변경이 같은 transaction에서 commit 또는 rollback된다.
- 시스템 로그가 공통 규약을 따르고 개인정보를 포함하지 않는다.
- 신규 함수와 validator에 docstring이 있다.
- 관련 통합 테스트, 전체 pytest, Ruff와 diff 검사가 통과한다.
- 실제 완료 범위가 로드맵과 프로젝트 문서에 반영된다.
