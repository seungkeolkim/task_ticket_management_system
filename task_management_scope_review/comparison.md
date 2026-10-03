# Jira·Notion task management 비교와 구현 범위 검토

- 조사일: 2026-10-03
- 저장소 기준: `main`, `4523def`
- 상태: 범위 검토 중. 58개 항목 중 A01은 **방향 확정·세부 범위 미정**, 나머지 57개는 **미결정**이다.
- 목적: 기능을 추가하기 전에 ticket 속성과 업무 흐름을 비교하고, 항목별로 `이번 범위 포함 / 후속 / 제외 / 현행 유지`를 결정한다.
- 이 문서는 별도 브랜치의 범위 검토 자료다. 결정은 이 폴더의 `decisions.md`에만 기록하며 기존 요구사항·decision·로드맵은 변경하지 않는다. 공식 문서 반영은 범위 검토 후 별도 합의한다.

## 1. 비교 기준

Jira는 Cloud의 일반 업무·software task management를 기준으로 한다. Jira Service Management의 SLA, 고객 portal, incident/change management와 Marketplace app은 기본 비교에서 제외한다. 공식 문서의 work item은 이 문서의 ticket에 해당하며, space는 기존 project 용어에 대응한다. 기능은 project 유형·요금제·관리 설정·배포 상태에 따라 다르므로 모든 Jira 사용자가 동일한 기능을 기본 제공받는다는 의미가 아니다.

Notion은 task database, Projects·Tasks·Sprints, 업무에 적용하는 properties·views·relations·automations만 비교한다. 일반 wiki, 문서 publishing, meeting notes, CRM과 범용 AI는 제외한다. Notion task database는 Status·Assignee·Due date에 대응하는 property를 지정하는 구조다. [Notion task databases][N02]

표에서 **구성**은 제품이 해당 의미의 전용 기능을 바로 제공한다는 뜻이 아니라, 기본 property·relation·automation을 이용해 사용자가 설계할 수 있다는 뜻이다. 예를 들어 Notion의 Number property를 예상 시간으로 쓰는 것과 Jira의 Work log는 동등하지 않다. **미확인**은 공식 문서에서 동등한 전용 기능을 확인하지 못했다는 뜻이며, 제품 전체에 절대로 없다는 단정이 아니다.

현재 상태는 다음과 같이 구분한다.

| 표시 | 의미 |
|---|---|
| 구현 | 코드에서 service·API·화면 연결을 확인한 범위 |
| 부분 | 일부 조회·처리만 구현됨 |
| 기반만 | DB 모델·계약은 있으나 사용자가 쓰는 기능은 미구현 |
| 없음 | 조사한 모델·service·API·화면에 해당 기능이 없음 |
| 기존 MVP | 요구사항에 포함되어 있고 아직 완료되지 않음 |
| 후속 | 문서에서 다음 범위로 미뤄둠 |
| 제외 | 현재 요구사항에서 명시적으로 제외하거나 제한함 |
| 미정 | 명확한 구현 범위가 아직 없음 |

이번 조사는 문서 및 정적 코드 확인이다. 테스트나 실행 중인 화면 검증은 수행하지 않았다. `구현`은 이번에 새로 테스트를 통과했다는 의미가 아니다.

## 2. 현재 제공하는 공통 기반

