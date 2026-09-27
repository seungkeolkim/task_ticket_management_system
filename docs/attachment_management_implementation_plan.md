# 첨부파일 관리 구현 계획 및 인수인계

## 1. 문서 목적

이 문서는 다음 개발 세션에서 첨부파일 작업을 바로 이어가기 위한 구현 계획과 현재 상태를 기록한다. 제품 요구사항과 완료 여부의 공식 기준은 각각 `REQUIREMENTS.md`와 `IMPLEMENTATION_ROADMAP.md`이며, 이 문서는 구현 세부사항·파일 위치·남은 작업 순서와 주의점을 보충한다.

현재 작업 브랜치는 `feature/attachment-foundation`이다. `main`의 `d921e70`에서 분기했으며 일반 첨부파일 기반과 본문 이미지 기능은 `710cd98`(`첨부파일과 본문 이미지 기능 구현`)에 commit되어 있다. 이전에 만든 `feature/mention-management` 브랜치는 변경 없는 상태로 별도 보존되어 있다.

## 2. 목표 범위

초기 MVP의 첨부파일은 다음 세 사용 형태를 지원한다.

1. 티켓의 일반 첨부파일 업로드·목록·다운로드·삭제
2. 댓글에 종속된 일반 첨부파일
3. 같은 attachment metadata와 blob을 참조하는 Tiptap 본문 image node와 이미지 미리보기

현재 완료 범위는 1번의 업로드·목록·다운로드 기반과 3번의 기존 티켓 본문 이미지 업로드·표시다. 삭제 수명 주기와 댓글에 직접 종속된 일반 첨부파일은 미구현 상태다. 이 중 삭제는 의도적으로 후순위로 미뤘으며, 다음 작업으로 간주하지 않는다.

## 3. 확정된 정책

- blob은 DB가 아니라 `[storage].attachments_dir`로 설정한 mount directory에 저장한다.
- DB에는 원본 파일명, MIME type, 크기, SHA-256, 저장 backend·상대 key, 업로더와 생성·삭제 정보를 저장한다.
- mount directory를 공개 static 경로로 제공하지 않는다. 모든 다운로드는 프로젝트와 티켓 접근 권한을 검사하는 endpoint를 통한다.
- 프로젝트 게스트는 목록 조회와 다운로드만 할 수 있다.
- 프로젝트 사용자·관리자는 활성 프로젝트에 업로드할 수 있다. 시스템 관리자 override는 기존 프로젝트 정책에 따라 감사한다.
- 완료·취소 티켓에도 사후 증빙을 위한 첨부파일 등록을 허용한다.
- 비활성 프로젝트와 휴지통 티켓에는 업로드할 수 없다.
- 기본 파일당 제한은 25MB다. 확장자별 MIME type과 실제 signature 또는 OOXML container를 함께 검증한다.
- 실행 파일과 script 확장자는 차단한다. 기본 allowlist는 CNT-013과 `config/application.toml`을 따른다.
- 업로드는 티켓 version을 증가시키고 `CONTENT_CHANGED` 이력과 `attachment.created` 감사 로그를 metadata와 같은 DB transaction에 기록한다.
- 원본 파일명과 파일 본문, 내부 storage key는 시스템 로그에 기록하지 않는다.
- 실제 삭제는 즉시 수행하지 않는다. 삭제 시 접근을 즉시 차단하고 기본 30일 뒤 blob과 metadata를 영구 삭제하는 기존 요구사항을 유지한다.
- 기존 티켓의 설명·댓글 이미지는 일반 티켓 첨부파일로 즉시 업로드하고 Tiptap에는 attachment ID만 저장한다. 본문 저장을 취소해도 해당 파일은 일반 첨부파일로 유지한다.
- 새 티켓은 ticket ID가 없으므로 생성 후 편집 화면에서 본문 이미지를 추가한다.

관련 결정은 `docs/decisions/content-comments-and-attachments.md`의 CNT-004·CNT-005·CNT-006·CNT-007·CNT-009·CNT-013·CNT-014를 확인한다.

## 4. 저장 경로와 업로드 흐름

### 4.1 최종 저장 key

최종 상대 key는 다음 구조다.

```text
projects/<project-key>/tickets/<ticket-id>/<uuid 앞 2자>/<다음 2자>/<uuid>.<확장자>
```

