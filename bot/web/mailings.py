"""Mailings in the web panel: a Botobot-style editor (toolbar, placeholders, live preview), audiences,
scheduling, a delivery report and a test message to yourself.

Imported lazily by ``create_admin_app`` (it needs the shared base views from ``bot.web.admin``).
"""
import datetime
import json
import logging
from typing import Any

from markupsafe import Markup, escape
from sqladmin import action
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route
from wtforms import BooleanField, FileField, Form, SelectField, StringField, TextAreaField
from wtforms.fields import DateTimeLocalField
from wtforms.validators import Optional as WtfOptional

from bot.database.main import Database
from bot.database.methods.mailings import cancel_mailing, get_mailing, get_mailing_image, segment_counts
from bot.database.models.main import Mailings, MailingSegment, MailingStatus
from bot.i18n.main import localize
from bot.misc.images import ImageError, validate_image
from bot.misc.mailing_text import (
    CAPTION_LIMIT, MESSAGE_LIMIT, PLACEHOLDERS, personalize, sanitize_mailing_html, visible_length,
)
from bot.web.admin import AuditModelView, LocalizedForm, _client_ip, _picture_error
from bot.web.language import LazyText, Localized
from bot.web.session import current_web_user, session_is_admin

logger = logging.getLogger(__name__)

MODES = ("draft", "now", "scheduled")
_SCHEDULE_GRACE = datetime.timedelta(minutes=1)