| 영역 | 현재 구현 | 비교할 때의 주의점 |
|---|---|---|
| 식별·본문 | 프로젝트, 티켓 key, 제목, Tiptap 설명, 생성·수정일시 | Jira의 Summary·Description, Notion의 제목·페이지 본문·metadata에 대응 |
| 분류·상태 | Epic·Task·Subtask, 고정 5개 상태와 FSM, 고정 5단계 Priority | 사용자 정의 분류·상태·전이와는 다름 |
| 책임자 | 자동 기록하는 creator, 선택 가능한 단일 assignee | 대리 요청자·협업자·reviewer는 별도 속성으로 없음 |
| 일정 | 날짜 단위 due date, 최초 착수·완료·취소 시각 자동 기록 | 계획 기간을 편집하거나 예상·실제 공수를 기록하는 기능은 아님 |
| 계층 | 동일 프로젝트의 Epic→Task→Subtask, parent 이동, 하위 티켓 빠른 생성 | 유형 변환과 프로젝트 간 이동은 없음 |
| 관계 | Related·Depends on, 역방향 표시, 미완료 의존 대상에 따른 완료 차단 | Jira·Notion의 관계 표시가 동일한 완료 차단을 보장하는 것은 아님 |
| 협업 | 댓글·1단계 답글·수정·soft delete, 일반 첨부·본문 이미지·다운로드 | 멘션 생성·읽음과 첨부파일 삭제는 미완성 |
| 조회 | 목록 필터·정렬·pagination, key·제목 검색, inline/full 상세 | Notion의 임의 property·view 구성이나 Jira의 JQL은 없음 |
| 칸반 | 상태 열, Epic 그룹, Subtask 표시, drag 상태 변경 | 필터·수동 순위 변경·WIP 제한은 없음 |
| 내 작업 | 담당 티켓과 담당자 없는 본인 생성 티켓, 기한·최근 수정 집계 | 프로젝트별 통계·공수 기반 workload와는 다름 |
| 추적·보호 | version 충돌 처리, 변경 전후 이력, 감사 로그, 프로젝트 권한, 휴지통·계층 복구 | 삭제 보존 기간 만료 후 정리 명령은 미구현 |

외부 대응 근거: [Jira 기본 필드][J01], [Jira 유형·계층][J02], [Notion properties][N01], [Notion sub-items][N03].

## 3. 코드와 로드맵을 대조하면서 확인한 사항

1. **계획 일정·진행률·마일스톤은 기반만 있다.** `Ticket`과 이력 snapshot에는 있지만 `TicketCreate`·`TicketUpdate` 및 편집 화면에는 없다. 따라서 간트의 화면만 추가하면 되는 상태로 계산하지 않는다. [모델](../app/models/work.py), [입력 DTO](../app/schemas/tickets.py), [편집 service](../app/services/tickets.py)
2. **칸반 필터는 요구사항에는 있지만 연결되지 않았다.** board route·service는 project만 받아 전체 board를 구성한다. 목록의 `TicketFilter` 연결과 분리해서 추적해야 한다. [요구사항 §8.4](../REQUIREMENTS.md), [web route](../app/web/tickets.py), [board service](../app/services/tickets.py)
3. **멘션은 조회 기반까지다.** DB와 dashboard query는 있지만 editor의 허용 inline node에 mention이 없고 생성·동기화·읽음 API가 없다. 다만 dashboard query의 membership join과 삭제 원본 제외는 이미 있으므로 ‘권한 은폐가 전혀 없다’고 분류하지 않는다. [본문 계약 코드](../app/domain/rich_text.py), [dashboard query](../app/repositories/dashboard.py)
4. **저장 필터는 모델·DTO만 있다.** 개인/프로젝트 visibility와 definition은 있으나 저장·수정·삭제·호출 기능은 미구현이다. [모델](../app/models/content.py), [필터 계약](../app/schemas/contracts.py)
5. **카드 순서도 기반만 있다.** `sort_order`로 조회하지만 사용자 재정렬 쓰기 기능은 없다. drag 상태 변경과 순서 변경을 구분한다. [repository](../app/repositories/tickets.py), [board JavaScript](../app/web/static/board.js)
6. **첨부파일 보존 필드가 삭제 기능의 완료를 의미하지 않는다.** API는 조회·등록·다운로드이고 CLI는 bootstrap만 제공한다. 삭제·30일 후 blob 정리·휴지통 purge는 남아 있다. [첨부 API](../app/api/routes/attachments.py), [CLI](../app/cli.py)
7. **관리 화면 전체가 미구현인 것은 아니다.** 사용자 수정·비활성화·비밀번호 초기화와 프로젝트·참여자 관리는 연결되어 있다. 남은 큰 범위는 조직 수정·이동·비활성화와 JSON 입출력이다. 로드맵의 포괄 checkbox를 기능별로 읽어야 한다. [관리 API](../app/api/routes/administration.py), [로드맵](../IMPLEMENTATION_ROADMAP.md)

## 4. A — Ticket 속성별 결정 목록

현재의 제목·설명·key·Priority·creator·assignee·due date·생성/수정일·parent는 위 공통 기반으로 보존해서 비교한다. 아래는 추가 또는 확장 여부를 결정할 속성이다. ‘이번 범위’가 기존 MVP의 추가인지 대체인지도 결정 시 기록한다.