예시:

```text
projects/DEV/tickets/42/ab/cd/abcdef0123456789abcdef0123456789.pdf
```

- project key는 전역 unique이고 생성 후 변경하지 않는다.
- ticket ID는 서버 DB에서 전역 unique다.
- project key와 ticket ID를 모두 노출하여 운영자가 local filesystem에서 파일 위치를 찾기 쉽게 한다.
- 최종 파일명은 UUID이므로 사용자 파일명 충돌과 경로 조작을 피한다.
- UUID 앞 4자를 2단계 shard로 분리하여 같은 티켓에 파일이 많아져도 한 directory에 파일이 몰리지 않게 한다.
- DB의 `storage_key`에는 OS 독립적인 `/` 구분 상대 key만 저장한다. local adapter가 `os.path.join`으로 실제 경로를 구성하고 `realpath`·`commonpath`로 root 탈출을 차단한다.

### 4.2 업로드 처리 순서

1. 원본 파일명에서 client 경로를 제거하고 길이·제어문자를 검증한다.
2. 확장자가 allowlist에 있고 blocklist에 없으며 요청 MIME type이 확장자별 allowlist와 일치하는지 확인한다.
3. blob을 `<attachments-root>/.staging/<uuid>.upload`에 stream으로 기록하면서 최대 크기와 SHA-256을 계산한다.
4. staging blob의 실제 signature, UTF-8 text 또는 ZIP·OOXML container 구조를 검증한다.
5. SQLite write transaction에서 프로젝트 write 권한·활성 상태·티켓 접근·`expected_version`을 다시 검증한다.
6. staging blob을 최종 shard 경로로 `os.replace`하여 원자 이동한다.
7. attachment metadata, 티켓 version, `CONTENT_CHANGED` 이력과 감사 로그를 저장하고 한 번 commit한다.
8. DB transaction이 실패하면 최종 blob을 보상 삭제한다. 권한·version 검증 전에 거부되면 staging blob을 제거한다.

이 구조는 큰 업로드 stream을 읽는 동안 SQLite `BEGIN IMMEDIATE` lock을 유지하지 않게 한다. 최종 이동과 DB 쓰기 구간만 write transaction 안에서 수행한다.

## 5. 완료한 작업

### 5.1 저장소와 보안 경계

- [x] `AttachmentStorage` protocol 정의
- [x] `LocalAttachmentStorage` adapter 구현
- [x] staging·원자 이동·stream download·멱등 삭제 계약 구현
- [x] project·ticket·UUID shard 기반 storage key 생성
- [x] 상대 경로 탈출과 최종 key 충돌 방어
- [x] stream 기반 최대 크기 제한과 SHA-256 계산
- [x] 파일명·확장자·MIME type allowlist 검증
- [x] PNG·JPEG·GIF·WebP·PDF signature 검증
- [x] UTF-8 TXT·Markdown·CSV 검증
- [x] ZIP·DOCX·XLSX·PPTX container 검증
- [x] ZIP 중앙 directory 항목 수 상한 적용
- [x] 외부 설정의 확장자별 MIME mapping 기동 검증

주요 파일:

- `app/domain/attachments.py`
- `app/storage/attachments.py`
- `app/core/config.py`
- `config/application.toml`

### 5.2 Repository·Service·이력

- [x] 일반 티켓 첨부파일 목록과 단일 활성 row repository 구현
- [x] 프로젝트 membership과 티켓 scope를 적용한 목록·다운로드 service 구현
- [x] 프로젝트 사용자 이상 업로드 service 구현
- [x] 완료·취소 티켓 업로드 허용
- [x] 필수 `expected_version`과 stale write 차단
- [x] 업로드 시 티켓 version·updated_at 증가
- [x] attachment ID 전후 목록을 담은 `CONTENT_CHANGED` 티켓 이력 기록
- [x] 파일 본문·원본 이름·storage key를 제외한 `attachment.created` 감사 기록
- [x] 성공 시 `attachment_uploaded` 시스템 로그 기록
- [x] DB transaction 실패 후 최종 blob 보상 삭제

주요 파일:

- `app/repositories/attachments.py`
- `app/schemas/attachments.py`
- `app/services/attachments.py`
- `app/services/tickets.py`

### 5.3 API와 Web UI