def _utc(value: datetime.datetime | None) -> datetime.datetime | None:
    """Datetimes come back naive from SQLite and aware from PostgreSQL; the panel treats both as UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=datetime.timezone.utc) if value.tzinfo is None else value.astimezone(datetime.timezone.utc)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def sample_profile() -> dict:
    """The made-up person the preview talks to (in the viewer's language)."""
    return {key: localize(f"web.mailing.sample.{key}") for key in PLACEHOLDERS}


def render_preview_html(text: str) -> str:
    """The stored (already sanitised) message with sample values for the placeholders, as HTML for the page."""
    return personalize(text or "", sample_profile()).replace("\n", "<br>")


# ---------------------------------------------------------------------------------------------------------------
# The editor widget
# ---------------------------------------------------------------------------------------------------------------

_EDITOR_SCRIPT = r"""
(function () {
  var ta = document.getElementById(__ID__);
  if (!ta) { return; }
  var T = __LABELS__, SAMPLE = __SAMPLE__, PLACEHOLDERS = __PLACEHOLDERS__;
  var CAPTION = __CAPTION__, MESSAGE = __MESSAGE__;
  var form = ta.form;
  var box = document.createElement('div');
  box.className = 'mailing-editor';

  var bar = document.createElement('div');
  bar.className = 'btn-list mb-2';
  function tool(label, title, handler, html) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn-sm btn-outline-secondary';
    b.title = title;
    if (html) { b.innerHTML = html; } else { b.textContent = label; }
    b.addEventListener('mousedown', function (e) { e.preventDefault(); });   // keep the selection
    b.addEventListener('click', function () { handler(); sync(); });
    bar.appendChild(b);
    return b;
  }
  tool('B', T.bold, function () { document.execCommand('bold'); }, '<b>B</b>');
  tool('I', T.italic, function () { document.execCommand('italic'); }, '<i>I</i>');
  tool('U', T.underline, function () { document.execCommand('underline'); }, '<u>U</u>');
  tool('S', T.strike, function () { document.execCommand('strikeThrough'); }, '<s>S</s>');
  tool('', T.link, function () {
    var url = window.prompt(T.link_prompt, 'https://');
    if (url && /^(https?:\/\/|tg:\/\/|mailto:)/i.test(url.trim())) { document.execCommand('createLink', false, url.trim()); }
  }, '&#128279;');
  tool('', T.unlink, function () { document.execCommand('unlink'); }, '&#10005;&#128279;');

  var editor = document.createElement('div');
  editor.contentEditable = 'true';
  editor.className = 'form-control';
  editor.style.minHeight = '160px';
  editor.style.height = 'auto';
  editor.style.whiteSpace = 'pre-wrap';
  editor.setAttribute('role', 'textbox');
  editor.setAttribute('aria-multiline', 'true');

  var holders = document.createElement('div');
  holders.className = 'btn-list mt-2';
  var lead = document.createElement('span');
  lead.className = 'text-muted me-1';
  lead.textContent = T.insert;
  holders.appendChild(lead);
  PLACEHOLDERS.forEach(function (name) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn-sm btn-outline-primary';
    b.textContent = '{' + name + '}';
    b.addEventListener('mousedown', function (e) { e.preventDefault(); });
    b.addEventListener('click', function () {
      editor.focus();
      document.execCommand('insertText', false, name === 'first_name' ? '{first_name|' + SAMPLE.friend + '}' : '{' + name + '}');
      sync();
    });
    holders.appendChild(b);
  });

  var counter = document.createElement('div');
  counter.className = 'form-hint mt-2';
  var previewTitle = document.createElement('div');
  previewTitle.className = 'mt-3 text-muted';
  previewTitle.textContent = T.preview + ' — ' + T.preview_hint;
  var bubble = document.createElement('div');
  bubble.className = 'p-3 mt-1';
  bubble.style.cssText = 'background:#e7f0fa;border-radius:12px;max-width:420px;overflow-wrap:anywhere;color:#111;';
  var pic = document.createElement('img');
  pic.style.cssText = 'display:none;max-width:100%;border-radius:8px;margin-bottom:8px;';
  var body = document.createElement('div');
  body.style.whiteSpace = 'pre-wrap';
  bubble.appendChild(pic);
  bubble.appendChild(body);

  box.appendChild(bar);
  box.appendChild(editor);
  box.appendChild(holders);
  box.appendChild(counter);
  box.appendChild(previewTitle);
  box.appendChild(bubble);
  ta.style.display = 'none';
  ta.parentNode.insertBefore(box, ta.nextSibling);

  // ---- editor DOM  <->  Telegram HTML ----
  function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  var TAGS = { B: 'b', STRONG: 'b', I: 'i', EM: 'i', U: 'u', S: 's', STRIKE: 's', DEL: 's' };
  function serialize(node) {
    var out = '';
    node.childNodes.forEach(function (n) {
      if (n.nodeType === 3) { out += esc(n.nodeValue); return; }
      if (n.nodeType !== 1) { return; }
      var tag = n.tagName;
      if (tag === 'BR') { out += '\n'; return; }
      var inner = serialize(n);
      if (TAGS[tag]) { out += '<' + TAGS[tag] + '>' + inner + '</' + TAGS[tag] + '>'; }
      else if (tag === 'A' && /^(https?:\/\/|tg:\/\/|mailto:)/i.test(n.getAttribute('href') || '')) {
        out += '<a href="' + n.getAttribute('href').replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '">' + inner + '</a>';
      }
      else if (tag === 'DIV' || tag === 'P') { out += (out && out.slice(-1) !== '\n' ? '\n' : '') + inner; }
      else { out += inner; }
    });
    return out;
  }
  function plain(html) { var d = document.createElement('div'); d.innerHTML = html; return d.textContent || ''; }
  function personalize(html) {
    return html.replace(/\{(first_name|last_name|full_name|username|telegram_id)(?:\|([^{}]*))?\}/g, function (m, key, dflt) {
      return esc(SAMPLE[key] || (dflt || '').trim());
    });
  }
  function hasPicture() { return !!(picture && picture.files && picture.files.length) || (existing && !removeBox.checked); }

  var picture = form.querySelector('input[name="picture"]');
  var removeBox = form.querySelector('input[name="remove_picture"]') || { checked: false, addEventListener: function () {} };
  var existing = false;
  var idMatch = window.location.pathname.match(/\/edit\/(\d+)/);

  function sync() {
    var html = serialize(editor).replace(/\n{3,}/g, '\n\n').replace(/^\n+|\n+$/g, '');
    ta.value = html;
    body.innerHTML = personalize(html).replace(/\n/g, '<br>');
    var n = plain(html).length, limit = hasPicture() ? CAPTION : MESSAGE;
    counter.textContent = T.counter.replace('{n}', n).replace('{limit}', limit);
    counter.className = 'form-hint mt-2' + (n > MESSAGE ? ' text-danger' : (n > limit ? ' text-warning' : ''));
    if (hasPicture() && n > CAPTION) { counter.textContent += ' — ' + T.caption_overflow; }
    if (pic.getAttribute('src') && !removeBox.checked) { pic.style.display = 'block'; } else { pic.style.display = 'none'; }
  }

  editor.innerHTML = (ta.value || '').replace(/\n/g, '<br>');
  editor.addEventListener('input', sync);
  editor.addEventListener('paste', function (e) {       // paste as plain text: no foreign formatting
    e.preventDefault();
    var text = (e.clipboardData || window.clipboardData).getData('text/plain');
    document.execCommand('insertText', false, text);
  });
  editor.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey) {
      var k = e.key.toLowerCase();
      if (k === 'b' || k === 'i' || k === 'u') { return; }   // the browser's own shortcuts
    }
  });
  if (form) { form.addEventListener('submit', sync); }

  if (picture) {
    picture.addEventListener('change', function () {
      var f = picture.files && picture.files[0];
      if (f) { pic.src = URL.createObjectURL(f); } else if (!existing) { pic.removeAttribute('src'); }
      sync();
    });
  }
  removeBox.addEventListener('change', sync);
  if (idMatch) {
    pic.addEventListener('load', function () { existing = true; sync(); });
    pic.addEventListener('error', function () { existing = false; pic.removeAttribute('src'); sync(); });
    pic.src = '/mailing-image/' + idMatch[1];
  }
  sync();
})();
"""


class MailingTextWidget:
    """Rich text editor for the message: toolbar, placeholder buttons, character counter and live preview.

    The posted value is the Telegram HTML in a (hidden) textarea; without JavaScript the textarea itself
    stays editable (and the server sanitises whatever arrives)."""

    def __call__(self, field, **kwargs):
        element_id = kwargs.get("id") or field.id
        labels = {
            "bold": localize("web.mailing.editor.bold"), "italic": localize("web.mailing.editor.italic"),
            "underline": localize("web.mailing.editor.underline"), "strike": localize("web.mailing.editor.strike"),
            "link": localize("web.mailing.editor.link"), "unlink": localize("web.mailing.editor.unlink"),
            "link_prompt": localize("web.mailing.editor.link_prompt"), "insert": localize("web.mailing.editor.placeholders"),
            "counter": localize("web.mailing.editor.counter", n="{n}", limit="{limit}"),
            "preview": localize("web.mailing.editor.preview"), "preview_hint": localize("web.mailing.editor.preview_hint"),
            "caption_overflow": localize("web.mailing.editor.caption_overflow"),
        }
        sample = {**sample_profile(), "friend": "friend"}
        script = (_EDITOR_SCRIPT
                  .replace("__ID__", json.dumps(element_id))
                  .replace("__LABELS__", _js(labels)).replace("__SAMPLE__", _js(sample))
                  .replace("__PLACEHOLDERS__", json.dumps(list(PLACEHOLDERS)))
                  .replace("__CAPTION__", str(CAPTION_LIMIT)).replace("__MESSAGE__", str(MESSAGE_LIMIT)))
        textarea = (f'<textarea id="{escape(element_id)}" name="{escape(field.name)}" class="form-control" rows="8">'
                    f'{escape(field._value())}</textarea>')
        return Markup(textarea + "<script>" + script + "</script>")


def _js(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


# ---------------------------------------------------------------------------------------------------------------
# The admin view
# ---------------------------------------------------------------------------------------------------------------

def status_badge(status: str) -> Markup:
    tone = {"draft": "secondary", "scheduled": "azure", "sending": "blue", "sent": "green",
            "cancelled": "orange", "failed": "red"}.get(status, "secondary")
    return Markup(f'<span class="badge bg-{tone}-lt">{escape(localize(f"web.mailing.status.{status}"))}</span>')


def _format_status(model, name):
    return status_badge(getattr(model, "status", ""))


def _format_segment(model, name):
    return localize(f"web.mailing.segment.{model.segment}")


def _format_delivered(model, name):
    if model.status in (MailingStatus.DRAFT, MailingStatus.SCHEDULED) and not model.total:
        return "—"
    return localize("web.mailing.delivered", sent=model.sent, total=model.total)


def _format_date(model, name):
    value = _utc(getattr(model, name, None))
    return value.strftime("%Y-%m-%d %H:%M") if value else "—"


def _format_flag(model, name):
    return "✓" if getattr(model, name, False) else "—"


def _format_image(model, name):
    return "✓" if getattr(model, "image", None) else "—"


# SQLAdmin looks an upload field up on the edited object; the picture lives in ``Mailings.image``.
Mailings.picture = None
Mailings.send_mode = property(lambda self: MailingStatus.SCHEDULED == self.status and "scheduled" or "draft")


class MailingAdmin(AuditModelView, model=Mailings):
    category = "marketing"
    column_list = [Mailings.title, Mailings.status, Mailings.segment, Mailings.scheduled_at, "delivered",
                   Mailings.created_by]
    column_details_list = [Mailings.id, Mailings.title, Mailings.status, Mailings.segment, Mailings.scheduled_at,
                           Mailings.started_at, Mailings.finished_at, "delivered", Mailings.created_by,
                           Mailings.created_at, Mailings.disable_preview, Mailings.silent, Mailings.protect_content]
    column_searchable_list = [Mailings.title]
    column_sortable_list = [Mailings.id, Mailings.title, Mailings.status, Mailings.scheduled_at, Mailings.created_at]
    column_default_sort = (Mailings.id, True)
    column_formatters = {
        "status": _format_status, "segment": _format_segment, "scheduled_at": _format_date,
        "delivered": _format_delivered, "disable_preview": _format_flag, "silent": _format_flag,
        "protect_content": _format_flag, "started_at": _format_date, "finished_at": _format_date,
        "created_at": _format_date,
    }
    column_formatters_detail = column_formatters
    details_template = "mailing_details.html"
    name = Localized("web.model.mailing.one")
    name_plural = Localized("web.model.mailing.many")
    icon = "fa-solid fa-paper-plane"

    def is_accessible(self, request: Request) -> bool:
        return session_is_admin(request)

    def is_visible(self, request: Request) -> bool:
        return session_is_admin(request)

    # -- form ---------------------------------------------------------------------------------------------------

    async def scaffold_form(self, *args, **kwargs):
        counts = await segment_counts()
        segments = [(s, localize("web.mailing.segment_option", label=localize(f"web.mailing.segment.{s}"),
                                  count=counts.get(s, 0))) for s in MailingSegment.CHOICES]
        modes = [(m, localize(f"web.mailing.mode.{m}")) for m in MODES]
        now = _now().strftime("%Y-%m-%d %H:%M")

        class MailingForm(LocalizedForm):
            title = StringField(localize("web.col.title"), description=localize("web.mailing.title_hint"),
                                render_kw={"maxlength": 200})
            segment = SelectField(localize("web.col.segment"), choices=segments,
                                  description=localize("web.mailing.segment_hint"))
            text = TextAreaField(localize("web.col.text"), widget=MailingTextWidget(),
                               description=localize("web.mailing.text_hint"), validators=[WtfOptional()])
            picture = FileField(localize("web.col.image"), description=localize("web.mailing.image_hint"))
            remove_picture = BooleanField(localize("web.mailing.remove_image"))
            send_mode = SelectField(localize("web.col.send_mode"), choices=modes,
                                    description=localize("web.mailing.mode_hint"))
            scheduled_at = DateTimeLocalField(
                localize("web.col.scheduled_at"), format=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"],
                validators=[WtfOptional()], description=localize("web.mailing.scheduled_hint", now=now))
            disable_preview = BooleanField(localize("web.col.disable_preview"),
                                           description=localize("web.mailing.disable_preview_hint"))
            silent = BooleanField(localize("web.col.silent"), description=localize("web.mailing.silent_hint"))
            protect_content = BooleanField(localize("web.col.protect_content"),
                                           description=localize("web.mailing.protect_hint"))

        return MailingForm

    # -- saving -------------------------------------------------------------------------------------------------

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        if not is_created and model.status not in MailingStatus.EDITABLE:
            raise ValueError(localize("web.mailing.err.not_editable",
                                      status=localize(f"web.mailing.status.{model.status}")))
        title = (data.get("title") or "").strip()
        if not title:
            raise ValueError(localize("web.mailing.err.title_required"))
        data["title"] = title[:200]
        if data.get("segment") not in MailingSegment.CHOICES:
            raise ValueError(localize("web.mailing.err.bad_segment"))

        upload = data.pop("picture", None)
        remove = bool(data.pop("remove_picture", False))
        mode = data.pop("send_mode", None)
        content = await upload.read() if upload is not None and hasattr(upload, "read") else b""
        if content:
            try:
                validate_image(content)
            except ImageError as e:
                raise ValueError(_picture_error(e.code))
            data["image"], data["image_file_id"] = content, None
        elif remove:
            data["image"], data["image_file_id"] = None, None
        has_image = bool(content) or (not remove and not is_created and bool(getattr(model, "image", None)))

        text = sanitize_mailing_html(data.get("text"))
        length = visible_length(text)
        if length > MESSAGE_LIMIT:
            raise ValueError(localize("web.mailing.err.text_too_long", length=length, limit=MESSAGE_LIMIT))
        if not text and not has_image:
            raise ValueError(localize("web.mailing.err.content_required"))
        data["text"] = text

        if mode not in MODES:
            raise ValueError(localize("web.mailing.err.bad_mode"))
        scheduled_at = _utc(data.get("scheduled_at"))
        if mode == "draft":
            data["status"], data["scheduled_at"] = MailingStatus.DRAFT, scheduled_at
        elif mode == "now":
            data["status"], data["scheduled_at"] = MailingStatus.SCHEDULED, _now()
        else:
            if scheduled_at is None:
                raise ValueError(localize("web.mailing.err.date_required"))
            if scheduled_at < _now() - _SCHEDULE_GRACE:
                raise ValueError(localize("web.mailing.err.date_past"))
            data["status"], data["scheduled_at"] = MailingStatus.SCHEDULED, scheduled_at

        if is_created:
            user = await current_web_user(request)
            data["created_by"] = (user or {}).get("username")

    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        # Not the base class's repr of the row: ``updated_at`` is refreshed by the database and would need a
        # lazy load here. The audit line names the mailing and what it was set to.
        from bot.database.methods.audit import log_audit
        await log_audit(
            f"sqladmin_{'create' if is_created else 'update'}", resource_type=type(self).name,
            resource_id=str(getattr(model, "id", "")),
            details=f"title={data.get('title')!r}, status={data.get('status')}, segment={data.get('segment')}",
            ip_address=_client_ip(request))

    async def on_model_delete(self, model: Any, request: Request) -> None:
        if model.status == MailingStatus.SENDING:
            raise ValueError(localize("web.mailing.err.delete_sending"))

    # -- actions ------------------------------------------------------------------------------------------------

    def _back(self, request: Request, mailing_id: int | None, notice: str, **extra) -> RedirectResponse:
        if mailing_id is None:
            url = str(request.url_for("admin:list", identity=self.identity))
        else:
            url = str(request.url_for("admin:details", identity=self.identity, pk=mailing_id))
        query = "&".join(f"{k}={v}" for k, v in {"notice": notice, **extra}.items())
        return RedirectResponse(f"{url}?{query}", status_code=302)

    @staticmethod
    def _pk(request: Request) -> int | None:
        raw = request.query_params.get("pks", "").split(",")[0].strip()
        return int(raw) if raw.isdigit() else None

    @action(name="send_test", label=LazyText("web.mailing.action.test"),
            confirmation_message=LazyText("web.mailing.action.test.ask"), add_in_detail=False, add_in_list=False)
    async def send_test(self, request: Request):
        mailing_id = self._pk(request)
        user = await current_web_user(request)
        if mailing_id is None or not user:
            return self._back(request, mailing_id, "no_telegram")
        if not user.get("telegram_id"):
            return self._back(request, mailing_id, "no_telegram")
        from bot.web import admin as admin_module
        bot = admin_module._notifier_bot
        if bot is None:
            return self._back(request, mailing_id, "no_bot")
        from bot.misc.services.mailing_sender import MailingSender
        ok, code = await MailingSender(bot).send_test(mailing_id, int(user["telegram_id"]))
        if ok:
            return self._back(request, mailing_id, "test_sent")
        return self._back(request, mailing_id, "test_failed", detail=code)

    @action(name="cancel_mailing", label=LazyText("web.mailing.action.cancel"),
            confirmation_message=LazyText("web.mailing.action.cancel.ask"), add_in_detail=False, add_in_list=False)
    async def cancel(self, request: Request):
        mailing_id = self._pk(request)
        if mailing_id is not None and await cancel_mailing(mailing_id):
            await self._audit(request, "mailing_cancel", mailing_id)
            return self._back(request, mailing_id, "cancelled")
        return self._back(request, mailing_id, "not_cancellable")

    @action(name="duplicate", label=LazyText("web.mailing.action.duplicate"), add_in_detail=False, add_in_list=False)
    async def duplicate(self, request: Request):
        mailing_id = self._pk(request)
        original = await get_mailing(mailing_id) if mailing_id is not None else None
        if original is None:
            return self._back(request, None, "not_cancellable")
        image = await get_mailing_image(mailing_id)
        user = await current_web_user(request)
        async with Database().session() as s:
            copy = Mailings(
                title=f"{original['title']} (2)"[:200], text=original["text"], image=image, segment=original["segment"],
                status=MailingStatus.DRAFT, disable_preview=original["disable_preview"], silent=original["silent"],
                protect_content=original["protect_content"], created_by=(user or {}).get("username"))
            s.add(copy)
            await s.flush()
            new_id = copy.id
        await self._audit(request, "mailing_duplicate", new_id)
        return self._back(request, new_id, "duplicated")

    async def _audit(self, request: Request, action_name: str, mailing_id: int) -> None:
        from bot.database.methods.audit import log_audit
        await log_audit(action_name, resource_type=type(self).name, resource_id=str(mailing_id),
                        details=f"mailing={mailing_id}", ip_address=_client_ip(request))

    # -- details page helpers -----------------------------------------------------------------------------------

    @staticmethod
    def preview_html(model) -> Markup:
        return Markup(render_preview_html(model.text))

    @staticmethod
    def progress_percent(model) -> int:
        if model.status == MailingStatus.SENT:
            return 100
        done = (model.sent or 0) + (model.blocked or 0) + (model.failed or 0)
        return min(100, int(done * 100 / model.total)) if model.total else 0

    @staticmethod
    def stats_text(model) -> str:
        return localize("web.mailing.details.stats", sent=model.sent, blocked=model.blocked,
                        failed=model.failed, total=model.total)

    @staticmethod
    def notice_for(request: Request) -> tuple[str, str] | None:
        """``(kind, message)`` for the banner shown after an action (kind: success / danger)."""
        notice = request.query_params.get("notice", "")
        if notice not in ("test_sent", "no_telegram", "test_failed", "cancelled", "not_cancellable",
                          "duplicated", "no_bot"):
            return None
        kind = "success" if notice in ("test_sent", "cancelled", "duplicated") else "danger"
        detail = request.query_params.get("detail", "")[:60]
        return kind, localize(f"web.mailing.notice.{notice}", error=detail)


# ---------------------------------------------------------------------------------------------------------------
# The picture, for the editor preview and the details page
# ---------------------------------------------------------------------------------------------------------------

async def mailing_image(request: Request) -> Response:
    user = await current_web_user(request)
    if not user or user["role"] != "admin":
        return Response(status_code=403)
    data = await get_mailing_image(int(request.path_params["mailing_id"]))
    if not data:
        return Response(status_code=404)
    kind = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/webp" if data[8:12] == b"WEBP" else "image/jpeg"
    return Response(data, media_type=kind, headers={"Cache-Control": "private, max-age=60",
                                                    "X-Content-Type-Options": "nosniff"})


mailing_routes = [Route("/mailing-image/{mailing_id:int}", mailing_image)]
