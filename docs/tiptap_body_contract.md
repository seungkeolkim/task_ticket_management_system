# Tiptap body schema v2·v3

티켓 설명과 댓글의 canonical 원본은 Tiptap JSON document다. 기존 node만 있으면 `body_schema_version=2`, mention node가 있으면 3을 사용한다. 기존 v2를 계속 읽고 이력은 일괄 변환하지 않는다. HTML과 plain text는 원본 JSON에서 생성하는 파생값이며 독립적으로 수정하거나 원본으로 사용하지 않는다.

## 공통 규칙

- 빈 본문은 `{"type":"doc","content":[{"type":"paragraph"}]}`로 정규화한다.
- canonical JSON은 UTF-8, `ensure_ascii=false`, key 오름차순, 공백 없는 separator를 사용한다.
- document hash는 canonical JSON UTF-8 byte의 SHA-256 hex digest다.
- 전체 JSON은 256,000 bytes, node는 2,000개, 중첩은 20단계, 전체 text는 100,000자로 제한한다.
- 알 수 없는 node·mark·attribute와 임의 HTML·CSS·data attribute는 거부한다.
- 링크는 `http`, `https`, `/`로 시작하는 내부 경로와 `#` anchor만 허용한다. protocol-relative URL, 인증정보가 포함된 URL과 `javascript:` 등은 거부한다.
- Tiptap 3이 link mark에 생성하는 선택적 `title`은 호환 입력으로 길이를 검증한 뒤 canonical JSON에서 제거한다. `href`를 임의 보정하거나 `title`을 저장 데이터로 유지하지 않는다.
- image는 `attachmentId` 양의 정수만 원본 참조로 저장한다. `src`, base64와 외부 URL은 받지 않으며 저장 시 프로젝트 범위와 삭제 상태를 다시 확인한다.

## Node

| Node | 주요 attribute | 허용 content |
|---|---|---|
| `doc` | 없음 | block node |
| `paragraph` | 없음 | `text`, `hardBreak`, v3의 `mention` |
| `heading` | `level`: 1·2·3 | `text`, `hardBreak`, v3의 `mention` |
| `text` | `text`, 선택적 `marks` | 없음 |
| `hardBreak` | 없음 | 없음 |
| `mention` (v3) | 양의 정수 `userId`, 1~200자 `label` | 없음(atom), mark 금지 |
| `bulletList`, `orderedList` | ordered list의 `start` | `listItem` |
| `taskList` | 없음 | `taskItem` |
| `listItem`, `taskItem` | task item의 `checked` | paragraph와 중첩 list 등 |
| `blockquote` | 없음 | block node |
| `codeBlock` | 없음 | mark 없는 `text` |
| `table` | 없음 | `tableRow` |
| `tableRow` | 없음 | `tableHeader`, `tableCell` |
| `tableHeader`, `tableCell` | `colspan`, `rowspan`, `colwidth` | paragraph와 list 등 |
| `image` | `attachmentId`, 선택적 `alt`, `title` | 없음 |

## Mark

- `bold`, `italic`, `underline`, `strike`, `code`
- `link`: 검증된 `href`, 선택적 `_blank` target. 입력의 호환용 `title`·빈 `class`·정해진 `rel`은 검증하지만 canonical mark에는 필요한 `href`·`target`·`rel`만 남긴다.
- `textStyle`: allowlist의 `color`와 `fontSize`

허용 색상과 글자 크기의 실제 목록 및 구조 검증의 단일 구현 기준은 `app/domain/rich_text.py`다. `docs/contracts/tiptap-body.v2.schema.json`은 외부 교환 형식의 기본 구조를, `docs/contracts/tiptap-body.v2.example.ko.json`은 한국어 round-trip 예시를 제공한다.

멘션 lifecycle·권한·migration은 [멘션 계약](mentions.md)을 따른다. v3 교환 schema는 [tiptap-body.v3.schema.json](contracts/tiptap-body.v3.schema.json)이며 `convert_body_v2_to_v3`는 기존 node를 손실 없이 정규화한다. outer ticket-event v2·report-input v1은 body_schema_version으로 본문 계약을 구분하여 v2·v3를 허용한다.
