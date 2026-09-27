"""티켓 하위 댓글 JSON API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.auth import Identity
from app.schemas.comments import CommentCreate, CommentDelete, CommentUpdate, CommentView
from app.services import comments as service
from app.web.security import require_api_user, verify_csrf

router = APIRouter(
    prefix="/api/projects/{project_key}/tickets/{ticket_key}/comments",
    tags=["comments"],
)
Database = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[Identity, Depends(require_api_user)]


@router.get("", response_model=list[CommentView])
def list_ticket_comments_api(
    project_key: str,
    ticket_key: str,
    session: Database,
    actor: Actor,
):
    """티켓의 삭제 자리표시자를 포함한 thread 순서 댓글 목록을 조회한다."""
    return service.list_ticket_comments(session, actor, project_key, ticket_key)[2]


@router.post("", response_model=CommentView, status_code=201)
def create_comment_api(
    project_key: str,
    ticket_key: str,
    request: Request,
    payload: CommentCreate,
    session: Database,
    actor: Actor,
):
    """티켓 댓글을 생성한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.create_comment(session, actor, project_key, ticket_key, payload)


@router.patch("/{comment_id}", response_model=CommentView)
def update_comment_api(
    project_key: str,
    ticket_key: str,
    comment_id: int,
    request: Request,
    payload: CommentUpdate,
    session: Database,
    actor: Actor,
):
    """티켓 댓글 본문을 수정한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    return service.update_comment(
        session,
        actor,
        project_key,
        ticket_key,
        comment_id,
        payload,
    )


@router.delete("/{comment_id}", status_code=204)
def delete_comment_api(
    project_key: str,
    ticket_key: str,
    comment_id: int,
    request: Request,
    payload: CommentDelete,
    session: Database,
    actor: Actor,
) -> Response:
    """티켓 댓글을 soft delete한다."""
    verify_csrf(request, request.headers.get("x-csrf-token", ""), actor, get_settings())
    service.delete_comment(
        session,
        actor,
        project_key,
        ticket_key,
        comment_id,
        payload,
    )
    return Response(status_code=204)
