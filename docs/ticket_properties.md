# Ticket Label·Ad-hoc 필드

## 사용 방법

- ticket 생성·편집의 `Label·추가 정보`에서 Label을 한 줄에 하나씩 자유 입력한다. 별도 등록·허용 목록은 없다.
- `+ 필드 추가`로 이름과 Text 값을 입력하고 필요 없으면 `필드 제거`한다. 저장 전에는 DB가 바뀌지 않는다.
- 같은 필드의 이름·값 수정 시 고유 ID를 유지한다. 필드는 ticket끼리 재사용하지 않으며 프로젝트 관리자가 미리 정의할 필요도 없다.
- 전체·인라인 상세에서 추가 필드 이름과 값을 안전한 평문으로 표시한다. 목록·칸반은 Label 3개와 초과 개수만 표시하고 추가 필드 전체는 펼치지 않는다.

## 입력 정책

| 항목 | 정책 |
|---|---|
| Label | 최대 30개, 각 64자, NFC·trim, 빈 이름·제어 문자 거부, 대소문자 무시 중복 제거, 최초 표기·순서 유지 |
| 필드 이름 | 최대 100자, NFC·trim, 빈 이름·제어 문자·ticket 내 대소문자 무시 중복 거부 |
| 필드 개수 | ticket당 최대 30개 |
| ID | UUID, 생략한 새 항목은 서버 생성. 기존 항목 수정 시 반환받은 ID 재전송 |
| 타입 | 현재 `TEXT`만 지원. 임의 타입 및 추가 속성 거부 |
| 값 | 최대 10,000자 문자열, 여러 줄·공백·빈 문자열 보존 |

Label과 추가 필드는 기존 ticket 쓰기 권한·활성 프로젝트·종료 잠금·optimistic locking을 적용한다. 동일 값 저장은 version과 이력을 늘리지 않는다. 새 값은 시스템 로그에 출력하지 않고 기존 ticket ID·변경 필드명 로그만 사용한다.

## API·저장 계약

```json
{
  "labels": ["보안", "고객 요청"],
  "custom_fields": [
    {
      "field_id": "00000000-0000-4000-8000-000000000001",
      "name": "방문 장소",
      "field_type": "TEXT",
      "value": "판교 사무실\n3층"
    }
  ]
}
```

- 위 속성은 기존 생성·수정 요청에 추가한다. 수정 시 각 속성 생략은 보존, `[]`는 전체 제거이며 `null`은 거부한다.
- HTML은 Label 줄 단위 문자열과 필드 JSON을 전송한다. `properties_present=true`로 빈 form 값과 기존 form의 미전송을 구분한다.
- `tickets.labels`·`tickets.custom_fields`는 SQLAlchemy JSON 컬럼이다. 작은 ticket-local 목록을 검증 후 전체 교체하므로 N+1 조회나 별도 카탈로그가 없다. 대용량 검색용 저장소로 설계한 것은 아니며 필터 작업 시 조회 방식·index 필요성을 검토한다.
- `field_type`이 저장되어 향후 타입별 검증·입력 도구를 확장할 수 있다. 아직 Date·Number 값을 저장하거나 Calendar를 표시하지 않는다.
- TicketState v2의 선택 속성으로 추가되어 과거 v2 snapshot은 누락 속성을 빈 목록으로 읽는다. 기존 이력을 backfill하거나 수정하지 않는다. 새 선택 속성을 모르는 구버전 reader는 호환되지 않을 수 있다.
- Label·필드 변경은 전후 전체 목록을 ticket 이력에 기록하며 필드 ID로 이름 변경과 새 항목을 구분할 수 있다.
- `20261003_0007` upgrade는 기존 ticket에 빈 배열을 부여한다. downgrade는 현재 Label·필드 값을 제거하지만 ticket·이력은 보존한다. 되돌리기 전에 DB 백업이 필요하며 downgrade 후 re-upgrade는 제거된 현재 값을 복원하지 않는다.
- 실행 중인 서비스에 새 코드를 적용하기 전에 같은 설정·DB를 대상으로 `python -m alembic upgrade head`를 실행한다. 자동 테스트는 임시 DB를 사용한다. 2026-10-03에는 사용자 요청에 따라 로컬 업무 DB를 별도 백업한 뒤 해당 revision을 적용하고 기존 데이터 보존을 확인했다. 다른 배포 DB에는 별도로 적용해야 한다.

## 이번 범위 밖

- 자동완성, Label·추가 필드 검색/필터, 수동 순서 변경 UI
- Text 이외 타입의 실제 사용 및 타입별 Calendar 등 입력 도구
- 시스템 제공 필드 중 프로젝트가 선택하는 확장 필드(후속)
- 사용자 정의 계산식·관계 집계(백로그)

## 검증 실행

- Python: `.venv/Scripts/python.exe -m pytest`
- 정적 검사: `.venv/Scripts/python.exe -m ruff check app tests scripts migrations`
- Browser component: Playwright가 설치된 Node 환경에서 `node --test tests/browser/ticket-properties.test.cjs`. 번들 Chromium이 없고 Edge가 설치된 Windows에서는 `PLAYWRIGHT_CHANNEL=msedge`를 설정한다. 번들 runtime의 package를 사용하면 `NODE_PATH`도 해당 node_modules로 설정한다.
- Browser component 검증은 새 필드 편집 script를 실제 browser에서 확인하는 범위이며 배포 환경 전체 E2E 검증을 대신하지 않는다.
