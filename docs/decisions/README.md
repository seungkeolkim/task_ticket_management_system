# Decision log index

이 폴더는 대화 중간이나 구현 과정에서 확정된 선택을 세션 간에 보존한다. 제품 요구사항 자체는 `REQUIREMENTS.md`, 작업 진척도는 `IMPLEMENTATION_ROADMAP.md`, 결정의 이유와 구현 방향은 이 폴더에서 관리한다.

## 읽기 및 갱신 규칙

- 모든 작업 세션은 이 문서와 아래 목록의 파일을 먼저 읽는다.
- 새 결정은 가장 가까운 유형의 파일에 기록한다.
- 표의 `결정`에는 선택한 결과를, `근거·영향`에는 선택 이유나 구현에 미치는 영향을 짧게 적는다.
- 동일한 내용을 여러 파일에 복제하지 않고 필요한 경우 결정 ID를 참조한다.
- 변경된 결정은 삭제하지 않고 상태를 `SUPERSEDED`로 바꾼 뒤 대체 결정 ID를 적는다.
- 아직 확정할 수 없는 사항은 각 파일의 `Open decisions`에만 둔다.
- 구현 과정이나 커밋 내역은 기록하지 않는다. 반복 적용될 정책과 선택만 기록한다.

상태 값:

- `DECIDED`: 현재 적용하는 결정
- `SUPERSEDED`: 다른 결정으로 대체됨
- `DEFERRED`: 의도적으로 후속 단계까지 미룸

## 유형별 파일

| 파일 | ID 접두사 | 범위 | 다음 ID |
|---|---|---|---|
| [architecture-and-configuration.md](architecture-and-configuration.md) | `ARC` | 기술 구조, 실행 환경, 외부 설정 | `ARC-014` |
| [users-auth-and-permissions.md](users-auth-and-permissions.md) | `IAM` | 사용자, 인증, 세션, 역할, 권한 | `IAM-016` |
| [organizations-and-projects.md](organizations-and-projects.md) | `ORG`, `PRJ` | 조직 계층, 프로젝트, 구성원 격리 | `ORG-006`, `PRJ-009` |
| [tickets-and-workflow.md](tickets-and-workflow.md) | `TKT` | 티켓 계층, 상태, 관계, 삭제 | `TKT-014` |
| [content-comments-and-attachments.md](content-comments-and-attachments.md) | `CNT` | 구조화 본문, 댓글, 멘션, 첨부파일 | `CNT-010` |
| [database-and-data-lifecycle.md](database-and-data-lifecycle.md) | `DB` | DB 타입, migration, transaction, 보존 | `DB-019` |
| [ui-search-and-notifications.md](ui-search-and-notifications.md) | `UI` | 화면, 목록, 검색, 칸반, 알림 범위 | `UI-016` |
| [planning-and-reporting.md](planning-and-reporting.md) | `RPT` | 간트 일정, 기간 이력, 보고서·LLM·스킬 계약 | `RPT-009` |

마지막 정리일: 2026-09-26
