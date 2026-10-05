# Module status

Per-module state at a glance. Legend: ✅ complete & tested · 🟡 works, has known limits · 🔧 built but not yet used live · ⬜ not built.
"Live" = verified by the owner on the deployed bot (none yet). Everything ✅ is covered by automated tests; nothing has been verified
in a live Telegram chat by Claude. Update this table in the same PR that changes a module.

| Module | Since | State | Tests | Notes / known limits |
|---|---|---|---|---|
| **Catalog** — categories, subcategories, products, stock | #1, #6 | ✅ | `test_database_crud`, `test_subcategories_*` | two levels max; category holds subcategories *or* products |
| **Weight options** | #7, #12, #13 | 🟡 | `test_product_options_*` | changing an option's **label** in the web rows = delete + create (its stock is lost); renaming a head in the bot does not rename options; head delete removes options in a separate step |
| **Translated catalog** | #3, #4, #11 | ✅ | `test_localized_catalog_*`, `test_admin_language_*`, `test_web_translations` | product name is one field in the web form; descriptions per language |
| **Product pictures** | #1 | ✅ | `test_images`, `test_web_images`, `test_item_card_photo` | stored as uploaded (≤ 10 MB); options show the head's picture |
| **Cart, promo codes, sales, reviews, restock notify** | upstream, adapted | ✅ | `test_cart_reviews`, `test_promo_*`, `test_sales`, `test_user_handlers` | |
| **Checkout** (delivery/pickup, name, phone, address, shipping, comment, payment, summary) | #1, #23 | ✅ | `test_payment_handlers`, `test_shipping` | |
| **Payments** — MIA (staff-verified) + cash on delivery/pickup | #1 | ✅ / 🔧 | `test_orders`, `test_payment_handlers` | MIA needs real `MIA_*` details in the server `.env`; cash recorded on completion |
| **Orders** — lifecycle, stock reservation, expiry, referral commission | #1 | ✅ | `test_orders`, `test_orders_admin`, `test_recovery` | order ownership intentionally not built |
| **Order management in chat** | #1 | ✅ | `test_orders_admin`, `test_admin_handlers` | |
| **Order management in web** (action buttons, Payments to verify) | #1, #15, #19 | ✅ | `test_web_roles_orders`, `test_web_menu` | actions only (no free edit) by design; statuses in the *list* are raw values (roadmap 4.7) |
| **Shipping methods** | #23 | ✅ 🔧 | `test_shipping` | no method active ⇒ delivery free/unpriced; shipping name stored in canonical language only (roadmap 4.10); referral commission includes the fee (6.1) |
| **Client profiles** | #22 | ✅ | `test_client_profiles` | names fill as people use the bot; phone/address from latest order; no import by design |
| **Mailings** (web) | #20, #21 | ✅ 🔧 | `test_mailings_core`, `test_web_mailings` | Admin only; UTC schedule; interrupted ≠ resumed; no per-recipient log; **not yet tried against live Telegram** — send a test first |
| **Text broadcast** (bot) | upstream | ✅ | `test_broadcast*` | the older in-chat broadcast |
| **Web panel shell** — grouped sidebar, translated chrome, My account | #19, #21 | ✅ | `test_web_menu`, `test_web_i18n`, `test_web_accounts` | built on SQLAdmin 0.16.1 with template overrides |
| **Web accounts & roles** | #1, #15 | ✅ | `test_web_accounts`, `test_role_management`, `test_web_roles_orders` | Admin/Staff levels; role permissions as tags; no 2FA |
| **Languages** (bot + web) | #1, #21 | ✅ | `test_i18n`, `test_language_picker`, `test_web_i18n` | en/ru/ro parity enforced by tests |
| **Bottom menu + welcome line** | #5, #14, #16, #17 | 🟡 | `test_bottom_nav`, `test_language_picker` | one short line always stays at the top; a real-device check after the last changes is still pending |
| **Clean chat** | #8 | 🟡 | `test_clean_chat` | 48 h delete limit; real-device behaviour not yet confirmed by the owner |
| **Referrals & balance** | upstream, adapted | ✅ | `test_referral_system`, `test_transactions` | |
| **Audit log, CSV export** | upstream | ✅ | `test_audit`, `test_export` | export includes profile columns (#22) |
| **Rate limiting, security middleware** | upstream | ✅ | `test_middleware`, `test_login_rate_limiter` | web login limiter is per-process |
| **Caching (Redis optional)** | upstream | ✅ | `test_cache_invalidation` | |
| **UMBRA crawler + importer** | #10 | 🔧 | `test_import_catalog` | **not run on the live shop**: waiting for the owner's prices (50 g / 200 g, MDL) and the Puff/accessories decision |
| **Docs & process** | #2, #18, docs set | ✅ | — | AGENTS/CLAUDE/CHANGELOG/ROADMAP/docs set |
| Import page in web (price list) | — | ⬜ | | roadmap 4.1 |
| Print order / packing slip | — | ⬜ | | roadmap 4.2 |
| Customer groups, unsubscribe | — | ⬜ | | roadmap 4.3 / 4.4 |
| Per-recipient mailing log, resumable mailings | — | ⬜ | | roadmap 4.6 / 6.2 |
| Checkout prefill from profile | — | ⬜ | | roadmap 5.1 |
