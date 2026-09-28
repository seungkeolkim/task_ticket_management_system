# 첨부파일 저장과 권한

현재 연결 범위는 티켓에 종속된 일반 파일의 업로드·목록·다운로드와 기존 티켓 설명·댓글의 본문 이미지 업로드·표시다. 댓글에 직접 종속된 일반 첨부파일, 삭제와 30일 보존·영구 삭제는 후속 범위다.

## 저장 구조

DB에는 원본 파일명, MIME type, 크기, SHA-256, 업로더와 상대 `storage_key`를 저장한다. 실제 blob은 `[storage].attachments_dir` 아래 다음 구조로 저장한다.

```text
projects/<project-key>/tickets/<ticket-id>/<uuid 앞 2자>/<다음 2자>/<uuid>.<확장자>
```

예시는 `projects/DEV/tickets/42/ab/cd/abcdef...1234.pdf`다. 프로젝트 key와 전역 ticket ID로 운영자가 파일을 찾을 수 있고, UUID shard가 한 directory에 파일이 몰리는 것을 방지한다. 사용자 원본 파일명은 경로에 사용하지 않는다.

업로드 stream은 먼저 `.staging`에 기록하며 설정된 최대 크기와 SHA-256을 계산한다. 확장자·MIME type·파일 signature 또는 OOXML container 검증이 끝나면 최종 경로로 원자 이동한다. 이후 DB transaction이 실패하면 최종 blob을 보상 삭제한다.

## 기본 검증 정책

- 기본 파일당 최대 크기: 25MB
- 허용 확장자: PNG, JPEG, GIF, WebP, PDF, UTF-8 TXT·Markdown·CSV, DOCX, XLSX, PPTX, ZIP
- 차단 확장자: 실행 파일과 shell·script 계열
- 확장자별 요청 MIME type과 실제 signature 또는 container를 함께 검증
- 원본 파일명에서 client 경로와 제어문자를 제거하고 512자로 제한
- storage adapter에서 절대 경로와 `..` 경로 탈출을 거부

확장자 목록과 확장자별 MIME type은 `config/application.toml`의 `[attachments]`와 `[attachments.allowed_media_types]`에서 조정한다. MIME mapping 없이 확장자만 추가하면 기동 검증이 실패한다.

## 권한과 이력

- 프로젝트 게스트를 포함한 프로젝트 구성원은 목록 조회와 다운로드를 할 수 있다.
- 프로젝트 사용자·관리자와 감사되는 시스템 관리자 override는 활성 프로젝트에 업로드할 수 있다.
- 완료·취소 티켓에도 사후 증빙 파일을 등록할 수 있다.
- 업로드는 티켓 version을 증가시키고 `CONTENT_CHANGED` 티켓 이력과 `attachment.created` 감사 로그를 같은 DB transaction에 기록한다.
- 다운로드는 mount directory를 정적 경로로 공개하지 않고 프로젝트와 티켓 접근 권한을 다시 검사한다.

## 본문 이미지

- 기존 티켓의 설명·댓글 editor는 PNG·JPEG·GIF·WebP를 일반 티켓 첨부파일로 즉시 업로드한다.
- editor는 업로드 결과의 내부 attachment ID만 Tiptap image node에 저장한다.
- `/attachments/{attachment_id}`는 로그인 사용자에게 활성 attachment의 프로젝트·티켓 접근 권한을 다시 검사하고 raster image만 `inline`으로 제공한다.
- 본문 저장을 취소해도 먼저 업로드된 파일은 일반 첨부파일 목록에 남는다.
- 새 티켓은 아직 ticket ID가 없으므로 티켓 생성 후 편집 화면에서 이미지를 추가한다.
- 참조 중인 이미지의 삭제 처리와 30일 후 blob 정리는 후속 TODO다.
