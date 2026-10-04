"""Scheduler가 실행할 수 있는 작업의 명시적 registry.

실제 정리·삭제 작업은 아직 등록하지 않는다. 새 작업은 여기에서 허용한 뒤
scheduled_jobs에 설정을 추가해야 cron에 노출된다.
"""

from collections.abc import Callable

JOB_HANDLERS: dict[str, Callable[[], None]] = {}
