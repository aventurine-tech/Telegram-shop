import pytest
from decimal import Decimal
from pydantic import ValidationError

from bot.misc.validators import validate_telegram_id, validate_money_amount, sanitize_html, \
    CategoryRequest, BroadcastMessage, validate_customer_name, validate_phone, clean_text


class TestValidateTelegramId:

    @pytest.mark.parametrize("raw,expected", [
        (12345, 12345),
        (9999999999, 9999999999),
        ("12345", 12345),  # numeric strings are coerced
    ])
    def test_accepted(self, raw, expected):
        assert validate_telegram_id(raw) == expected

    @pytest.mark.parametrize("raw", [
        0,
        -1,
        10000000000,  # above Telegram's id range
        "abc",
        None,
    ])
    def test_rejected(self, raw):
        with pytest.raises(ValueError):
            validate_telegram_id(raw)


class TestValidateMoneyAmount:

    @pytest.mark.parametrize("raw,kwargs,expected", [
        ("50", {}, Decimal("50.00")),
        ("99.99", {}, Decimal("99.99")),
        ("0.01", {"min_amount": Decimal("0.01")}, Decimal("0.01")),          # exact min
        ("1000000", {"max_amount": Decimal("1000000")}, Decimal("1000000.00")),  # exact max
    ])
    def test_accepted(self, raw, kwargs, expected):
        assert validate_money_amount(raw, **kwargs) == expected

    @pytest.mark.parametrize("raw,kwargs", [
        ("0.001", {"min_amount": Decimal("0.01")}),
        ("2000000", {"max_amount": Decimal("1000000")}),
        ("abc", {}),
        ("-10", {}),
    ])
    def test_rejected(self, raw, kwargs):
        with pytest.raises(ValueError):
            validate_money_amount(raw, **kwargs)


class TestSanitizeHtml:

    @pytest.mark.parametrize("raw,must_contain,must_not_contain", [
        ("<script>alert('xss')</script>", "&lt;", "<script>"),
        ("a & b", "&amp;", None),
        ('he said "hello"', "&quot;", None),
    ])
    def test_escapes_unsafe_markup(self, raw, must_contain, must_not_contain):
        result = sanitize_html(raw)
        assert must_contain in result
        if must_not_contain is not None:
            assert must_not_contain not in result

    @pytest.mark.parametrize("tag", ["b", "i", "code"])
    def test_preserves_telegram_safe_tags(self, tag):
        result = sanitize_html(f"<{tag}>text</{tag}>")
        assert f"<{tag}>" in result
        assert f"</{tag}>" in result

    def test_plain_text_unchanged(self):
        assert sanitize_html("hello world") == "hello world"


class TestCheckoutFields:

    @pytest.mark.parametrize("raw,expected", [
        ("Ana", "Ana"),
        ("  Ion Popescu  ", "Ion Popescu"),
        ("Ана-Мария", "Ана-Мария"),
        ("N" * 100, "N" * 100),
    ])
    def test_name_accepted(self, raw, expected):
        assert validate_customer_name(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", None, "N" * 101, "Two\nLines", "bad\x00name"])
    def test_name_rejected(self, raw):
        with pytest.raises(ValueError):
            validate_customer_name(raw)

    @pytest.mark.parametrize("raw", [
        "+37369123456", "069 123 456", "069-123-456", "+373 (69) 123456", "123456",
    ])
    def test_phone_accepted(self, raw):
        assert validate_phone(raw) == raw.strip()

    @pytest.mark.parametrize("raw", [
        "", "12345", "call me", "+", "1" * 21, "+373 69 123 456 ext 5", "<b>123456</b>", "()- ()-",
    ])
    def test_phone_rejected(self, raw):
        with pytest.raises(ValueError):
            validate_phone(raw)

    def test_free_text_keeps_newlines_but_not_control_chars(self):
        assert clean_text("Str. Mare 1\napt 4", 500) == "Str. Mare 1\napt 4"
        with pytest.raises(ValueError):
            clean_text("a\x07b", 500)

    def test_free_text_length_limit(self):
        assert len(clean_text("a" * 500, 500)) == 500
        with pytest.raises(ValueError):
            clean_text("a" * 501, 500)


class TestCategoryRequest:

    def test_valid_category(self):
        assert CategoryRequest(name="Electronics").name == "Electronics"

    @pytest.mark.parametrize("raw,sanitized", [
        ("<b>Bold</b> Category", "Bold Category"),
        ("too   many   spaces", "too many spaces"),
    ])
    def test_sanitize_name(self, raw, sanitized):
        assert CategoryRequest(name=raw).sanitize_name() == sanitized

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            CategoryRequest(name="")


class TestBroadcastMessage:

    @pytest.mark.parametrize("text,kwargs", [
        ("<b>Hello</b> world", {}),
        ("Hello world", {"parse_mode": "HTML"}),
    ])
    def test_accepted(self, text, kwargs):
        assert BroadcastMessage(text=text, **kwargs).text == text

    @pytest.mark.parametrize("text", [
        "<b>Hello world",              # unbalanced bold
        "<i>Hello</i><i>unclosed",     # unbalanced italic
        "x" * 4097,                    # over the length cap
        "",
    ])
    def test_rejected(self, text):
        with pytest.raises(ValidationError):
            BroadcastMessage(text=text)


class TestEnvValidation:
    def _env(self, monkeypatch, **overrides):
        from bot.misc.env import EnvKeys
        defaults = {
            "ADMIN_HOST": "localhost",
            "WEBHOOK_ENABLED": "0",
            "SECRET_KEY": "a-real-key",
            "ADMIN_PASSWORD": "a-real-password",
            "ADMIN_COOKIE_SECURE": "auto",
        }
        for key, value in {**defaults, **overrides}.items():
            monkeypatch.setattr(EnvKeys, key, value, raising=False)
        return EnvKeys

    @pytest.mark.parametrize("exposure", [
        {"ADMIN_HOST": "0.0.0.0"},
        {"WEBHOOK_ENABLED": "1"},
    ])
    @pytest.mark.parametrize("bad", [
        {"SECRET_KEY": "change-me-in-production"},
        {"ADMIN_PASSWORD": "admin"},
    ])
    def test_default_credentials_are_fatal_when_reachable(self, monkeypatch, exposure, bad):
        env = self._env(monkeypatch, **exposure, **bad)
        with pytest.raises(RuntimeError, match="Refusing to start"):
            env.validate()

    def test_default_credentials_only_warn_on_loopback(self, monkeypatch):
        env = self._env(
            monkeypatch,
            SECRET_KEY="change-me-in-production", ADMIN_PASSWORD="admin",
        )
        env.validate()  # must not raise — local development still works

    def test_real_credentials_pass_when_exposed(self, monkeypatch):
        env = self._env(monkeypatch, ADMIN_HOST="0.0.0.0")
        env.validate()

    @pytest.mark.parametrize("setting,host,expected", [
        ("auto", "localhost", False),
        ("auto", "0.0.0.0", True),
        ("0", "0.0.0.0", False),
        ("1", "localhost", True),
    ])
    def test_session_cookie_secure(self, monkeypatch, setting, host, expected):
        env = self._env(monkeypatch, ADMIN_COOKIE_SECURE=setting, ADMIN_HOST=host)
        assert env.session_cookie_secure() is expected