- [x] `GET /api/projects/{project_key}/tickets/{ticket_key}/attachments`
- [x] `POST /api/projects/{project_key}/tickets/{ticket_key}/attachments`
- [x] `GET /api/projects/{project_key}/tickets/{ticket_key}/attachments/{attachment_id}/download`
- [x] JSON API upload에 CSRF·same-origin 검증 적용
- [x] 티켓 상세의 multipart 업로드 form과 첨부파일 목록 연결
- [x] 티켓 상세의 권한 기반 다운로드 route 연결
- [x] 원본 파일명·크기·업로더·생성 시각 표시
- [x] UTF-8 `Content-Disposition`과 정확한 `Content-Length` 응답
- [x] 게스트 upload form 은폐와 서버 write 차단
- [x] 기존 티켓 설명·댓글 editor의 raster image upload·삽입
- [x] image node에 내부 attachment ID만 저장
- [x] `/attachments/{attachment_id}` 보호 endpoint의 inline image 응답
- [x] image만 있는 티켓 설명 표시
- [x] 설명·댓글의 같은 프로젝트·티켓 활성 attachment 재검증
- [x] image upload 후 editor와 티켓 form의 최신 ticket version 동기화

주요 파일:

- `app/api/routes/attachments.py`
- `app/api/router.py`
- `app/web/attachment_responses.py`
- `app/web/tickets.py`
- `app/web/templates/ticket_detail.html`
- `app/web/templates/ticket_form.html`
- `app/web/static/app.css`
- `frontend/tiptap-editor.js`
- `frontend/tiptap-editor.css`

### 5.4 문서와 검증

- [x] CNT-013 저장 경로·검증 정책 결정 기록
- [x] CNT-014 본문 이미지 업로드·표시 정책 결정 기록
- [x] `docs/attachments.md` 운영·권한 설명 작성
- [x] README·관리·프로젝트 문서와 로드맵 동기화
- [x] 저장 경로·path traversal·signature·OOXML 단위 테스트
- [x] 업로드·목록·다운로드·권한·UI form 통합 테스트
- [x] stale `expected_version` 거부 시 staging 정리와 DB 실패 후 최종 blob 보상 삭제 테스트
- [x] allowlist 설정 정규화·누락 검증 테스트
- [x] image-only 설명의 상세·인라인 상세 표시와 보호 endpoint 권한 테스트
- [x] 다른 티켓의 attachment image 참조 차단 테스트

마지막 검증 결과:

```text
pytest: 294 passed
Ruff: All checks passed
기존 dependency deprecation warning: 2건
```

Windows Python 3.13 가상환경에서 실행했다. frontend bundle build도 통과했다. 이번 첨부파일 변경의 Docker Linux와 실제 macOS volume mount 검증은 아직 수행하지 않았다.

## 6. 작업 순서와 다음 작업

본문 이미지까지 구현을 완료했다. 첨부파일 삭제·접근 차단·30일 후 영구 정리는 의도적으로 뒤로 미뤘으며, 별도 우선순위 결정 전에는 착수하지 않는다. 댓글에 직접 종속된 일반 첨부파일과 운영 정책도 후속 후보로만 유지하며, 이 문서에서 다음 즉시 구현 대상을 확정하지 않는다.

### 6.1 완료: 이미지 미리보기와 Tiptap 본문 image

- [x] PNG·JPEG·GIF·WebP inline 표시 endpoint 구현
- [x] 일반 파일 다운로드의 `Content-Disposition: attachment` 유지
- [x] 공통 보안 header의 `nosniff`·`no-store` 적용
- [x] Tiptap toolbar의 이미지 upload·삽입 UI 구현
- [x] image node에 내부 attachment ID만 저장하고 base64·외부 URL 거부
- [x] 티켓 설명과 댓글 저장 시 같은 프로젝트·티켓의 활성 attachment 재검증
- [x] image만 있는 설명을 빈 설명으로 오인하지 않도록 표시 조건 보완
- [x] 새 티켓에서는 생성 후 편집 화면에서만 이미지 추가
- [x] 본문 저장 취소 시 업로드 파일을 일반 첨부파일로 유지

현재 body schema v2의 `image` node와 `attachmentId` 계약을 그대로 사용하므로 schema version은 변경하지 않는다. 이미지 upload는 일반 첨부파일과 같은 저장·검증·이력·감사 경로를 사용한다.

