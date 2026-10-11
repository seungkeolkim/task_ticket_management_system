"""API와 Web의 필터 JSON 전송 및 크기 검증을 공유한다."""

from typing import Annotated
from urllib.parse import quote

from fastapi import Query, Request
from pydantic import ValidationError

from app.core.config import get_settings
from app.domain.auth import AuthError
from app.schemas.ticket_filters import MAX_FILTER_BYTES, TicketFilter


def project_ticket_filter_parameters(
    request: Request, filter_payload: Annotated[str, Query(alias="filter")] = ""
) -> TicketFilter:
    """v2 filter만 수신하며 구형 parameter나 중복·과도한 입력을 명시적으로 거부한다."""
    allowed_parameters = {"filter", "page", "selected", "created", "loaded_scope", "loaded_id"}
    for parameter_name in request.query_params:
        if parameter_name not in allowed_parameters:
            raise AuthError("invalid_filter", "검색 조건 형식을 확인하세요.")
        if len(request.query_params.getlist(parameter_name)) != 1:
            raise AuthError("invalid_filter", "중복된 검색 조건을 제거하세요.")
    if not filter_payload:
        return TicketFilter(page_size=get_settings().pagination.default_size)
    if len(filter_payload.encode("utf-8")) > MAX_FILTER_BYTES or len(quote(filter_payload)) > 12288:
        raise AuthError("invalid_filter", "검색 조건 크기를 줄여 주세요.")
    try:
        return TicketFilter.model_validate_json(filter_payload)
    except (ValidationError, ValueError, RecursionError):
        raise AuthError("invalid_filter", "검색 조건의 필드·연산자·값을 확인하세요.") from None
