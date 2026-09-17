import os

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.core.config import get_settings
from app.web.security import csrf_for_page

WEB_DIRECTORY = os.path.dirname(__file__)
STATIC_DIRECTORY = os.path.join(WEB_DIRECTORY, "static")
templates = Jinja2Templates(directory=os.path.join(WEB_DIRECTORY, "templates"))


def render(request: Request, template_name: str, *, status_code: int = 200, **context):
    identity = getattr(request.state, "current_user", None)
    # Set the token before rendering. Copy cookies onto the final template response.
    cookie_response = Response()
    token = csrf_for_page(request, cookie_response, identity, get_settings())
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        status_code=status_code,
        context={"current_user": identity, "csrf_token": token, **context},
    )
    for key, value in cookie_response.raw_headers:
        if key.lower() == b"set-cookie":
            response.raw_headers.append((key, value))
    return response
