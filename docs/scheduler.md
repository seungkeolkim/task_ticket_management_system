# 공통 cron scheduler

## 현재 범위

Docker Compose의 `scheduler` service는 웹 `app`의 readiness 이후 시작한다. 웹 container가 migration을 적용하고, scheduler는 공유 DB의 활성 `scheduled_jobs`를 읽어 자체 crontab을 복원한다. 현재 두 scheduler 테이블에는 기본 row를 만들지 않으며 **감사 로그·휴지통·첨부파일 정리 작업은 등록하지 않는다.** 실행할 job이 없어도 service와 cron은 기동할 수 있다.

`scheduled_jobs`의 `job_key`는 코드의 `app/scheduler_jobs.py` registry에 등록된 값만 활성화할 수 있다. `cron_expression`은 5개 필드로 저장하고 Debian `crontab`이 최종 문법을 검사한다. `timezone_name`은 현재 `Asia/Seoul`만 허용한다. DB의 표현식·활성 상태가 crontab의 원본이며 `scheduled_job_runs`는 실행 결과만 기록한다. 마지막 실행 시각을 다음 실행 조건으로 사용하지 않는다.

## 기동·변경·다운타임

1. `scheduler`가 DB의 활성 설정을 읽고 crontab 전체를 설치한 뒤 `cron -f`를 시작한다. 등록되지 않은 작업이나 잘못된 설정은 조용히 건너뛰지 않고 service 기동을 실패시킨다.
2. 실행 중에는 DB 설정 내용을 주기적으로 다시 읽어 변경되었을 때만 crontab을 재설치한다. 이 확인은 설정 동기화이며 실행 시각을 계산하지 않는다.
3. cron 시각이 되면 내부 Unix socket으로 job key와 일정 지문을 manager에 전달한다. manager와 작업 프로세스는 현재 DB 활성 상태·일정 지문·registry를 다시 확인하여 변경 전 crontab에서 온 트리거를 무시한다. 원래 container 환경에서 작업을 실행하며, 작업별 data mount 파일 잠금으로 겹치는 실행을 건너뛴다.
4. container가 꺼져 있던 동안의 실행은 소급하지 않는다. 재기동 시 crontab을 복원하고 다음 cron 시각부터 실행한다.

`scheduler`는 단일 replica를 전제로 한다. 등록·수정용 관리자 API와 실제 정리 job, 다중 replica 조정은 후속 범위다. 새 작업은 고정된 Python handler와 일정 row를 함께 추가하고, 권한·감사·실패·재실행 정책을 해당 작업 단위로 검증한다. 작업 결과는 `scheduled_job_runs`와 scheduler container의 표준 출력 시스템 로그에 남기며 웹과 같은 회전 파일을 여러 프로세스가 동시에 쓰지 않는다.
DB 설정 확인 주기는 `[scheduler].sync_interval_seconds`에서 조정하고 재기동 후 적용한다. 이 값은 cron 실행 간격이 아니다.
재기동 시 이전 scheduler의 `CRON/RUNNING` 실행 이력은 `FAILED/interrupted`로 마감한다. 별도 수동 실행은 영향을 받지 않는다. 실행 이력은 관측용이며 cron 일정을 변경하지 않는다.
운영자가 container 안에서 활성 작업을 직접 실행할 때는 `python -m app.scheduler run-job <job_key> --source MANUAL`을 사용한다. 이 명령도 등록·활성 상태와 작업 잠금을 확인하며, 관리자 화면의 수동 실행 권한·감사 처리는 아직 연결하지 않았다.

## 설정과 운영

`sh ./run_compose.sh start` 또는 `./run_compose.ps1 start`는 두 service를 시작한다. scheduler는 app과 같은 선택적 외부 설정 경로와 data mount를 사용하며 별도 HTTP 포트를 열지 않는다. 설정 파일이 없으면 app과 동일한 기본값을 적용한다. `docker ps --filter label=com.docker.compose.service=scheduler`로 container를 찾고 `docker logs <container-id>`에서 동기화·실패 로그를 확인한다. `20261005_0009` migration은 일정·실행 이력 테이블만 추가하며 기존 업무 데이터와 현재 휴지통 보존 정책을 바꾸지 않는다.
