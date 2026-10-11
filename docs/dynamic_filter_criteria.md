# 동적 필터 기준값

정리일: 2026-10-12. 상태: 독립 날짜 경계 확장 구현·검증 완료. UI-035·UI-039·UI-040·DB-029·DB-030을 따른다.

## 입력과 의미

날짜 또는 사용자 필드를 추가했을 때만 기준값 선택창을 표시한다. 고정 Date·사용자 복수 선택과 동적 규칙은 같은 조건 행에서 전환한다. 조건의 values와 rule은 동시에 지정하지 않는다. 사용자 고정값과 현재 사용자 규칙을 혼합하려면 AND/OR 그룹에 같은 필드 조건을 추가한다. 날짜 기간은 date_range의 시작·종료 안에서 고정 날짜와 동적 기준을 섞을 수 있다.

| 기준값 | 입력 | 해석 |
|---|---|---|
| 오늘 | 추가 입력 없음 | 적용 요청의 Asia/Seoul 날짜 |
| 오늘 기준 N일 전/후 | 전/후, 일수 1~3650 | 오늘−N일 또는 오늘+N일 |
| 상대 기간 | 최근/앞으로, 일수 1~3650 | 오늘 포함 총 N개 달력 날짜 |
| 이번 working week | 추가 입력 없음 | 이번 달력 주의 월~금 |
| 지난 working week | 추가 입력 없음 | 지난 달력 주의 월~금 |
| 이번·지난주 요일 | 주와 월~일 요일 | 해당 달력 주의 단일 날짜 |
| 시작·종료 직접 지정 | 경계별 기준값 | 독립 경계의 기간, 양 끝 날짜 포함 |
| 현재 사용자 | 추가 입력 없음 | 적용 요청의 인증된 사용자 |

`최근 7일`은 오늘−6일부터 오늘까지다. `앞으로 7일`은 오늘부터 오늘+6일까지다. `1일`은 두 방향 모두 오늘이다. 오늘부터 7일 전까지 양 끝을 포함하는 범위를 원하면 최근 8일을 선택한다.

오늘·N일 전/후·이번/지난주 요일은 on/before/after로 비교한다. before/after는 기준일 전체를 제외한다. 상대 기간·working week·독립 시작/종료는 between으로 비교하며 NOT으로 기간 밖을 조회할 수 있다. working week는 주말 조회에서도 해당 달력 주의 월~금이며 공휴일과 아직 지나지 않은 금요일을 포함한다. 외부 Calendar는 없다.

```text
수정일 [기간 내] [상대 기간] [최근] [7]일
→ 최근 7일 · 오늘 포함 · 2026-10-06 ~ 2026-10-12

생성일 [이전] [오늘 기준 N일 전/후] [전] [7]일
→ 2026-10-05보다 이전 · 기준일 제외
```

Browser 미리보기는 서버가 화면을 조회한 한국 날짜로 계산한다. 실제 적용 결과는 서버의 해석값을 별도로 표시한다. 화면을 자정 너머 열어두면 미리보기는 이전 요청 기준으로 남고 적용·새로고침 시 서버가 새 날짜로 계산한다. 자동 refresh나 Scheduler는 추가하지 않는다.

## v4 계약과 Resolver

[JSON Schema](contracts/ticket-filter.v4.schema.json)와 [예시](contracts/ticket-filter.v4.example.ko.json)를 게시한다. 조건의 values는 기존 고정값 목록이며 rule은 다음 중 하나다.

```json
{"kind":"current_user"}
{"kind":"today"}
{"kind":"day_offset","days":7,"direction":"past"}
{"kind":"relative_period","days":7,"direction":"future"}
{"kind":"working_week","week":"this"}
{"kind":"week_day","week":"last","weekday":4}
{"kind":"date_range","start":{"kind":"week_day","week":"last","weekday":0},"end":{"kind":"week_day","week":"last","weekday":4}}
```

고정 조건에서는 rule을 생략한다. 동적 조건에는 values를 생략하거나 빈 목록으로 둔다. 알 수 없는 kind·필드·연산자·추가 속성·소수·boolean 일수와 고정/동적 동시 지정은 거부한다. JSON 4 KiB·전체 node 60·root 포함 깊이 5·조건당 선택값 30 제한은 유지한다.

service가 프로젝트 권한과 고정 참조를 검사한 뒤 Resolver를 한 번 호출한다. Resolver는 기준 시각·한국 날짜·인증된 사용자를 고정하고 원본을 보존한 조회용 복사본을 반환한다. 고정값 복사본은 기존 SQLAlchemy 조건 변환기로 조회한다. 목록의 count와 row는 같은 query를 사용한다.

