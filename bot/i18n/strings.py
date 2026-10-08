DEFAULT_LOCALE = "ru"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        # === Common Buttons ===
        "btn.shop": "🏪 Магазин",
        "btn.search": "🔍 Поиск по каталогу",
        "btn.rules": "📜 Правила",
        "btn.profile": "👤 Профиль",
        "btn.support": "🆘 Поддержка",
        "btn.channel": "ℹ Новостной канал",
        "btn.admin_menu": "🎛 Панель администратора",
        "btn.back": "⬅️ Назад",
        "btn.to_menu": "🏠 В меню",
        "btn.close": "✖ Закрыть",
        "btn.yes": "✅ Да",
        "btn.no": "❌ Нет",
        "btn.check": "🔄 Проверить",
        "btn.check_subscription": "🔄 Проверить подписку",

        # === Admin Buttons (user management shortcuts) ===
        "btn.admin.view_profile": "👁 Посмотреть профиль",
        "btn.admin.promote": "⬆️ Назначить администратором",
        "btn.admin.demote": "⬇️ Снять администратора",
        "btn.admin.replenish_user": "💸 Пополнить баланс",
        "btn.admin.deduct_user": "💳 Списать с баланса",
        "btn.admin.block": "🚫 Заблокировать",
        "btn.admin.unblock": "✅ Разблокировать",

        # === Titles / Generic Texts ===
        "menu.title": "⛩️ Основное меню",
        "menu.welcome": "Добро пожаловать в UMBRA",
        "profile.caption": "👤 <b>Профиль</b> — <a href='tg://user?id={id}'>{name}</a>",
        "rules.not_set": "❌ Правила не были добавлены",

        # === Subscription Flow ===
        "subscribe.prompt": "Для начала подпишитесь на новостной канал",
        "subscribe.open_channel": "Открыть канал",

        # === Profile ===
        "profile.referral_id": "👤 <b>Реферал</b> — <code>{id}</code>",
        "btn.referral": "🎲 Реферальная система",

        # === Profile Info Lines ===
        "profile.id": "🆔 <b>ID</b> — <code>{id}</code>",
        "profile.balance": "💳 <b>Баланс</b> — <code>{amount}</code> {currency}",
        "profile.total_topup": "💵 <b>Всего пополнено</b> — <code>{amount}</code> {currency}",
        "profile.registration_date": "🕢 <b>Дата регистрации</b> — <code>{dt}</code>",

        # === Referral ===
        "referral.title": "💚 Реферальная система",
        "referral.link": "🔗 Ссылка: https://t.me/{bot_username}?start={user_id}",
        "referral.count": "Количество рефералов: {count}",
        "referral.description": (
            "📔 Реферальная система позволит Вам заработать деньги без всяких вложений. "
            "Необходимо всего лишь распространять свою реферальную ссылку и Вы будете получать "
            "{percent}% от суммы выполненных заказов Ваших рефералов на Ваш баланс в магазине."
        ),
        "btn.view_referrals": "👥 Мои рефералы",
        "btn.view_earnings": "💰 Мои поступления",
        "btn.back_to_referral": "⬅️ К реферальной системе",

        "referrals.list.title": "👥 Ваши рефералы:",
        "referrals.list.empty": "У вас пока нет активных рефералов",
        "referrals.item.format": "ID: {telegram_id} | Принёс: {total_earned} {currency}",

        "referral.earnings.title": "💰 Поступления от реферала <code>{telegram_id}</code> (<a href='tg://user?id={telegram_id}'>{name}</a>):",
        "referral.earnings.empty": "От данного реферала <code>{id}</code> (<a href='tg://user?id={id}'>{name}</a>) пока не было поступлений",
        "referral.earning.format": "{amount} {currency} | {date} | (с {original_amount} {currency})",
        "referral.item.info": ("💰 Поступление номер: <code>{id}</code>\n"
                               "👤 Реферал: <code>{telegram_id}</code> (<a href='tg://user?id={telegram_id}'>{name}</a>)\n"
                               "🔢 Количество: {amount} {currency}\n"
                               "🕘 Дата: <code>{date}</code>\n"
                               "💵 С заказа на {original_amount} {currency}"),

        "all.earnings.title": "💰 Все ваши реферальные поступления:",
        "all.earnings.empty": "У вас пока нет реферальных поступлений",
        "all.earning.format": "{amount} {currency} от ID:{referral_id} | {date}",

        "referrals.stats.template": (
            "📊 Статистика реферальной системы:\n\n"
            "👥 Активных рефералов: {active_count}\n"
            "💰 Всего заработано: {total_earned} {currency}\n"
            "📈 Общая сумма заказов рефералов: {total_original} {currency}\n"
            "🔢 Количество начислений: {earnings_count}"
        ),

        # === Admin: Main Menu ===
        "admin.menu.main": "⛩️ Меню администратора",
        "admin.menu.shop": "🛒 Управление магазином",
        "admin.menu.goods": "📦 Управление позициями",
        "admin.menu.categories": "📂 Управление категориями",
        "admin.menu.users": "👥 Управление пользователями",
        "admin.menu.broadcast": "📝 Рассылка",
        "admin.menu.roles": "🛡 Управление ролями",
        "admin.menu.rights": "Недостаточно прав",

        # === Admin: Role Management ===
        "admin.roles.list_title": "🛡 Роли системы:",
        "admin.roles.create": "➕ Создать роль",
        "admin.roles.edit": "✏️ Редактировать",
        "admin.roles.delete": "🗑 Удалить",
        "admin.roles.detail": "🛡 <b>Роль</b>: {name}\n📋 Права: {perms}\n👥 Пользователей: {users}",
        "admin.roles.prompt_name": "Введите название роли (макс. 64 символа):",
        "admin.roles.name_invalid": "⚠️ Некорректное название (пустое или длиннее 64 символов).",
        "admin.roles.name_exists": "❌ Роль с таким именем уже существует",
        "admin.roles.select_perms": "Выберите права для роли «{name}»:",
        "admin.roles.confirm": "✅ Подтвердить",
        "admin.roles.created": "✅ Роль «{name}» создана",
        "admin.roles.updated": "✅ Роль «{name}» обновлена",
        "admin.roles.deleted": "✅ Роль удалена",
        "admin.roles.delete_confirm": "Вы уверены, что хотите удалить роль «{name}»?",
        "admin.roles.delete_fail": "❌ Не удалось удалить: {error}",
        "admin.roles.perm_denied": "⚠️ Недостаточно прав для этого действия",
        "admin.roles.assign_prompt": "Выберите роль для пользователя {id}:",
        "admin.roles.assigned": "✅ Роль {role} назначена пользователю {name}",
        "admin.roles.assigned_notify": "ℹ️ Вам назначена роль: {role}",
        "admin.roles.edit_name_prompt": "Введите новое название роли (или /skip чтобы оставить текущее):",
        "btn.admin.assign_role": "🛡 Назначить роль",

        # === Admin: User Management ===
        "admin.users.prompt_enter_id": "👤 Введите id пользователя,\nчтобы посмотреть | изменить его данные",
        "admin.users.invalid_id": "⚠️ Введите корректный числовой ID пользователя.",
        "admin.users.profile_unavailable": "❌ Профиль недоступен (такого пользователя никогда не существовало)",
        "admin.users.not_found": "❌ Пользователь не найден",
        "admin.users.cannot_change_owner": "Нельзя менять роль владельца",
        "admin.users.referrals": "👥 <b>Рефералы пользователя</b> — {count}",
        "admin.users.btn.view_referrals": "👥 Рефералы пользователя",
        "admin.users.btn.view_earnings": "💰 Поступления",
        "admin.users.role": "🎛 <b>Роль</b> — {role}",
        "admin.users.set_admin.success": "✅ Роль присвоена пользователю {name}",
        "admin.users.set_admin.notify": "✅ Вам присвоена роль АДМИНИСТРАТОРА бота",
        "admin.users.remove_admin.success": "✅ Роль отозвана у пользователя {name}",
        "admin.users.remove_admin.notify": "❌ У вас отозвана роль АДМИНИСТРАТОРА бота",
        "admin.users.balance.topped": "✅ Баланс пользователя {name} пополнен на {amount} {currency}",
        "admin.users.balance.topped.notify": "✅ Ваш баланс пополнен на {amount} {currency}",
        "admin.users.balance.deducted": "✅ С баланса пользователя {name} списано {amount} {currency}",
        "admin.users.balance.deducted.notify": "ℹ️ С вашего баланса списано {amount} {currency}",
        "admin.users.balance.insufficient": "❌ Недостаточно средств. Текущий баланс: {balance} {currency}",
        "admin.users.blocked.success": "🚫 Пользователь {name} заблокирован",
        "admin.users.unblocked.success": "✅ Пользователь {name} разблокирован",
        "admin.users.cannot_block_owner": "❌ Невозможно заблокировать владельца",
        "admin.users.status.blocked": "🚫 <b>Статус</b> — Заблокирован",

        # === Admin: Shop Management Menu ===
        "admin.shop.menu.title": "⛩️ Меню управления магазином",
        "admin.shop.menu.statistics": "📊 Статистика",
        "admin.shop.menu.logs": "📁 Показать логи",
        "admin.shop.menu.users": "👤 Пользователи",

        # === Admin: Categories Management ===
        "admin.categories.menu.title": "⛩️ Меню управления категориями",
        "admin.categories.add": "➕ Добавить категорию",
        "admin.categories.rename": "✏️ Переименовать категорию",
        "admin.categories.delete": "🗑 Удалить категорию",
        "admin.categories.prompt.add": "Введите название новой категории:",
        "admin.categories.prompt.delete": "Введите название категории для удаления:",
        "admin.categories.prompt.rename.old": "Введите текущее название категории, которую нужно переименовать:",
        "admin.categories.prompt.rename.new": "Введите новое имя для категории:",
        "admin.categories.add.exist": "❌ Категория не создана (такая уже существует)",
        "admin.categories.add.success": "✅ Категория создана",
        "admin.categories.delete.not_found": "❌ Категория не удалена (такой категории не существует)",
        "admin.categories.delete.success": "✅ Категория удалена",
        "admin.categories.rename.not_found": "❌ Категория не может быть обновлена (такой категории не существует)",
        "admin.categories.rename.exist": "❌ Переименование невозможно (категория с таким именем уже существует)",
        "admin.categories.rename.success": "✅ Категория \"{old}\" переименована в \"{new}\"",

        # === Admin: Time-limited sales ===
        "admin.goods.sale_manage": "🔥 Управление скидкой",
        "admin.sale.prompt.name": "Введите название позиции, для которой хотите настроить скидку:",
        "admin.sale.not_found": "❌ Позиция с таким названием не найдена.",
        "admin.sale.current.active": "ℹ️ Текущая скидка: <b>{percent}%</b> до <b>{until}</b> (UTC).",
        "admin.sale.current.none": "ℹ️ Сейчас на этой позиции скидки нет.",
        "admin.sale.prompt.percent": "Введите процент скидки (1–100).\nОтправьте <b>0</b>, чтобы убрать скидку.",
        "admin.sale.percent.invalid": "⚠️ Некорректный процент. Введите целое число от 0 до 100.",
        "admin.sale.disabled": "✅ Скидка для позиции «{name}» отключена.",
        "admin.sale.prompt.days": "На сколько дней установить скидку? Введите целое число (например, 3).",
        "admin.sale.days.invalid": "⚠️ Некорректный срок. Введите целое число дней больше 0.",
        "admin.sale.success": "✅ Скидка <b>{percent}%</b> установлена для «{name}» до <b>{until}</b> (UTC).",

        # === Admin: Logs ===
        "admin.shop.logs.caption": "Логи бота",
        "admin.shop.logs.empty": "❗️ Логов пока нет",
        "admin.shop.logs.too_large": "⚠️ Логи слишком велики для отправки ({files}) — забирайте их с диска.",

        # === Admin: Statistics ===
        "admin.shop.stats.roles_header": "\n➖➖➖➖➖➖➖➖➖➖➖➖➖\n◽<b>РОЛИ</b>",

        # === Admin: Lists & Broadcast ===
        "admin.shop.users.title": "Пользователи бота:",
        "broadcast.prompt": "Отправьте сообщение для рассылки:",
        "broadcast.creating": "📤 Начинаем рассылку...\n👥 Всего пользователей: {ids}",
        "broadcast.progress": (
            "📤 Рассылка в процессе...\n\n"
            "📊 Прогресс: {progress:.1f}%\n"
            "✅ Отправлено: {sent}/{total}\n"
            "❌ Ошибок: {failed}\n"
            "⏱ Прошло времени: {time} сек"),
        "broadcast.done": (
            "✅ Рассылка завершена!\n\n"
            "📊 Статистика:\n"
            "👥 Всего: {total}\n"
            "✅ Доставлено: {sent}\n"
            "❌ Не доставлено: {failed}\n"
            "🚫 Заблокировали бота: {blocked}\n"
            "📈 Успешность: {success}%\n"
            "⏱ Время: {duration} сек"
        ),
        "broadcast.cancel": "❌ Рассылка отменена",
        "broadcast.warning": "Нет активной рассылки",
        "broadcast.already_running": "⏳ Рассылка уже выполняется. Дождитесь её завершения.",
        "broadcast.btn.cancel": "🛑 Отменить рассылку",

        # === Payments / Top-up Flow ===
        "payments.replenish_prompt": "Введите сумму пополнения в {currency}:",
        "payments.replenish_invalid": "❌ Неверная сумма. Введите число от {min_amount} до {max_amount} {currency}.",
        "payments.deduct_prompt": "Введите сумму списания в {currency}:",
        "payments.deduct_invalid": "❌ Неверная сумма. Введите число от {min_amount} до {max_amount} {currency}.",

        # === Shop Browsing (Categories / Goods / Item Page) ===
        "shop.categories.title": "🏪 Категории магазина",
        "shop.goods.choose": "🏪 Выберите нужный товар",
        "shop.search.prompt": "🔍 Напишите, что ищете, словами: название, вкус, крепость, объём… Например: «вишня 50 мг».\nНайдутся товары, где есть все слова.",
        "shop.search.too_short": "Запрос должен быть от 2 до 64 символов. Попробуйте ещё раз:",
        "shop.search.results": "🔍 Результаты по запросу «{query}» — найдено: {count}",
        "shop.search.empty": "🔍 По запросу «{query}» ничего не найдено.",
        "shop.item.not_found": "Товар не найден",
        "shop.item.title": "🏪 Товар {name}",
        "shop.item.description": "Описание: {description}",
        "shop.item.price": "Цена — {amount} {currency}",

        # === Purchases ===

        # === Middleware ===
        "middleware.ban": "⏳ Вы временно заблокированы. Подождите {time} секунд",
        "middleware.above_limits": "⚠️ Слишком много запросов! Вы временно заблокированы.",
        "middleware.waiting": "⏳ Подождите {time} секунд перед следующим действием.",
        "middleware.security.session_outdated": "⚠️ Сессия устарела. Пожалуйста, начните заново.",
        "middleware.security.invalid_data": "❌ Недопустимые данные",
        "middleware.security.blocked": "❌ Доступ заблокирован",
        "middleware.security.not_admin": "⛔ Недостаточно прав",
        "middleware.security.invalid_csrf": "⚠️ Сессия устарела. Пожалуйста, попробуйте снова.",
        "maintenance.active": "🔧 Бот находится на техническом обслуживании. Пожалуйста, попробуйте позже.",

        # === Admin: Maintenance ===
        "admin.menu.maintenance_on": "🔧 Тех. работы: ВКЛ",
        "admin.menu.maintenance_off": "🔧 Тех. работы: ВЫКЛ",
        "admin.maintenance.enabled": "✅ Режим тех. работ включён",
        "admin.maintenance.disabled": "✅ Режим тех. работ выключён",

        # === Promo Codes ===
        "admin.menu.promo": "🏷 Промокоды",
        "admin.promo.title": "🏷 <b>Управление промокодами</b>",
        "admin.promo.create": "➕ Создать промокод",
        "admin.promo.list_empty": "Промокодов пока нет.",
        "admin.promo.prompt.code": "Введите код промокода (до 50 символов):",
        "admin.promo.prompt.type": "Выберите тип скидки:",
        "admin.promo.type.percent": "📊 Процент (%)",
        "admin.promo.type.fixed": "💰 Фиксированная сумма",
        "admin.promo.prompt.value": "Введите размер скидки ({type}):",
        "admin.promo.prompt.max_uses": "Введите макс. число использований (0 = без лимита):",
        "admin.promo.prompt.expires": "Введите последний день действия (ГГГГ-ММ-ДД) — код работает до конца этого дня, или 0 — бессрочно:",
        "admin.promo.prompt.binding": "Привязать к категории/товару?\n\nОтправьте:\n• Название категории\n• Название товара\n• 0 — без привязки",
        "admin.promo.created": "✅ Промокод <code>{code}</code> создан!",
        "admin.promo.code_exists": "❌ Промокод с таким кодом уже существует.",
        "admin.promo.invalid_code": "❌ Код может содержать только буквы, цифры и дефис (до 50 символов).",
        "admin.promo.deleted": "✅ Промокод удалён.",
        "admin.promo.toggled_on": "✅ Промокод активирован.",
        "admin.promo.toggled_off": "⛔ Промокод деактивирован.",
        "admin.promo.btn.activate": "✅ Активировать",
        "admin.promo.btn.deactivate": "⛔ Деактивировать",
        "admin.promo.btn.delete": "🗑 Удалить",
        "admin.promo.detail": "🏷 <b>Промокод</b>: <code>{code}</code>\n📊 Тип: {discount_type}\n💰 Скидка: {discount_value}\n🔗 Применим к: {binding}\n🔢 Использований: {current_uses}/{max_uses}\n📅 Истекает: {expires_at}\n✅ Активен: {is_active}",
        "admin.promo.confirm_delete": "Удалить промокод <code>{code}</code>?",
        "admin.promo.invalid_value": "❌ Некорректное значение. Попробуйте ещё раз.",
        "admin.promo.invalid_date": "❌ Некорректная дата. Формат: ГГГГ-ММ-ДД",
        "promo.not_found": "❌ Промокод не найден.",
        "promo.inactive": "❌ Промокод неактивен.",
        "promo.expired": "❌ Промокод истёк.",
        "promo.max_uses_reached": "❌ Промокод исчерпан.",
        "promo.already_used": "❌ Вы уже использовали этот промокод.",
        "promo.wrong_item": "❌ Промокод не применим к этому товару.",
        "promo.wrong_category": "❌ Промокод не применим к этой категории.",
        "promo.applied": "✅ Промокод <code>{code}</code> применён! Скидка: {discount}",
        "promo.enter_code": "Введите промокод:",
        "promo.removed": "Промокод убран.",
        "promo.not_balance_type": "❌ Этот промокод не начисляет баланс.",
        "promo.enter_redeem_code": "Введите промокод для активации:",
        "promo.balance_redeemed": "✅ Промокод <code>{code}</code> активирован! На баланс начислено {amount} {currency}.",
        "shop.item.price_sale": "🔥 <b>Цена</b>: <s>{original}</s> <b>{sale}</b> {currency} (скидка {percent}%)",
        "admin.promo.type.balance": "💰 Пополнение баланса",
        "admin.promo.prompt.binding_type": "Привязать промокод к категории или товару?",
        "admin.promo.binding.category": "Категория",
        "admin.promo.binding.item": "Товар",
        "admin.promo.binding.none": "Без привязки",
        "admin.promo.binding.on_category": "категория «{name}»",
        "admin.promo.binding.on_item": "товар «{name}»",
        "admin.promo.binding.dangling": "⚠️ привязка удалена — промокод ни к чему не применяется",
        "admin.promo.prompt.category_name": "Введите название категории:",
        "admin.promo.prompt.item_name": "Введите название товара:",
        "admin.promo.category_not_found": "❌ Категория не найдена.",
        "admin.promo.item_not_found": "❌ Товар не найден.",
        "btn.redeem_promo": "🏷 Активировать промокод",
        "review.disabled": "Отзывы отключены.",

        # === Cart ===
        "btn.cart": "🛒 Корзина ({count})",
        "btn.cart_empty": "🛒 Корзина",
        "btn.add_to_cart": "🛒 В корзину",
        "btn.cart_checkout": "💳 Оформить заказ",
        "btn.cart_clear": "🗑 Очистить корзину",
        "btn.cart_remove_item": "❌ {name}",
        "btn.cart_remove_promo": "🏷 Убрать промокод {code}",
        "cart.title": "🛒 <b>Корзина</b>",
        "cart.empty": "Корзина пуста.",
        "cart.item": "• {name} ×{qty} — {price} {currency}",
        "cart.item_sale": "🔥 <b>{name}</b> ×{qty} — <s>{original}</s> {price} {currency}",
        "cart.item_promo": "🏷 <b>{name}</b> ×{qty} — <s>{original}</s> {price} {currency} ({code})",
        "cart.item_promo_invalid": "⚠️ <b>{name}</b> ×{qty} — {price} {currency}\n    промокод {code} к этому товару не применяется",
        "cart.item_promo_elsewhere": "• {name} ×{qty} — {price} {currency}\n    промокод {code} учтён в другой позиции",
        "cart.total": "\n💰 <b>Итого</b>: {total} {currency}",
        "cart.added": "✅ {name} добавлен в корзину.",
        "cart.full": "❌ Корзина переполнена (макс. 10 товаров).",
        "cart.qty_max": "❌ Максимум {max} шт. одного товара.",
        "cart.price_changed": "Цена в корзине изменилась. Откройте корзину и подтвердите новую сумму.",
        "cart.item_not_found": "❌ Товар не найден.",
        "cart.removed": "✅ Товар убран из корзины.",
        "cart.cleared": "✅ Корзина очищена.",
        "cart.items_unavailable": "Некоторые товары более недоступны и были убраны из корзины.",


        # === Stock Subscriptions ===
        "btn.notify_stock": "🔔 Сообщить о поступлении",
        "btn.notify_stock_off": "🔕 Не сообщать",
        "stock.subscribed": "🔔 Сообщим, когда товар появится.",
        "stock.unsubscribed": "🔕 Уведомление отменено.",
        "stock.back_in_stock": "🔔 Товар <b>{name}</b> снова в наличии!",


        # === Operation History ===

        # === Reviews ===
        "btn.leave_review": "⭐ Оставить отзыв",
        "btn.view_reviews": "📝 Отзывы ({count})",
        "btn.skip_review_text": "⏭ Пропустить текст",
        "review.prompt_rating": "Оцените товар <b>{name}</b> от 1 до 5:",
        "review.prompt_text": "Напишите текст отзыва (до 500 символов) или нажмите «Пропустить»:",
        "review.created": "✅ Спасибо за отзыв!",
        "review.already_exists": "Вы уже оставили отзыв на этот товар.",
        "review.not_purchased": "Вы не покупали этот товар.",
        "review.avg_rating": "⭐ Рейтинг: {rating}/5 ({count} отзывов)",
        "review.item": "⭐ {rating}/5 — {text}",
        "review.item_no_text": "⭐ {rating}/5",
        "review.list_title": "📝 <b>Отзывы на {name}</b>",
        "review.list_empty": "Отзывов пока нет.",

        # === Errors ===
        "errors.not_subscribed": "Вы не подписались",
        "errors.something_wrong": "❌ Что-то пошло не так. Попробуйте ещё раз.",
        "errors.pagination_invalid": "Некорректные данные пагинации",
        "errors.invalid_data": "❌ Неправильные данные",
        "errors.id_should_be_number": "❌ ID должен быть числом.",
        "errors.channel.telegram_not_found": "Я не могу писать в канал. Добавьте меня админом канала для заливов @{channel} с правом публиковать сообщения.",
        "errors.channel.telegram_forbidden_error": "Канал не найден. Проверьте username канала для заливов @{channel}.",
        "errors.channel.telegram_bad_request": "Не удалось отправить в канал для заливов: {e}",
        "errors.general_error": "❌ Ошибка: {e}",
        "errors.invalid_item_name": "❌ Некорректное название товара",
        "errors.invalid_user": "❌ Некорректный пользователь",
    },

    "en": {
        # === Common Buttons ===
        "btn.shop": "🏪 Shop",
        "btn.search": "🔍 Search catalog",
        "btn.rules": "📜 Rules",
        "btn.profile": "👤 Profile",
        "btn.support": "🆘 Support",
        "btn.channel": "ℹ News channel",
        "btn.admin_menu": "🎛 Admin panel",
        "btn.back": "⬅️ Back",
        "btn.to_menu": "🏠 Menu",
        "btn.close": "✖ Close",
        "btn.yes": "✅ Yes",
        "btn.no": "❌ No",
        "btn.check": "🔄 Check",
        "btn.check_subscription": "🔄 Check subscription",

        # === Admin Buttons (user management shortcuts) ===
        "btn.admin.view_profile": "👁 View profile",
        "btn.admin.promote": "⬆️ Make admin",
        "btn.admin.demote": "⬇️ Remove admin",
        "btn.admin.replenish_user": "💸 Top up balance",
        "btn.admin.deduct_user": "💳 Deduct from balance",
        "btn.admin.block": "🚫 Block",
        "btn.admin.unblock": "✅ Unblock",

        # === Titles / Generic Texts ===
        "menu.title": "⛩️ Main menu",
        "menu.welcome": "Welcome to UMBRA",
        "profile.caption": "👤 <b>Profile</b> — <a href='tg://user?id={id}'>{name}</a>",
        "rules.not_set": "❌ Rules have not been added",

        # === Profile ===
        "btn.referral": "🎲 Referral system",
        "profile.referral_id": "👤 <b>Referral</b> — <code>{id}</code>",

        # === Subscription Flow ===
        "subscribe.prompt": "First, subscribe to the news channel",
        "subscribe.open_channel": "Open channel",

        # === Profile Info Lines ===
        "profile.id": "🆔 <b>ID</b> — <code>{id}</code>",
        "profile.balance": "💳 <b>Balance</b> — <code>{amount}</code> {currency}",
        "profile.total_topup": "💵 <b>Total topped up</b> — <code>{amount}</code> {currency}",
        "profile.registration_date": "🕢 <b>Registered at</b> — <code>{dt}</code>",

        # === Referral ===
        "referral.title": "💚 Referral system",
        "referral.link": "🔗 Link: https://t.me/{bot_username}?start={user_id}",
        "referral.count": "Referrals count: {count}",
        "referral.description": (
            "📔 The referral system lets you earn without any investment. "
            "Share your personal link and you will receive {percent}% of your referrals’ "
            "completed orders, credited to your store balance."
        ),
        "btn.view_referrals": "👥 My referrals",
        "btn.view_earnings": "💰 My earnings",
        "btn.back_to_referral": "⬅️ Back to referral system",

        "referrals.list.title": "👥 Your referrals:",
        "referrals.list.empty": "You don't have any active referrals yet",
        "referrals.item.format": "ID: {telegram_id} | Earned: {total_earned} {currency}",

        "referral.earnings.title": "💰 Earnings from referral <code>{telegram_id}</code> (<a href='tg://user?id={telegram_id}'>{name}</a>):",
        "referral.earnings.empty": "No earnings from this referral <code>{id}</code> (<a href='tg://user?id={id}'>{name}</a>) yet",
        "referral.earning.format": "{amount} {currency} | {date} | (from {original_amount} {currency})",
        "referral.item.info": ("💰 Earning number: <code>{id}</code>\n"
                               "👤 Referral: <code>{telegram_id}</code> (<a href='tg://user?id={telegram_id}'>{name}</a>)\n"
                               "🔢 Amount: {amount} {currency}\n"
                               "🕘 Date: <code>{date}</code>\n"
                               "💵 From an order of {original_amount} {currency}"),

        "all.earnings.title": "💰 All your referral earnings:",
        "all.earnings.empty": "You have no referral earnings yet",
        "all.earning.format": "{amount} {currency} from ID:{referral_id} | {date}",

        "referrals.stats.template": (
            "📊 Referral system statistics:\n\n"
            "👥 Active referrals: {active_count}\n"
            "💰 Total earned: {total_earned} {currency}\n"
            "📈 Total referral orders: {total_original} {currency}\n"
            "🔢 Number of earnings: {earnings_count}"
        ),

        # === Admin: Main Menu ===
        "admin.menu.main": "⛩️ Admin Menu",
        "admin.menu.shop": "🛒 Shop management",
        "admin.menu.goods": "📦 Items management",
        "admin.menu.categories": "📂 Categories management",
        "admin.menu.users": "👥 Users management",
        "admin.menu.broadcast": "📝 Broadcast",
        "admin.menu.roles": "🛡 Role management",
        "admin.menu.rights": "Insufficient permissions",

        # === Admin: Role Management ===
        "admin.roles.list_title": "🛡 System roles:",
        "admin.roles.create": "➕ Create role",
        "admin.roles.edit": "✏️ Edit",
        "admin.roles.delete": "🗑 Delete",
        "admin.roles.detail": "🛡 <b>Role</b>: {name}\n📋 Permissions: {perms}\n👥 Users: {users}",
        "admin.roles.prompt_name": "Enter the role name (max 64 characters):",
        "admin.roles.name_invalid": "⚠️ Invalid name (empty or exceeds 64 characters).",
        "admin.roles.name_exists": "❌ A role with this name already exists",
        "admin.roles.select_perms": "Select permissions for role \"{name}\":",
        "admin.roles.confirm": "✅ Confirm",
        "admin.roles.created": "✅ Role \"{name}\" created",
        "admin.roles.updated": "✅ Role \"{name}\" updated",
        "admin.roles.deleted": "✅ Role deleted",
        "admin.roles.delete_confirm": "Are you sure you want to delete the role \"{name}\"?",
        "admin.roles.delete_fail": "❌ Failed to delete: {error}",
        "admin.roles.perm_denied": "⚠️ Insufficient permissions for this action",
        "admin.roles.assign_prompt": "Select a role for user {id}:",
        "admin.roles.assigned": "✅ Role {role} assigned to {name}",
        "admin.roles.assigned_notify": "ℹ️ Your role has been set to: {role}",
        "admin.roles.edit_name_prompt": "Enter the new role name (or /skip to keep current):",
        "btn.admin.assign_role": "🛡 Assign role",

        # === Admin: User Management ===
        "admin.users.prompt_enter_id": "👤 Enter the user ID to view / edit data",
        "admin.users.invalid_id": "⚠️ Please enter a valid numeric user ID.",
        "admin.users.profile_unavailable": "❌ Profile unavailable (such user never existed)",
        "admin.users.not_found": "❌ User not found",
        "admin.users.cannot_change_owner": "You cannot change the owner’s role",
        "admin.users.referrals": "👥 <b>User referrals</b> — {count}",
        "admin.users.btn.view_referrals": "👥 User's referrals",
        "admin.users.btn.view_earnings": "💰 User's earnings",
        "admin.users.role": "🎛 <b>Role</b> — {role}",
        "admin.users.set_admin.success": "✅ Role assigned to {name}",
        "admin.users.set_admin.notify": "✅ You have been granted the ADMIN role",
        "admin.users.remove_admin.success": "✅ Admin role revoked from {name}",
        "admin.users.remove_admin.notify": "❌ Your ADMIN role has been revoked",
        "admin.users.balance.topped": "✅ {name}'s balance has been topped up by {amount} {currency}",
        "admin.users.balance.topped.notify": "✅ Your balance has been topped up by {amount} {currency}",
        "admin.users.balance.deducted": "✅ Deducted {amount} {currency} from {name}'s balance",
        "admin.users.balance.deducted.notify": "ℹ️ {amount} {currency} has been deducted from your balance",
        "admin.users.balance.insufficient": "❌ Insufficient funds. Current balance: {balance} {currency}",
        "admin.users.blocked.success": "🚫 User {name} has been blocked",
        "admin.users.unblocked.success": "✅ User {name} has been unblocked",
        "admin.users.cannot_block_owner": "❌ Cannot block the owner",
        "admin.users.status.blocked": "🚫 <b>Status</b> — Blocked",

        # === Admin: Shop Management Menu ===
        "admin.shop.menu.title": "⛩️ Shop management",
        "admin.shop.menu.statistics": "📊 Statistics",
        "admin.shop.menu.logs": "📁 Show logs",
        "admin.shop.menu.users": "👤 Users",

        # === Admin: Categories Management ===
        "admin.categories.menu.title": "⛩️ Categories management",
        "admin.categories.add": "➕ Add category",
        "admin.categories.rename": "✏️ Rename category",
        "admin.categories.delete": "🗑 Delete category",
        "admin.categories.prompt.add": "Enter a new category name:",
        "admin.categories.prompt.delete": "Enter the category name to delete:",
        "admin.categories.prompt.rename.old": "Enter the current category name to rename:",
        "admin.categories.prompt.rename.new": "Enter the new category name:",
        "admin.categories.add.exist": "❌ Category not created (already exists)",
        "admin.categories.add.success": "✅ Category created",
        "admin.categories.delete.not_found": "❌ Category not deleted (does not exist)",
        "admin.categories.delete.success": "✅ Category deleted",
        "admin.categories.rename.not_found": "❌ Category cannot be updated (does not exist)",
        "admin.categories.rename.exist": "❌ Cannot rename (a category with this name already exists)",
        "admin.categories.rename.success": "✅ Category \"{old}\" renamed to \"{new}\"",

        # === Admin: Time-limited sales ===
        "admin.goods.sale_manage": "🔥 Manage discount",
        "admin.sale.prompt.name": "Enter the item name you want to set a discount for:",
        "admin.sale.not_found": "❌ No item with that name was found.",
        "admin.sale.current.active": "ℹ️ Current discount: <b>{percent}%</b> until <b>{until}</b> (UTC).",
        "admin.sale.current.none": "ℹ️ This item currently has no discount.",
        "admin.sale.prompt.percent": "Enter the discount percent (1–100).\nSend <b>0</b> to remove the discount.",
        "admin.sale.percent.invalid": "⚠️ Invalid percent. Enter an integer from 0 to 100.",
        "admin.sale.disabled": "✅ Discount for «{name}» has been removed.",
        "admin.sale.prompt.days": "For how many days should the discount last? Enter an integer (e.g. 3).",
        "admin.sale.days.invalid": "⚠️ Invalid duration. Enter an integer number of days greater than 0.",
        "admin.sale.success": "✅ Discount <b>{percent}%</b> set for «{name}» until <b>{until}</b> (UTC).",

        # === Admin: Logs ===
        "admin.shop.logs.caption": "Bot logs",
        "admin.shop.logs.empty": "❗️ No logs yet",
        "admin.shop.logs.too_large": "⚠️ Logs are too large to send ({files}) — grab them from disk.",

        # === Admin: Statistics ===
        "admin.shop.stats.roles_header": "\n➖➖➖➖➖➖➖➖➖➖➖➖➖\n◽<b>ROLES</b>",

        # === Admin: Lists & Broadcast ===
        "admin.shop.users.title": "Bot users:",
        "broadcast.prompt": "Send a message to broadcast:",
        "broadcast.creating": "📤 Starting the newsletter...\n👥 Total users: {ids}",
        "broadcast.progress": (
            "📤 Broadcasting in progress...\n\n"
            "📊 Progress: {progress:.1f}%\n"
            "✅ Sent: {sent}/{total}\n"
            "❌ Errors: {failed}\n"
            "⏱ Time elapsed: {time} sec"),
        "broadcast.done": (
            "✅ Broadcasting is complete! \n\n"
            "📊 Statistics:📊\n"
            "👥 Total: {total}\n"
            "✅ Delivered: {sent}\n"
            "❌ Undelivered: {failed}\n"
            "🚫 Blocked bot: {blocked}\n"
            "📈 Success rate: {success}%\n"
            "⏱ Time: {duration} sec"
        ),
        "broadcast.cancel": "❌ The broadcast has been canceled.",
        "broadcast.warning": "No active broadcast",
        "broadcast.already_running": "⏳ A broadcast is already running. Wait for it to finish.",
        "broadcast.btn.cancel": "🛑 Cancel broadcast",

        # === Payments / Top-up Flow ===
        "payments.replenish_prompt": "Enter top-up amount in {currency}:",
        "payments.replenish_invalid": "❌ Invalid amount. Enter a number from {min_amount} to {max_amount} {currency}.",
        "payments.deduct_prompt": "Enter deduction amount in {currency}:",
        "payments.deduct_invalid": "❌ Invalid amount. Enter a number from {min_amount} to {max_amount} {currency}.",

        # === Shop Browsing (Categories / Goods / Item Page) ===
        "shop.categories.title": "🏪 Shop categories",
        "shop.search.prompt": "🔍 Describe what you are looking for in words: name, flavour, strength, size… For example: “cherry 50 mg”.\nProducts that match all the words are shown.",
        "shop.search.too_short": "The query must be 2 to 64 characters. Try again:",
        "shop.search.results": "🔍 Results for “{query}” — found: {count}",
        "shop.search.empty": "🔍 Nothing found for “{query}”.",
        "shop.goods.choose": "🏪 Choose a product",
        "shop.item.not_found": "Item not found",
        "shop.item.title": "🏪 Item {name}",
        "shop.item.description": "Description: {description}",
        "shop.item.price": "Price — {amount} {currency}",

        # === Purchases ===

        # === Middleware ===
        "middleware.ban": "⏳ You are temporarily blocked. Wait {time} seconds.",
        "middleware.above_limits": "⚠️ Too many requests! You are temporarily blocked.",
        "middleware.waiting": "⏳ Wait {time} seconds for the next action.",
        "middleware.security.session_outdated": "⚠️ Session is outdated. Please start again.",
        "middleware.security.invalid_data": "❌ Invalid data",
        "middleware.security.blocked": "❌ Access blocked",
        "middleware.security.not_admin": "⛔ Insufficient permissions",
        "middleware.security.invalid_csrf": "⚠️ Session expired. Please try again.",
        "maintenance.active": "🔧 The bot is under maintenance. Please try again later.",

        # === Admin: Maintenance ===
        "admin.menu.maintenance_on": "🔧 Maintenance: ON",
        "admin.menu.maintenance_off": "🔧 Maintenance: OFF",
        "admin.maintenance.enabled": "✅ Maintenance mode enabled",
        "admin.maintenance.disabled": "✅ Maintenance mode disabled",

        # === Promo Codes ===
        "admin.menu.promo": "🏷 Promo Codes",
        "admin.promo.title": "🏷 <b>Promo Code Management</b>",
        "admin.promo.create": "➕ Create promo code",
        "admin.promo.list_empty": "No promo codes yet.",
        "admin.promo.prompt.code": "Enter promo code (up to 50 characters):",
        "admin.promo.prompt.type": "Choose discount type:",
        "admin.promo.type.percent": "📊 Percent (%)",
        "admin.promo.type.fixed": "💰 Fixed amount",
        "admin.promo.prompt.value": "Enter discount value ({type}):",
        "admin.promo.prompt.max_uses": "Enter max uses (0 = unlimited):",
        "admin.promo.prompt.expires": "Enter the last valid day (YYYY-MM-DD) — the code works through the end of that day, or 0 for no expiry:",
        "admin.promo.prompt.binding": "Bind to category/item?\n\nSend:\n• Category name\n• Item name\n• 0 — no binding",
        "admin.promo.created": "✅ Promo code <code>{code}</code> created!",
        "admin.promo.code_exists": "❌ Promo code already exists.",
        "admin.promo.invalid_code": "❌ A code may contain only letters, digits and hyphens (up to 50 characters).",
        "admin.promo.deleted": "✅ Promo code deleted.",
        "admin.promo.toggled_on": "✅ Promo code activated.",
        "admin.promo.toggled_off": "⛔ Promo code deactivated.",
        "admin.promo.btn.activate": "✅ Activate",
        "admin.promo.btn.deactivate": "⛔ Deactivate",
        "admin.promo.btn.delete": "🗑 Delete",
        "admin.promo.detail": "🏷 <b>Promo Code</b>: <code>{code}</code>\n📊 Type: {discount_type}\n💰 Discount: {discount_value}\n🔗 Applies to: {binding}\n🔢 Uses: {current_uses}/{max_uses}\n📅 Expires: {expires_at}\n✅ Active: {is_active}",
        "admin.promo.confirm_delete": "Delete promo code <code>{code}</code>?",
        "admin.promo.invalid_value": "❌ Invalid value. Try again.",
        "admin.promo.invalid_date": "❌ Invalid date. Format: YYYY-MM-DD",
        "promo.not_found": "❌ Promo code not found.",
        "promo.inactive": "❌ Promo code is inactive.",
        "promo.expired": "❌ Promo code has expired.",
        "promo.max_uses_reached": "❌ Promo code uses exhausted.",
        "promo.already_used": "❌ You already used this promo code.",
        "promo.wrong_item": "❌ Promo code is not applicable to this item.",
        "promo.wrong_category": "❌ Promo code is not applicable to this category.",
        "promo.applied": "✅ Promo code <code>{code}</code> applied! Discount: {discount}",
        "promo.enter_code": "Enter promo code:",
        "promo.removed": "Promo code removed.",
        "promo.not_balance_type": "❌ This promo code does not credit your balance.",
        "promo.enter_redeem_code": "Enter promo code to redeem:",
        "promo.balance_redeemed": "✅ Promo code <code>{code}</code> redeemed! {amount} {currency} added to your balance.",
        "shop.item.price_sale": "🔥 <b>Price</b>: <s>{original}</s> <b>{sale}</b> {currency} ({percent}% off)",
        "admin.promo.type.balance": "💰 Balance top-up",
        "admin.promo.prompt.binding_type": "Bind promo code to category or item?",
        "admin.promo.binding.category": "Category",
        "admin.promo.binding.item": "Item",
        "admin.promo.binding.none": "No binding",
        "admin.promo.binding.on_category": "category “{name}”",
        "admin.promo.binding.on_item": "item “{name}”",
        "admin.promo.binding.dangling": "⚠️ binding deleted — this promo applies to nothing",
        "admin.promo.prompt.category_name": "Enter category name:",
        "admin.promo.prompt.item_name": "Enter item name:",
        "admin.promo.category_not_found": "❌ Category not found.",
        "admin.promo.item_not_found": "❌ Item not found.",
        "btn.redeem_promo": "🏷 Redeem promo code",
        "review.disabled": "Reviews are disabled.",

        # === Cart ===
        "btn.cart": "🛒 Cart ({count})",
        "btn.cart_empty": "🛒 Cart",
        "btn.add_to_cart": "🛒 Add to cart",
        "btn.cart_checkout": "💳 Checkout",
        "btn.cart_clear": "🗑 Clear cart",
        "btn.cart_remove_item": "❌ {name}",
        "btn.cart_remove_promo": "🏷 Remove promo {code}",
        "cart.title": "🛒 <b>Cart</b>",
        "cart.empty": "Cart is empty.",
        "cart.item": "• {name} ×{qty} — {price} {currency}",
        "cart.item_sale": "🔥 <b>{name}</b> ×{qty} — <s>{original}</s> {price} {currency}",
        "cart.item_promo": "🏷 <b>{name}</b> ×{qty} — <s>{original}</s> {price} {currency} ({code})",
        "cart.item_promo_invalid": "⚠️ <b>{name}</b> ×{qty} — {price} {currency}\n    promo {code} does not apply to this item",
        "cart.item_promo_elsewhere": "• {name} ×{qty} — {price} {currency}\n    promo {code} was applied to another line",
        "cart.total": "\n💰 <b>Total</b>: {total} {currency}",
        "cart.added": "✅ {name} added to cart.",
        "cart.full": "❌ Cart is full (max 10 items).",
        "cart.qty_max": "❌ Maximum {max} units of one item.",
        "cart.price_changed": "The cart total changed. Open the cart and confirm the new amount.",
        "cart.item_not_found": "❌ Item not found.",
        "cart.removed": "✅ Item removed from cart.",
        "cart.cleared": "✅ Cart cleared.",
        "cart.items_unavailable": "Some items are no longer available and were removed from cart.",


        # === Stock Subscriptions ===
        "btn.notify_stock": "🔔 Notify me when in stock",
        "btn.notify_stock_off": "🔕 Cancel notification",
        "stock.subscribed": "🔔 We'll let you know when it's back.",
        "stock.unsubscribed": "🔕 Notification cancelled.",
        "stock.back_in_stock": "🔔 <b>{name}</b> is back in stock!",


        # === Operation History ===

        # === Reviews ===
        "btn.leave_review": "⭐ Leave a review",
        "btn.view_reviews": "📝 Reviews ({count})",
        "btn.skip_review_text": "⏭ Skip text",
        "review.prompt_rating": "Rate <b>{name}</b> from 1 to 5:",
        "review.prompt_text": "Write a review (up to 500 chars) or click Skip:",
        "review.created": "✅ Thank you for your review!",
        "review.already_exists": "You already reviewed this item.",
        "review.not_purchased": "You haven't purchased this item.",
        "review.avg_rating": "⭐ Rating: {rating}/5 ({count} reviews)",
        "review.item": "⭐ {rating}/5 — {text}",
        "review.item_no_text": "⭐ {rating}/5",
        "review.list_title": "📝 <b>Reviews for {name}</b>",
        "review.list_empty": "No reviews yet.",

        # === Errors ===
        "errors.not_subscribed": "You are not subscribed",
        "errors.something_wrong": "❌ Something went wrong. Please try again.",
        "errors.pagination_invalid": "Invalid pagination data",
        "errors.invalid_data": "❌ Invalid data",
        "errors.id_should_be_number": "❌ ID must be a number.",
        "errors.channel.telegram_not_found": "I can't write to the channel. Add me as a channel admin for uploads @{channel} with the right to publish messages.",
        "errors.channel.telegram_forbidden_error": "Channel not found. Check the channel username for uploads @{channel}.",
        "errors.channel.telegram_bad_request": "Failed to send to the channel for uploads: {e}",
        "errors.general_error": "❌ Error: {e}",
        "errors.invalid_item_name": "❌ Invalid item name",
        "errors.invalid_user": "❌ Invalid user",
    },
}


# Physical-goods strings live in their own modules (shared order texts, customer flow, admin
# flow) and are merged here, so `TRANSLATIONS` stays the single lookup table for `localize`.
# A module may define extra locales; keys missing from a locale fall back to DEFAULT_LOCALE.
def _merge_extra_translations() -> None:
    import importlib
    for module_name in (
        "strings_orders", "strings_customer", "strings_admin",
        "strings_ro_1", "strings_ro_2", "strings_ro_orders", "strings_ro_customer", "strings_ro_admin",
        "strings_web", "strings_ro_web",
    ):
        try:
            module = importlib.import_module(f"{__package__}.{module_name}")
        except ModuleNotFoundError as e:
            if e.name != f"{__package__}.{module_name}":
                raise
            continue
        for locale, entries in module.TRANSLATIONS.items():
            TRANSLATIONS.setdefault(locale, {}).update(entries)


_merge_extra_translations()
