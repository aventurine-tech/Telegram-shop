"""Help, settings, support, terms of sale and the privacy policy (Telegram's bot rules ask for all of them, D-25).

The terms and the policy are the shop's own texts: `{seller}` comes from SELLER_INFO, the 18+ clause from ADULTS_ONLY.
Each must stay under Telegram's 4096-character message limit in every language.
"""

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "cmd.help": "Help",
        "cmd.settings": "Settings",
        "cmd.support": "Support",
        "cmd.terms": "Terms of sale",
        "cmd.privacy": "Privacy and my data",

        "help.text": (
            "ℹ️ <b>Help</b>\n\n"
            "This bot is a shop. Browse the catalog, add products to the cart and place an order "
            "with delivery or pickup. You can follow your orders here as well.\n\n"
            "{commands}\n\n"
            "Something went wrong with an order? Use /support."
        ),
        "help.command_line": "/{command} — {description}",

        "settings.title": "⚙️ <b>Settings</b>",
        "settings.language": "🌐 Language: {language}",
        "settings.mailings_on": "🔔 Shop news: on",
        "settings.mailings_off": "🔕 Shop news: off",
        "btn.privacy": "🔒 Privacy and my data",

        "support.text": (
            "🆘 <b>Support</b>\n\n"
            "Questions about an order, a payment or a delivery: write to us with the button below "
            "and include your order number. We answer as soon as we can.\n\n"
            "Telegram support and @BotSupport cannot help with purchases made in this bot. "
            "Only the shop can."
        ),
        "btn.support.write": "✍️ Write to support",

        "legal.seller_default": "the shop that runs this bot",
        "legal.terms": (
            "📄 <b>Terms of sale</b>\n\n"
            "<b>1. Seller.</b> This shop is run by {seller}. It is an independent seller. "
            "Telegram is not a party to your purchase.\n\n"
            "<b>2. Orders.</b> An order is placed when you press Confirm at checkout. Prices are in {currency} "
            "and are the ones shown at that moment. If a product turns out to be unavailable we may cancel "
            "the order and return anything you paid.\n\n"
            "<b>3. Payment.</b> You pay with one of the methods offered at checkout: a MIA bank transfer or cash "
            "when you receive the order. A MIA order that is not paid within {minutes} minutes is cancelled "
            "automatically. The bot never asks for card details.\n\n"
            "<b>4. Delivery.</b> Delivery methods, their prices and the pickup address are shown at checkout. "
            "Delivery times are estimates.\n\n"
            "<b>5. Problems with an order.</b> If a product arrives damaged or is not what you ordered, write to "
            "/support with the order number. We replace it or return your money. These terms do not limit "
            "your rights under consumer protection law.\n\n"
            "<b>6. Balance and promo codes.</b> Shop balance can be spent only on orders in this shop "
            "and cannot be paid out in cash.\n\n"
            "<b>7. Messages.</b> The bot writes to you about your orders. Shop news can be turned off at any time "
            "in /settings or with the button under each such message.\n\n"
            "<b>8. Support.</b> Use /support. Telegram support and @BotSupport cannot help with purchases "
            "made in this bot.\n\n"
            "<b>9. Your data.</b> See /privacy.\n\n"
            "<b>10. Changes.</b> We may update these terms. The version shown here applies to new orders."
            "{adults}"
        ),
        "legal.terms.adults": (
            "\n\n<b>11. Adults only.</b> This shop sells only to people aged 18 or over. By placing an order "
            "you confirm that you are. We may ask for proof of age on delivery."
        ),
        "legal.privacy": (
            "🔒 <b>Privacy policy</b>\n\n"
            "Your data in this bot is handled by {seller}.\n\n"
            "<b>What we store</b>\n"
            "• From Telegram: your ID, name, @username and language.\n"
            "• From you at checkout: the name for delivery, phone, city, address and order comment.\n"
            "• Your orders, cart, favorites and reviews, and the payment confirmation you send for a MIA transfer.\n"
            "• When you last used the bot, whether you receive shop news, and notes our staff make about your orders.\n"
            "We never receive your card details, your contacts or messages from your other chats.\n\n"
            "<b>Why</b>\n"
            "To take, deliver and support your orders, to show you your order history, and to send shop news "
            "if you have not turned it off.\n\n"
            "<b>Who sees it</b>\n"
            "The shop's staff. The delivery service gets the name, phone and address needed for your delivery. "
            "We do not sell your data and give it to nobody else unless the law requires it.\n\n"
            "<b>How long</b>\n"
            "While you use the shop. Order records are kept for as long as accounting and tax law require.\n\n"
            "<b>Your choices</b>\n"
            "• <b>My data</b> below shows what we hold about you.\n"
            "• <b>Delete my data</b> below removes your name, phone and address. "
            "Order amounts and dates stay, without them.\n"
            "• Turn shop news off in /settings.\n"
            "• For anything else write to /support. We answer within 30 days."
        ),
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
        "my_data.label.orders": "Orders",
        "my_data.label.mailings": "Shop news",
        "my_data.label.registered": "With us since",
        "my_data.on": "on",
        "my_data.off": "off",
        "my_data.orders_hint": "Each order also keeps the name, phone, address and comment you gave for it. See /orders.",
        "my_data.erase.ask": (
            "🗑 <b>Delete my data?</b>\n\n"
            "Your name, @username, phone, city and address are removed from your profile and from all your "
            "past orders. Your cart, favorites and review texts are deleted.\n\n"
            "Order amounts, dates and your balance stay, because the shop's accounts need them. "
            "This cannot be undone."
        ),
        "my_data.erase.done": (
            "✅ Your personal data has been deleted.\n\n"
            "If you keep using the bot, Telegram tells it your name and @username again."
        ),
        "my_data.erase.active_orders": (
            "You still have an order in progress, and we need your details to deliver it. "
            "Try again when it is completed or cancelled."
        ),
        "my_data.erase.failed": "We could not delete your data here. Please write to /support.",

        "checkout.summary.agree": "By confirming you accept the Terms of sale (/terms) and the Privacy policy (/privacy).",
        "checkout.summary.agree_adults": (
            "By confirming you accept the Terms of sale (/terms) and the Privacy policy (/privacy), "
            "and confirm that you are 18 or over."
        ),
    },
    "ru": {
        "cmd.help": "Помощь",
        "cmd.settings": "Настройки",
        "cmd.support": "Поддержка",
        "cmd.terms": "Условия продажи",
        "cmd.privacy": "Конфиденциальность и мои данные",

        "help.text": (
            "ℹ️ <b>Помощь</b>\n\n"
            "Этот бот — магазин. Смотрите каталог, добавляйте товары в корзину и оформляйте заказ "
            "с доставкой или самовывозом. Здесь же можно следить за своими заказами.\n\n"
            "{commands}\n\n"
            "Что-то не так с заказом? Откройте /support."
        ),
        "help.command_line": "/{command} — {description}",

        "settings.title": "⚙️ <b>Настройки</b>",
        "settings.language": "🌐 Язык: {language}",
        "settings.mailings_on": "🔔 Новости магазина: включены",
        "settings.mailings_off": "🔕 Новости магазина: выключены",
        "btn.privacy": "🔒 Конфиденциальность и мои данные",

        "support.text": (
            "🆘 <b>Поддержка</b>\n\n"
            "Вопросы о заказе, оплате или доставке: напишите нам по кнопке ниже "
            "и укажите номер заказа. Мы ответим, как только сможем.\n\n"
            "Поддержка Telegram и @BotSupport не помогают с покупками в этом боте. "
            "Помочь может только магазин."
        ),
        "btn.support.write": "✍️ Написать в поддержку",

        "legal.seller_default": "магазин, которому принадлежит этот бот",
        "legal.terms": (
            "📄 <b>Условия продажи</b>\n\n"
            "<b>1. Продавец.</b> Магазином управляет {seller}. Это независимый продавец. "
            "Telegram не является стороной вашей покупки.\n\n"
            "<b>2. Заказы.</b> Заказ оформлен, когда вы нажали «Подтвердить» при оформлении. Цены указаны в {currency} "
            "и действуют те, что показаны в этот момент. Если товара не окажется в наличии, мы можем отменить "
            "заказ и вернуть всё, что вы оплатили.\n\n"
            "<b>3. Оплата.</b> Вы платите одним из способов, предложенных при оформлении: переводом MIA или наличными "
            "при получении. Заказ MIA, не оплаченный в течение {minutes} мин., отменяется автоматически. "
            "Бот никогда не просит данные карты.\n\n"
            "<b>4. Доставка.</b> Способы доставки, их стоимость и адрес самовывоза показаны при оформлении. "
            "Сроки доставки ориентировочные.\n\n"
            "<b>5. Проблемы с заказом.</b> Если товар пришёл повреждённым или не тот, что вы заказали, напишите в "
            "/support и укажите номер заказа. Мы заменим товар или вернём деньги. Эти условия не ограничивают "
            "ваши права по закону о защите прав потребителей.\n\n"
            "<b>6. Баланс и промокоды.</b> Баланс магазина можно потратить только на заказы в этом магазине, "
            "наличными он не выдаётся.\n\n"
            "<b>7. Сообщения.</b> Бот пишет вам о ваших заказах. Новости магазина можно отключить в любой момент "
            "в /settings или кнопкой под каждым таким сообщением.\n\n"
            "<b>8. Поддержка.</b> Откройте /support. Поддержка Telegram и @BotSupport не помогают с покупками "
            "в этом боте.\n\n"
            "<b>9. Ваши данные.</b> См. /privacy.\n\n"
            "<b>10. Изменения.</b> Мы можем обновлять эти условия. К новым заказам применяется версия, показанная здесь."
            "{adults}"
        ),
        "legal.terms.adults": (
            "\n\n<b>11. Только для взрослых.</b> Магазин продаёт товары только лицам от 18 лет. Оформляя заказ, "
            "вы подтверждаете, что вам есть 18. При доставке мы можем попросить подтвердить возраст."
        ),
        "legal.privacy": (
            "🔒 <b>Политика конфиденциальности</b>\n\n"
            "За ваши данные в этом боте отвечает {seller}.\n\n"
            "<b>Что мы храним</b>\n"
            "• Из Telegram: ваш ID, имя, @username и язык.\n"
            "• От вас при оформлении: имя для доставки, телефон, город, адрес и комментарий к заказу.\n"
            "• Ваши заказы, корзину, избранное и отзывы, а также подтверждение оплаты, которое вы присылаете при переводе MIA.\n"
            "• Когда вы последний раз пользовались ботом, получаете ли новости магазина, и заметки сотрудников о ваших заказах.\n"
            "Мы никогда не получаем данные вашей карты, ваши контакты или сообщения из других чатов.\n\n"
            "<b>Зачем</b>\n"
            "Чтобы принимать, доставлять и сопровождать ваши заказы, показывать вам историю заказов и присылать "
            "новости магазина, если вы их не отключили.\n\n"
            "<b>Кто это видит</b>\n"
            "Сотрудники магазина. Служба доставки получает имя, телефон и адрес, нужные для вашей доставки. "
            "Мы не продаём ваши данные и никому больше их не передаём, если этого не требует закон.\n\n"
            "<b>Как долго</b>\n"
            "Пока вы пользуетесь магазином. Записи о заказах хранятся столько, сколько требует бухгалтерское "
            "и налоговое законодательство.\n\n"
            "<b>Ваш выбор</b>\n"
            "• <b>Мои данные</b> ниже показывает, что мы о вас храним.\n"
            "• <b>Удалить мои данные</b> ниже убирает ваше имя, телефон и адрес. "
            "Суммы и даты заказов остаются, но уже без них.\n"
            "• Новости магазина отключаются в /settings.\n"
            "• По остальным вопросам напишите в /support. Мы отвечаем в течение 30 дней."
        ),
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
        "my_data.label.orders": "Заказов",
        "my_data.label.mailings": "Новости магазина",
        "my_data.label.registered": "С нами с",
        "my_data.on": "включены",
        "my_data.off": "выключены",
        "my_data.orders_hint": "В каждом заказе также хранятся имя, телефон, адрес и комментарий, которые вы для него указали. См. /orders.",
        "my_data.erase.ask": (
            "🗑 <b>Удалить мои данные?</b>\n\n"
            "Ваше имя, @username, телефон, город и адрес будут удалены из профиля и из всех ваших "
            "прошлых заказов. Корзина, избранное и тексты отзывов будут удалены.\n\n"
            "Суммы и даты заказов и ваш баланс останутся: они нужны для учёта магазина. "
            "Это действие нельзя отменить."
        ),
        "my_data.erase.done": (
            "✅ Ваши персональные данные удалены.\n\n"
            "Если вы продолжите пользоваться ботом, Telegram снова сообщит ему ваше имя и @username."
        ),
        "my_data.erase.active_orders": (
            "У вас есть заказ в работе, и ваши данные нужны, чтобы его доставить. "
            "Попробуйте ещё раз, когда он будет выполнен или отменён."
        ),
        "my_data.erase.failed": "Не удалось удалить ваши данные здесь. Пожалуйста, напишите в /support.",

        "checkout.summary.agree": "Подтверждая заказ, вы принимаете Условия продажи (/terms) и Политику конфиденциальности (/privacy).",
        "checkout.summary.agree_adults": (
            "Подтверждая заказ, вы принимаете Условия продажи (/terms) и Политику конфиденциальности (/privacy) "
            "и подтверждаете, что вам есть 18 лет."
        ),
    },
    "ro": {
        "cmd.help": "Ajutor",
        "cmd.settings": "Setări",
        "cmd.support": "Suport",
        "cmd.terms": "Condiții de vânzare",
        "cmd.privacy": "Confidențialitate și datele mele",

        "help.text": (
            "ℹ️ <b>Ajutor</b>\n\n"
            "Acest bot este un magazin. Răsfoiți catalogul, adăugați produse în coș și plasați o comandă "
            "cu livrare sau ridicare personală. Tot aici vă puteți urmări comenzile.\n\n"
            "{commands}\n\n"
            "Ceva nu este în regulă cu o comandă? Folosiți /support."
        ),
        "help.command_line": "/{command} — {description}",

        "settings.title": "⚙️ <b>Setări</b>",
        "settings.language": "🌐 Limbă: {language}",
        "settings.mailings_on": "🔔 Noutățile magazinului: activate",
        "settings.mailings_off": "🔕 Noutățile magazinului: dezactivate",
        "btn.privacy": "🔒 Confidențialitate și datele mele",

        "support.text": (
            "🆘 <b>Suport</b>\n\n"
            "Întrebări despre o comandă, o plată sau o livrare: scrieți-ne cu butonul de mai jos "
            "și indicați numărul comenzii. Răspundem cât de repede putem.\n\n"
            "Suportul Telegram și @BotSupport nu pot ajuta cu achizițiile făcute în acest bot. "
            "Vă poate ajuta doar magazinul."
        ),
        "btn.support.write": "✍️ Scrieți suportului",

        "legal.seller_default": "magazinul care administrează acest bot",
        "legal.terms": (
            "📄 <b>Condiții de vânzare</b>\n\n"
            "<b>1. Vânzătorul.</b> Magazinul este administrat de {seller}. Este un vânzător independent. "
            "Telegram nu este parte la achiziția dumneavoastră.\n\n"
            "<b>2. Comenzi.</b> Comanda este plasată când apăsați „Confirmă” la finalizare. Prețurile sunt în {currency} "
            "și sunt cele afișate în acel moment. Dacă un produs nu mai este disponibil, putem anula "
            "comanda și vă returnăm tot ce ați plătit.\n\n"
            "<b>3. Plata.</b> Plătiți cu una dintre metodele oferite la finalizare: transfer MIA sau numerar "
            "la primirea comenzii. O comandă MIA neplătită în {minutes} minute se anulează automat. "
            "Botul nu cere niciodată datele cardului.\n\n"
            "<b>4. Livrarea.</b> Metodele de livrare, prețurile lor și adresa de ridicare sunt afișate la finalizare. "
            "Termenele de livrare sunt estimative.\n\n"
            "<b>5. Probleme cu o comandă.</b> Dacă un produs ajunge deteriorat sau nu este cel comandat, scrieți la "
            "/support și indicați numărul comenzii. Îl înlocuim sau vă returnăm banii. Aceste condiții nu limitează "
            "drepturile dumneavoastră prevăzute de legislația privind protecția consumatorilor.\n\n"
            "<b>6. Sold și coduri promoționale.</b> Soldul din magazin poate fi folosit doar pentru comenzi în acest "
            "magazin și nu se plătește în numerar.\n\n"
            "<b>7. Mesaje.</b> Botul vă scrie despre comenzile dumneavoastră. Noutățile magazinului pot fi oprite "
            "oricând în /settings sau cu butonul de sub fiecare astfel de mesaj.\n\n"
            "<b>8. Suport.</b> Folosiți /support. Suportul Telegram și @BotSupport nu pot ajuta cu achizițiile "
            "făcute în acest bot.\n\n"
            "<b>9. Datele dumneavoastră.</b> Vedeți /privacy.\n\n"
            "<b>10. Modificări.</b> Putem actualiza aceste condiții. Pentru comenzile noi se aplică versiunea afișată aici."
            "{adults}"
        ),
        "legal.terms.adults": (
            "\n\n<b>11. Doar pentru adulți.</b> Magazinul vinde doar persoanelor de cel puțin 18 ani. Plasând o comandă, "
            "confirmați că aveți această vârstă. La livrare vă putem cere o dovadă a vârstei."
        ),
        "legal.privacy": (
            "🔒 <b>Politica de confidențialitate</b>\n\n"
            "Pentru datele dumneavoastră din acest bot răspunde {seller}.\n\n"
            "<b>Ce păstrăm</b>\n"
            "• Din Telegram: ID-ul, numele, @username și limba.\n"
            "• De la dumneavoastră, la finalizarea comenzii: numele pentru livrare, telefonul, orașul, adresa și comentariul la comandă.\n"
            "• Comenzile, coșul, favoritele și recenziile, precum și confirmarea plății pe care o trimiteți pentru un transfer MIA.\n"
            "• Când ați folosit ultima dată botul, dacă primiți noutățile magazinului și notițele personalului despre comenzile dumneavoastră.\n"
            "Nu primim niciodată datele cardului, contactele sau mesajele din celelalte conversații ale dumneavoastră.\n\n"
            "<b>De ce</b>\n"
            "Pentru a prelua, livra și susține comenzile, pentru a vă arăta istoricul comenzilor și pentru a trimite "
            "noutățile magazinului, dacă nu le-ați oprit.\n\n"
            "<b>Cine le vede</b>\n"
            "Personalul magazinului. Serviciul de livrare primește numele, telefonul și adresa necesare livrării. "
            "Nu vindem datele dumneavoastră și nu le dăm nimănui altcuiva, decât dacă legea o cere.\n\n"
            "<b>Cât timp</b>\n"
            "Cât timp folosiți magazinul. Evidența comenzilor se păstrează atât cât cere legislația contabilă și fiscală.\n\n"
            "<b>Opțiunile dumneavoastră</b>\n"
            "• <b>Datele mele</b>, mai jos, arată ce păstrăm despre dumneavoastră.\n"
            "• <b>Șterge datele mele</b>, mai jos, elimină numele, telefonul și adresa. "
            "Sumele și datele comenzilor rămân, fără acestea.\n"
            "• Noutățile magazinului se opresc în /settings.\n"
            "• Pentru orice altceva scrieți la /support. Răspundem în 30 de zile."
        ),
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
        "my_data.label.orders": "Comenzi",
        "my_data.label.mailings": "Noutățile magazinului",
        "my_data.label.registered": "Client din",
        "my_data.on": "activate",
        "my_data.off": "dezactivate",
        "my_data.orders_hint": "Fiecare comandă păstrează și numele, telefonul, adresa și comentariul indicate pentru ea. Vedeți /orders.",
        "my_data.erase.ask": (
            "🗑 <b>Ștergeți datele mele?</b>\n\n"
            "Numele, @username, telefonul, orașul și adresa sunt eliminate din profil și din toate "
            "comenzile anterioare. Coșul, favoritele și textele recenziilor sunt șterse.\n\n"
            "Sumele și datele comenzilor și soldul rămân, deoarece sunt necesare pentru evidența magazinului. "
            "Acțiunea nu poate fi anulată."
        ),
        "my_data.erase.done": (
            "✅ Datele dumneavoastră personale au fost șterse.\n\n"
            "Dacă folosiți botul în continuare, Telegram îi transmite din nou numele și @username."
        ),
        "my_data.erase.active_orders": (
            "Aveți încă o comandă în lucru, iar datele sunt necesare pentru a o livra. "
            "Încercați din nou după ce este finalizată sau anulată."
        ),
        "my_data.erase.failed": "Nu am putut șterge datele aici. Vă rugăm să scrieți la /support.",

        "checkout.summary.agree": "Confirmând, acceptați Condițiile de vânzare (/terms) și Politica de confidențialitate (/privacy).",
        "checkout.summary.agree_adults": (
            "Confirmând, acceptați Condițiile de vânzare (/terms) și Politica de confidențialitate (/privacy) "
            "și confirmați că aveți cel puțin 18 ani."
        ),
    },
}