현재 사용자 규칙은 저장자나 선택 후보의 ID로 변환해 저장하지 않는다. 게스트·비참여 시스템 관리자가 고정 사용자 후보에 없어도 프로젝트 접근 권한 확인 후 인증 actor로 조회한다. 본인과 일치하는 티켓이 없으면 정상 빈 결과다. NOT·미지정 의미와 권한·휴지통 제외 조건은 기존과 동일하다.

API의 TicketPage·BoardView에 filter_resolution을 추가해 evaluated_at, reference_date, timezone, user_id, user_label, conditions를 제공한다. 각 동적 조건은 트리 path와 이번 요청의 고정 values를 갖는다. URL·저장 JSON·편집기에는 원본 규칙을 유지하며 해석 metadata를 저장 조건에 섞지 않는다. 전역 목록처럼 동적 필터를 사용하지 않는 기존 응답은 filter_resolution이 null이다.

## 저장 데이터와 migration

Alembic `20261012_0011`에서 v2 저장 필터를 v3로 한 번 이관하고 기본값을 3으로 변경한다. 조건·정렬·페이지 크기·이름·범위·소유자·row ID·created_at·updated_at과 다른 업무 데이터는 보존한다. v1 정리는 기존 0010 정책을 유지한다. 과거 계약의 runtime reader나 dual-read는 추가하지 않는다.

downgrade는 고정 v3 필터를 v2로 복원한다. 동적 규칙이 하나라도 있으면 어떤 row나 schema도 바꾸기 전에 중단하며 날짜·사용자로 임의 고정하거나 삭제하지 않는다. 실제 사용 DB에는 이번 migration을 아직 적용하지 않았다.

## 검증과 후속 논의

한국 자정·월/연도·윤일·월요일·금요일·주말 경계, 기간의 오늘 포함, 사용자별 공용 내 이슈, 후보 밖 actor·권한, NULL 부정, 저장 규칙 보존·재적용과 migration 왕복을 검증한다. 실제 Browser에서 기준값 전환·숫자 입력·미리보기·저장/복원·목록/칸반 전환을 확인한다.

주 요일은 단일 날짜 비교와 기간의 시작·종료에 모두 사용할 수 있다. 월요일에 지난주 내용을 조회하려면 시작은 지난주 월요일, 종료는 지난주 금요일로 지정한다. 주는 월요일 시작의 달력 주이며 주말에도 같은 정의를 사용한다. 수정일 조회는 현재 마지막 수정일 기준이며 모든 변경 이력의 주간보고 수집은 별도 범위다.

기간의 시작·종료는 고정 날짜·오늘·N일 전후·이번/지난주 요일을 독립 선택한다. 역순은 안내하고 거부하며 같은 날짜는 하루 전체다. 규칙을 저장·URL에 유지하고 요청마다 같은 기준 시각으로 양 경계를 해석한다.

2026-10-12 검증 결과: Windows 전체 pytest 519개가 실제 Edge 시나리오를 포함해 통과했다. Linux 전체 pytest는 492개 통과·15개 skip이며 Ruff도 통과했다. JavaScript 문법·문서 링크·결정 ID·diff 검사와 데이터가 있는 migration 왕복·동적 rule downgrade 중단을 확인했다. 기존 dependency 경고는 Windows 2개·Linux 1개이며 macOS·PostgreSQL은 검증하지 않았다.

0012 migration은 기존 v3 고정값·동적 규칙과 메타데이터를 보존해 v4로 이관한다. 새 week_day/date_range가 있으면 downgrade는 모든 row/schema 변경 전에 중단하며 기존 규칙만 v3로 복원할 수 있다. 실제 사용 DB에는 적용하지 않았다.

입력 예시: 수정일 → 기간 내 → 시작·종료 직접 지정 → 시작: 지난주 월요일 / 종료: 지난주 금요일. 둘 다 이번 주로 바꾸거나 한 경계를 날짜 직접 선택·오늘·N일 전후로 바꿀 수 있다. 같은 주의 금요일은 주말에도 해당 주의 금요일이며 직전에 지난 금요일로 자동 해석하지 않는다.

날짜 경계 확장 검증: Windows 전체 pytest 543개(실제 Edge 포함), Linux 전체 pytest 515개 통과·16개 skip, Ruff·JavaScript 문법·문서 링크·결정 ID·diff 검사 통과. 실제 DB에서 지난주 월요일 00시~토요일 00시 직전의 timestamp와 월~금 Date, 금요일 하루, 역순 거부·원본 규칙 보존, v3 이관·신규 경계 downgrade 중단과 Browser 저장·복원을 확인했다. 기존 dependency 경고와 미검증 플랫폼 범위는 앞선 기록과 동일하다.
