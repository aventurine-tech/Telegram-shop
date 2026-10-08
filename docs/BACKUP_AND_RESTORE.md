# Backup and restore

Everything the shop owns — customers, orders, catalog, product pictures, web accounts — lives in PostgreSQL. Back up the
database and you have backed up the shop. (`.env` is separate: keep a copy of it somewhere safe too, it holds your secrets.)

## Back up
```bash
./scripts/backup_db.sh
```
Writes `backups/shop-YYYYmmdd-HHMMSS.dump` (compressed, readable only by you) from the compose `db` service, checks that the
dump can be read back, and keeps the newest 14 (`BACKUP_KEEP=30` for more, `BACKUP_DIR=/other/place` to move them).
`backups/` is git-ignored; dumps contain customer data, so never commit, e-mail or paste them.

Run it every night with cron:
```
30 3 * * *  cd /path/to/Telegram-shop && ./scripts/backup_db.sh >> logs/backup.log 2>&1
```
**Copy the dumps off the machine** (another server, a cloud drive, a USB disk): a backup on the same disk does not survive the disk.

## Restore
```bash
./scripts/restore_db.sh backups/shop-20261008-033000.dump
```
Asks you to type the database name, stops the bot, **replaces** the database with the dump, starts the bot again (pending
migrations run on start). Orders placed after the dump was taken are lost, so restore from the newest good dump.

**Practice once on a spare machine** (install the project, `docker compose up -d db`, run the restore, open the web panel).
A backup that was never restored is only a hope.

## Without Docker
`DB_EXEC="" PGHOST=localhost ./scripts/backup_db.sh` (and `restore_db.sh`) use the PostgreSQL client tools on the machine
instead; the bot is then not stopped for you, stop it yourself before a restore.

## Erasing a customer's data on request
Web panel → Clients → open the client → **Erase personal data** (Admin accounts only). It removes name, @username, phone,
address, city and notes from the profile and from every one of their orders, and deletes their cart, favorites, restock
subscriptions and review texts. Orders (amounts, items, dates), balance, referral links and star ratings stay. It refuses
the owner account and clients with orders still in progress. Erased data also lives on in **old backups**: expire those
on your normal schedule, and when you restore an old dump, erase again whoever asked in the meantime.