| ID | 결정할 항목 | Jira | Notion task management | 현재 구현 / 기존 범위 | 결정 |
|---|---|---|---|---|---|
| A01 | Bug·Story 등 업무 유형 | 표준 유형과 custom work type [J02] | Select로 구성 [N01] | Epic·Task·Subtask만 구현 / 별도 업무 분류 도입 방향 확정, 미구현 | 2026-10-03: 계층 유지 + 업무 분류 속성 분리. 세부 범위·구현 시점 미정. [결정 기록](decisions.md) |
| A02 | Labels·Tags | Labels [J01] | Multi-select [N01] | 없음 / 요구사항 §5.2의 확장 후보 | 미결정 |
| A03 | Component·업무 영역 | project별 component, owner·자동 할당; company-managed [J03] | Select 또는 Relation으로 구성 [N01][N04] | 없음 / 확장 후보 | 미결정 |
| A04 | 목표 Release·Fix version | release와 Fix version [J04] | Release database relation으로 구성 [N04] | 없음 / 미정 | 미결정 |
| A05 | 영향받는 Version | Affects version [J01] | Select·Relation으로 구성 [N01][N04] | 없음 / 미정 | 미결정 |
| A06 | 재현 환경·재현 절차·Acceptance criteria | Environment와 본문·custom field로 구성 [J05][J06] | 본문·property·template으로 구성 [N01][N06] | 본문에 수동 기재 가능, 독립 필드·template 없음 / 미정 | 미결정 |
| A07 | Severity — Priority와 별도 관리 | custom Select로 구성 가능; 모든 Jira의 기본 필드로 간주하지 않음 [J06] | Select로 구성 [N01] | Priority만 있음 / 미정 | 미결정 |
| A08 | Reporter·요청자 — 생성자와 분리 | Reporter 및 변경 권한 [J01][J07] | Created by 외 Person으로 구성 [N01] | creator만 자동 기록 / 미정 | 미결정 |
| A09 | 복수 담당자·협업자·Reviewer | 추가 multi-user field로 구성 가능 [J06] | Person에 여러 사용자 지정 [N01] | 단일 assignee만 있음 / 미정 | 미결정 |
| A10 | 계획 시작일·종료일 | Start/end 일정·Plans [J08] | Date range [N01] | 기반만 / 후속 간트 | 미결정 |
| A11 | 시간까지 지정하는 기한 | Date time custom field로 구성 [J06] | Date의 time·timezone [N01] | due date는 날짜만 / 미정 | 미결정 |
| A12 | Story points·상대적 작업량 | Story points [J09] | Number로 구성 [N01] | 없음 / 확장 후보 | 미결정 |
| A13 | 예상 공수·남은 공수 | Original·Remaining estimate [J09] | Number property로 구성; 전용 추적과 구분 [N01] | 없음 / 예상 작업량은 확장 후보 | 미결정 |
| A14 | 실제 작업 시간·Work log | 작업별 시간 기록 [J07][J09] | 시간 기록 database와 Relation·Rollup으로 구성 [N04] | 없음; 최초 착수 시각은 작업 시간 합계가 아님 / 미정 | 미결정 |
| A15 | 진행률 % | 개수·estimate 기반 진행 집계, custom numeric field [J08][J06] | Number·Formula·Rollup [N01][N04] | `progress_percent` 기반만 / 후속 | 미결정 |
| A16 | Milestone 표시 | timeline의 일정 관리와 custom field로 구성; 동일한 범용 Boolean은 미확인 [J08][J06] | Date·Checkbox 등으로 구성 [N01] | `is_milestone` 기반만 / 후속 | 미결정 |
| A17 | Sprint 소속 | Sprint 필드 [J10] | task와 Sprint relation [N02] | Sprint 모델·기능 없음 / 후속 | 미결정 |
| A18 | Resolution·종료 사유 | 상태와 별도 Resolution [J11] | Select·Text로 구성 [N01] | 완료·취소만 구분 / 미정 | 미결정 |
| A19 | Blocked flag·막힘 사유 | Flag와 dependency link [J12][J13] | Checkbox·Status·dependency로 구성 [N01][N03] | ON_HOLD·Depends on은 있으나 독립 flag·사유 없음 / 미정 | 미결정 |
| A20 | 사용자 정의 필드 | Text·Number·Select·Date·User 등 [J06] | database property 추가 [N01] | 없음 / 후속 | 미결정 |
| A21 | 계산 필드·관계 집계 | Formula field 및 Plans roll-up [J14][J08] | Formula·Rollup [N04][N05] | 고정 dashboard 집계만 구현 / 범용 계산은 미정 | 미결정 |
| A22 | 외부 참고 자료 URL 목록 | Web link [J13] | URL·Relation·본문 link [N01][N04] | 본문 link 구현, 별도 자료 목록 없음 / 미정 | 미결정 |
| A23 | 담당 Team·조직 | Team 필드 [J10] | Team database Relation 등으로 구성 [N04] | 사용자 소속 조직은 있지만 ticket 담당 조직 속성은 없음 / 미정 | 미결정 |
| A24 | 목표·OKR 연결 | Goal 연결 [J35] | 목표 database Relation으로 구성 [N04] | 없음 / 미정; 목표 관리 시스템 전체 도입과 구분 | 미결정 |