### 6.2 보류: 삭제·접근 차단 정책 연결

삭제 구현은 본문 이미지 기능 완료 후 진행할 예정이었으나 현재 우선순위에서 뒤로 미뤘다. 아래 항목은 삭제 작업을 재개할 때 사용할 TODO이며, 현재 진행 중인 작업이나 바로 이어서 수행할 작업이 아니다.

- [ ] 프로젝트 사용자·관리자와 시스템 관리자 override의 첨부파일 삭제 API 구현
- [ ] 삭제 즉시 일반 목록·다운로드·본문 참조에서 접근 차단
- [ ] `deleted_at`, `deleted_by_id`, `purge_after` 기록
- [ ] `[attachments].deleted_file_retention_days` 적용
- [ ] 삭제 시 티켓 version·`CONTENT_CHANGED` 이력·감사 로그 기록
- [ ] `attachment.deleted` 시스템·감사 event 이름 확정
- [ ] stale `expected_version`과 동시 삭제 충돌 처리
- [ ] 삭제된 blob은 보존 기간 동안 filesystem에 유지
- [ ] 삭제 metadata와 blob의 사용자 복구 기능은 현재 요구사항에 없으므로 추가하지 않음
- [ ] 삭제·권한 상실 image의 viewer 자리표시자 처리

구현 전에 반드시 결정할 항목:

- Tiptap 설명·댓글에서 현재 참조 중인 attachment의 삭제를 차단할지, 삭제를 허용하고 깨진 참조 자리표시자를 보여줄지 결정한다.
- 일반 첨부파일과 본문 image가 같은 row를 사용하므로 참조 여부를 조회하는 방법과 삭제 UX를 결정한다.
- 댓글 soft delete 시 댓글 attachment를 바로 삭제 상태로 전환할지, 댓글 원문 보존 기간과 함께 유지할지 결정한다.

### 6.3 후속 후보: 댓글에 직접 종속된 일반 첨부파일

- [ ] 업로드 시 선택적 `comment_id` 연결 계약 확정
- [ ] 댓글 생성 전에 먼저 업로드하는 임시 attachment의 소유·만료 정책 결정
- [ ] 기존 댓글에 첨부하는 경우 comment optimistic locking 적용 여부 결정
- [ ] 댓글 삭제·영구 정리와 attachment 수명 주기 연결
- [ ] 댓글 thread 화면의 파일 목록·다운로드 UI 구현
- [ ] 다른 티켓·댓글 attachment 참조 차단 테스트

### 6.4 명시적 TODO: 30일 후 영구 정리와 운영 수명 주기

삭제 작업을 재개하여 이미지 참조와 삭제 방식이 확정된 뒤 구현한다. 현재 단계에서는 착수하지 않으며 완료 처리하지 않는다.

- [ ] `purge_after <= now`인 attachment 조회 repository 구현
- [ ] blob 삭제 성공 후 metadata 물리 삭제 순서 적용
- [ ] blob 삭제 실패 시 metadata를 유지하고 재시도 가능하게 처리
- [ ] 티켓 영구 삭제 전에 attachment blob과 metadata를 먼저 정리
- [ ] 관리자 수동 실행과 내부 system actor 자동 실행 구분
- [ ] 작업 시작·완료·실패 시스템 로그와 감사 로그 적용
- [ ] 명령 중복 실행과 재시작에 안전한 멱등성 검증
- [ ] `.staging`에 남은 오래된 임시 파일 정리 정책·명령 구현
- [ ] 빈 shard directory 정리 여부 결정
- [ ] scheduler 구조는 architecture decision 문서의 open decision과 운영 준비 단계에서 확정

### 6.5 운영 정책 후속

- [ ] instance 전체 attachment 저장 용량 상한 확정
- [ ] 프로젝트별 또는 전체 quota 적용 여부 결정
- [ ] quota 임계치 경고와 업로드 차단 정책 결정
- [ ] backup archive에 blob과 manifest를 포함하는 방식 구현
- [ ] local blob과 DB metadata 불일치 점검 명령 검토
- [ ] Docker Linux volume 권한·원자 이동 검증
- [ ] macOS Docker Desktop volume mount와 한글 파일명 다운로드 검증

