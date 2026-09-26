# Tiptap body schema v2

티켓 설명과 댓글의 canonical 원본은 `body_schema_version=2`인 Tiptap JSON document다. HTML과 plain text는 원본 JSON에서 생성하는 파생값이며 독립적으로 수정하거나 원본으로 사용하지 않는다.

## 공통 규칙

- 빈 본문은 `{"type":"doc","content":[{"type":"paragraph"}]}`로 정규화한다.
- canonical JSON은 UTF-8, `ensure_ascii=false`, key 오름차순, 공백 없는 separator를 사용한다.
- document hash는 canonical JSON UTF-8 byte의 SHA-256 hex digest다.
- 전체 JSON은 256,000 bytes, node는 2,000개, 중첩은 20단계, 전체 text는 100,000자로 제한한다.
- 알 수 없는 node·mark·attribute와 임의 HTML·CSS·data attribute는 거부한다.
- 링크는 `http`, `https`, `/`로 시작하는 내부 경로와 `#` anchor만 허용한다. protocol-relative URL, 인증정보가 포함된 URL과 `javascript:` 등은 거부한다.
- image는 `attachmentId` 양의 정수만 원본 참조로 저장한다. `src`, base64와 외부 URL은 받지 않으며 저장 시 프로젝트 범위와 삭제 상태를 다시 확인한다.

## Node

| Node | 주요 attribute | 허용 content |
|---|---|---|
| `doc` | 없음 | block node |
| `paragraph` | 없음 | `text`, `hardBreak` |
| `heading` | `level`: 1·2·3 | `text`, `hardBreak` |
| `text` | `text`, 선택적 `marks` | 없음 |
| `hardBreak` | 없음 | 없음 |
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
- `link`: 검증된 `href`, 선택적 `_blank` target
- `textStyle`: allowlist의 `color`와 `fontSize`

허용 색상과 글자 크기의 실제 목록 및 구조 검증의 단일 구현 기준은 `app/domain/rich_text.py`다. `docs/contracts/tiptap-body.v2.schema.json`은 외부 교환 형식의 기본 구조를, `docs/contracts/tiptap-body.v2.example.ko.json`은 한국어 round-trip 예시를 제공한다.