A06은 ‘별도 속성’과 ‘본문 template’ 중 선택할 수 있다. A09는 ‘책임자 1명 + 협업자 여러 명’과 ‘복수 책임자’를 분리해 결정한다. A12·A13·A14는 상대 크기·시간 예상·실제 투입량이므로 서로 대신하는 필드가 아니다. A15의 직접 입력 진행률과 하위 완료율 집계도 별개다.

## 5. B — 해당 속성을 활용하는 기능별 결정 목록

| ID | 결정할 기능 | Jira | Notion task management | 현재 구현 / 기존 범위 | 결정 |
|---|---|---|---|---|---|
| B01 | @mention 생성·조회·읽음 | mention·협업 알림 [J15] | mention·Inbox [N07] | 모델·dashboard 조회만, editor·생성·읽음 없음 / 기존 MVP 7단계 | 미결정 |
| B02 | Watcher·변경 구독 | Watcher [J15] | page의 comment notification 구독; Jira와 이벤트 범위 다름 [N07] | 없음 / 미정 | 미결정 |
| B03 | 담당자·상태·댓글 변경 알림 | Watcher 등에 변경 통지 [J15] | 할당·mention·reply 등의 Inbox 통지 [N07] | dashboard 멘션 영역만 / email·realtime push·toast는 제외 | 미결정 |
| B04 | 기한 Reminder | scheduled automation으로 구성 [J16] | Date reminder [N08] | 기한 초과·임박 집계만 / 별도 reminder는 미정 | 미결정 |
| B05 | 개인 저장 필터 | private saved filter [J17] | 개인 적용 filter/view [N09] | 모델·DTO 기반만 / 기존 MVP 9단계 | 미결정 |
| B06 | 프로젝트 공유 필터 | 공유 saved filter [J17] | 공유 view·Save for everyone [N09] | 모델·DTO 기반만 / 기존 MVP 9단계 | 미결정 |
| B07 | 칸반 필터 | board/custom filters [J18] | board view filter [N09] | 없음; 목록 필터는 구현 / 요구사항 §8.4 포함 | 미결정 |
| B08 | 표시 열·카드 필드·Group·Swimlane 구성 | board/card/swimlane 설정 [J19] | property visibility·group·sub-group [N09] | 고정 목록 열·카드·Epic 그룹 / 미정 | 미결정 |
| B09 | 목록에서 바로 값 편집 | 지원되는 필드의 inline edit [J20] | table cell 편집 [N01] | 별도 편집 form만 / 미정 | 미결정 |
| B10 | Drag로 수동 순위 정렬 | Rank [J12] | row drag 정렬 [N10] | `sort_order` 조회만, 순위 변경 없음 / 후속 기록은 있으나 독립 checklist 없음 | 미결정 |
| B11 | Timeline·Gantt·의존 일정 조정 | timeline·Plans; 고급 Plans는 Premium/Enterprise [J08][J21] | timeline·dependency date shifting [N03][N09] | 일정·관계 필드 기반만 / 후속 | 미결정 |
| B12 | Calendar 업무 보기 | calendar 일정 편집 [J22] | Calendar view [N09] | 없음 / 미정 | 미결정 |
| B13 | Backlog·Sprint 계획·종료·이월 | Scrum/backlog·Sprint 종료와 미완료 이월 [J36] | Sprint planning·backlog·완료 시 이월 [N02] | 없음 / 후속 | 미결정 |
| B14 | WIP 제한 | column constraint 초과 표시 [J24] | 동등한 native 제한은 미확인; 집계 구성은 가능 [N04] | 없음 / 미정 | 미결정 |
| B15 | 팀 통계·Workload·진척 report | Sprint·Velocity·Burndown·Cycle time 등 [J23] | task 집계·chart·Sprint 완료율; Jira report와 동일하지 않음 [N11][N20] | 개인 dashboard만 / 프로젝트·업무 통계 후속 | 미결정 |
| B16 | 티켓 작성 Template | clone·automation 활용 가능; Notion식 범용 본문 template와 구분 [J25][J16] | database template [N06] | 없음 / 미정 | 미결정 |
| B17 | 반복 Task 자동 생성 | recurring automation [J26] | repeating template [N13] | 없음 / 미정 | 미결정 |
| B18 | 조건 기반 자동 처리 | trigger·condition·action [J16] | database automation, 유료 plan 중심 [N14] | 없음; 자동 시각 기록·FSM은 사용자 설정 자동화가 아님 / 미정 | 미결정 |
| B19 | 일괄 수정·상태 변경 | Bulk edit/transition [J27] | 여러 row의 property 변경 [N10] | 없음 / 명시적 제외 | 미결정 |
| B20 | 티켓 복제 | Clone [J25] | page·sub-items duplicate [N03] | 없음 / 명시적 제외 | 미결정 |
| B21 | CSV 가져오기·내보내기 | CSV import·검색 결과 export [J28][J17] | CSV import·database export, relation 왕복 제한 [N15][N04] | 없음 / 명시적 제외; 조직 JSON과 별개 | 미결정 |
| B22 | 본문·댓글 검색·고급 조건 | text 검색·JQL [J05] | workspace는 본문 검색, database는 제목/property; 댓글 검색 제외 [N16] | key·제목 검색만 / 한국어 전문 검색 후속, JQL 제외 | 미결정 |
| B23 | 사용자 정의 상태·Workflow·Review 단계 | status·transition·rule 편집 [J29] | Status·automation으로 구성; 서버 FSM과 동등하다고 보지 않음 [N01][N14] | 고정 5상태·FSM / 후속 | 미결정 |
| B24 | 첨부파일 삭제·본문 참조 처리 | 첨부 삭제 권한 [J07] | 파일 property 삭제 [N01] | 등록·조회·다운로드만 / 8단계 후순위 | 미결정 |
| B25 | 휴지통·첨부파일 보존 만료 정리 | 이번 조사에서 동일한 30일 cascade 정책 비교는 하지 않음 | 동일 정책으로 간주하지 않음 | 휴지통·복구 구현, purge·scheduler 없음 / 기존 MVP 6·8·11단계 | 미결정 |
| B26 | 요청 접수 Form | Form 제출로 work item 생성 [J37] | Form 응답을 database property로 저장 [N19] | 일반 ticket 생성 form만 있음 / 별도 접수 form은 미정 | 미결정 |
| B27 | Git commit·PR 연결 | 개발 도구 연동 [J34] | GitHub PR 연결·동기화; plan·연동 전환 상태에 따라 다름 [N21][N22] | 본문 URL 외 전용 연동 없음 / 미정 | 미결정 |

