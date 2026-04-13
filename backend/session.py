from starlette.requests import Request
from typing import Optional

TOKENS_KEY = "google_tokens"
USER_KEY = "google_user"


def save_tokens(request: Request, tokens: dict, user_info: dict) -> None:
    request.session[TOKENS_KEY] = tokens
    request.session[USER_KEY] = user_info


def get_tokens(request: Request) -> Optional[dict]:
    return request.session.get(TOKENS_KEY)


def get_user(request: Request) -> Optional[dict]:
    return request.session.get(USER_KEY)


def clear_session(request: Request) -> None:
    request.session.pop(TOKENS_KEY, None)
    request.session.pop(USER_KEY, None)


def is_authenticated(request: Request) -> bool:
    return get_tokens(request) is not None
