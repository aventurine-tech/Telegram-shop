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
        "admin.goods.add.prompt.name": "Введите название товара",
        "admin.goods.add.name.exists": "❌ Товар не может быть создан (такой товар уже существует)",
        "admin.goods.add.name.invalid": "⚠️ Недопустимое название (1–100 символов, без управляющих символов).",
        "admin.goods.add.prompt.description": "Введите описание товара:",
        "admin.goods.add.prompt.price": "Введите цену товара (число в {currency}):",
        "admin.goods.add.price.invalid": "⚠️ Некорректное значение цены. Введите целое число.",
        "admin.goods.add.prompt.category": "Введите категорию, к которой относится товар:",
        "admin.goods.add.category.not_found": "❌ Товар не может быть создан (категория введена неверно)",
        "admin.goods.add.prompt.stock": "Сколько единиц товара сейчас на складе? Введите целое число (0 — нет в наличии):",
        "admin.goods.add.result.created": "✅ Товар «{name}» создан. На складе: <b>{qty}</b> шт.",
        "admin.goods.prompt.enter_item_name": "Введите название товара",
        "admin.goods.position.not_found": "❌ Такого товара не существует",
        "admin.goods.channel.arrival": "📦 Поступление на склад: <b>{name}</b>\nВ наличии: <b>{qty}</b> шт.",

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
        "admin.goods.add.prompt.name": "Enter the product name",
        "admin.goods.add.name.exists": "❌ Product cannot be created (it already exists)",
        "admin.goods.add.name.invalid": "⚠️ Invalid name (1–100 characters, no control characters).",
        "admin.goods.add.prompt.description": "Enter the product description:",
        "admin.goods.add.prompt.price": "Enter the product price (a number in {currency}):",
        "admin.goods.add.price.invalid": "⚠️ Invalid price. Please enter a whole number.",
        "admin.goods.add.prompt.category": "Enter the category the product belongs to:",
        "admin.goods.add.category.not_found": "❌ Product cannot be created (invalid category)",
        "admin.goods.add.prompt.stock": "How many units are in stock right now? Enter a whole number (0 means out of stock):",
        "admin.goods.add.result.created": "✅ Product “{name}” created. In stock: <b>{qty}</b> pcs.",
        "admin.goods.prompt.enter_item_name": "Enter the product name",
        "admin.goods.position.not_found": "❌ This product doesn't exist",
        "admin.goods.channel.arrival": "📦 New arrival: <b>{name}</b>\nIn stock: <b>{qty}</b> pcs.",

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
    },
}