B03은 앱 내 Inbox 확대와 email·push를 별도 선택할 수 있다. B08은 목록 열 선택부터 시작하고 임의 view designer는 후속으로 둘 수 있다. B11은 일정 수동 편집·timeline 표시·자동 재계획을 따로 결정한다. B15도 단순 상태별 통계와 공수 기반 workload, Agile report를 한 번에 포함할 필요는 없다. B22에서 본문 검색 추가가 JQL 또는 별도 검색 서버 도입을 자동으로 뜻하지 않는다.

## 6. C — 기능 수보다 정책 차이가 큰 항목

| ID | 검토할 정책 | Jira·Notion과의 차이 | 현재 정책 / 영향 | 결정 |
|---|---|---|---|---|
| C01 | 관계 유형 확장 | Jira는 blocks·duplicates·clones·relates to 등을 구분 [J28]. Notion은 Relation을 구성 [N04] | Related·Depends on 두 종류. duplicate·원본/파생 등을 추가할지 선택 | 미결정 |
| C02 | 프로젝트 간 티켓 관계 | Jira는 권한이 있는 다른 space와 link 가능 [J07]. Notion은 DB 간 Relation [N04] | 동일 프로젝트만 허용. 양쪽 조회 권한·정보 은폐·DB 제약 재설계 필요 | 미결정 |
| C03 | 티켓의 프로젝트 간 이동 | Jira는 field/status 매핑을 거치는 move [J30]. Notion은 다른 DB로 page 이동 [N03] | 금지. key·계층·첨부 경로·이력·권한·이전 URL 정책을 함께 결정해야 함 | 미결정 |
| C04 | 생성 후 Type 변환·계층 유연화 | Jira는 work type 변경 [J31]. Notion은 Select와 sub-items를 각각 변경 [N01][N03] | Type은 수정 불가. Task↔Subtask 등의 전환과 Bug 분류 추가는 별도 문제 | 미결정 |
| C05 | Ticket별·Field별 권한 | Jira의 work-item security [J32]. Notion의 page sharing 및 Business/Enterprise의 page/property access [N17][N18] | project role 기준. creator·assignee와 무관한 전체 업무 수정 정책을 유지할지 검토 | 미결정 |
| C06 | 종료 티켓 잠금·의존 완료 차단 | Jira는 Workflow rule로 제어 [J29][J33]. Notion의 dependency는 날짜 조정 기능이며 같은 완료 차단은 확인되지 않음 [N03] | 종료 티켓 편집 금지·의존 대상 미완료 시 완료 금지. 편의성 때문에 완화할지, 현행 유지할지 선택 | 미결정 |
| C07 | 하위 상태·진척의 상위 집계 | Jira Plans roll-up [J08], Notion Relation·Rollup·프로젝트 완료율 [N04][N12] | 상위 상태 자동 연동 없음, 상세에 완료율도 표시하지 않는 확정 정책. 표시용 집계와 자동 상태 변경은 따로 결정 | 미결정 |

