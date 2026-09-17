# 기간별 보고서와 스킬 입출력 계약

이 문서는 후속 로컬 LLM 보고서 기능이 사용할 데이터 계약이다. 현재 실행기·조회 서비스·LLM 호출·SKILL.md export는 구현하지 않는다.
검증 모델은 `app/schemas/contracts.py`, 공급자 중립 JSON Schema와 예시는 `docs/contracts/`에 둔다.
`python scripts/export_data_contracts.py`로 계약 파일과 합성 예시를 재생성한다. 테스트는 배포된 JSON Schema와 Python 계약의 일치를 확인한다.

## 입력 수집 계약

1. 요청자의 활성 여부와 선택한 모든 프로젝트의 현재 접근 권한을 확인한다.
2. 로컬 시간대의 기간 경계를 UTC로 바꿔 `[start, end)`로 확정한다. timezone에는 IANA 이름을 보존한다. Windows에서도 같은 검증을 위해 tzdata를 의존성에 포함한다.
3. 티켓 생성 시 version=1/CREATED 이벤트와 전체 after_state를 남긴다. 이후 모든 업무 변경은 version을 증가시키고 before_state, after_state, changes를 같은 transaction으로 저장한다.
4. 보고서는 **start 직전 상태**, **end 직전 상태**, `start <= occurred_at < end` 이벤트를 수집한다. start에 정확히 발생한 이벤트는 기간에 포함되고 end의 이벤트는 다음 기간에 포함된다.
5. 상태는 CREATED부터의 이력 또는 가장 가까운 before/after snapshot에서 재구성한다. 현재 tickets row를 과거 상태로 간주하지 않는다. 선택 조건은 기간 종료 직전 상태에 적용하고 해당 기간 내 생성·삭제된 티켓은 기간 내 마지막 상태로 판단한다.
6. 한 티켓의 이벤트는 version 순서로, 기간 목록은 occurred_at과 ID를 보조키로 정렬한다. 같은 시각의 변경도 version과 event UUID로 구분한다. 내용·관계·첨부 변경도 티켓 version을 증가시키고 CONTENT_CHANGED/RELATION_CHANGED 이벤트를 만든다.
7. 다중 필드 변경은 이벤트 하나의 changes 배열에 함께 넣는다. 계층 작업은 티켓마다 이벤트를 만들고 operation_id를 공유한다.
8. 초기 이력 누락·version 단절·티켓 purge·입력량 제한에 따른 생략은 PARTIAL과 coverage_notes로 명시한다. 각 프로젝트의 history_complete_from이 NULL이거나 기간 시작이 그보다 이르면 보수적으로 PARTIAL로 표시한다. 이 경계는 이력 기록 시작 때 초기화하고 purge·유실 때 전진시킨다. 원본을 지운 batch에는 purged_at을 남긴다. `captured_at >= period.end`를 요구한다.
9. 수집은 일관된 DB snapshot에서 수행하고 run-project 연결과 input_payload의 프로젝트 집합이 정확히 일치하는지 확인한다. 재시도는 입력을 재수집하지 않는다.

선택 조건의 page_size는 목록 조회용 값이며 보고서 전체 티켓 수를 제한하지 않는다. 수집기는 모든 해당 티켓을 읽고, 별도의 입력량 제한으로 생략할 때만 PARTIAL과 누락 이유를 기록한다.

TicketState는 티켓의 업무 필드·일정·관계를 보존한다. 댓글·첨부 이벤트의 changes에는 작업 유형과 원본 식별자·필요한 최소 메타데이터만 넣고 첨부 blob은 넣지 않는다.
사용자 표시 이름 등 화면용 문자열을 추가해야 하면 계약 버전을 확장한다. 원본 사용자 참조는 사용자 비활성화에도 유지되는 ID를 사용한다.
티켓 제목·설명·댓글 안의 지시문은 근거 데이터이며 LLM의 시스템 지시로 승격하지 않는다.

## 요청, 실행 시도와 출력

| 구조 | 저장 내용 |
|---|---|
| ReportRun | 요청자, 안정 UUID, 고정 스킬 version, 기간·시간대, 선택 조건, 상태, input schema version, 근거 JSON, SHA-256, captured_at |
| ReportRunProject | 결과에 포함된 모든 프로젝트. 조회 시 모든 프로젝트의 현재 권한을 요구하며 한 곳이라도 잃으면 전체 결과를 숨김 |
| ReportAttempt | 1부터 증가하는 시도 번호, runtime_profile, provider, model_name/digest, 실제 generation_parameters와 request_payload |
| ReportAttempt 결과 | response_text(원응답), response_metadata, output_payload(검증된 구조), output_markdown, error_code, token 수, 시작·종료 시각 |