## 7. 삭제 작업 재개 시 권장 transaction 순서

이 절은 보류된 삭제 작업을 나중에 재개할 때 따를 구현 지침이다.

1. write transaction과 SQLite lock을 시작한다.
2. 프로젝트 write 권한·활성 상태·티켓·attachment scope를 다시 검증한다.
3. 티켓 `expected_version`을 검사한다.
4. 본문 참조 정책에 따라 삭제 가능 여부를 판정한다.
5. 티켓 before snapshot과 활성 attachment ID 목록을 만든다.
6. attachment에 `deleted_at`, `deleted_by_id`, `purge_after`를 기록한다. 이 단계에서는 blob을 제거하지 않는다.
7. 티켓 version·updated_at을 증가시킨다.
8. after snapshot과 attachment ID 목록으로 `CONTENT_CHANGED` 이력을 기록한다.
9. `attachment.deleted` 감사 로그를 기록하고 한 번 commit한다.
10. 다운로드 service는 `deleted_at IS NULL` 조건으로 즉시 접근을 차단한다.

영구 삭제 작업에서는 반대로 blob 삭제가 성공하기 전 metadata를 제거하지 않는다(CNT-007). blob 삭제 성공 후 같은 작업 단위에서 metadata를 물리 삭제한다.

## 8. 다음 세션 시작 체크리스트

1. `REQUIREMENTS.md`, `IMPLEMENTATION_ROADMAP.md`와 전체 decision 문서를 다시 읽는다.
2. DB 작업이므로 `docs/database_conventions.md`, Python·운영 작업이므로 `docs/logging_conventions.md`를 읽는다.
3. 현재 branch가 `feature/attachment-foundation`인지 확인한다.
4. `git status`에서 이 문서에 기록된 미커밋 변경 외에 사용자 변경이 있는지 확인한다.
5. `docs/attachments.md`와 이 문서를 읽고 CNT-013 저장 key를 유지한다.
6. 삭제 작업의 우선순위가 다시 정해지면, 구현 전에 본문 참조 중인 attachment 삭제 정책을 결정하고 decision log에 CNT-015로 기록한다.
7. 완료된 체크리스트만 `IMPLEMENTATION_ROADMAP.md`에 반영한다.

## 9. 테스트 파일과 재검증 명령

관련 테스트:

- `tests/unit/test_attachment_storage.py`
- `tests/unit/test_config.py`
- `tests/integration/test_attachments.py`

권장 재검증:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_attachment_storage.py tests/unit/test_config.py tests/integration/test_attachments.py -q
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app tests
git diff --check
```

보류된 삭제·purge 구현을 재개할 때 최소한 다음 실패 경로를 추가한다.

- 게스트·외부 사용자·비활성 프로젝트 삭제 거부
- 다른 프로젝트·티켓 attachment ID 존재 은폐
- stale ticket version 거부와 metadata·이력·감사 rollback
- 감사 기록 실패 시 삭제 상태 rollback
- 보존 기간 전 다운로드 차단과 blob 유지
- 만료 후 blob 삭제 성공·실패·재시도
- 티켓 purge가 attachment FK RESTRICT 순서를 지키는지 검증
- 본문에서 참조 중인 attachment 삭제 정책 회귀

## 10. 현재 완료 기준과 남은 완료 기준

현재 일반 첨부파일 기반은 다음 조건을 충족한다.

- 안전한 local storage key와 directory 분산
- 크기·확장자·MIME·실제 내용 검증
- 프로젝트 권한이 적용된 업로드·목록·다운로드
- 티켓 version·이력·감사와 DB/blob 보상 처리
- 티켓 상세 Web UI와 JSON API
- Tiptap 설명·댓글의 image upload·내부 ID 삽입과 보호된 inline 표시
- 전체 pytest와 Ruff 통과

로드맵의 첨부파일 단계 전체를 완료하려면 다음 조건이 추가로 필요하다. 모두 후속 범위이며, 특히 삭제와 30일 영구 정리는 현재 우선순위에서 뒤로 미뤘다.

- 삭제 즉시 접근 차단과 30일 보존
- blob·metadata 영구 삭제 명령
- 댓글 첨부 수명 주기
- 운영 환경의 저장 용량 정책
- Docker Linux·macOS volume과 운영 정리 절차 검증
