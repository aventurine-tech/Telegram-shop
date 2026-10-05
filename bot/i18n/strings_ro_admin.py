TRANSLATIONS = {"ro": {
        # === Admin: console ===
        "admin.menu.orders": "📦 Comenzi",

        # === Admin: Products menu / add ===
        "admin.goods.menu.title": "⛩️ Gestionarea produselor",
        "admin.goods.add_position": "➕ Adaugă produs",
        "admin.goods.stock_manage": "📦 Stoc",
        "admin.goods.update_position": "📝 Editează produs",
        "admin.goods.delete_position": "❌ Șterge produs",
        "admin.goods.add.prompt.name": "Introduceți denumirea produsului",
        "admin.goods.add.name.exists": "❌ Produsul nu poate fi creat (există deja)",
        "admin.goods.add.name.invalid": "⚠️ Denumire invalidă (1–100 de caractere, fără caractere de control).",
        "admin.goods.add.prompt.description": "Introduceți descrierea produsului:",
        "admin.goods.add.prompt.price": "Introduceți prețul produsului (un număr în {currency}):",
        "admin.goods.add.price.invalid": "⚠️ Preț invalid. Vă rugăm să introduceți un număr întreg.",
        "admin.goods.add.prompt.category": "Introduceți categoria din care face parte produsul:",
        "admin.goods.add.category.not_found": "❌ Produsul nu poate fi creat (categorie invalidă)",
        "admin.goods.add.prompt.stock": "Câte unități sunt în stoc acum? Introduceți un număr întreg (0 înseamnă stoc epuizat):",
        "admin.goods.add.result.created": "✅ Produsul „{name}” a fost creat. În stoc: <b>{qty}</b> buc.",
        "admin.goods.prompt.enter_item_name": "Introduceți denumirea produsului",
        "admin.goods.position.not_found": "❌ Acest produs nu există",
        "admin.goods.channel.arrival": "📦 Produs nou: <b>{name}</b>\nÎn stoc: <b>{qty}</b> buc.",

        # === Admin: product pictures ===
        "admin.goods.add.prompt.photo": "Trimiteți fotografia produsului (o puteți trimite ca fișier, pentru a păstra calitatea originală) sau apăsați «Omite».",
        "admin.goods.photo.btn.skip": "⏭ Omite",
        "admin.goods.photo.btn.change": "🖼 Schimbă fotografia",
        "admin.goods.photo.btn.remove": "🗑 Șterge fotografia",
        "admin.goods.photo.status.yes": "🖼 Fotografie: da",
        "admin.goods.photo.status.no": "🖼 Fotografie: nu",
        "admin.goods.photo.prompt.change": "Trimiteți noua fotografie a produsului (o puteți trimite ca fișier, pentru a păstra calitatea originală):",
        "admin.goods.photo.reprompt": "⚠️ Vă rugăm să trimiteți o fotografie sau o imagine ca fișier.",
        "admin.goods.photo.too_large": "⚠️ Fișierul este prea mare (cel mult 10 MB). Vă rugăm să trimiteți altul.",
        "admin.goods.photo.invalid": "⚠️ Imaginea nu a putut fi citită. Vă rugăm să trimiteți alt fișier.",
        "admin.goods.photo.unsupported": "⚠️ Sunt acceptate doar JPEG, PNG și WEBP. Vă rugăm să trimiteți alt fișier.",
        "admin.goods.photo.download_failed": "⚠️ Fișierul nu a putut fi descărcat din Telegram. Vă rugăm să încercați din nou.",
        "admin.goods.photo.updated": "✅ Fotografia produsului a fost salvată.",
        "admin.goods.photo.removed": "✅ Fotografia produsului a fost ștearsă.",
        "admin.goods.photo.none": "ℹ️ Produsul nu are fotografie.",
        "admin.goods.photo.remove.confirm": "Ștergeți fotografia produsului „{name}”?",
        "admin.goods.photo.remove.yes": "✅ Da, șterge",
        "admin.goods.photo.remove.no": "↩️ Anulează",

        # === Admin: Stock screen ===
        "admin.goods.stock.card": (
            "📦 <b>{name}</b>\n"
            "💵 Preț: <code>{price}</code> {currency}\n"
            "🏬 În stoc: <b>{stock}</b> buc."
        ),
        "admin.goods.stock.btn.set": "✏️ Setează",
        "admin.goods.stock.btn.add": "➕ Adaugă",
        "admin.goods.stock.btn.sub": "➖ Scade",
        "admin.goods.stock.prompt.set": "Introduceți noul stoc (un număr întreg, 0 înseamnă stoc epuizat):",
        "admin.goods.stock.prompt.add": "Câte unități se adaugă la stoc? Introduceți un număr întreg:",
        "admin.goods.stock.prompt.sub": "Câte unități se scad din stoc? Introduceți un număr întreg:",
        "admin.goods.stock.invalid": "⚠️ Introduceți un număr întreg nenegativ (cel puțin 1 pentru adăugare și scădere).",
        "admin.goods.stock.updated": "✅ Stoc actualizat: {old} → <b>{new}</b> buc.",

        # === Admin: Product update flow ===
        "admin.goods.update.prompt.name": "Introduceți denumirea produsului",
        "admin.goods.update.not_exists": "❌ Produsul nu poate fi actualizat (nu există)",
        "admin.goods.update.prompt.new_name": "Introduceți noua denumire a produsului:",
        "admin.goods.update.prompt.description": "Introduceți descrierea produsului:",
        "admin.goods.update.prompt.category": "Introduceți categoria produsului (în prezent „{category}”):",
        "admin.goods.update.keep_category": "Păstrează categoria curentă",
        "admin.goods.update.category.not_found": "❌ Această categorie nu există. Introduceți denumirea unei categorii existente.",
        "admin.goods.update.position.invalid": "Produsul nu a fost găsit.",
        "admin.goods.update.position.exists": "Un produs cu această denumire există deja.",
        "admin.goods.update.success": "✅ Produsul a fost actualizat",

        # === Admin: Product delete flow ===
        "admin.goods.delete.prompt.name": "Introduceți denumirea produsului",
        "admin.goods.delete.position.not_found": "❌ Produsul nu a fost șters (nu există)",
        "admin.goods.delete.position.success": "✅ Produsul a fost șters",

        # === Admin: Statistics ===
        "admin.shop.stats.template": (
            "Statistica magazinului:\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "<b>◽UTILIZATORI</b>\n"
            "◾️Noi în 24 h: {today_users}\n"
            "◾️Total: {users}\n"
            "◾️Clienți: {buyers}\n"
            "◾️Blocați: {blocked}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>COMENZI</b>\n"
            "◾Noi (în așteptare): {new_orders}\n"
            "◾Ultimele 24 h: {today_sold_count} în valoare de {today_orders} {currency}\n"
            "◾Venit, în total: {all_orders} {currency}\n"
            "◾Comanda medie: {avg_order} {currency}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>SOLDURILE CLIENȚILOR</b>\n"
            "◾Realimentări în 24 h: {today_topups} {currency}\n"
            "◾Fonduri în solduri: {system_balance} {currency}\n"
            "◾Total realimentat: {all_topups} {currency}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>CATALOG</b>\n"
            "◾În stoc: {items} buc.\n"
            "◾Produse: {goods}\n"
            "◾Categorii: {categories}\n"
            "◾Unități vândute: {sold_count}"
        ),

        # === Admin: Users (orders) ===
        "admin.users.orders_count": "📦 <b>Comenzi</b> — {count}",
        "admin.users.btn.orders": "📦 Comenzile clientului",
        "admin.users.orders.title": "Comenzile clientului:",
        "admin.users.orders.empty": "ℹ️ Acest client nu are încă nicio comandă.",
        "admin.users.orders.item": "#{id} · {total} {currency} · {status}",

        # === Admin: Orders console ===
        "admin.orders.menu.title": "📦 Comenzi\n\nAlegeți o listă:",
        "admin.orders.list.new": "🆕 Noi",
        "admin.orders.list.chk": "🔎 Verifică plăți MIA",
        "admin.orders.list.cnf": "✅ Confirmate",
        "admin.orders.list.shp": "🚚 Expediate",
        "admin.orders.list.cmp": "🏁 Finalizate",
        "admin.orders.list.can": "❌ Anulate",
        "admin.orders.list.new.title": "🆕 Comenzi noi:",
        "admin.orders.list.chk.title": "🔎 Clientul a anunțat o plată MIA — verificați dacă a ajuns:",
        "admin.orders.list.cnf.title": "✅ Comenzi confirmate:",
        "admin.orders.list.shp.title": "🚚 Comenzi expediate:",
        "admin.orders.list.cmp.title": "🏁 Comenzi finalizate:",
        "admin.orders.list.can.title": "❌ Comenzi anulate:",
        "admin.orders.list.empty": "ℹ️ Nu există comenzi în această listă.",
        "admin.orders.find": "🔎 Caută comanda după număr",
        "admin.orders.find.prompt": "Introduceți numărul comenzii:",
        "admin.orders.btn.proof": "🖼 Captura plății",
        "admin.orders.btn.confirm": "✅ Confirmă comanda",
        "admin.orders.btn.ship": "🚚 Expediată / gata de ridicare",
        "admin.orders.btn.complete": "🏁 Finalizată",
        "admin.orders.btn.cancel": "❌ Anulează comanda",
        "admin.orders.btn.contact": "💬 Scrie clientului",
        "admin.orders.proof.caption": "🖼 Captura plății pentru comanda #{id}",
        "admin.orders.cancel.confirm": "❓ Anulați comanda #{id}? Produsele revin în stoc, iar partea achitată din sold se returnează clientului.",
        "admin.orders.cancel.refund_warning": "⚠️ Clientul a achitat deja {amount} {currency} (MIA sau numerar). Botul nu returnează acești bani — rambursați-i manual după anulare.",
        "admin.orders.cancel.refund_manual": "↩️ Rambursați manual {amount} {currency} clientului (plata este marcată ca „returnată”).",
        "admin.orders.cancel.yes": "✅ Da, anulează",
        "admin.orders.cancel.no": "↩️ Nu",
        "admin.orders.done.payment_confirmed": "✅ Plata a fost confirmată, comanda este acceptată. Clientul a fost notificat.",
        "admin.orders.done.payment_rejected": "⚠️ Transferul nu a fost găsit: comanda revine la „se așteaptă plata”. Clientul a fost notificat.",
        "admin.orders.done.confirmed": "✅ Comanda a fost confirmată. Clientul a fost notificat.",
        "admin.orders.done.shipped": "🚚 Comanda a fost marcată ca expediată. Clientul a fost notificat.",
        "admin.orders.done.completed": "🏁 Comanda a fost finalizată. Clientul a fost notificat.",
        "admin.orders.done.cancelled": "❌ Comanda a fost anulată. Clientul a fost notificat.",
        "admin.orders.err.not_found": "❌ Comanda nu a fost găsită",
        "admin.orders.err.not_mia": "❌ Aceasta nu este o comandă MIA",
        "admin.orders.err.not_awaiting_payment": "❌ Comanda nu mai așteaptă verificarea plății (este posibil ca un alt angajat să o fi procesat)",
        "admin.orders.err.invalid_transition": "❌ Acest status nu poate fi setat acum",
        "admin.orders.err.payment_not_confirmed": "❌ Confirmați mai întâi plata MIA",
        "admin.orders.err.not_cancellable": "❌ Această comandă nu mai poate fi anulată",
        "admin.orders.err.no_proof": "ℹ️ Clientul nu a trimis nicio captură",
        "admin.orders.err.proof_unavailable": "⚠️ Captura nu a putut fi afișată",
}}
