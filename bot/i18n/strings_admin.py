"""Admin-side strings of the physical-goods shop: catalog and stock, orders console, statistics."""

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        # === Admin: console ===
        "admin.menu.orders": "📦 Заказы",

        # === Admin: Products menu / add ===
        "admin.goods.menu.title": "⛩️ Меню управления товарами",
        "admin.goods.add_position": "➕ Добавить товар",
        "admin.goods.stock_manage": "📦 Остатки на складе",
        "admin.goods.update_position": "📝 Изменить товар",
        "admin.goods.delete_position": "❌ Удалить товар",
        "admin.goods.add.prompt.name": "Введите название товара ({language})",
        "admin.goods.add.name.exists": "❌ Товар не может быть создан (такой товар уже существует)",
        "admin.goods.add.name.invalid": "⚠️ Недопустимое название (1–100 символов, без управляющих символов).",
        "admin.goods.add.prompt.description": "Введите описание товара ({language}):",
        "admin.categories.prompt.add": "Введите название новой категории ({language}):",
        "admin.goods.add.prompt.price": "Введите цену товара (число в {currency}):",
        "admin.goods.add.price.invalid": "⚠️ Некорректное значение цены. Введите целое число.",
        "admin.goods.add.prompt.category": "Введите категорию, к которой относится товар:",
        "admin.goods.add.category.not_found": "❌ Товар не может быть создан (категория введена неверно)",
        "admin.goods.add.prompt.stock": "Сколько единиц товара сейчас на складе? Введите целое число (0 — нет в наличии):",
        "admin.goods.add.result.created": "✅ Товар «{name}» создан. На складе: <b>{qty}</b> шт.",
        "admin.goods.prompt.enter_item_name": "Введите название товара",
        "admin.goods.position.not_found": "❌ Такого товара не существует",
        "admin.goods.channel.arrival": "📦 Поступление на склад: <b>{name}</b>\nВ наличии: <b>{qty}</b> шт.",

        # === Admin: product pictures ===
        "admin.goods.add.prompt.photo": "Отправьте фото товара (можно файлом — так сохранится исходное качество) или нажмите «Пропустить».",
        "admin.goods.photo.btn.skip": "⏭ Пропустить",
        "admin.goods.photo.btn.change": "🖼 Изменить фото",
        "admin.goods.photo.btn.remove": "🗑 Удалить фото",
        "admin.goods.photo.status.yes": "🖼 Фото: есть",
        "admin.goods.photo.status.no": "🖼 Фото: нет",
        "admin.goods.photo.prompt.change": "Отправьте новое фото товара (можно файлом — так сохранится исходное качество):",
        "admin.goods.photo.reprompt": "⚠️ Отправьте фото или изображение файлом.",
        "admin.goods.photo.too_large": "⚠️ Файл слишком большой (не более 10 МБ). Отправьте другой.",
        "admin.goods.photo.invalid": "⚠️ Не удалось прочитать изображение. Отправьте другой файл.",
        "admin.goods.photo.unsupported": "⚠️ Поддерживаются только JPEG, PNG и WEBP. Отправьте другой файл.",
        "admin.goods.photo.download_failed": "⚠️ Не удалось загрузить файл из Telegram. Попробуйте ещё раз.",
        "admin.goods.photo.updated": "✅ Фото товара сохранено.",
        "admin.goods.photo.removed": "✅ Фото товара удалено.",
        "admin.goods.photo.none": "ℹ️ У товара нет фото.",
        "admin.goods.photo.remove.confirm": "Удалить фото товара «{name}»?",
        "admin.goods.photo.remove.yes": "✅ Да, удалить",
        "admin.goods.photo.remove.no": "↩️ Отмена",

        # === Admin: Stock screen ===
        "admin.goods.stock.card": (
            "📦 <b>{name}</b>\n"
            "💵 Цена: <code>{price}</code> {currency}\n"
            "🏬 На складе: <b>{stock}</b> шт."
        ),
        "admin.goods.stock.btn.set": "✏️ Задать",
        "admin.goods.stock.btn.add": "➕ Добавить",
        "admin.goods.stock.btn.sub": "➖ Убрать",
        "admin.goods.stock.prompt.set": "Введите новый остаток (целое число, 0 — нет в наличии):",
        "admin.goods.stock.prompt.add": "Сколько единиц добавить на склад? Введите целое число:",
        "admin.goods.stock.prompt.sub": "Сколько единиц списать со склада? Введите целое число:",
        "admin.goods.stock.invalid": "⚠️ Введите целое неотрицательное число (для «добавить» и «убрать» — не меньше 1).",
        "admin.goods.stock.updated": "✅ Остаток обновлён: {old} → <b>{new}</b> шт.",

        # === Admin: Product update flow ===
        "admin.goods.update.prompt.name": "Введите название товара",
        "admin.goods.update.not_exists": "❌ Товар не может быть изменён (такого товара не существует)",
        "admin.goods.update.prompt.new_name": "Введите новое название товара:",
        "admin.goods.update.prompt.description": "Введите описание товара:",
        "admin.goods.update.prompt.category": "Введите категорию товара (сейчас: «{category}»):",
        "admin.goods.update.keep_category": "Оставить текущую категорию",
        "admin.goods.update.category.not_found": "❌ Такой категории не существует. Введите название существующей категории.",
        "admin.goods.update.position.invalid": "Товар не найден.",
        "admin.goods.update.position.exists": "Товар с таким названием уже существует.",
        "admin.goods.update.success": "✅ Товар обновлён",

        # === Admin: Product delete flow ===
        "admin.goods.delete.prompt.name": "Введите название товара",
        "admin.goods.delete.position.not_found": "❌ Товар не удалён (такого товара не существует)",
        "admin.goods.delete.position.success": "✅ Товар удалён",
        # === Admin: Weight options ===
        "admin.goods.add_option": "➕ Добавить вариант (вес)",
        "admin.goods.option.prompt.head": "Введите название основного товара, для которого добавляется вариант (например, «50 г»):",
        "admin.goods.option.head_not_found": "❌ Такого товара не существует",
        "admin.goods.option.head_is_option": "❌ Это уже вариант товара. Введите название основного товара.",
        "admin.goods.option.prompt.label": "Введите название варианта (например, «50 г»):",
        "admin.goods.option.label.invalid": "⚠️ Недопустимое название варианта (1–32 символа, без символа «·»).",
        "admin.goods.option.exists": "❌ Такой вариант у этого товара уже есть",
        "admin.goods.option.result.created": "✅ Вариант «{name}» создан. На складе: <b>{qty}</b> шт.",
        "admin.goods.options.title": "🧩 Варианты:",
        "admin.goods.options.line": "• {label} — {price} {currency}, на складе: {stock} шт.",
        "admin.goods.delete.position.success_options": "✅ Товар удалён вместе с вариантами: {count}",

        # === Admin: Statistics ===
        "admin.shop.stats.template": (
            "Статистика магазина:\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "<b>◽ПОЛЬЗОВАТЕЛИ</b>\n"
            "◾️Новых за 24 часа: {today_users}\n"
            "◾️Всего: {users}\n"
            "◾️Покупателей: {buyers}\n"
            "◾️Заблокировано: {blocked}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>ЗАКАЗЫ</b>\n"
            "◾Новых (ждут обработки): {new_orders}\n"
            "◾За 24 часа: {today_sold_count} шт. на {today_orders} {currency}\n"
            "◾Выручка за всё время: {all_orders} {currency}\n"
            "◾Средний чек: {avg_order} {currency}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>БАЛАНС КЛИЕНТОВ</b>\n"
            "◾Пополнений за 24 часа: {today_topups} {currency}\n"
            "◾Средств на балансах: {system_balance} {currency}\n"
            "◾Пополнено всего: {all_topups} {currency}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>КАТАЛОГ</b>\n"
            "◾На складе: {items} шт.\n"
            "◾Товаров: {goods}\n"
            "◾Категорий: {categories}\n"
            "◾Продано единиц: {sold_count}"
        ),

        # === Admin: Users (orders) ===
        "admin.users.orders_count": "📦 <b>Заказов</b> — {count}",
        "admin.users.btn.orders": "📦 Заказы клиента",
        "admin.users.orders.title": "Заказы клиента:",
        "admin.users.orders.empty": "ℹ️ У этого клиента пока нет заказов.",
        "admin.users.orders.item": "#{id} · {total} {currency} · {status}",

        # === Admin: Orders console ===
        "admin.orders.menu.title": "📦 Заказы\n\nВыберите список:",
        "admin.orders.list.new": "🆕 Новые",
        "admin.orders.list.chk": "🔎 Проверить оплату MIA",
        "admin.orders.list.cnf": "✅ Подтверждённые",
        "admin.orders.list.shp": "🚚 Отправленные",
        "admin.orders.list.cmp": "🏁 Выполненные",
        "admin.orders.list.can": "❌ Отменённые",
        "admin.orders.list.new.title": "🆕 Новые заказы:",
        "admin.orders.list.chk.title": "🔎 Клиент сообщил об оплате MIA — проверьте поступление:",
        "admin.orders.list.cnf.title": "✅ Подтверждённые заказы:",
        "admin.orders.list.shp.title": "🚚 Отправленные заказы:",
        "admin.orders.list.cmp.title": "🏁 Выполненные заказы:",
        "admin.orders.list.can.title": "❌ Отменённые заказы:",
        "admin.orders.list.empty": "ℹ️ В этом списке заказов нет.",
        "admin.orders.find": "🔎 Найти заказ по номеру",
        "admin.orders.find.prompt": "Введите номер заказа:",
        "admin.orders.btn.proof": "🖼 Скриншот оплаты",
        "admin.orders.btn.confirm": "✅ Подтвердить заказ",
        "admin.orders.btn.ship": "🚚 Отправлен / готов к выдаче",
        "admin.orders.btn.complete": "🏁 Выполнен",
        "admin.orders.btn.cancel": "❌ Отменить заказ",
        "admin.orders.btn.contact": "💬 Написать клиенту",
        "admin.orders.proof.caption": "🖼 Скриншот оплаты заказа #{id}",
        "admin.orders.cancel.confirm": "❓ Отменить заказ #{id}? Товары вернутся на склад, оплаченная с баланса часть вернётся клиенту.",
        "admin.orders.cancel.refund_warning": "⚠️ Клиент уже оплатил {amount} {currency} (MIA или наличными). Бот не возвращает эти деньги — после отмены верните их вручную.",
        "admin.orders.cancel.refund_manual": "↩️ Верните клиенту {amount} {currency} вручную (оплата помечена как «возврат»).",
        "admin.orders.cancel.yes": "✅ Да, отменить",
        "admin.orders.cancel.no": "↩️ Нет",
        "admin.orders.done.payment_confirmed": "✅ Оплата подтверждена, заказ принят. Клиент уведомлён.",
        "admin.orders.done.payment_rejected": "⚠️ Перевод не найден: заказ вернулся в «ожидает оплаты». Клиент уведомлён.",
        "admin.orders.done.confirmed": "✅ Заказ подтверждён. Клиент уведомлён.",
        "admin.orders.done.shipped": "🚚 Заказ отмечен как отправленный. Клиент уведомлён.",
        "admin.orders.done.completed": "🏁 Заказ выполнен. Клиент уведомлён.",
        "admin.orders.done.cancelled": "❌ Заказ отменён. Клиент уведомлён.",
        "admin.orders.err.not_found": "❌ Заказ не найден",
        "admin.orders.err.not_mia": "❌ Это не заказ с оплатой MIA",
        "admin.orders.err.not_awaiting_payment": "❌ Заказ уже не ждёт проверки оплаты (возможно, его обработал другой сотрудник)",
        "admin.orders.err.invalid_transition": "❌ Этот статус сейчас нельзя установить",
        "admin.orders.err.payment_not_confirmed": "❌ Сначала подтвердите оплату MIA",
        "admin.orders.err.not_cancellable": "❌ Этот заказ уже нельзя отменить",
        "admin.orders.err.no_proof": "ℹ️ Клиент не прислал скриншот",
        "admin.orders.err.proof_unavailable": "⚠️ Не удалось показать скриншот",

        # === Admin: catalog translations ===
        "admin.categories.add.prompt.translation": "Введите название категории на языке {language} или нажмите «Пропустить» (тогда будет показано основное название):",
        "admin.goods.add.prompt.name_translation": "Введите название товара на языке {language} или нажмите «Пропустить» (тогда будет показано основное название):",
        "admin.goods.add.prompt.description_translation": "Введите описание товара на языке {language} или нажмите «Пропустить» (тогда будет показано основное описание):",
        "admin.translations.btn.skip": "⏭ Пропустить",
        "admin.translations.btn.open": "🌐 Переводы",
        "admin.translations.btn.name": "Название",
        "admin.translations.btn.description": "Описание",
        "admin.translations.btn.clear": "🗑 Очистить",
        "admin.translations.invalid": "⚠️ Введите текст или нажмите «Пропустить».",
        "admin.translations.too_long": "⚠️ Слишком длинный текст (максимум {max} символов). Введите короче.",
        "admin.translations.not_set": "— не задано",
        "admin.translations.main": "основной",
        "admin.translations.field.name": "Название",
        "admin.translations.field.description": "Описание",
        "admin.translations.card.title.category": "🌐 Переводы категории <b>{name}</b>",
        "admin.translations.card.title.item": "🌐 Переводы товара <b>{name}</b>",
        "admin.translations.card.hint": "Выберите язык и поле для изменения. Если перевод не задан, показывается основной текст.",
        "admin.translations.prompt.category": "Введите название категории, переводы которой нужно изменить:",
        "admin.translations.prompt.name": "✏️ <b>{name}</b>\nНазвание на языке {language}\nСейчас: {current}\n\nОтправьте новый текст (до {max} символов) или нажмите «Очистить».",
        "admin.translations.prompt.description": "✏️ <b>{name}</b>\nОписание на языке {language}\nСейчас: {current}\n\nОтправьте новый текст (до {max} символов) или нажмите «Очистить».",
        "admin.translations.saved": "✅ Перевод сохранён ({language}).",
        "admin.translations.cleared": "🗑 Перевод удалён ({language}): будет показан основной текст.",
        "admin.translations.err.category_not_found": "❌ Категория не найдена",
        "admin.categories.add.prompt.parent": "Укажите родительскую категорию (название на любом языке), чтобы создать подкатегорию, или нажмите «Пропустить» (тогда категория будет создана на верхнем уровне):",
        "admin.categories.add.parent.not_found": "❌ Родительская категория не найдена. Введите название существующей категории или нажмите «Пропустить».",
        "admin.categories.add.parent.not_top_level": "❌ Подкатегория не может быть родительской: допускается только два уровня. Выберите категорию верхнего уровня.",
        "admin.categories.add.parent.has_items": "❌ В этой категории уже есть товары, поэтому в ней нельзя создать подкатегорию. Сначала перенесите товары.",
        "admin.categories.delete.has_subcategories": "❌ В этой категории есть подкатегории. Сначала удалите их или перенесите.",
        "admin.goods.add.category.has_subcategories": "❌ В этой категории есть подкатегории. Выберите одну из них.",
        "admin.goods.update.category.has_subcategories": "❌ В этой категории есть подкатегории. Выберите одну из них.",
        "admin.translations.card.parent": "Родитель: {name}",
        "admin.translations.err.item_not_found": "❌ Товар не найден",
        "admin.translations.err.invalid_language": "❌ Неподдерживаемый язык",
        "admin.translations.err.invalid_field": "❌ Неподдерживаемое поле",
        "admin.translations.err.too_long": "⚠️ Слишком длинный текст (максимум {max} символов).",
    },
    "en": {
        # === Admin: console ===
        "admin.menu.orders": "📦 Orders",

        # === Admin: Products menu / add ===
        "admin.goods.menu.title": "⛩️ Products management",
        "admin.goods.add_position": "➕ Add product",
        "admin.goods.stock_manage": "📦 Stock",
        "admin.goods.update_position": "📝 Edit product",
        "admin.goods.delete_position": "❌ Delete product",
        "admin.goods.add.prompt.name": "Enter the product name ({language})",
        "admin.goods.add.name.exists": "❌ Product cannot be created (it already exists)",
        "admin.goods.add.name.invalid": "⚠️ Invalid name (1–100 characters, no control characters).",
        "admin.goods.add.prompt.description": "Enter the product description ({language}):",
        "admin.categories.prompt.add": "Enter the new category name ({language}):",
        "admin.goods.add.prompt.price": "Enter the product price (a number in {currency}):",
        "admin.goods.add.price.invalid": "⚠️ Invalid price. Please enter a whole number.",
        "admin.goods.add.prompt.category": "Enter the category the product belongs to:",
        "admin.goods.add.category.not_found": "❌ Product cannot be created (invalid category)",
        "admin.goods.add.prompt.stock": "How many units are in stock right now? Enter a whole number (0 means out of stock):",
        "admin.goods.add.result.created": "✅ Product “{name}” created. In stock: <b>{qty}</b> pcs.",
        "admin.goods.prompt.enter_item_name": "Enter the product name",
        "admin.goods.position.not_found": "❌ This product doesn't exist",
        "admin.goods.channel.arrival": "📦 New arrival: <b>{name}</b>\nIn stock: <b>{qty}</b> pcs.",

        # === Admin: product pictures ===
        "admin.goods.add.prompt.photo": "Send the product photo (you can send it as a file to keep the original quality) or tap Skip.",
        "admin.goods.photo.btn.skip": "⏭ Skip",
        "admin.goods.photo.btn.change": "🖼 Change photo",
        "admin.goods.photo.btn.remove": "🗑 Remove photo",
        "admin.goods.photo.status.yes": "🖼 Photo: yes",
        "admin.goods.photo.status.no": "🖼 Photo: none",
        "admin.goods.photo.prompt.change": "Send the new product photo (you can send it as a file to keep the original quality):",
        "admin.goods.photo.reprompt": "⚠️ Please send a photo or an image file.",
        "admin.goods.photo.too_large": "⚠️ The file is too large (10 MB at most). Please send another one.",
        "admin.goods.photo.invalid": "⚠️ The image could not be read. Please send another file.",
        "admin.goods.photo.unsupported": "⚠️ Only JPEG, PNG and WEBP are supported. Please send another file.",
        "admin.goods.photo.download_failed": "⚠️ The file could not be downloaded from Telegram. Please try again.",
        "admin.goods.photo.updated": "✅ Product photo saved.",
        "admin.goods.photo.removed": "✅ Product photo removed.",
        "admin.goods.photo.none": "ℹ️ This product has no photo.",
        "admin.goods.photo.remove.confirm": "Remove the photo of “{name}”?",
        "admin.goods.photo.remove.yes": "✅ Yes, remove",
        "admin.goods.photo.remove.no": "↩️ Cancel",

        # === Admin: Stock screen ===
        "admin.goods.stock.card": (
            "📦 <b>{name}</b>\n"
            "💵 Price: <code>{price}</code> {currency}\n"
            "🏬 In stock: <b>{stock}</b> pcs."
        ),
        "admin.goods.stock.btn.set": "✏️ Set",
        "admin.goods.stock.btn.add": "➕ Add",
        "admin.goods.stock.btn.sub": "➖ Remove",
        "admin.goods.stock.prompt.set": "Enter the new stock (a whole number, 0 means out of stock):",
        "admin.goods.stock.prompt.add": "How many units to add to the stock? Enter a whole number:",
        "admin.goods.stock.prompt.sub": "How many units to remove from the stock? Enter a whole number:",
        "admin.goods.stock.invalid": "⚠️ Enter a whole non-negative number (at least 1 for add and remove).",
        "admin.goods.stock.updated": "✅ Stock updated: {old} → <b>{new}</b> pcs.",

        # === Admin: Product update flow ===
        "admin.goods.update.prompt.name": "Enter the product name",
        "admin.goods.update.not_exists": "❌ Product cannot be updated (it does not exist)",
        "admin.goods.update.prompt.new_name": "Enter the new product name:",
        "admin.goods.update.prompt.description": "Enter the product description:",
        "admin.goods.update.prompt.category": "Enter the product's category (currently “{category}”):",
        "admin.goods.update.keep_category": "Keep the current category",
        "admin.goods.update.category.not_found": "❌ This category doesn't exist. Enter the name of an existing category.",
        "admin.goods.update.position.invalid": "Product not found.",
        "admin.goods.update.position.exists": "A product with this name already exists.",
        "admin.goods.update.success": "✅ Product updated",

        # === Admin: Product delete flow ===
        "admin.goods.delete.prompt.name": "Enter the product name",
        "admin.goods.delete.position.not_found": "❌ Product not deleted (it doesn't exist)",
        "admin.goods.delete.position.success": "✅ Product deleted",
        # === Admin: Weight options ===
        "admin.goods.add_option": "➕ Add option (weight)",
        "admin.goods.option.prompt.head": "Enter the name of the main product to add an option to (the option label comes next, e.g. “50 g”):",
        "admin.goods.option.head_not_found": "❌ No such product",
        "admin.goods.option.head_is_option": "❌ That is already an option. Enter the name of the main product.",
        "admin.goods.option.prompt.label": "Enter the option label (e.g. “50 g”):",
        "admin.goods.option.label.invalid": "⚠️ Invalid option label (1–32 characters, no “·” character).",
        "admin.goods.option.exists": "❌ This product already has such an option",
        "admin.goods.option.result.created": "✅ Option “{name}” created. In stock: <b>{qty}</b> pcs.",
        "admin.goods.options.title": "🧩 Options:",
        "admin.goods.options.line": "• {label} — {price} {currency}, in stock: {stock} pcs.",
        "admin.goods.delete.position.success_options": "✅ Product deleted together with its options: {count}",

        # === Admin: Statistics ===
        "admin.shop.stats.template": (
            "Shop statistics:\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "<b>◽USERS</b>\n"
            "◾️New in 24h: {today_users}\n"
            "◾️Total: {users}\n"
            "◾️Customers: {buyers}\n"
            "◾️Blocked: {blocked}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>ORDERS</b>\n"
            "◾New (waiting to be handled): {new_orders}\n"
            "◾Last 24h: {today_sold_count} for {today_orders} {currency}\n"
            "◾Revenue, all time: {all_orders} {currency}\n"
            "◾Average order: {avg_order} {currency}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>CUSTOMER BALANCES</b>\n"
            "◾Top-ups in 24h: {today_topups} {currency}\n"
            "◾Funds on balances: {system_balance} {currency}\n"
            "◾Topped up in total: {all_topups} {currency}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>CATALOG</b>\n"
            "◾In stock: {items} pcs.\n"
            "◾Products: {goods}\n"
            "◾Categories: {categories}\n"
            "◾Units sold: {sold_count}"
        ),

        # === Admin: Users (orders) ===
        "admin.users.orders_count": "📦 <b>Orders</b> — {count}",
        "admin.users.btn.orders": "📦 Customer's orders",
        "admin.users.orders.title": "Customer's orders:",
        "admin.users.orders.empty": "ℹ️ This customer has no orders yet.",
        "admin.users.orders.item": "#{id} · {total} {currency} · {status}",

        # === Admin: Orders console ===
        "admin.orders.menu.title": "📦 Orders\n\nChoose a list:",
        "admin.orders.list.new": "🆕 New",
        "admin.orders.list.chk": "🔎 Check MIA payments",
        "admin.orders.list.cnf": "✅ Confirmed",
        "admin.orders.list.shp": "🚚 Shipped",
        "admin.orders.list.cmp": "🏁 Completed",
        "admin.orders.list.can": "❌ Cancelled",
        "admin.orders.list.new.title": "🆕 New orders:",
        "admin.orders.list.chk.title": "🔎 The customer reports an MIA payment — check that it arrived:",
        "admin.orders.list.cnf.title": "✅ Confirmed orders:",
        "admin.orders.list.shp.title": "🚚 Shipped orders:",
        "admin.orders.list.cmp.title": "🏁 Completed orders:",
        "admin.orders.list.can.title": "❌ Cancelled orders:",
        "admin.orders.list.empty": "ℹ️ There are no orders in this list.",
        "admin.orders.find": "🔎 Find order by number",
        "admin.orders.find.prompt": "Enter the order number:",
        "admin.orders.btn.proof": "🖼 Payment screenshot",
        "admin.orders.btn.confirm": "✅ Confirm order",
        "admin.orders.btn.ship": "🚚 Shipped / ready for pickup",
        "admin.orders.btn.complete": "🏁 Completed",
        "admin.orders.btn.cancel": "❌ Cancel order",
        "admin.orders.btn.contact": "💬 Message the customer",
        "admin.orders.proof.caption": "🖼 Payment screenshot for order #{id}",
        "admin.orders.cancel.confirm": "❓ Cancel order #{id}? The goods go back to stock and the part paid from the balance is returned to the customer.",
        "admin.orders.cancel.refund_warning": "⚠️ The customer has already paid {amount} {currency} (MIA or cash). The bot does not return that money — refund it manually after cancelling.",
        "admin.orders.cancel.refund_manual": "↩️ Refund {amount} {currency} to the customer manually (the payment is marked as “refunded”).",
        "admin.orders.cancel.yes": "✅ Yes, cancel",
        "admin.orders.cancel.no": "↩️ No",
        "admin.orders.done.payment_confirmed": "✅ Payment confirmed, the order is accepted. The customer has been notified.",
        "admin.orders.done.payment_rejected": "⚠️ Transfer not found: the order is back to “awaiting payment”. The customer has been notified.",
        "admin.orders.done.confirmed": "✅ Order confirmed. The customer has been notified.",
        "admin.orders.done.shipped": "🚚 Order marked as shipped. The customer has been notified.",
        "admin.orders.done.completed": "🏁 Order completed. The customer has been notified.",
        "admin.orders.done.cancelled": "❌ Order cancelled. The customer has been notified.",
        "admin.orders.err.not_found": "❌ Order not found",
        "admin.orders.err.not_mia": "❌ This is not an MIA order",
        "admin.orders.err.not_awaiting_payment": "❌ The order no longer waits for a payment check (another staff member may have handled it)",
        "admin.orders.err.invalid_transition": "❌ This status cannot be set right now",
        "admin.orders.err.payment_not_confirmed": "❌ Confirm the MIA payment first",
        "admin.orders.err.not_cancellable": "❌ This order can no longer be cancelled",
        "admin.orders.err.no_proof": "ℹ️ The customer did not send a screenshot",
        "admin.orders.err.proof_unavailable": "⚠️ Could not show the screenshot",

        # === Admin: catalog translations ===
        "admin.categories.add.prompt.translation": "Enter the category name in {language} or tap Skip (the main name will be shown instead):",
        "admin.goods.add.prompt.name_translation": "Enter the product name in {language} or tap Skip (the main name will be shown instead):",
        "admin.goods.add.prompt.description_translation": "Enter the product description in {language} or tap Skip (the main description will be shown instead):",
        "admin.translations.btn.skip": "⏭ Skip",
        "admin.translations.btn.open": "🌐 Translations",
        "admin.translations.btn.name": "Name",
        "admin.translations.btn.description": "Description",
        "admin.translations.btn.clear": "🗑 Clear",
        "admin.translations.invalid": "⚠️ Enter some text or tap Skip.",
        "admin.translations.too_long": "⚠️ Text is too long (maximum {max} characters). Please enter a shorter one.",
        "admin.translations.not_set": "— not set",
        "admin.translations.main": "main",
        "admin.translations.field.name": "Name",
        "admin.translations.field.description": "Description",
        "admin.translations.card.title.category": "🌐 Translations of category <b>{name}</b>",
        "admin.translations.card.title.item": "🌐 Translations of product <b>{name}</b>",
        "admin.translations.card.hint": "Pick a language and a field to change. Where no translation is set, the main text is shown.",
        "admin.translations.prompt.category": "Enter the name of the category whose translations you want to change:",
        "admin.translations.prompt.name": "✏️ <b>{name}</b>\nName in {language}\nCurrent: {current}\n\nSend the new text (up to {max} characters) or tap Clear.",
        "admin.translations.prompt.description": "✏️ <b>{name}</b>\nDescription in {language}\nCurrent: {current}\n\nSend the new text (up to {max} characters) or tap Clear.",
        "admin.translations.saved": "✅ Translation saved ({language}).",
        "admin.translations.cleared": "🗑 Translation removed ({language}): the main text will be shown.",
        "admin.translations.err.category_not_found": "❌ Category not found",
        "admin.categories.add.prompt.parent": "Enter the parent category (its name in any language) to create a subcategory, or tap Skip to create a top-level category:",
        "admin.categories.add.parent.not_found": "❌ Parent category not found. Enter the name of an existing category or tap Skip.",
        "admin.categories.add.parent.not_top_level": "❌ A subcategory cannot be a parent: only two levels are allowed. Choose a top-level category.",
        "admin.categories.add.parent.has_items": "❌ This category already has products, so it cannot get subcategories. Move its products first.",
        "admin.categories.delete.has_subcategories": "❌ This category has subcategories. Delete or move them first.",
        "admin.goods.add.category.has_subcategories": "❌ This category has subcategories. Choose one of its subcategories.",
        "admin.goods.update.category.has_subcategories": "❌ This category has subcategories. Choose one of its subcategories.",
        "admin.translations.card.parent": "Parent: {name}",
        "admin.translations.err.item_not_found": "❌ Product not found",
        "admin.translations.err.invalid_language": "❌ Unsupported language",
        "admin.translations.err.invalid_field": "❌ Unsupported field",
        "admin.translations.err.too_long": "⚠️ Text is too long (maximum {max} characters).",
    },
}
