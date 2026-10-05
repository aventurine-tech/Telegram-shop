"""Mailing text helpers: Telegram-safe HTML, placeholders, and the length Telegram will count."""
import html
import re
from html.parser import HTMLParser

# Tags Telegram's HTML mode understands that the editor can produce.
ALLOWED_TAGS = ("b", "i", "u", "s", "code", "pre", "tg-spoiler")
_ALIASES = {"strong": "b", "em": "i", "ins": "u", "strike": "s", "del": "s"}
_SAFE_HREF = re.compile(r"^(https?://|tg://|mailto:)", re.I)

CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096

PLACEHOLDERS = ("first_name", "last_name", "full_name", "username", "telegram_id")
_PLACEHOLDER = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")(?:\|([^{}]*))?\}")


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = _ALIASES.get(tag, tag)
        if tag == "br":
            self.out.append("\n")
        elif tag in ("p", "div"):
            if self.out and not self.out[-1].endswith("\n"):
                self.out.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if _SAFE_HREF.match(href.strip()):
                self.out.append(f'<a href="{html.escape(href.strip(), quote=True)}">')
                self.stack.append("a")
            else:
                self.stack.append("")       # keep the text, drop the link
        elif tag in ALLOWED_TAGS:
            self.out.append(f"<{tag}>")
            self.stack.append(tag)
        else:
            self.stack.append("")

    def handle_endtag(self, tag):
        tag = _ALIASES.get(tag, tag)
        if tag in ("p", "div"):
            if self.out and not self.out[-1].endswith("\n"):
                self.out.append("\n")
            return
        if tag == "br" or not self.stack:
            return
        # close up to the matching open tag, so tags are always balanced
        if tag in ("a",) + ALLOWED_TAGS and (tag in self.stack):
            while self.stack:
                top = self.stack.pop()
                if top:
                    self.out.append(f"</{top}>")
                if top == tag:
                    break
        elif self.stack and self.stack[-1] == "" and tag not in ALLOWED_TAGS and tag != "a":
            self.stack.pop()

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            top = self.stack.pop()
            if top:
                self.out.append(f"</{top}>")
        return "".join(self.out)


def sanitize_mailing_html(text: str | None) -> str:
    """Keep only what Telegram can show (b, i, u, s, code, pre, spoiler, links), escape the rest, balance the tags."""
    parser = _Sanitizer()
    parser.feed(text or "")
    parser.close()
    return re.sub(r"\n{3,}", "\n\n", parser.result()).strip()


def visible_length(text: str | None) -> int:
    """Characters Telegram counts toward its limit: the text without tags, entities decoded."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", text or "")))


def limit_for(has_image: bool) -> int:
    return CAPTION_LIMIT if has_image else MESSAGE_LIMIT


def has_placeholders(text: str | None) -> bool:
    return bool(_PLACEHOLDER.search(text or ""))


def personalize(text: str, profile: dict | None) -> str:
    """Replace ``{first_name}`` / ``{first_name|friend}`` … with the person's data (escaped); a missing value
    becomes the default after ``|`` or an empty string."""
    profile = profile or {}
    first, last = (profile.get("first_name") or "").strip(), (profile.get("last_name") or "").strip()
    values = {
        "first_name": first, "last_name": last, "full_name": f"{first} {last}".strip(),
        "username": (profile.get("username") or "").strip(), "telegram_id": str(profile.get("telegram_id") or ""),
    }

    def fill(m: re.Match) -> str:
        value = values.get(m.group(1)) or (m.group(2) or "").strip()
        return html.escape(value, quote=False)

    return _PLACEHOLDER.sub(fill, text)
