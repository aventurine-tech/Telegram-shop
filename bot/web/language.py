"""Panel language: who reads what, in which language.

Resolution order for a request: the signed-in account's language (kept in the session as ``lang``),
then the ``web_lang`` cookie set from the login page, then the bot default (BOT_LOCALE). The result
goes into the i18n ContextVar for the duration of the request, so ``localize`` and the Jinja ``_()``
helper need no request object.
"""
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bot.i18n.main import LANGUAGE_CODES, localize, use_language
from bot.i18n.strings import TRANSLATIONS
from bot.misc import EnvKeys

LANG_COOKIE = "web_lang"
_COOKIE_MAX_AGE = 365 * 24 * 3600


def _valid(lang: str | None) -> str | None:
    return lang if lang in LANGUAGE_CODES else None


class LazyText:
    """A string that is translated when it is rendered, so one object follows each request's language.

    For labels SQLAdmin keeps on the view for its whole life (order actions) and only ever prints.
    """

    __slots__ = ("key",)

    def __init__(self, key: str):
        self.key = key

    def __str__(self) -> str:
        return localize(self.key)

    def __repr__(self) -> str:
        return f"LazyText({self.key!r})"


class Localized:
    """A class attribute that reads as the current language on an instance and as English on the class.

    SQLAdmin reads ``name`` / ``name_plural`` off the view instance while rendering (menu, titles), so they
    follow the request; code that needs a stable value (audit entries) reads it off the class.
    """

    def __init__(self, key: str):
        self.key = key

    def __get__(self, obj, owner=None) -> str:
        if obj is None:
            return TRANSLATIONS["en"].get(self.key, self.key)
        return localize(self.key)


def request_language(scope: Scope) -> str | None:
    """Session language, else the cookie, else None (= the bot default)."""
    session = scope.get("session") or {}
    lang = _valid(session.get("lang")) if isinstance(session, dict) else None
    if lang:
        return lang
    raw = dict(scope.get("headers") or []).get(b"cookie", b"").decode("latin-1")
    if raw:
        try:
            jar = SimpleCookie(raw)
        except Exception:
            return None
        if LANG_COOKIE in jar:
            return _valid(jar[LANG_COOKIE].value)
    return None


def cookie_language(request) -> str | None:
    """The language chosen on the login page (cookie only), for saving on first login."""
    return _valid(request.cookies.get(LANG_COOKIE))


class LanguageMiddleware:
    """Resolve the request language into the i18n ContextVar. Sits inside SessionMiddleware.

    ``?lang=xx`` (the login page's picker) is honoured only while nobody is signed in: it sets the
    cookie and applies at once. A signed-in account's own language always wins.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        session = scope.get("session") or {}
        signed_in = isinstance(session, dict) and session.get("uid") is not None
        picked = None
        if not signed_in:
            picked = _valid((parse_qs(scope.get("query_string", b"").decode("latin-1")).get("lang") or [None])[0])
        lang = picked or request_language(scope)

        async def send_with_cookie(message: Message) -> None:
            if picked and message["type"] == "http.response.start":
                secure = "; Secure" if EnvKeys.session_cookie_secure() else ""
                value = (f"{LANG_COOKIE}={picked}; Path=/; Max-Age={_COOKIE_MAX_AGE}; HttpOnly; SameSite=strict{secure}")
                message = {**message, "headers": [*message.get("headers", []), (b"set-cookie", value.encode("latin-1"))]}
            await send(message)

        with use_language(lang):
            await self.app(scope, receive, send_with_cookie if picked else send)
