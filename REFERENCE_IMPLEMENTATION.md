# 기존 프로젝트 참조 및 차용 가이드

## 1. 문서 목적

신규 태스크·티켓 관리 시스템을 구현할 때 기존 `government-project-analysis-agent` 프로젝트에서 참고하거나 차용할 수 있는 설계, 코드 및 테스트를 정리한다.

기존 프로젝트 전체를 기반으로 개발하는 것이 아니라 신규 프로젝트의 요구사항에 맞는 부분만 선별하여 이식하는 것을 원칙으로 한다.

## 2. 참조 대상

- 저장소: [seungkeolkim/government-project-analysis-agent](https://github.com/seungkeolkim/government-project-analysis-agent)
- 확인 브랜치: `main`
- 확인 커밋: [`79a41d676378abfb62dbf4fe2d4bf33a0c7bf843`](https://github.com/seungkeolkim/government-project-analysis-agent/tree/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843)
- 주요 기술: Python, FastAPI, SQLAlchemy, Alembic, Jinja2, SQLite, vanilla JavaScript

이 문서의 파일 링크는 이후 원본 저장소가 변경되어도 동일한 코드를 확인할 수 있도록 위 커밋에 고정한다.

## 3. 전체 판단

| 영역 | 차용 수준 | 판단 |
|---|---|---|
| 인증 서비스 | 수정 후 차용 | 해시, 로그인, 세션 구조와 테스트를 재사용할 가치가 높음 |
| 시스템 관리자 권한 | 수정 후 차용 | FastAPI dependency 패턴은 재사용하고 권한 모델은 확장 필요 |
| 프로젝트 권한 | 재구현 | 기존 프로젝트에는 프로젝트별 관리자·사용자 역할이 없음 |
| 초기 관리자 생성 | 수정 후 차용 | 기존 CLI 코어를 최초 기동 bootstrap 정책으로 확장 |
| 조직 트리 CRUD | 적극 차용 | 트리 구성, 순환 방지, 이동 및 중복 검증을 활용 가능 |
| 조직 JSON 입출력 | 개념만 참고 | 기존 구현은 전체 교체 방식이므로 신규 비파괴 정책과 맞지 않음 |
| 에디터 | 개념만 참고 | 기존 `execCommand` 기반 프런트엔드는 그대로 채택하지 않는 것을 권장 |
| HTML 정화 및 뷰어 | 수정 후 차용 | allowlist와 안전한 렌더링 계약 및 테스트를 활용 가능 |
| 댓글 에디터 | 재구현 | 기존 댓글은 평문이며 신규 시스템은 포맷팅과 멘션이 필요 |
| 페이지네이션 | 적극 차용 | query 검증, count/list 분리, batch 조회 구조 활용 가능 |
| SQLite 백업 | 적극 차용 | 안전한 SQLite snapshot 로직을 신규 ZIP 백업의 기반으로 사용 가능 |
| DB 연결 및 migration | 수정 후 차용 | SQLAlchemy/Alembic 구조는 유효하나 신규 프로젝트 기준으로 정리 필요 |
| 화면 스타일 | 선택 차용 | 관리자 목록·조직 트리·폼 스타일을 참고하되 신규 화면 구조에 맞게 분리 |

## 4. 인증 및 사용자 관리

### 4.1 차용할 부분

다음 구현 패턴은 신규 시스템에서도 사용할 수 있다.

- 비밀번호 해시와 검증 함수 분리
- 사용자명 정규화 및 입력 정책 검증
- 중복 사용자명을 사전 조회가 아니라 DB unique constraint로 최종 방어
- 로그인 실패 시 사용자 부재와 비밀번호 오류를 구분하지 않는 공통 응답
- 존재하지 않는 사용자명에도 dummy password 검증을 수행하여 시간 차이를 줄이는 방식
- `secrets.token_urlsafe`를 이용한 세션 토큰 생성
- 세션 만료 시각 저장 및 검증
- 비밀번호 변경 시 사용자의 기존 세션을 모두 무효화하는 처리
- 일반 사용자와 시스템 관리자를 구분하는 FastAPI dependency
- 서비스 테스트와 HTTP 로그인 흐름 테스트의 분리

참조 코드:

- [비밀번호 해시 및 검증](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/auth/service.py#L83-L113)
- [사용자 생성](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/auth/service.py#L192-L254)
- [사용자 인증](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/auth/service.py#L257-L301)
- [세션 생성 및 검증](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/auth/service.py#L325-L426)
- [인증 및 관리자 dependency](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/auth/dependencies.py#L65-L186)
- [인증 HTTP 테스트](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/tests/auth/test_routes.py)

### 4.2 신규 시스템에 맞게 변경할 부분

기존 `User` 모델에는 신규 시스템에 필요한 일부 필드가 없다. 다음 필드를 추가하거나 변경한다.

- 표시 이름
- 시스템 역할 또는 관리자 여부
- 소속 조직
- 활성 여부
- 최초 또는 초기화된 비밀번호 변경 필요 여부
- 생성일시 및 수정일시
- 비활성화 시각과 비활성화 수행자(감사 목적, 선택)

신규 시스템에서는 다음 정책을 적용한다.

- 자유 회원가입을 제공하지 않는다.
- 시스템 관리자가 사용자를 생성한다.
- 사용자를 물리 삭제하지 않고 비활성화한다.
- 비활성 사용자의 모든 세션을 제거하고 로그인을 거부한다.
- 마지막 활성 시스템 관리자를 비활성화하거나 관리자 권한에서 해제하지 못하게 한다.
- 관리자에 의한 비밀번호 초기화 후 다음 로그인에서 비밀번호 변경을 강제한다.

### 4.3 그대로 가져오지 않을 부분

- 기존 시스템의 자유 회원가입 라우트
- 사용자 물리 삭제 및 연관 데이터 cascade 삭제
- 시스템 관리자를 단순 Boolean 하나만으로 처리한 뒤 프로젝트 역할까지 같은 방식으로 해결하는 설계
- 세션과 resource mutation에서 서로 다른 SQLAlchemy Session을 열어 ORM 객체를 전달하는 방식

기존 프로젝트도 인증용 DB 세션과 라우트의 DB 세션이 달라질 수 있어 객체를 다시 조회해야 한다는 주석을 가지고 있다. 신규 시스템에서는 요청 단위 DB 세션을 일관되게 주입하고, 계층 사이에는 ORM 객체보다 식별자나 DTO를 전달하는 방식을 우선한다.

### 4.4 보안 보완

기존 `ensure_same_origin`은 경량 방어로 구현되어 있다. 신규 시스템에서는 다음과 같이 강화한다.

- 상태 변경 요청에 CSRF token 적용
- `Origin`을 검사한다면 URL을 파싱한 뒤 scheme, host 및 port를 정확히 비교
- `Origin`과 `Referer`가 모두 없다는 이유만으로 브라우저 쓰기 요청을 자동 허용하지 않음
- 운영 HTTPS 환경에서는 session cookie의 `Secure` 활성화
- `HttpOnly`와 적절한 `SameSite` 적용
- 로그인 실패 횟수 제한 또는 지연 처리
- 필요 시 DB에는 세션 토큰 원문 대신 해시 저장

참조 코드:

- [기존 same-origin 검사](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/auth/dependencies.py#L189-L224)
- [기존 cookie 설정](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/auth/routes.py#L81-L106)

## 5. 최초 시스템 관리자 생성

### 5.1 차용할 부분

기존 `create_admin.py`의 다음 구조를 차용한다.

- 실제 생성 로직과 CLI 입력 로직 분리
- 비밀번호를 `getpass`로 두 번 입력하여 확인
- 공통 사용자 생성 서비스를 호출하여 validation과 password hash 중복 구현 방지
- `session_scope`를 이용한 commit, rollback 및 close 처리
- 중복 사용자명과 입력 정책 오류에 대한 명확한 종료 코드
- 신규 DB에서도 먼저 migration을 적용한 후 관리자를 생성하는 흐름

참조 코드:

- [초기 관리자 생성 CLI](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/scripts/python/create_admin.py#L73-L109)
- [CLI 실행 및 오류 처리](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/scripts/python/create_admin.py#L183-L244)
- [초기 관리자 테스트](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/tests/auth/test_create_admin.py)

### 5.2 신규 bootstrap 정책

신규 시스템에서는 기존 CLI 코어를 다음과 같이 확장한다.

1. Alembic migration을 적용한다.
2. 사용자 수를 확인한다.
3. 사용자가 0명일 때만 bootstrap을 허용한다.
4. 초기 관리자 환경 변수가 있으면 관리자 계정을 생성한다.
5. 환경 변수가 없다면 별도의 일회성 CLI로 관리자를 생성할 수 있게 한다.
6. 초기 비밀번호 원문은 로그에 기록하지 않는다.
7. 생성된 관리자는 `must_change_password=true`로 시작한다.
8. 이미 사용자가 존재하면 재기동 시 아무 계정도 만들거나 변경하지 않는다.

초기 관리자 자동 생성은 컨테이너가 재시작될 때마다 실행되어도 결과가 달라지지 않는 멱등 동작이어야 한다.

## 6. 프로젝트 권한

기존 프로젝트의 인증 및 관리자 dependency 작성 방식은 참고할 수 있지만 신규 시스템의 프로젝트 권한 자체는 새로 구현한다.

권장 구성:

- `ProjectMember`
  - `project_id`
  - `user_id`
  - `role`: `PROJECT_ADMIN` 또는 `PROJECT_USER`
  - 생성일시 및 수정일시
- `require_project_member(project_id)`
- `require_project_admin(project_id)`
- `can_edit_ticket(user_id, ticket_id)`
- `can_manage_comment(user_id, comment_id)`
- `can_access_attachment(user_id, attachment_id)`

모든 프로젝트 리소스 조회는 데이터를 가져온 뒤 권한을 확인하는 방식보다 SQL 조회 조건 자체에 `project_id`와 사용자 membership 조건을 포함하는 방식을 우선한다. 목록, 인라인 상세 뷰, 첨부파일 다운로드, 멘션 및 검색 결과에도 같은 조건을 적용한다.

시스템 관리자 override는 별도 분기로 명시하고 감사 로그를 남긴다.

## 7. 조직 관리

### 7.1 적극 차용할 부분

기존 조직 서비스의 다음 구현을 차용할 수 있다.

- `parent_id`를 이용한 self-referencing tree
- 전체 조직을 한 번 조회한 뒤 메모리에서 트리를 구성하는 방식
- 자기 자신을 상위 조직으로 지정하지 못하게 하는 검증
- 자신의 하위 조직으로 이동하지 못하게 하는 순환 참조 검증
- 같은 부모 아래 동일 조직명 중복 방지
- 서비스 함수에서는 `flush`까지만 수행하고 transaction 경계는 호출자가 관리하는 방식
- 조직 생성, 이름 변경, 이동에 대한 단위 테스트
- 관리자 조직 트리 화면과 이동 UI

조직 수가 크지 않은 사내 시스템이므로 전체 조직을 읽어 메모리에서 트리를 구성하는 방식은 초기 버전에 적합하다.

참조 코드:

- [조직 트리 구성](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/organizations/service.py#L65-L119)
- [조직 생성](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/organizations/service.py#L122-L183)
- [조직 이름 변경과 이동](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/organizations/service.py#L211-L368)
- [조직 이동 테스트](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/tests/db/test_organization_rename_move.py)
- [조직 관리 화면](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/web/templates/admin/organizations.html)

### 7.2 모델 변경

신규 `Organization`에는 기존 모델에 없는 다음 필드를 둔다.

- 외부 입출력과 갱신 기준으로 사용할 변경되지 않는 조직 식별 키
- 조직명
- 상위 조직 ID
- 설명
- 활성 여부
- 생성일시 및 수정일시

현재 요구사항에서 사용자는 하나의 조직에 소속되는 것으로 정의되어 있으므로 초기 구현은 `User.organization_id` 형태를 우선한다. 향후 복수 소속 요구가 확인되면 기존 프로젝트의 `UserOrganization` M:N 구조를 참고하여 migration한다.

### 7.3 조직 JSON 입출력

기존 JSON export의 다음 부분은 참고할 수 있다.

- `ensure_ascii=False`를 사용한 한글 보존
- 재귀적인 `children` 구조
- pretty-print JSON
- import와 export round-trip 테스트

그러나 기존 import 구현은 다음 이유로 그대로 사용하지 않는다.

- 기존 조직을 모두 삭제한 뒤 새 조직을 삽입한다.
- 조직 ID가 전부 바뀔 수 있다.
- 이름 경로가 사라진 사용자-조직 매핑을 조용히 삭제한다.
- 스키마 버전이나 변경되지 않는 조직 식별 키가 없다.
- 적용 전 미리보기가 없다.

참조 코드:

- [기존 조직 JSON export](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/organizations/io.py#L28-L43)
- [기존 전체 교체 import](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/organizations/io.py#L126-L228)
- [조직 JSON 테스트](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/tests/db/test_organization_io.py)

신규 import는 다음 순서로 재구현한다.

1. JSON parsing 및 스키마 버전 검사
2. 필수 필드와 타입 검사
3. 중복 조직 키, 중복 형제 이름 및 순환 구조 검사
4. 현재 데이터와 비교하여 추가·갱신·충돌 목록 생성
5. 관리자에게 적용 전 미리보기 제공
6. 관리자의 확정 요청 후 하나의 transaction으로 추가 및 갱신
7. JSON에 없다는 이유만으로 기존 조직을 삭제하거나 비활성화하지 않음

## 8. 에디터, 뷰어 및 멘션

### 8.1 기존 구현의 구조

기존 에디터는 다음 방식으로 동작한다.

1. `textarea[data-rich-editor]`를 찾는다.
2. textarea를 숨기고 툴바와 `contenteditable` 영역을 생성한다.
3. `document.execCommand`로 굵게, 목록, 색상, 표 등의 HTML을 만든다.
4. form 제출 직전에 편집 영역의 `innerHTML`을 textarea에 복사한다.
5. 서버가 HTML allowlist sanitizer를 적용한다.
6. 정화된 HTML만 뷰어에서 `safe`로 렌더링한다.

참조 코드:

- [기존 리치 텍스트 에디터](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/web/static/js/rich_text_editor.js)
- [HTML allowlist sanitizer](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/suggestions/sanitize.py#L49-L143)
- [HTML 정화 함수](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/suggestions/sanitize.py#L151-L331)
- [정화된 HTML viewer](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/web/templates/suggestions/detail.html#L141-L151)
- [sanitizer 테스트](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/tests/suggestions/test_post_html_sanitize.py)
- [에디터 통합 테스트](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/tests/web/test_board_rich_text_integration.py)

### 8.2 차용 방침

다음 개념과 테스트는 차용한다.

- 사용자 입력과 최종 렌더링 결과를 신뢰하지 않는 원칙
- 허용 태그, 속성, URL scheme 및 CSS의 allowlist
- `javascript:` URL, event handler, 위험 태그 및 위험 CSS 제거
- 평문과 formatted body를 구분하는 저장 계약
- 기존 평문 데이터의 하위 호환 처리
- 저장 → 조회 → 렌더링 round-trip 테스트
- viewer에서 정화되지 않은 값을 `safe`로 출력하지 않는 규칙

기존 `rich_text_editor.js`는 `document.execCommand`에 의존하므로 그대로 이식하지 않는 것을 권장한다. 에디터 프런트엔드는 별도로 선택하되 저장 포맷에 따라 다음 중 하나를 적용한다.

#### Markdown을 저장하는 경우

- Markdown 원문을 DB에 저장한다.
- Markdown renderer에서 raw HTML을 비활성화한다.
- 렌더링된 HTML에도 sanitizer를 적용한다.
- 에디터와 viewer가 같은 Markdown 확장 집합을 사용한다.
- 멘션은 본문의 `@표시명`만 신뢰하지 않고 별도 Mention row로 확정하여 저장한다.

#### HTML을 저장하는 경우

- 새로운 에디터가 생성한 HTML을 서버에서 반드시 정화한 후 저장한다.
- 정화 허용목록에 멘션을 나타내는 제한된 tag와 data attribute를 추가한다.
- 외부 이미지 URL보다 권한 검사를 거치는 내부 첨부파일 식별자를 사용한다.
- DB에는 정화된 HTML만 저장하고 원본 HTML은 저장하지 않는 것을 기본으로 한다.

기존 프로젝트의 댓글은 평문이므로 댓글 UI와 저장 로직은 직접 재사용할 수 없다. 신규 시스템에서는 티켓 설명과 댓글이 동일한 포맷 계약, sanitizer 및 viewer를 공유하게 한다.

### 8.3 멘션 처리

- 에디터는 현재 프로젝트에 접근 가능한 사용자만 멘션 후보로 제공한다.
- 저장 요청에서 서버가 멘션 대상 사용자의 프로젝트 접근 권한을 다시 확인한다.
- 티켓 또는 댓글 저장과 Mention row 생성은 같은 transaction에서 처리한다.
- 본문 수정 시 추가된 멘션과 제거된 멘션의 차이를 계산한다.
- 같은 원본과 대상 사용자의 미확인 멘션을 중복 생성하지 않는다.
- 사용자가 표시 이름을 바꿔도 멘션 대상이 유지되도록 최종 관계는 사용자 ID로 저장한다.

## 9. 페이지네이션과 목록 조회

### 9.1 차용할 부분

- FastAPI `Query`를 통한 `page >= 1`, `page_size` 범위 검증
- 1-based page를 `(page - 1) * page_size` offset으로 변환
- 조회 함수와 count 함수를 분리
- 전체 건수와 전체 페이지 수 계산
- 현재 페이지의 연관 데이터만 ID 묶음으로 batch 조회하여 N+1 방지
- 필터와 정렬 조건을 repository 함수에 명시적으로 전달
- 목록과 count에 같은 필터 함수를 적용하는 구조

참조 코드:

- [목록 route와 페이지 계산](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/web/main.py#L581-L646)
- [목록 repository](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/db/repository.py#L1543-L1602)
- [count repository](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/db/repository.py#L1605-L1630)
- [필터를 보존하는 페이지 링크](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/web/templates/list.html#L571-L590)

### 9.2 신규 시스템에서 보완할 부분

- 페이지 크기는 임의의 1~100이 아니라 10, 20, 50만 허용한다.
- 기본 페이지 크기는 20으로 한다.
- 티켓 키 또는 ID를 마지막 보조 정렬로 항상 추가하여 페이지 사이의 중복과 누락을 줄인다.
- 목록과 count query에 동일한 프로젝트 접근 조건을 적용한다.
- 휴지통 티켓은 일반 목록에서 제외한다.
- 페이지 이동 시 `page_size`, 프로젝트, 필터, 정렬 및 검색 query parameter를 모두 보존한다.
- query string을 템플릿에서 문자열로 직접 이어 붙이기보다 URL encoder 또는 공통 query builder로 생성한다.
- 현재 페이지가 필터 변경이나 삭제로 전체 페이지 수를 초과하면 마지막 유효 페이지로 보정하거나 1페이지로 이동한다.
- 저장된 필터도 같은 typed filter DTO를 사용하도록 하여 목록 조회 로직을 이중 구현하지 않는다.

Offset pagination은 초기 규모에 충분하다. 데이터가 매우 커진 뒤에만 keyset pagination 도입을 검토한다.

## 10. SQLite 백업

### 10.1 적극 차용할 부분

기존 백업 서비스의 다음 부분을 차용한다.

- `sqlite3.Connection.backup()`을 이용한 실행 중 DB의 일관된 snapshot 생성
- 단순 파일 복사를 사용하지 않는 원칙
- 백업 실행 이력 저장
- 수동 및 예약 실행 구분
- 성공 여부, 오류, 실행 시간 및 파일 크기 기록
- 보관 수를 초과한 오래된 백업 정리
- 관리자 전용 백업 화면 및 실행 route
- 실제 파일 SQLite를 사용하는 백업 테스트

참조 코드:

- [기존 SQLite 백업 서비스](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/backup/service.py#L190-L284)
- [백업 목록 및 이력](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/backup/service.py#L292-L344)
- [백업 테스트](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/tests/db/test_backup_service.py)
- [관리자 백업 route](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/web/routes/admin.py#L2103-L2257)

### 10.2 신규 백업으로 확장할 부분

기존 백업은 DB 파일만 대상으로 하며 첨부파일을 포함하지 않는다. 신규 시스템은 다음 순서로 확장한다.

1. DB backup adapter를 통해 일관된 DB snapshot 생성
2. snapshot과 첨부파일 목록 확정
3. 애플리케이션 버전, DB 종류, 스키마 revision, 생성 시각을 manifest에 기록
4. DB snapshot, attachment 및 manifest를 하나의 임시 ZIP으로 생성
5. ZIP 생성을 완료한 후 최종 백업 파일명으로 이동
6. 관리자에게 인증된 다운로드 route 제공
7. 생성 중인 임시 파일과 기존 `backups` 디렉터리는 ZIP에서 제외
8. 보관 기간 또는 보관 개수에 따라 생성된 ZIP 정리

PostgreSQL 등으로 DB가 바뀌면 snapshot 생성 부분만 DB별 adapter로 교체하고 ZIP 조립과 다운로드 로직은 유지한다.

## 11. SQLAlchemy 및 Alembic

### 11.1 차용할 부분

- DB URL을 환경 변수와 설정 객체로 주입
- SQLite에서만 필요한 engine option을 engine factory에 격리
- `sessionmaker` 및 transaction context manager
- SQLAlchemy 범용 타입 우선 사용
- constraint에 명시적인 이름 지정
- Alembic migration을 통한 스키마 변경
- migration의 upgrade와 downgrade 구현
- SQLite와 PostgreSQL 이식성 체크리스트

참조 코드:

- [DB engine과 session factory](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/db/session.py)
- [DB portability 문서](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/docs/db_portability.md)
- [Alembic 기반 초기화](https://github.com/seungkeolkim/government-project-analysis-agent/blob/79a41d676378abfb62dbf4fe2d4bf33a0c7bf843/app/db/init_db.py)

### 11.2 신규 시스템에서 변경할 부분

- 메인 DB와 게시판 DB를 분리한 기존 구조는 가져오지 않고 하나의 애플리케이션 DB로 시작한다.
- SQLite connection마다 `PRAGMA foreign_keys=ON`이 실행되도록 SQLAlchemy connect event를 등록한다.
- 프로젝트, 티켓, 댓글, 멘션 및 첨부파일 사이의 무결성은 실제 FK와 constraint로 보장한다.
- 비어 있지 않은 임의의 DB를 자동으로 baseline stamp하는 휴리스틱은 사용하지 않는다.
- 기존 DB 도입이 필요하면 예상 테이블과 revision을 명시적으로 검사한 뒤 별도의 migration 절차를 수행한다.
- PostgreSQL 지원 여부는 문서상의 중립성만으로 판단하지 않고 PostgreSQL 대상 migration 및 repository 테스트를 실행한다.
- 신규 코드의 OS 경로 조합은 요구사항에 따라 `os.path.join`을 사용한다.

## 12. Windows 개발 및 macOS 실행 고려사항

기존 프로젝트는 Ubuntu 개발·실행 환경에서 대부분 정상 작동한 시스템이다. Windows에서 확인된 `tzdata` 및 CP949 관련 실패는 기존 기능 자체의 결함으로 단정하지 않고, 실행 환경이 달라졌을 때 드러난 이식성 차이로 본다.

다만 신규 프로젝트는 Windows에서 개발하고 macOS에서 실행하므로 다음 항목을 초기부터 적용한다.

- `tzdata`를 Windows용 조건부 Python 의존성으로 선언하거나 모든 지원 OS에서 시간대 로딩 테스트를 수행한다.
- DB에는 UTC를 저장하고 화면에서 `Asia/Seoul`로 변환한다.
- `alembic.ini`처럼 런타임 라이브러리가 OS 기본 인코딩으로 읽을 수 있는 설정 파일에는 비 ASCII 주석을 넣지 않는다.
- Python에서 직접 읽는 텍스트와 JSON에는 `encoding="utf-8"`을 명시한다.
- 소스, Markdown, JSON 및 템플릿은 UTF-8로 통일한다.
- 애플리케이션 경로는 `os.path.join`으로 구성한다.
- Docker 내부에서는 POSIX 경로를 사용하되 host 경로를 애플리케이션 로직에 직접 노출하지 않는다.
- 최소한 Windows 개발 환경과 Docker Linux 환경에서 단위 테스트를 실행한다.
- 실제 운영 전 macOS의 Docker 환경에서 volume mount, 첨부파일, 백업 및 복구를 검증한다.

### 12.1 확인 과정의 테스트 결과 해석

Windows 임시 환경에서 선택한 테스트를 실행했을 때 일부 순수 로직 테스트는 통과했으나 DB fixture가 Alembic 설정 파일을 CP949로 읽으며 다수 setup error가 발생했다. 처음에는 Windows의 `Asia/Seoul` 데이터 부재로 `tzdata` 오류도 발생했다.

이는 Ubuntu에서 정상 운영되었다는 사실과 충돌하지 않는다. 신규 프로젝트에서는 해당 결과를 기존 구현의 기능 평가가 아니라 교차 OS 테스트 항목을 미리 발견한 사례로 활용한다.

## 13. 우선 이식할 테스트

코드보다 테스트의 의도와 사례를 먼저 가져온다. 다음 순서로 신규 도메인에 맞게 포팅한다.

1. 비밀번호 hash 및 verify 테스트
2. 사용자명과 비밀번호 정책 테스트
3. 로그인 성공·실패 및 세션 만료 테스트
4. 관리자 권한 401·403 테스트
5. 최초 관리자 생성과 중복 실행 테스트
6. 조직 생성, 이름 변경 및 이동 테스트
7. 조직 순환 참조와 같은 위치 중복 테스트
8. 조직 JSON 한글 round-trip 및 검증 실패 테스트
9. formatted body sanitizer 보안 테스트
10. 에디터 저장 및 viewer round-trip 테스트
11. 페이지네이션 경계와 필터 보존 테스트
12. 페이지 단위 연관 데이터 batch 조회 및 N+1 방지 테스트
13. SQLite snapshot과 백업 보관 정책 테스트

기존 테스트를 그대로 복사한 뒤 모델 이름만 바꾸는 방식보다 신규 요구사항의 acceptance criteria로 다시 작성한다.

## 14. 가져오지 않을 영역

다음 영역은 신규 태스크·티켓 관리 시스템과 직접 관계가 없거나 신규 요구사항과 충돌하므로 이식 대상에서 제외한다.

- 정부과제 scraper와 source adapter
- canonical project 및 중복 공고 판정
- 이메일 전송과 M365 OAuth
- 공고 전달 기능
- scraper 실행 제어와 재시작 로직
- 기존 cron 기반 수집 scheduler
- 메인 DB와 boards DB의 분리 구조
- 자유 회원가입
- 사용자 물리 삭제
- 조직 트리 전체 교체 import
- `document.execCommand` 기반 에디터 프런트엔드
- 기존 프로젝트의 `pathlib` 기반 경로 구성
- 공고 도메인에 종속된 관련성, 진행 상태 및 즐겨찾기 모델

## 15. 권장 이식 순서

1. 신규 프로젝트 기본 구조와 설정
2. SQLAlchemy engine, session 및 Alembic
3. User 모델과 인증 서비스
4. 최초 관리자 bootstrap
5. 시스템 관리자 dependency와 사용자 관리
6. Organization 모델, 서비스 및 관리 화면
7. 프로젝트 membership과 권한 서비스 신규 구현
8. 티켓 도메인과 FSM 신규 구현
9. 공통 본문 포맷, sanitizer 및 viewer
10. 댓글과 멘션
11. 티켓 목록, 필터 및 페이지네이션
12. 칸반 보드
13. 첨부파일 저장소
14. SQLite snapshot 기반 백업 ZIP

각 단계에서 기존 코드를 먼저 복사하기보다 신규 인터페이스와 데이터 모델을 확정한 뒤 필요한 함수와 테스트만 옮긴다.

## 16. 구현 시 참조 규칙

- 원본 파일 전체를 복사하지 않고 필요한 함수 단위로 검토한다.
- 공고 도메인 명칭과 가정을 신규 티켓 도메인에 남기지 않는다.
- 원본 주석을 그대로 유지하기보다 신규 요구사항에 맞는 근거를 새로 기록한다.
- 원본에서 SQLite 기본 동작에 의존한 부분은 DB constraint와 테스트로 보강한다.
- 참조 코드를 수정한 경우 새 테스트가 신규 요구사항을 검증하는지 확인한다.
- 신규 시스템의 프로젝트 격리 조건은 UI뿐 아니라 모든 repository query에서 검증한다.
- 경로 생성에는 `os.path.join`을 사용한다.

