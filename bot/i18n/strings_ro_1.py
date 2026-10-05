TRANSLATIONS = {"ro": {
    # === Common Buttons ===
    "btn.shop": "🏪 Magazin",
    "btn.search": "🔍 Căutare în catalog",
    "btn.rules": "📜 Reguli",
    "btn.profile": "👤 Profil",
    "btn.support": "🆘 Suport",
    "btn.channel": "ℹ Canal de știri",
    "btn.admin_menu": "🎛 Panou admin",
    "btn.back": "⬅️ Înapoi",
    "btn.to_menu": "🏠 Meniu",
    "btn.close": "✖ Închide",
    "btn.buy": "🛍 Comandă acum",
    "btn.yes": "✅ Da",
    "btn.no": "❌ Nu",
    "btn.check": "🔄 Verifică",
    "btn.check_subscription": "🔄 Verifică abonarea",

    # === Admin Buttons (user management shortcuts) ===
    "btn.admin.view_profile": "👁 Vezi profilul",
    "btn.admin.promote": "⬆️ Numește admin",
    "btn.admin.demote": "⬇️ Retrage drepturile de admin",
    "btn.admin.replenish_user": "💸 Alimentează soldul",
    "btn.admin.deduct_user": "💳 Debitează din sold",
    "btn.admin.block": "🚫 Blochează",
    "btn.admin.unblock": "✅ Deblochează",

    # === Titles / Generic Texts ===
    "menu.title": "⛩️ Meniu principal",
    "profile.caption": "👤 <b>Profil</b> — <a href='tg://user?id={id}'>{name}</a>",
    "rules.not_set": "❌ Regulile nu au fost adăugate",

    # === Profile ===
    "btn.referral": "🎲 Sistem de referire",
    "profile.referral_id": "👤 <b>Referent</b> — <code>{id}</code>",

    # === Subscription Flow ===
    "subscribe.prompt": "Mai întâi, abonați-vă la canalul de știri",
    "subscribe.open_channel": "Deschide canalul",

    # === Profile Info Lines ===
    "profile.id": "🆔 <b>ID</b> — <code>{id}</code>",
    "profile.balance": "💳 <b>Sold</b> — <code>{amount}</code> {currency}",
    "profile.total_topup": "💵 <b>Total alimentat</b> — <code>{amount}</code> {currency}",
    "profile.registration_date": "🕢 <b>Data înregistrării</b> — <code>{dt}</code>",

    # === Referral ===
    "referral.title": "💚 Sistem de referire",
    "referral.link": "🔗 Link: https://t.me/{bot_username}?start={user_id}",
    "referral.count": "Număr de referiți: {count}",
    "referral.description": (
        "📔 Sistemul de referire vă permite să câștigați fără nicio investiție. "
        "Distribuiți link-ul dumneavoastră personal și veți primi {percent}% din valoarea "
        "comenzilor finalizate ale referiților dumneavoastră, creditat în soldul magazinului."
    ),
    "btn.view_referrals": "👥 Referiții mei",
    "btn.view_earnings": "💰 Câștigurile mele",
    "btn.back_to_referral": "⬅️ Înapoi la sistemul de referire",

    "referrals.list.title": "👥 Referiții dumneavoastră:",
    "referrals.list.empty": "Nu aveți încă referiți activi",
    "referrals.item.format": "ID: {telegram_id} | Câștigat: {total_earned} {currency}",

    "referral.earnings.title": "💰 Câștiguri de la referitul <code>{telegram_id}</code> (<a href='tg://user?id={telegram_id}'>{name}</a>):",
    "referral.earnings.empty": "Nu există încă câștiguri de la acest referit <code>{id}</code> (<a href='tg://user?id={id}'>{name}</a>)",
    "referral.earning.format": "{amount} {currency} | {date} | (din {original_amount} {currency})",
    "referral.item.info": ("💰 Număr câștig: <code>{id}</code>\n"
                           "👤 Referit: <code>{telegram_id}</code> (<a href='tg://user?id={telegram_id}'>{name}</a>)\n"
                           "🔢 Sumă: {amount} {currency}\n"
                           "🕘 Data: <code>{date}</code>\n"
                           "💵 Dintr-o comandă de {original_amount} {currency}"),

    "all.earnings.title": "💰 Toate câștigurile dumneavoastră din referiri:",
    "all.earnings.empty": "Nu aveți încă câștiguri din referiri",
    "all.earning.format": "{amount} {currency} de la ID:{referral_id} | {date}",

    "referrals.stats.template": (
        "📊 Statistici ale sistemului de referire:\n\n"
        "👥 Referiți activi: {active_count}\n"
        "💰 Total câștigat: {total_earned} {currency}\n"
        "📈 Total comenzi ale referiților: {total_original} {currency}\n"
        "🔢 Număr de câștiguri: {earnings_count}"
    ),

    # === Admin: Main Menu ===
    "admin.menu.main": "⛩️ Meniu admin",
    "admin.menu.shop": "🛒 Gestionarea magazinului",
    "admin.menu.goods": "📦 Gestionarea produselor",
    "admin.menu.categories": "📂 Gestionarea categoriilor",
    "admin.menu.users": "👥 Gestionarea utilizatorilor",
    "admin.menu.broadcast": "📝 Newsletter",
    "admin.menu.roles": "🛡 Gestionarea rolurilor",
    "admin.menu.rights": "Permisiuni insuficiente",

    # === Admin: Role Management ===
    "admin.roles.list_title": "🛡 Rolurile sistemului:",
    "admin.roles.create": "➕ Creează rol",
    "admin.roles.edit": "✏️ Editează",
    "admin.roles.delete": "🗑 Șterge",
    "admin.roles.detail": "🛡 <b>Rol</b>: {name}\n📋 Permisiuni: {perms}\n👥 Utilizatori: {users}",
    "admin.roles.prompt_name": "Introduceți numele rolului (maximum 64 de caractere):",
    "admin.roles.name_invalid": "⚠️ Nume invalid (gol sau depășește 64 de caractere).",
    "admin.roles.name_exists": "❌ Un rol cu acest nume există deja",
    "admin.roles.select_perms": "Selectați permisiunile pentru rolul \"{name}\":",
    "admin.roles.confirm": "✅ Confirmă",
    "admin.roles.created": "✅ Rolul \"{name}\" a fost creat",
    "admin.roles.updated": "✅ Rolul \"{name}\" a fost actualizat",
    "admin.roles.deleted": "✅ Rolul a fost șters",
    "admin.roles.delete_confirm": "Sigur doriți să ștergeți rolul \"{name}\"?",
    "admin.roles.delete_fail": "❌ Ștergerea a eșuat: {error}",
    "admin.roles.perm_denied": "⚠️ Permisiuni insuficiente pentru această acțiune",
    "admin.roles.assign_prompt": "Selectați un rol pentru utilizatorul {id}:",
    "admin.roles.assigned": "✅ Rolul {role} a fost atribuit utilizatorului {name}",
    "admin.roles.assigned_notify": "ℹ️ Rolul dumneavoastră a fost setat la: {role}",
    "admin.roles.edit_name_prompt": "Introduceți noul nume al rolului (sau /skip pentru a-l păstra pe cel actual):",
    "btn.admin.assign_role": "🛡 Atribuie rol",

    # === Admin: User Management ===
    "admin.users.prompt_enter_id": "👤 Introduceți ID-ul utilizatorului pentru a vizualiza / edita datele",
    "admin.users.invalid_id": "⚠️ Introduceți un ID de utilizator numeric valid.",
    "admin.users.profile_unavailable": "❌ Profil indisponibil (un astfel de utilizator nu a existat niciodată)",
    "admin.users.not_found": "❌ Utilizatorul nu a fost găsit",
    "admin.users.cannot_change_owner": "Nu puteți schimba rolul proprietarului",
    "admin.users.referrals": "👥 <b>Referiții utilizatorului</b> — {count}",
    "admin.users.btn.view_referrals": "👥 Referiții utilizatorului",
    "admin.users.btn.view_earnings": "💰 Câștigurile utilizatorului",
    "admin.users.role": "🎛 <b>Rol</b> — {role}",
    "admin.users.set_admin.success": "✅ Rolul a fost atribuit utilizatorului {name}",
    "admin.users.set_admin.notify": "✅ V-a fost acordat rolul de ADMIN",
    "admin.users.remove_admin.success": "✅ Rolul de admin a fost retras utilizatorului {name}",
    "admin.users.remove_admin.notify": "❌ Rolul dumneavoastră de ADMIN a fost retras",
    "admin.users.balance.topped": "✅ Soldul utilizatorului {name} a fost alimentat cu {amount} {currency}",
    "admin.users.balance.topped.notify": "✅ Soldul dumneavoastră a fost alimentat cu {amount} {currency}",
    "admin.users.balance.deducted": "✅ Au fost debitați {amount} {currency} din soldul utilizatorului {name}",
    "admin.users.balance.deducted.notify": "ℹ️ Din soldul dumneavoastră au fost debitați {amount} {currency}",
    "admin.users.balance.insufficient": "❌ Fonduri insuficiente. Sold curent: {balance} {currency}",
    "admin.users.blocked.success": "🚫 Utilizatorul {name} a fost blocat",
    "admin.users.unblocked.success": "✅ Utilizatorul {name} a fost deblocat",
    "admin.users.cannot_block_owner": "❌ Proprietarul nu poate fi blocat",
    "admin.users.status.blocked": "🚫 <b>Stare</b> — Blocat",

    # === Admin: Shop Management Menu ===
    "admin.shop.menu.title": "⛩️ Gestionarea magazinului",
    "admin.shop.menu.statistics": "📊 Statistici",
    "admin.shop.menu.logs": "📁 Afișează jurnalele",
    "admin.shop.menu.users": "👤 Utilizatori",

    # === Admin: Categories Management ===
    "admin.categories.menu.title": "⛩️ Gestionarea categoriilor",
    "admin.categories.add": "➕ Adaugă categorie",
    "admin.categories.rename": "✏️ Redenumește categoria",
    "admin.categories.delete": "🗑 Șterge categoria",
    "admin.categories.prompt.add": "Introduceți numele noii categorii:",
    "admin.categories.prompt.delete": "Introduceți numele categoriei de șters:",
    "admin.categories.prompt.rename.old": "Introduceți numele actual al categoriei de redenumit:",
    "admin.categories.prompt.rename.new": "Introduceți noul nume al categoriei:",
    "admin.categories.add.exist": "❌ Categoria nu a fost creată (există deja)",
    "admin.categories.add.success": "✅ Categoria a fost creată",
    "admin.categories.delete.not_found": "❌ Categoria nu a fost ștearsă (nu există)",
    "admin.categories.delete.success": "✅ Categoria a fost ștearsă",
    "admin.categories.rename.not_found": "❌ Categoria nu poate fi actualizată (nu există)",
    "admin.categories.rename.exist": "❌ Redenumirea nu este posibilă (există deja o categorie cu acest nume)",
    "admin.categories.rename.success": "✅ Categoria \"{old}\" a fost redenumită în \"{new}\"",

    # === Admin: Time-limited sales ===
    "admin.goods.sale_manage": "🔥 Gestionează reducerea",
    "admin.sale.prompt.name": "Introduceți numele produsului pentru care doriți să setați o reducere:",
    "admin.sale.not_found": "❌ Nu a fost găsit niciun produs cu acest nume.",
    "admin.sale.current.active": "ℹ️ Reducere curentă: <b>{percent}%</b> până la <b>{until}</b> (UTC).",
    "admin.sale.current.none": "ℹ️ Acest produs nu are momentan nicio reducere.",
    "admin.sale.prompt.percent": "Introduceți procentul reducerii (1–100).\nTrimiteți <b>0</b> pentru a elimina reducerea.",
    "admin.sale.percent.invalid": "⚠️ Procent invalid. Introduceți un număr întreg de la 0 la 100.",
    "admin.sale.disabled": "✅ Reducerea pentru «{name}» a fost eliminată.",
    "admin.sale.prompt.days": "Pentru câte zile să fie valabilă reducerea? Introduceți un număr întreg (de ex. 3).",
    "admin.sale.days.invalid": "⚠️ Durată invalidă. Introduceți un număr întreg de zile mai mare decât 0.",
    "admin.sale.success": "✅ Reducerea de <b>{percent}%</b> a fost setată pentru «{name}» până la <b>{until}</b> (UTC).",

    # === Admin: Logs ===
    "admin.shop.logs.caption": "Jurnalele botului",
    "admin.shop.logs.empty": "❗️ Nu există încă jurnale",
    "admin.shop.logs.too_large": "⚠️ Jurnalele sunt prea mari pentru a fi trimise ({files}) — preluați-le de pe disc.",

    # === Admin: Statistics ===
    "admin.shop.stats.roles_header": "\n➖➖➖➖➖➖➖➖➖➖➖➖➖\n◽<b>ROLURI</b>",

    # === Admin: Lists & Broadcast ===
    "admin.shop.users.title": "Utilizatorii botului:",
    "broadcast.prompt": "Trimiteți mesajul pentru newsletter:",
    "broadcast.creating": "📤 Se pornește newsletter-ul...\n👥 Total utilizatori: {ids}",
    "broadcast.progress": (
        "📤 Trimiterea este în curs...\n\n"
        "📊 Progres: {progress:.1f}%\n"
        "✅ Trimise: {sent}/{total}\n"
        "❌ Erori: {failed}\n"
        "⏱ Timp scurs: {time} sec"),
    "broadcast.done": (
        "✅ Trimiterea s-a încheiat! \n\n"
        "📊 Statistici:📊\n"
        "👥 Total: {total}\n"
        "✅ Livrate: {sent}\n"
        "❌ Nelivrate: {failed}\n"
        "🚫 Bot blocat: {blocked}\n"
        "📈 Rata de succes: {success}%\n"
        "⏱ Timp: {duration} sec"
    ),
    "broadcast.cancel": "❌ Trimiterea a fost anulată.",
    "broadcast.warning": "Nu există nicio trimitere activă",
    "broadcast.already_running": "⏳ O trimitere este deja în desfășurare. Așteptați finalizarea ei.",
    "broadcast.btn.cancel": "🛑 Anulează trimiterea",
}}
