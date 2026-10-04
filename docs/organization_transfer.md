# 조직 JSON 내보내기·가져오기

시스템 관리자는 조직 관리 화면에서 전체 조직 계층을 JSON 파일로 내려받거나 파일을 선택해 가져올 수 있다. 내보내기에는 조직 정보만 포함하며 사용자, 프로젝트, 참여 권한, 티켓과 비밀번호는 포함하지 않는다.

## 파일 형식

UTF-8 JSON의 최상위에는 `schema_version`과 `organizations`만 둔다. 현재 버전은 `1`이다. 각 조직에는 변하지 않는 `key`, `name`, `description`, `is_active`, `children`이 모두 필요하다. `children`은 같은 형식의 조직 배열이며 최상위 조직도 배열에 넣는다.

```json
{
  "schema_version": 1,
  "organizations": [
    {
      "key": "default",
      "name": "기본 조직",
      "description": "",
      "is_active": true,
      "children": [
        {
          "key": "team-001",
          "name": "개발팀",
          "description": "제품 개발",
          "is_active": true,
          "children": []
        }
      ]
    }
  ]
}
```

파일은 최대 16MB, 조직 2,000개, 계층 32단계까지 받는다. 조직 key는 1~64자, 공백을 제거한 이름은 1~200자, 설명은 최대 4,000자다. 파일의 중복 key·형제 이름·JSON 필드, 잘못된 타입·버전·인코딩을 거부한다. 내보낸 파일은 수정 없이 미리보기에서 다시 읽을 수 있다.

## 적용 절차와 보존 범위

1. 파일을 선택하고 **적용 내용 미리보기**를 누른다. 서버가 각 key에 대해 추가·갱신·변경 없음과 충돌을 표시한다.
2. 오류가 없으면 **확인한 변경 적용**을 누른다. 적용 직전에 파일과 조직 상태가 미리보기 때와 같은지 다시 검사한다. 그 사이 조직이 변경되었으면 새 미리보기가 필요하다.
3. 추가·갱신과 조직별 감사 기록을 하나의 DB transaction으로 저장한다. 중간 실패 시 전체 변경을 되돌린다.

기존 조직은 key로 식별하고 내부 ID와 사용자 소속을 유지한다. 파일에 없는 조직은 삭제하거나 비활성화하지 않는다. 파일에 명시한 조직의 이름, 설명, 활성 상태와 부모는 갱신할 수 있다. 사용자·프로젝트 데이터는 변경하지 않는다. 최종 계층에서 기존 조직과의 형제 이름 중복, 순환 구조, 비활성 상위 조직 아래의 새 배치를 차단한다. 새로 가져오는 비활성 계층은 같은 transaction에서 자식을 만든 다음 비활성 상태를 적용하므로 내보낸 트리를 복원할 수 있다.

API에서는 `GET /api/admin/organizations/export`로 파일을 받고, JSON 원문을 `POST /api/admin/organizations/import/preview`에 보내 미리보기를 받는다. 적용은 `POST /api/admin/organizations/import/apply`에 `document_json` 원문 문자열과 미리보기의 `preview_token`을 함께 보낸다. 두 POST 모두 로그인한 시스템 관리자의 CSRF token을 요구한다.