## 7. 이번 목록에서 별도로 유지할 범위

다음은 현재 로드맵에 남아 있으나 ticket 속성 비교와는 구분할 작업이다. 이번 비교만으로 제거하거나 완료 처리하지 않는다.

- 조직 수정·이동·비활성화와 조직 JSON import/export — 3단계. 조직 비활성화의 사용자 영향은 미확정이다.
- 감사 로그 정리, 수동/자동 actor 구분, 정리 작업 실행 구조 — 2·11단계.
- 운영 HTTPS·CSRF·감사 누락 점검, backup/restore 절차, macOS Docker mount, browser 통합 검증 — 10·11단계.
- 로컬 LLM 기간별 보고서와 보고서 스킬 — 저장 구조만 준비한 후속 기능. B15의 일반 업무 통계와 별도다.
- SSO·object storage·dark mode·관리자 backup ZIP — 기존 후속 범위.

요청 접수 Form·개발 도구 연결·목표 연결은 B26·B27·A24에서 검토하되, 고객 지원 portal·Git hosting·전사 OKR 시스템 전체를 구현 범위에 포함한다는 의미는 아니다.

## 8. 항목별 결정 진행 방식

1. A01부터 속성을 먼저 검토한다. 각 항목에서 실제 사용 사례와 최소 범위를 정한다.
2. 답변은 `이번 범위 포함`, `후속`, `제외`, `현행 유지`로 기록한다. 기존 MVP 항목도 우선순위 재조정이 가능하다.
3. 묶음 항목의 일부만 필요하면 ID를 분할해 기록한다. 예: A09는 단일 assignee를 유지하면서 collaborators만 추가할 수 있다.
4. 결정한 항목에 날짜·정확한 범위·짧은 근거를 이 폴더의 `decisions.md`에 기록한다. 기존 요구사항·decision·로드맵은 검토 중 갱신하지 않으며 미결정·미구현 항목을 완료로 표시하지 않는다.
5. 필드 추가를 포함하면 입력뿐 아니라 목록 표시·필터·정렬·이력·권한·기존 데이터 기본값까지 구현 범위에 포함할지 확인한다.
6. 속성 다음에 B의 사용 흐름, 마지막에 C의 정책을 점검한다. 선행 정책이 필요한 항목은 해당 C 항목을 앞당겨 논의한다.

