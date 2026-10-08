# Module status

Per-module state at a glance. Legend: ✅ complete & tested · 🟡 works, has known limits · 🔧 built but not yet used live · ⬜ not built.
"Live" = verified by the owner on the deployed bot (none yet). Everything ✅ is covered by automated tests; nothing has been verified
in a live Telegram chat by Claude. Update this table in the same PR that changes a module.

| Module | Since | State | Tests | Notes / known limits |
|---|---|---|---|---|
| **Catalog** — categories, subcategories, products, stock | #1, #6 | ✅ | `test_database_crud`, `test_subcategories_*` | two levels max; category holds subcategories *or* products |
| **Weight options** | #7, #12, #13 | 🟡 | `test_product_options_*` | changing an option's **label** in the web rows = delete + create (its stock is lost); renaming a head in the bot does not rename options; head delete removes options in a separate step |
| **Catalog search** — several words, any language: name, description, option label, category | #42 | ✅ | `test_search_words`, `test_localized_catalog_core` | substring match, no stemming; `ş`/`ţ` handled, other diacritics must match |
| **Translated catalog** | #3, #4, #11 | ✅ | `test_localized_catalog_*`, `test_admin_language_*`, `test_web_translations` | product name is one field in the web form; descriptions per language |
| **Product pictures** | #1 | ✅ | `test_images`, `test_web_images`, `test_item_card_photo` | stored as uploaded (≤ 10 MB); options show the head's picture |
| **Bot command menu** (☰ next to the input field) | #30 | ✅ | `test_bot_commands` | per-language lists published at startup; per-chat list follows the language chosen in the bot; Telegram may take a moment to refresh the menu |
| **Favorites** (⭐ on the card, paged list in the profile) | #28 | ✅ | `test_favorites` | stars the head product; opened from the profile or `/favorites` |
| **Cart, promo codes (applied in the cart), sales, reviews, restock notify** | upstream, adapted | ✅ | `test_cart_reviews`, `test_cart_promo`, `test_promo_*`, `test_sales`, `test_user_handlers` | |
| **Checkout** (delivery/pickup, name, phone, address, shipping, comment, payment, summary) | #1, #23 | ✅ | `test_payment_handlers`, `test_shipping` | |
| **Payments** — MIA (staff-verified) + cash on delivery/pickup | #1 | ✅ / 🔧 | `test_orders`, `test_payment_handlers` | MIA needs real `MIA_*` details in the server `.env`; cash recorded on completion |
| **Orders** — lifecycle, stock reservation, expiry, referral commission, order again | #1 | ✅ | `test_orders`, `test_orders_admin`, `test_recovery`, `test_shop_handlers` | order ownership intentionally not built; *Order again* refills the cart from a completed/cancelled order |
| **Order management in chat** | #1 | ✅ | `test_orders_admin`, `test_admin_handlers` | |
| **Payment reminders & stale-order alerts** | — | ✅ | `test_recovery` | recovery sweeps every 60 s; once per order (`reminder_sent_at`, `staff_alerted_at`); 0 in `.env` switches each off |
| **Error alerts** | — | ✅ | `test_error_alerts` | `bot/misc/error_alerts.py`: logging handler → owner (+ `ERROR_ALERT_CHAT_ID`); dedupe 10 min, 5 per 10 min, no tracebacks; **not seen in live Telegram** |
| **CI secret scan** | — | ✅ | `test_scan_secrets` | `scripts/scan_secrets.py`, job *Secret scan* in `tests.yml` |
| **Order management in web** (action buttons, Payments to verify) | #1, #15, #19 | ✅ | `test_web_roles_orders`, `test_web_menu`, `test_order_tools` | actions only (no free edit) by design; list filters (status / payment / dates), localized labels, printable packing slip, customer note (`bot/web/order_tools.py`) |
| **Shipping methods** | #23 | ✅ 🔧 | `test_shipping` | no method active ⇒ delivery free/unpriced; order keeps the en/ru/ro names it was placed with; referral commission excludes the fee |
| **My details** (customer edits name, phone, city, address; checkout "use saved") | #29 | ✅ | `test_profile_details` | Operation History button removed (data stays); typed name is separate from Telegram's |
| **Client profiles** | #22 | ✅ | `test_client_profiles` | names fill as people use the bot; phone/address from latest order; no import by design |
| **Mailings** (web) | #20, #21 | ✅ 🔧 | `test_mailings_core`, `test_web_mailings`, `test_mailing_prefs` | Admin only; schedule in `SHOP_TIMEZONE`; per-recipient log + resend to failed; opt-out button under every message and a profile toggle; a restart resumes it (≤ 24 h, D-22); **not yet tried against live Telegram** — send a test first |
| **Text broadcast** (bot) | upstream | ✅ | `test_broadcast*` | the older in-chat broadcast |
| **Dashboard** — panel home: period totals, attention box, top products, per-day table | #41 | ✅ | `test_dashboard` | read-only; revenue = completed orders; top 5 products; periods 7/30/90 days |
| **Web panel shell** — grouped sidebar, translated chrome, My account, **light/dark theme** | #19, #21, #27 | ✅ | `test_web_menu`, `test_web_i18n`, `test_web_accounts` | built on SQLAdmin 0.16.1 with template overrides |
| **Web accounts & roles** | #1, #15 | ✅ | `test_web_accounts`, `test_role_management`, `test_web_roles_orders` | Admin/Staff levels; role permissions as tags; no 2FA |
| **Languages** (bot + web) | #1, #21 | ✅ | `test_i18n`, `test_language_picker`, `test_web_i18n` | en/ru/ro parity enforced by tests |
| **Bottom menu + welcome line** | #5, #14, #16, #17 | 🟡 | `test_bottom_nav`, `test_language_picker` | one short line always stays at the top; a real-device check after the last changes is still pending |
| **Clean chat** | #8 | 🟡 | `test_clean_chat` | 48 h delete limit; real-device behaviour not yet confirmed by the owner |
| **Referrals & balance** | upstream, adapted | ✅ | `test_referral_system`, `test_transactions` | |
| **Backup / restore scripts, erase a client** | — | ✅ | `test_erasure` (scripts tried by hand against local PostgreSQL) | `scripts/backup_db.sh`, `restore_db.sh`; erase is Admin-only; no automatic retention yet |
| **Audit log, CSV export** | upstream | ✅ | `test_audit`, `test_export` | export includes profile columns (#22) |
| **Rate limiting, security middleware** | upstream | ✅ | `test_middleware`, `test_login_rate_limiter` | web login limiter is per-process |
| **Caching (Redis optional)** | upstream | ✅ | `test_cache_invalidation` | |
| **Docs & process** | #2, #18, docs set | ✅ | — | AGENTS/CLAUDE/CHANGELOG/ROADMAP/docs set |
| Import page in web (price list) | — | ⬜ | | roadmap 4.1 |
| Customer groups, unsubscribe | — | ⬜ | | roadmap 4.3 / 4.4 |
| Per-recipient mailing log, resumable mailings | — | ⬜ | | roadmap 4.6 / 6.2 |
