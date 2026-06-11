from __future__ import annotations

from functools import wraps

from fastapi import Request
from fastapi.responses import RedirectResponse

from .config import ADMIN_PASSWORD, ADMIN_USERNAME, SESSION_COOKIE


def is_logged_in(request: Request) -> bool:
    return request.session.get("auth") == True


def verify_login(username: str, password: str) -> bool:
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD


def login_required(view_func):
    @wraps(view_func)
    async def wrapper(*args, **kwargs):
        request: Request = kwargs.get("request")
        if request is None:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
        if request is None or not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        return await view_func(*args, **kwargs)

    return wrapper