A01은 2026-10-03에 **계층을 유지하고 업무 분류 property를 분리**하는 방향으로 확정했다. 예시로 제시한 개발·오류·운영·검토 또는 Bug·Story를 실제 분류 값으로 확정한 것은 아니다. 세부 미정 사항은 [검토 결정 기록](decisions.md)에 유지한다. 다음 검토 항목은 **A02 — Labels·Tags**다.

## 9. 코드 확인 위치

| 근거 | 확인한 경계 |
|---|---|
| [요구사항](../REQUIREMENTS.md) | §5 ticket 속성·규칙, §7·8 목록/보드, §9 후속, §12 포함/제외 |
| [로드맵](../IMPLEMENTATION_ROADMAP.md) | 3·6·7·8·9·10·11단계와 후속 범위 |
| [기존 결정 인덱스](../docs/decisions/README.md) | IAM-015, TKT-001~013, CNT-003~015, UI-002·005·018·021, RPT-001~008 등 |
| [Ticket 모델](../app/models/work.py) | `Ticket`, `TicketRelation`, `TicketHistory`, `TicketDeletionBatch` |
| [콘텐츠 모델](../app/models/content.py) | `Mention`, `Attachment`, `SavedFilter` |
| [Ticket DTO](../app/schemas/tickets.py) | `TicketCreate`, `TicketUpdate`, `TicketListItemView` |
| [저장 계약](../app/schemas/contracts.py) | `TicketFilter`, `TicketState`, `RelationSnapshot` |
| [Ticket service](../app/services/tickets.py) | `build_ticket_board`, `create_ticket_relation`, `update_ticket`, `transition_ticket` |
| [Ticket repository](../app/repositories/tickets.py) | 목록 조건·board 정렬·계층 query |
| [Dashboard repository](../app/repositories/dashboard.py) | 미확인 mention 조회의 membership·삭제 조건 |
| [Ticket web](../app/web/tickets.py) | 편집·목록 filter·board의 입력 경계 |
| [Ticket form](../app/web/templates/ticket_form.html) | 실제 편집 가능한 field |
| [Board 화면](../app/web/templates/board.html) | 고정 그룹·카드 구성 |
| [본문 검증](../app/domain/rich_text.py) | mention node 미연결, 공용 rich-text 계약 |
| [Frontend editor](../frontend/tiptap-editor.js) | 실제 toolbar·본문 기능 |
| [첨부 API](../app/api/routes/attachments.py), [CLI](../app/cli.py) | 삭제·purge 명령 미연결 |

외부 링크는 각 비교 행의 Jira/Notion 근거에 연결했다. 아래 link reference는 해당 공식 문서의 URL이다.

