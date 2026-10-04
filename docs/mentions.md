# 설명·댓글 멘션

## 입력과 대상

- 티켓 설명, 댓글, 한 단계 대댓글에서 `@` 또는 toolbar의 `@`를 입력하고 후보를 선택한다. 위·아래 방향키와 Enter, Escape 및 마우스를 지원한다.
- 로그인 ID·표시 이름으로 현재 프로젝트의 활성 구성원을 최대 50명 검색한다. 게스트와 자기 자신을 포함하고, 명시적 membership이 없는 시스템 관리자는 후보에서 제외한다.
- 후보에는 ID·로그인 ID·표시 이름만 반환한다. 후보 검색의 시스템 관리자 override는 기존 프로젝트 감사 정책을 따른다.
- 서버는 본문 저장 transaction의 쓰기 잠금 안에서 모든 대상의 현재 membership·활성 상태를 다시 확인한다. 표시 이름은 서버 값으로 정규화한다. 후보 선택 후 권한이 회수되었다면 해당 멘션을 제거한 뒤 저장해야 한다.
- 일반 text의 `@이름`은 알림을 만들지 않는다. `mention` node의 `userId`가 안정 식별자이고 `label`은 저장 시점 표시 이름이다.

## 본문과 알림 수명

- 멘션 node가 있는 본문은 `body_schema_version=3`, 기존 node만 있는 본문은 v2다. v3는 v2의 node를 모두 포함한다. 기존 row·이력을 일괄 변환하지 않으며 v2→v3 converter는 기존 구조를 손실 없이 정규화한다.
- 원본(ticket 설명 또는 comment)·대상 사용자별 row 한 개를 유지한다. 같은 대상을 여러 번 적어도 알림은 하나다.
- 유지된 멘션은 수정·no-op 저장에서 기존 `read_at`·시각·작성자를 보존한다. 제거 시 `removed_at`을 기록하고, 제거 후 다시 추가하면 같은 row를 현재 작성자·시각과 미확인 상태로 재활성화한다.
- 댓글 삭제 시 그 댓글의 멘션은 제거한다. 원댓글 삭제가 기존 대댓글의 멘션을 제거하지는 않는다.
- 티켓 휴지통 이동 또는 프로젝트 참여 해제 시 원본·멘션 모두 일반 조회에서 숨긴다. 복구·재참여 후에는 보존된 읽음 상태를 다시 적용한다.
- 멘션 동기화는 본문·감사·티켓 이력과 같은 transaction이다. 별도 commit이 없으며 실패 시 함께 rollback한다. 멘션 자체의 변경 때문에 ticket version을 한 번 더 증가시키지 않는다.

## 읽음 처리

- 대시보드는 현재 접근 가능한 미확인 멘션 최신 5개를 표시한다. 개별 읽음, 원본 보기·읽음, 모두 읽음을 제공한다.
- 원본 보기는 확인 후 ticket으로 이동하며 comment 원본이면 `#comment-<id>` 위치로 이동한다.
- 모두 읽음은 화면의 5개 제한과 무관하게 현재 접근 가능한 본인 미확인 멘션 전체에 적용한다. 읽지 못하는 멘션은 그대로 유지한다.
- 모든 쓰기는 CSRF·same-origin을 검증하는 POST다. 이미 읽은 항목의 재확인은 no-op이다. 시스템 관리자도 다른 사람의 멘션을 확인할 수 없다.
- 비활성 프로젝트에서도 현재 구성원은 읽음 처리할 수 있다. 프로젝트·원본 접근권한이 없으면 단일 읽음은 404다.
- 실질 읽음 변경만 `mention.read` 감사에 건수를 기록한다. 본문·검색어·표시 이름은 시스템 로그나 감사 context에 넣지 않는다. 시스템 로그는 기존 작업 context의 시작·실패와 DEBUG 완료 건수를 사용한다.

## API

| 경로 | 동작 |
|---|---|
| `GET /api/projects/{project_key}/mention-candidates?query=...` | 최대 100자 검색어, 최대 50명 후보 |
| `POST /api/mentions/{mention_id}/read` | 본인 항목 확인, `read_count`·`destination` 반환 |
| `POST /api/mentions/read-all` | 접근 가능한 본인 항목 전체 확인 |

## Migration과 검증

- Alembic `20261004_0008`은 ticket·comment의 본문 version CHECK를 2·3으로 확장한다. 기존 v2 본문·이력·FK·ID는 보존한다.
- SQLite table 재구성 동안 migration connection의 FK 검사를 잠시 해제하고 완료 후 `foreign_key_check`와 FK 활성화를 수행한다. 실행 전 애플리케이션을 중지하고 일관된 백업을 확보한다. SQLite DDL의 원자적 rollback은 보장하지 않는다.
- downgrade는 현재 본문과 ticket 이력의 mention node를 `@표시 이름` text로 변환하고 본문 version을 2로 되돌린다. 사용자 참조 의미는 손실되므로 완전 복구에는 백업이 필요하다. 멘션 row와 기존 읽음 이력은 보존하며 re-upgrade가 text를 멘션으로 추측 복원하지 않는다.
- 자동 검증은 임시 DB를 사용한다. 기존 업무 DB에 migration을 적용하는 작업은 별도다.
- 통합 테스트: `tests/integration/test_mentions.py`; 구조·XSS 검증: `tests/unit/test_mention_document.py`; 실제 Browser: `tests/browser/mentions.test.cjs`.
