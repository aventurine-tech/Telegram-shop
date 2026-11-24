"""Help, settings, support, the pre-order terms and the privacy policy (Telegram's bot rules ask for all of them, D-25).

The terms and the policy are the shop's own texts: `{seller}` comes from SELLER_INFO, the last clause of the terms
from ADULTS_ONLY (18+) or BUSINESS_ONLY (trade customers only, the wording of the shop's own website, D-26).
The bot takes pre-orders (D-27): a pre-order reserves the products, the sale takes place at handover. The payment
clause (`{payment}`) follows the payment methods that are switched on.
Each must stay under Telegram's 4096-character message limit in every language.
"""

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "cmd.help": "Help",
        "cmd.settings": "Settings",
        "cmd.support": "Support",
        "cmd.terms": "Pre-order terms",
        "cmd.privacy": "Privacy and my data",

        "help.text": (
            "ℹ️ <b>Help</b>\n\n"
            "This bot takes pre-orders for the shop. Browse the catalog, add products to the cart and place a "
            "pre-order with delivery or pickup. The sale itself takes place when you receive the products. You can "
            "follow your pre-orders here as well.\n\n"
            "{commands}\n\n"
            "Something went wrong with a pre-order? Use /support."
        ),
        "help.command_line": "/{command} — {description}",

        "settings.title": "⚙️ <b>Settings</b>",
        "settings.language": "🌐 Language: {language}",
        "settings.mailings_on": "🔔 Shop news: on",
        "settings.mailings_off": "🔕 Shop news: off",
        "btn.privacy": "🔒 Privacy and my data",

        "support.text": (
            "🆘 <b>Support</b>\n\n"
            "Questions about a pre-order, a payment or a delivery: write to us with the button below "
            "and include your pre-order number. We answer as soon as we can.\n\n"
            "Telegram support and @BotSupport cannot help with pre-orders made in this bot. "
            "Only the shop can."
        ),
        "btn.support.write": "✍️ Write to support",

        "legal.seller_default": "the shop that runs this bot",
        "legal.terms": (
            "📄 <b>Pre-order terms</b>\n\n"
            "<b>1. Seller.</b> Pre-orders in this bot are taken by {seller}, an independent seller. Telegram is not a"
            " party to them.\n\n"
            "<b>2. Pre-orders.</b> A pre-order is placed when you press Confirm. It reserves the products for you and"
            " is not yet a sale: the sale takes place when the products are handed over to you. Prices are in "
            "{currency} and are the ones shown when you place the pre-order. If a product turns out to be unavailable"
            " we may cancel the pre-order and return anything you paid.\n\n"
            "{payment}<b>4. Receiving.</b> Delivery methods, their prices and the pickup address are shown when you "
            "place the pre-order. Delivery times are estimates. Please check the products when you receive them.\n\n"
            "<b>5. Problems and returns.</b> If a product is damaged or is not what you pre-ordered, write to "
            "/support with the pre-order number. We replace it or return your money. A product of proper quality can "
            "be returned within 14 days if it is unopened and in its original packaging, unless the law excludes it "
            "from returns. These terms do not limit your rights under consumer protection law.\n\n"
            "<b>6. Balance and promo codes.</b> Shop balance can be spent only on pre-orders in this bot and cannot "
            "be paid out in cash.\n\n"
            "<b>7. Messages.</b> The bot writes to you about your pre-orders. Shop news can be turned off at any time"
            " in /settings or with the button under each such message.\n\n"
            "<b>8. Support.</b> Use /support. Telegram support and @BotSupport cannot help with pre-orders made in "
            "this bot.\n\n"
            "<b>9. Your data.</b> See /privacy.\n\n"
            "<b>10. Law and disputes.</b> These terms follow the law of the Republic of Moldova. Send any complaint "
            "to /support: we answer within 15 calendar days. A dispute we cannot settle together goes to the "
            "competent court of the Republic of Moldova. You can also turn to the Agency for Consumer Protection and "
            "Market Surveillance (consumator.gov.md).\n\n"
            "<b>11. Changes.</b> We may update these terms. The version shown here applies to new pre-orders.{adults}"
        ),
        "legal.terms.pay_cod": (
            "<b>3. Payment.</b> You pay when you receive the products. Nothing is paid in the bot, and the bot never "
            "asks for card details.\n\n"
            ""
        ),
        "legal.terms.pay_both": (
            "<b>3. Payment.</b> You pay when you receive the products or, if you prefer, in advance by MIA bank "
            "transfer. A pre-order with MIA payment that is not paid within {minutes} minutes is cancelled "
            "automatically. An advance is returned in full if the pre-order is cancelled. The bot never asks for card"
            " details.\n\n"
            ""
        ),
        "legal.terms.pay_mia": (
            "<b>3. Payment.</b> You pay in advance by MIA bank transfer. A pre-order that is not paid within "
            "{minutes} minutes is cancelled automatically. The advance is returned in full if the pre-order is "
            "cancelled. The bot never asks for card details.\n\n"
            ""
        ),
        "legal.terms.adults": (
            "\n\n"
            "<b>12. Adults only.</b> Pre-orders are accepted only from people aged 18 or over. By placing one you "
            "confirm that you are. We check your age when we hand over the products and may refuse to hand them over "
            "without proof."
        ),
        "legal.terms.business": (
            "\n\n"
            "<b>12. Who can pre-order.</b> Pre-orders are accepted only from businesses that, under art. 21(2) of the"
            " Tobacco Control Law of the Republic of Moldova no. 278/2007, make, import or sell tobacco products, "
            "related products and accessories for their use, acting through representatives aged 18 or over. By "
            "placing one you confirm that you are such a representative. We may ask for proof when we hand over the "
            "products and refuse to hand them over without it."
        ),
        "legal.privacy": (
            "🔒 <b>Privacy policy</b>\n\n"
            "Your data in this bot is handled by {seller}, under the personal data protection law "
            "of the Republic of Moldova.\n\n"
            "<b>What we store</b>\n"
            "• From Telegram: your ID, name, @username and language.\n"
            "• From you at checkout: the name for delivery, phone, city, address and pre-order comment.\n"
            "• Your pre-orders, cart, favorites and reviews, and the payment confirmation you send for a MIA transfer.\n"
            "• When you confirmed that you are 18 or over, when you last used the bot, whether you receive shop news, "
            "and notes our staff make about your pre-orders.\n"
            "We never receive your card details, your contacts or messages from your other chats.\n\n"
            "<b>Why</b>\n"
            "To take, deliver and support your pre-orders and to show you your pre-order history: we need it to carry "
            "out the pre-order you place. Shop news is sent only while you have not turned it off.\n\n"
            "<b>Who sees it</b>\n"
            "The shop's authorised staff. The delivery service gets the name, phone and address needed for your "
            "delivery. The data is kept on the server the bot runs on, which may belong to a hosting provider "
            "working for us. Messages travel through Telegram, which has its own privacy policy "
            "(telegram.org/privacy). We do not sell your data and give it to nobody else, except to state bodies "
            "when the law requires it.\n\n"
            "<b>How long</b>\n"
            "While you use the shop. Pre-order records are kept for as long as accounting and tax law require.\n\n"
            "<b>Your choices</b>\n"
            "• <b>My data</b> below shows what we hold about you.\n"
            "• <b>Delete my data</b> below removes your name, phone and address. "
            "Pre-order amounts and dates stay, without them.\n"
            "• To correct your details, enter new ones at your next pre-order or write to /support.\n"
            "• Turn shop news off in /settings.\n"
            "• For anything else write to /support. We answer within 15 calendar days.\n"
            "• If you think we handle your data wrongly, you can complain to the National Center "
            "for Personal Data Protection (datepersonale.md)."
        ),
        "age.ask": (
            "🔞 <b>Are you 18 or over?</b>\n\n"
            "This bot is only for adults. See /terms and /privacy."
        ),
        "age.denied": "This bot is only for adults, so it stays closed for you. See /privacy for your data.",
        "btn.age.yes": "✅ Yes, I am 18 or over",
        "btn.age.no": "No",
        "btn.my_data": "📋 My data",
        "btn.my_data_erase": "🗑 Delete my data",
        "btn.my_data_erase_yes": "🗑 Yes, delete",
        "my_data.title": "📋 <b>What we hold about you</b>",
        "my_data.line": "<b>{label}</b>: {value}",
        "my_data.label.id": "Telegram ID",
        "my_data.label.first_name": "First name",
        "my_data.label.last_name": "Last name",
        "my_data.label.username": "Username",
        "my_data.label.language": "Language",
        "my_data.label.contact_name": "Name for delivery",
        "my_data.label.phone": "Phone",
        "my_data.label.city": "City",
        "my_data.label.address": "Address",
        "my_data.label.orders": "Pre-orders",
        "my_data.label.mailings": "Shop news",
        "my_data.label.registered": "With us since",
        "my_data.label.age_confirmed": "Confirmed 18+ on",
        "my_data.on": "on",
        "my_data.off": "off",
        "my_data.orders_hint": "Each pre-order also keeps the name, phone, address and comment you gave for it. See /orders.",
        "my_data.erase.ask": (
            "🗑 <b>Delete my data?</b>\n\n"
            "Your name, @username, phone, city and address are removed from your profile and from all your "
            "past pre-orders. Your cart, favorites and review texts are deleted.\n\n"
            "Pre-order amounts, dates and your balance stay, because the shop's accounts need them. "
            "This cannot be undone."
        ),
        "my_data.erase.done": (
            "✅ Your personal data has been deleted.\n\n"
            "If you keep using the bot, Telegram tells it your name and @username again."
        ),
        "my_data.erase.active_orders": (
            "You still have a pre-order in progress, and we need your details to deliver it. "
            "Try again when it is completed or cancelled."
        ),
        "my_data.erase.failed": "We could not delete your data here. Please write to /support.",

        "checkout.summary.agree": "By confirming you accept the Pre-order terms (/terms) and the Privacy policy (/privacy).",
        "checkout.summary.agree_adults": (
            "By confirming you accept the Pre-order terms (/terms) and the Privacy policy (/privacy), and confirm "
            "that you are 18 or over."
        ),
        "checkout.summary.agree_business": (
            "By confirming you accept the Pre-order terms (/terms) and the Privacy policy (/privacy), and confirm "
            "that you are 18 or over and pre-order for a business that trades in these products."
        ),
    },
    "ru": {
        "cmd.help": "Помощь",
        "cmd.settings": "Настройки",
        "cmd.support": "Поддержка",
        "cmd.terms": "Условия предзаказа",
        "cmd.privacy": "Конфиденциальность и мои данные",

        "help.text": (
            "ℹ️ <b>Помощь</b>\n\n"
            "Этот бот принимает предзаказы магазина. Смотрите каталог, добавляйте товары в корзину и оформляйте "
            "предзаказ с доставкой или самовывозом. Сама продажа происходит при получении товара. Здесь же можно "
            "следить за своими предзаказами.\n\n"
            "{commands}\n\n"
            "Что-то не так с предзаказом? Откройте /support."
        ),
        "help.command_line": "/{command} — {description}",

        "settings.title": "⚙️ <b>Настройки</b>",
        "settings.language": "🌐 Язык: {language}",
        "settings.mailings_on": "🔔 Новости магазина: включены",
        "settings.mailings_off": "🔕 Новости магазина: выключены",
        "btn.privacy": "🔒 Конфиденциальность и мои данные",

        "support.text": (
            "🆘 <b>Поддержка</b>\n\n"
            "Вопросы о предзаказе, оплате или доставке: напишите нам по кнопке ниже "
            "и укажите номер предзаказа. Мы ответим, как только сможем.\n\n"
            "Поддержка Telegram и @BotSupport не помогают с предзаказами в этом боте. "
            "Помочь может только магазин."
        ),
        "btn.support.write": "✍️ Написать в поддержку",

        "legal.seller_default": "магазин, которому принадлежит этот бот",
        "legal.terms": (
            "📄 <b>Условия предзаказа</b>\n\n"
            "<b>1. Продавец.</b> Предзаказы в этом боте принимает {seller}, независимый продавец. Telegram не "
            "является их стороной.\n\n"
            "<b>2. Предзаказы.</b> Предзаказ оформлен, когда вы нажали «Подтвердить». Он резервирует для вас товар и "
            "ещё не является продажей: продажа происходит в момент передачи товара вам. Цены указаны в {currency} и "
            "действуют те, что показаны при оформлении предзаказа. Если товара не окажется в наличии, мы можем "
            "отменить предзаказ и вернуть всё, что вы оплатили.\n\n"
            "{payment}<b>4. Получение.</b> Способы доставки, их стоимость и адрес самовывоза показаны при оформлении "
            "предзаказа. Сроки доставки ориентировочные. Пожалуйста, проверяйте товар при получении.\n\n"
            "<b>5. Проблемы и возврат.</b> Если товар повреждён или не тот, что вы предзаказали, напишите в /support "
            "и укажите номер предзаказа. Мы заменим товар или вернём деньги. Товар надлежащего качества можно вернуть"
            " в течение 14 дней, если он не вскрыт и сохранена заводская упаковка, кроме товаров, которые по закону "
            "возврату не подлежат. Эти условия не ограничивают ваши права по закону о защите прав потребителей.\n\n"
            "<b>6. Баланс и промокоды.</b> Баланс магазина можно потратить только на предзаказы в этом боте, "
            "наличными он не выдаётся.\n\n"
            "<b>7. Сообщения.</b> Бот пишет вам о ваших предзаказах. Новости магазина можно отключить в любой момент "
            "в /settings или кнопкой под каждым таким сообщением.\n\n"
            "<b>8. Поддержка.</b> Откройте /support. Поддержка Telegram и @BotSupport не помогают с предзаказами в "
            "этом боте.\n\n"
            "<b>9. Ваши данные.</b> См. /privacy.\n\n"
            "<b>10. Право и споры.</b> К этим условиям применяется законодательство Республики Молдова. Любую "
            "претензию направляйте в /support: мы отвечаем в течение 15 календарных дней. Спор, который не удалось "
            "решить вместе, рассматривает компетентный суд Республики Молдова. Вы также можете обратиться в Агентство"
            " по защите прав потребителей и надзору за рынком (consumator.gov.md).\n\n"
            "<b>11. Изменения.</b> Мы можем обновлять эти условия. К новым предзаказам применяется версия, показанная"
            " здесь.{adults}"
        ),
        "legal.terms.pay_cod": (
            "<b>3. Оплата.</b> Вы платите при получении товара. В боте ничего не оплачивается, и бот никогда не "
            "просит данные карты.\n\n"
            ""
        ),
        "legal.terms.pay_both": (
            "<b>3. Оплата.</b> Вы платите при получении товара или, по желанию, заранее переводом MIA. Предзаказ с "
            "оплатой MIA, не оплаченный в течение {minutes} мин., отменяется автоматически. Аванс возвращается "
            "полностью, если предзаказ отменён. Бот никогда не просит данные карты.\n\n"
            ""
        ),
        "legal.terms.pay_mia": (
            "<b>3. Оплата.</b> Вы платите заранее переводом MIA. Предзаказ, не оплаченный в течение {minutes} мин., "
            "отменяется автоматически. Аванс возвращается полностью, если предзаказ отменён. Бот никогда не просит "
            "данные карты.\n\n"
            ""
        ),
        "legal.terms.adults": (
            "\n\n"
            "<b>12. Только для взрослых.</b> Предзаказы принимаются только от лиц старше 18 лет. Оформляя предзаказ, "
            "вы подтверждаете, что вам есть 18. При передаче товара мы проверяем возраст и можем не передать товар "
            "без подтверждения."
        ),
        "legal.terms.business": (
            "\n\n"
            "<b>12. Кто может оформить предзаказ.</b> Предзаказы принимаются исключительно от хозяйствующих "
            "субъектов, которые согласно ч. (2) ст. 21 Закона Республики Молдова о контроле над табаком № 278/2007 "
            "являются производителями, импортёрами или продавцами табачных изделий, сопутствующих изделий и "
            "аксессуаров для их использования, в лице представителей старше 18 лет. Оформляя предзаказ, вы "
            "подтверждаете, что являетесь таким представителем. При передаче товара мы можем попросить это "
            "подтвердить и не передать товар без подтверждения."
        ),
        "legal.privacy": (
            "🔒 <b>Политика конфиденциальности</b>\n\n"
            "За ваши данные в этом боте отвечает {seller}, в соответствии с законодательством "
            "Республики Молдова о защите персональных данных.\n\n"
            "<b>Что мы храним</b>\n"
            "• Из Telegram: ваш ID, имя, @username и язык.\n"
            "• От вас при оформлении: имя для доставки, телефон, город, адрес и комментарий к предзаказу.\n"
            "• Ваши предзаказы, корзину, избранное и отзывы, а также подтверждение оплаты, которое вы присылаете при переводе MIA.\n"
            "• Когда вы подтвердили, что вам есть 18 лет, когда последний раз пользовались ботом, получаете ли "
            "новости магазина, и заметки сотрудников о ваших предзаказах.\n"
            "Мы никогда не получаем данные вашей карты, ваши контакты или сообщения из других чатов.\n\n"
            "<b>Зачем</b>\n"
            "Чтобы принимать, доставлять и сопровождать ваши предзаказы и показывать вам историю предзаказов: это нужно "
            "для исполнения предзаказа, который вы оформляете. Новости магазина приходят, только пока вы их "
            "не отключили.\n\n"
            "<b>Кто это видит</b>\n"
            "Уполномоченные сотрудники магазина. Служба доставки получает имя, телефон и адрес, нужные для вашей "
            "доставки. Данные хранятся на сервере, где работает бот; он может принадлежать хостинг-провайдеру, "
            "который работает на нас. Сообщения проходят через Telegram, у которого своя политика "
            "конфиденциальности (telegram.org/privacy). Мы не продаём ваши данные и никому больше их не передаём, "
            "кроме государственных органов, когда этого требует закон.\n\n"
            "<b>Как долго</b>\n"
            "Пока вы пользуетесь магазином. Записи о предзаказах хранятся столько, сколько требует бухгалтерское "
            "и налоговое законодательство.\n\n"
            "<b>Ваш выбор</b>\n"
            "• <b>Мои данные</b> ниже показывает, что мы о вас храним.\n"
            "• <b>Удалить мои данные</b> ниже убирает ваше имя, телефон и адрес. "
            "Суммы и даты предзаказов остаются, но уже без них.\n"
            "• Чтобы исправить данные, укажите новые при следующем предзаказе или напишите в /support.\n"
            "• Новости магазина отключаются в /settings.\n"
            "• По остальным вопросам напишите в /support. Мы отвечаем в течение 15 календарных дней.\n"
            "• Если вы считаете, что мы обрабатываем ваши данные неправильно, вы можете обратиться "
            "в Национальный центр по защите персональных данных (datepersonale.md)."
        ),
        "age.ask": (
            "🔞 <b>Вам есть 18 лет?</b>\n\n"
            "Этот бот только для взрослых. См. /terms и /privacy."
        ),
        "age.denied": "Этот бот только для взрослых, поэтому для вас он закрыт. О ваших данных см. /privacy.",
        "btn.age.yes": "✅ Да, мне есть 18",
        "btn.age.no": "Нет",
        "btn.my_data": "📋 Мои данные",
        "btn.my_data_erase": "🗑 Удалить мои данные",
        "btn.my_data_erase_yes": "🗑 Да, удалить",
        "my_data.title": "📋 <b>Что мы о вас храним</b>",
        "my_data.line": "<b>{label}</b>: {value}",
        "my_data.label.id": "Telegram ID",
        "my_data.label.first_name": "Имя",
        "my_data.label.last_name": "Фамилия",
        "my_data.label.username": "Username",
        "my_data.label.language": "Язык",
        "my_data.label.contact_name": "Имя для доставки",
        "my_data.label.phone": "Телефон",
        "my_data.label.city": "Город",
        "my_data.label.address": "Адрес",
        "my_data.label.orders": "Предзаказов",
        "my_data.label.mailings": "Новости магазина",
        "my_data.label.registered": "С нами с",
        "my_data.label.age_confirmed": "Возраст 18+ подтверждён",
        "my_data.on": "включены",
        "my_data.off": "выключены",
        "my_data.orders_hint": "В каждом предзаказе также хранятся имя, телефон, адрес и комментарий, которые вы для него указали. См. /orders.",
        "my_data.erase.ask": (
            "🗑 <b>Удалить мои данные?</b>\n\n"
            "Ваше имя, @username, телефон, город и адрес будут удалены из профиля и из всех ваших "
            "прошлых предзаказов. Корзина, избранное и тексты отзывов будут удалены.\n\n"
            "Суммы и даты предзаказов и ваш баланс останутся: они нужны для учёта магазина. "
            "Это действие нельзя отменить."
        ),
        "my_data.erase.done": (
            "✅ Ваши персональные данные удалены.\n\n"
            "Если вы продолжите пользоваться ботом, Telegram снова сообщит ему ваше имя и @username."
        ),
        "my_data.erase.active_orders": (
            "У вас есть предзаказ в работе, и ваши данные нужны, чтобы его доставить. "
            "Попробуйте ещё раз, когда он будет выполнен или отменён."
        ),
        "my_data.erase.failed": "Не удалось удалить ваши данные здесь. Пожалуйста, напишите в /support.",

        "checkout.summary.agree": (
            "Подтверждая предзаказ, вы принимаете Условия предзаказа (/terms) и Политику конфиденциальности "
            "(/privacy)."
        ),
        "checkout.summary.agree_adults": (
            "Подтверждая предзаказ, вы принимаете Условия предзаказа (/terms) и Политику конфиденциальности "
            "(/privacy) и подтверждаете, что вам есть 18 лет."
        ),
        "checkout.summary.agree_business": (
            "Подтверждая предзаказ, вы принимаете Условия предзаказа (/terms) и Политику конфиденциальности "
            "(/privacy) и подтверждаете, что вам есть 18 лет и вы оформляете предзаказ от имени предприятия, "
            "торгующего такими товарами."
        ),
    },
    "ro": {
        "cmd.help": "Ajutor",
        "cmd.settings": "Setări",
        "cmd.support": "Suport",
        "cmd.terms": "Condiții de precomandă",
        "cmd.privacy": "Confidențialitate și datele mele",

        "help.text": (
            "ℹ️ <b>Ajutor</b>\n\n"
            "Acest bot preia precomenzi pentru magazin. Răsfoiți catalogul, adăugați produse în coș și plasați o "
            "precomandă cu livrare sau ridicare personală. Vânzarea propriu-zisă are loc la primirea produselor. Tot "
            "aici vă puteți urmări precomenzile.\n\n"
            "{commands}\n\n"
            "Ceva nu este în regulă cu o precomandă? Folosiți /support."
        ),
        "help.command_line": "/{command} — {description}",

        "settings.title": "⚙️ <b>Setări</b>",
        "settings.language": "🌐 Limbă: {language}",
        "settings.mailings_on": "🔔 Noutățile magazinului: activate",
        "settings.mailings_off": "🔕 Noutățile magazinului: dezactivate",
        "btn.privacy": "🔒 Confidențialitate și datele mele",

        "support.text": (
            "🆘 <b>Suport</b>\n\n"
            "Întrebări despre o precomandă, o plată sau o livrare: scrieți-ne cu butonul de mai jos "
            "și indicați numărul precomenzii. Răspundem cât de repede putem.\n\n"
            "Suportul Telegram și @BotSupport nu pot ajuta cu precomenzile făcute în acest bot. "
            "Vă poate ajuta doar magazinul."
        ),
        "btn.support.write": "✍️ Scrieți suportului",

        "legal.seller_default": "magazinul care administrează acest bot",
        "legal.terms": (
            "📄 <b>Condiții de precomandă</b>\n\n"
            "<b>1. Vânzătorul.</b> Precomenzile din acest bot sunt preluate de {seller}, un vânzător independent. "
            "Telegram nu este parte la acestea.\n\n"
            "<b>2. Precomenzi.</b> Precomanda este plasată când apăsați „Confirmă”. Ea vă rezervă produsele și nu "
            "este încă o vânzare: vânzarea are loc în momentul în care produsele vă sunt predate. Prețurile sunt în "
            "{currency} și sunt cele afișate la plasarea precomenzii. Dacă un produs nu mai este disponibil, putem "
            "anula precomanda și vă returnăm tot ce ați plătit.\n\n"
            "{payment}<b>4. Primirea.</b> Metodele de livrare, prețurile lor și adresa de ridicare sunt afișate la "
            "plasarea precomenzii. Termenele de livrare sunt estimative. Vă rugăm să verificați produsele la "
            "primire.\n\n"
            "<b>5. Probleme și returnări.</b> Dacă un produs este deteriorat sau nu este cel precomandat, scrieți la "
            "/support și indicați numărul precomenzii. Îl înlocuim sau vă returnăm banii. Un produs de calitate "
            "corespunzătoare poate fi returnat în 14 zile, dacă este nedesfăcut și în ambalajul original, cu excepția"
            " produselor pe care legea le exclude de la returnare. Aceste condiții nu limitează drepturile "
            "dumneavoastră prevăzute de legislația privind protecția consumatorilor.\n\n"
            "<b>6. Sold și coduri promoționale.</b> Soldul din magazin poate fi folosit doar pentru precomenzi în "
            "acest bot și nu se plătește în numerar.\n\n"
            "<b>7. Mesaje.</b> Botul vă scrie despre precomenzile dumneavoastră. Noutățile magazinului pot fi oprite "
            "oricând în /settings sau cu butonul de sub fiecare astfel de mesaj.\n\n"
            "<b>8. Suport.</b> Folosiți /support. Suportul Telegram și @BotSupport nu pot ajuta cu precomenzile "
            "făcute în acest bot.\n\n"
            "<b>9. Datele dumneavoastră.</b> Vedeți /privacy.\n\n"
            "<b>10. Legea aplicabilă și litigii.</b> Acestor condiții li se aplică legislația Republicii Moldova. "
            "Trimiteți orice reclamație la /support: răspundem în 15 zile calendaristice. Un litigiu pe care nu îl "
            "putem rezolva împreună este examinat de instanța competentă din Republica Moldova. Vă puteți adresa și "
            "Agenției pentru Protecția Consumatorilor și Supravegherea Pieței (consumator.gov.md).\n\n"
            "<b>11. Modificări.</b> Putem actualiza aceste condiții. Pentru precomenzile noi se aplică versiunea "
            "afișată aici.{adults}"
        ),
        "legal.terms.pay_cod": (
            "<b>3. Plata.</b> Plătiți la primirea produselor. În bot nu se plătește nimic, iar botul nu cere "
            "niciodată datele cardului.\n\n"
            ""
        ),
        "legal.terms.pay_both": (
            "<b>3. Plata.</b> Plătiți la primirea produselor sau, dacă doriți, în avans prin transfer MIA. O "
            "precomandă cu plată MIA neachitată în {minutes} minute se anulează automat. Avansul se returnează "
            "integral dacă precomanda este anulată. Botul nu cere niciodată datele cardului.\n\n"
            ""
        ),
        "legal.terms.pay_mia": (
            "<b>3. Plata.</b> Plătiți în avans prin transfer MIA. O precomandă neachitată în {minutes} minute se "
            "anulează automat. Avansul se returnează integral dacă precomanda este anulată. Botul nu cere niciodată "
            "datele cardului.\n\n"
            ""
        ),
        "legal.terms.adults": (
            "\n\n"
            "<b>12. Doar pentru adulți.</b> Precomenzile se acceptă doar de la persoane de cel puțin 18 ani. Plasând "
            "o precomandă, confirmați că aveți această vârstă. La predarea produselor verificăm vârsta și putem "
            "refuza predarea fără dovadă."
        ),
        "legal.terms.business": (
            "\n\n"
            "<b>12. Cine poate precomanda.</b> Precomenzile se acceptă exclusiv de la agenți economici care, potrivit"
            " art. 21 alin. (2) din Legea nr. 278/2007 privind controlul tutunului, sunt producători, importatori sau"
            " vânzători de produse din tutun, produse conexe și accesorii pentru utilizarea lor, prin reprezentanții "
            "lor de cel puțin 18 ani. Plasând o precomandă, confirmați că sunteți un astfel de reprezentant. La "
            "predarea produselor vă putem cere o dovadă și putem refuza predarea fără ea."
        ),
        "legal.privacy": (
            "🔒 <b>Politica de confidențialitate</b>\n\n"
            "Pentru datele dumneavoastră din acest bot răspunde {seller}, potrivit legislației "
            "Republicii Moldova privind protecția datelor cu caracter personal.\n\n"
            "<b>Ce păstrăm</b>\n"
            "• Din Telegram: ID-ul, numele, @username și limba.\n"
            "• De la dumneavoastră, la finalizarea precomenzii: numele pentru livrare, telefonul, orașul, adresa și comentariul la precomandă.\n"
            "• Precomenzile, coșul, favoritele și recenziile, precum și confirmarea plății pe care o trimiteți pentru un transfer MIA.\n"
            "• Când ați confirmat că aveți cel puțin 18 ani, când ați folosit ultima dată botul, dacă primiți noutățile "
            "magazinului și notițele personalului despre precomenzile dumneavoastră.\n"
            "Nu primim niciodată datele cardului, contactele sau mesajele din celelalte conversații ale dumneavoastră.\n\n"
            "<b>De ce</b>\n"
            "Pentru a prelua, livra și susține precomenzile și pentru a vă arăta istoricul precomenzilor: sunt necesare "
            "pentru executarea precomenzii pe care o plasați. Noutățile magazinului se trimit doar cât timp "
            "nu le-ați oprit.\n\n"
            "<b>Cine le vede</b>\n"
            "Personalul autorizat al magazinului. Serviciul de livrare primește numele, telefonul și adresa necesare "
            "livrării. Datele se păstrează pe serverul pe care rulează botul, care poate aparține unui furnizor de "
            "găzduire ce lucrează pentru noi. Mesajele trec prin Telegram, care are propria politică de "
            "confidențialitate (telegram.org/privacy). Nu vindem datele dumneavoastră și nu le dăm nimănui altcuiva, "
            "cu excepția autorităților statului, când legea o cere.\n\n"
            "<b>Cât timp</b>\n"
            "Cât timp folosiți magazinul. Evidența precomenzilor se păstrează atât cât cere legislația contabilă și fiscală.\n\n"
            "<b>Opțiunile dumneavoastră</b>\n"
            "• <b>Datele mele</b>, mai jos, arată ce păstrăm despre dumneavoastră.\n"
            "• <b>Șterge datele mele</b>, mai jos, elimină numele, telefonul și adresa. "
            "Sumele și datele precomenzilor rămân, fără acestea.\n"
            "• Pentru a corecta datele, indicați altele la următoarea precomandă sau scrieți la /support.\n"
            "• Noutățile magazinului se opresc în /settings.\n"
            "• Pentru orice altceva scrieți la /support. Răspundem în 15 zile calendaristice.\n"
            "• Dacă considerați că prelucrăm datele greșit, vă puteți adresa Centrului Național "
            "pentru Protecția Datelor cu Caracter Personal (datepersonale.md)."
        ),
        "age.ask": (
            "🔞 <b>Aveți cel puțin 18 ani?</b>\n\n"
            "Acest bot este doar pentru adulți. Vedeți /terms și /privacy."
        ),
        "age.denied": "Acest bot este doar pentru adulți, de aceea rămâne închis pentru dumneavoastră. Despre datele dumneavoastră vedeți /privacy.",
        "btn.age.yes": "✅ Da, am cel puțin 18 ani",
        "btn.age.no": "Nu",
        "btn.my_data": "📋 Datele mele",
        "btn.my_data_erase": "🗑 Șterge datele mele",
        "btn.my_data_erase_yes": "🗑 Da, șterge",
        "my_data.title": "📋 <b>Ce păstrăm despre dumneavoastră</b>",
        "my_data.line": "<b>{label}</b>: {value}",
        "my_data.label.id": "ID Telegram",
        "my_data.label.first_name": "Prenume",
        "my_data.label.last_name": "Nume",
        "my_data.label.username": "Username",
        "my_data.label.language": "Limbă",
        "my_data.label.contact_name": "Nume pentru livrare",
        "my_data.label.phone": "Telefon",
        "my_data.label.city": "Oraș",
        "my_data.label.address": "Adresă",
        "my_data.label.orders": "Precomenzi",
        "my_data.label.mailings": "Noutățile magazinului",
        "my_data.label.registered": "Client din",
        "my_data.label.age_confirmed": "Vârsta 18+ confirmată la",
        "my_data.on": "activate",
        "my_data.off": "dezactivate",
        "my_data.orders_hint": "Fiecare precomandă păstrează și numele, telefonul, adresa și comentariul indicate pentru ea. Vedeți /orders.",
        "my_data.erase.ask": (
            "🗑 <b>Ștergeți datele mele?</b>\n\n"
            "Numele, @username, telefonul, orașul și adresa sunt eliminate din profil și din toate "
            "precomenzile anterioare. Coșul, favoritele și textele recenziilor sunt șterse.\n\n"
            "Sumele și datele precomenzilor și soldul rămân, deoarece sunt necesare pentru evidența magazinului. "
            "Acțiunea nu poate fi anulată."
        ),
        "my_data.erase.done": (
            "✅ Datele dumneavoastră personale au fost șterse.\n\n"
            "Dacă folosiți botul în continuare, Telegram îi transmite din nou numele și @username."
        ),
        "my_data.erase.active_orders": (
            "Aveți încă o precomandă în lucru, iar datele sunt necesare pentru a o livra. "
            "Încercați din nou după ce este finalizată sau anulată."
        ),
        "my_data.erase.failed": "Nu am putut șterge datele aici. Vă rugăm să scrieți la /support.",

        "checkout.summary.agree": (
            "Confirmând, acceptați Condițiile de precomandă (/terms) și Politica de confidențialitate (/privacy)."
        ),
        "checkout.summary.agree_adults": (
            "Confirmând, acceptați Condițiile de precomandă (/terms) și Politica de confidențialitate (/privacy) și "
            "confirmați că aveți cel puțin 18 ani."
        ),
        "checkout.summary.agree_business": (
            "Confirmând, acceptați Condițiile de precomandă (/terms) și Politica de confidențialitate (/privacy) și "
            "confirmați că aveți cel puțin 18 ani și precomandați în numele unui agent economic care comercializează "
            "astfel de produse."
        ),
    },
}