[J01]: https://support.atlassian.com/jira-software-cloud/docs/configure-the-issue-detail-view/
[J02]: https://support.atlassian.com/jira-cloud-administration/docs/what-are-issue-types/
[J03]: https://support.atlassian.com/jira-software-cloud/docs/what-are-jira-components/
[J04]: https://support.atlassian.com/jira-software-cloud/docs/enable-releases-and-versions/
[J05]: https://support.atlassian.com/jira-software-cloud/docs/jql-operators/
[J06]: https://support.atlassian.com/jira-cloud-administration/docs/field-types-you-can-create-as-a-jira-admin/
[J07]: https://support.atlassian.com/jira-software-cloud/docs/next-gen-permissions/
[J08]: https://support.atlassian.com/jira-software-cloud/docs/estimate-and-schedule-issues-in-advanced-roadmaps/
[J09]: https://support.atlassian.com/jira-software-cloud/docs/estimate-an-issue/
[J10]: https://support.atlassian.com/jira-software-cloud/docs/what-is-the-list-view/
[J11]: https://support.atlassian.com/jira-cloud-administration/docs/configure-resolutions-in-a-jira-workflow/
[J12]: https://support.atlassian.com/jira-software-cloud/docs/work-on-and-progress-your-issues/
[J13]: https://support.atlassian.com/jira-software-cloud/docs/add-files-images-and-other-content-to-describe-an-issue/
[J14]: https://support.atlassian.com/jira-cloud-administration/docs/create-a-formula-field/
[J15]: https://support.atlassian.com/jira-software-cloud/docs/watch-share-and-comment-on-a-work-item/
[J16]: https://support.atlassian.com/cloud-automation/docs/jira-automation-triggers/
[J17]: https://support.atlassian.com/jira-software-cloud/docs/save-your-search-as-a-filter/
[J18]: https://support.atlassian.com/jira-software-cloud/docs/filter-work-items/
[J19]: https://support.atlassian.com/jira-software-cloud/docs/configure-a-company-managed-board/
[J20]: https://support.atlassian.com/jira-software-cloud/docs/edit-individual-and-multiple-work-items
[J21]: https://support.atlassian.com/jira-software-cloud/docs/edit-multiple-issues-in-bulk-on-your-timeline/
[J22]: https://support.atlassian.com/jira-software-cloud/docs/schedule-work-in-your-calendar/
[J23]: https://support.atlassian.com/jira-software-cloud/docs/generate-a-report/
[J24]: https://support.atlassian.com/jira-software-cloud/docs/configure-columns/
[J25]: https://support.atlassian.com/jira-software-cloud/docs/clone-an-issue/
[J26]: https://support.atlassian.com/cloud-automation/docs/automatically-clone-an-issue-when-done/
[J27]: https://support.atlassian.com/jira-software-cloud/docs/edit-multiple-issues/
[J28]: https://support.atlassian.com/jira-software-cloud/docs/mapping-csv-data-to-jira-fields
[J29]: https://support.atlassian.com/jira-cloud-administration/docs/create-and-manage-issue-workflows-and-issue-workflow-schemes/
[J30]: https://support.atlassian.com/jira-software-cloud/docs/move-multiple-issues/
[J31]: https://support.atlassian.com/jira-software-cloud/docs/update-a-work-items-details/
[J32]: https://support.atlassian.com/jira-software-cloud/docs/view-and-change-a-work-items-security-level/
[J33]: https://support.atlassian.com/jira-cloud-administration/docs/types-of-permissions-in-jira/
[J34]: https://support.atlassian.com/jira-software-cloud/docs/integrate-your-issues-and-development-tools/
[J35]: https://support.atlassian.com/jira-software-cloud/docs/link-issues-to-goals-in-the-issue-view/
[J36]: https://support.atlassian.com/jira-software-cloud/docs/complete-a-sprint/
[J37]: https://support.atlassian.com/jira-software-cloud/docs/what-are-forms-and-what-can-they-do/
[N01]: https://www.notion.com/help/database-properties
[N02]: https://www.notion.com/en-gb/help/sprints?nxtPslug=sprints
[N03]: https://www.notion.com/help/tasks-and-dependencies
[N04]: https://www.notion.com/help/relations-and-rollups
[N05]: https://www.notion.com/en-gb/help/formula-syntax
[N06]: https://www.notion.com/help/guides/using-database-templates-for-teams
[N07]: https://www.notion.com/help/notification-settings
[N08]: https://www.notion.com/en-gb/help/reminders
[N09]: https://www.notion.com/help/views-filters-and-sorts
[N10]: https://www.notion.com/en-gb/help/tables
[N11]: https://www.notion.com/help/charts
[N12]: https://www.notion.com/en-gb/help/guides/getting-started-with-projects-and-tasks?nxtPslug=getting-started-with-projects-and-tasks
[N13]: https://www.notion.com/en-gb/help/guides/automate-work-repeating-database-templates
[N14]: https://www.notion.com/help/database-automations
[N15]: https://www.notion.com/help/import-data-into-notion
[N16]: https://www.notion.com/help/search
[N17]: https://www.notion.com/en-gb/help/sharing-and-permissions
[N18]: https://www.notion.com/help/database-property-access
[N19]: https://www.notion.com/help/forms
[N20]: https://www.notion.com/help/guides/sprints-simplified-notions-sprint-tracking-system
[N21]: https://www.notion.com/en-gb/help/github
[N22]: https://www.notion.com/en-gb/help/connected-properties?nxtPslug=connected-properties