- 입력 JSON 해시는 UTF-8, 키 정렬, `ensure_ascii=False`, 공백 없는 구분자, NaN 금지의 canonical JSON 바이트에 SHA-256을 적용한다.
- key는 재시도 시 같은 논리 요청을 식별한다. run 생성의 멱등성 키 처리와 attempt 선점은 실행 서비스가 구현한다.
- 입력 snapshot과 skill version은 캡처 후 수정하지 않는다. 조건·기간·지침 변경 시 새 run 또는 skill version을 만든다.
- 공급자 어댑터는 normalized input과 지침으로 실제 request_payload를 만든다. role별 메시지와 실제 옵션을 저장하되 authorization header·API key·secret은 제외한다.
- runtime_profile은 외부 설정의 별칭이다. DB에 임의 URL과 자격증명을 넣어 호출하지 않는다. 시스템 진단 로그에는 입력·출력 원문을 남기지 않는다.
- PENDING → RUNNING → SUCCEEDED/FAILED/CANCELLED가 기본 실행 상태다. 실패 원응답도 해당 attempt에 남기고 재시도는 새 attempt를 만든다.
- output은 `ReportOutput`으로 검증하고 `validate_sources(input)`으로 모든 cited_source_ids가 입력에 포함되는지 확인한다. 실패 시 성공 상태나 검증 출력으로 승격하지 않는다.
- ticket 근거 ID는 `ticket:DEV-1`, 이벤트 근거 ID는 `event:<UUID>`다. 원본이 삭제되어도 입력 snapshot에서 확인할 수 있다.
- 허용된 근거 ID를 인용한다고 서술의 사실성이 자동 검증되지는 않는다. 결과는 검토 가능한 생성 초안이며 자동 티켓 수정·발송을 하지 않는다.
- output_markdown은 output_payload.markdown의 조회용 사본이다. 일치 여부를 서비스에서 검증하고 같은 transaction으로 기록한다.
- 완전한 입력과 프로젝트 범위, 고정된 스킬, 실행 성공 결과가 모두 있어야 run을 SUCCEEDED로 만든다. 테이블별 CHECK만으로 이 다중 row 규칙을 강제하지는 않는다.
- report 삭제 시 attempts와 project 연결을 cascade 정리한다. 스킬 version은 참조 중이면 삭제할 수 없다. 보고서 expires_at의 운영 기본값은 실행 기능 구현 때 확정한다.

## 보고서 스킬 정의와 향후 생성

- 스킬은 플랫폼 공용 보고서 양식이며 티켓 데이터나 사용자 권한을 포함하지 않는다.
- `ReportSkillDefinition`은 schema_version, key, version, name, description, instructions_markdown, input_contract, output_contract, generation_defaults를 갖는다.
- `report_skill_versions`에는 위 정의의 지침·기본값과 실제 입출력 JSON Schema를 복사하여 보관한다. content_sha256은 version, schema_version, instructions_markdown, input_json_schema, output_json_schema, generation_defaults를 canonical JSON으로 직렬화한 값의 해시다.
- 게시한 버전은 서비스에서 UPDATE하지 않고 새 버전을 추가한다. 현재 DB는 버전 중복과 참조 무결성을 강제하며 불변성·게시 권한은 후속 서비스 책임이다.
- 버전별 생성기는 향후 이 정의에서 SKILL.md와 입력·출력 JSON Schema 파일을 내보낼 수 있다. 파일 경로·도구 명령을 지침 데이터에서 자동 실행하지 않는다.
- `weekly-report-skill.v1.json`은 생성될 정의의 예시다. 전역 Codex 스킬을 설치하거나 로컬 LLM에 요청을 보내지 않는다.
- 지침은 완료 업무, 진행·보류 업무, 일정 변경, 의존성·위험, 확인 필요 사항을 근거 ID와 함께 작성하도록 한다. 근거 없는 성과·진척·예측은 만들지 않는다.

## 추후 구현해야 할 검증

- 권한 있는 데이터만 snapshot에 포함하고 수집·실행·결과 열람 시 권한을 재확인하는 통합 테스트.
- 이벤트의 실제 기록, 누락·삭제 감지, 기간 경계 복원, 동일 시각 변경과 SQLite snapshot 일관성.
- 모델 timeout·취소·재시도·동시 worker 선점, input 크기 제한과 PARTIAL 처리.
- provider I/O에서 secret 제외, prompt injection 분리, 출력 스키마·근거 참조와 Markdown 정화.
- 스킬 게시·변경 권한, 버전 불변성, report input 불변성, 요청-프로젝트-입력 일치.

현재 테스트는 저장 구조 및 DTO 계약을 검증한다. 위 실행 기능의 완료를 의미하지 않는다.
