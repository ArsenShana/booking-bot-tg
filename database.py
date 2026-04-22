import aiosqlite
import json
import secrets
from datetime import datetime, date, timedelta
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                duration_min INTEGER NOT NULL DEFAULT 60,
                prepayment_amount REAL DEFAULT 0,
                active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS working_hours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_of_week INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS blocked_dates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                reason TEXT
            );

            CREATE TABLE IF NOT EXISTS blocked_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                start_time TEXT DEFAULT NULL,
                end_time TEXT DEFAULT NULL,
                reason TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS clients (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                banned INTEGER DEFAULT 0,
                ban_reason TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                service_ids TEXT NOT NULL,
                total_price REAL NOT NULL,
                prepayment_amount REAL DEFAULT 0,
                prepayment_paid INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                notes TEXT,
                client_msg_id INTEGER DEFAULT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS waitlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                service_ids TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                expires_at TEXT NOT NULL
            );
        """)
        await db.commit()

        defaults = [
            ('master_name', 'Мастер'),
            ('master_bio', 'Профессиональный мастер'),
            ('master_location', 'Москва'),
            ('payment_card', ''),
            ('payment_phone', ''),
            ('payment_bank', 'Сбербанк'),
            ('prepayment_required', '0'),
            ('prepayment_percent', '30'),
            ('slot_duration', '30'),
            ('master_photo_id', ''),
            ('ban_photo_id', ''),
            ('payment_button_text', 'Оплатить'),
            ('payment_button_url', ''),
            ('admin_notifications', '1'),
            ('same_day_notifications', '1'),
            ('client_reminders', '1'),
            ('prepayment_mode', 'manual'),
            ('master_avatar_url', ''),
            ('instagram_url', ''),
        ]
        for key, value in defaults:
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
        await db.commit()

        # Migration: add user_id to admin_tokens if missing
        try:
            await db.execute("ALTER TABLE admin_tokens ADD COLUMN user_id INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass

        # Migration: add client_msg_id to appointments if missing
        try:
            await db.execute("ALTER TABLE appointments ADD COLUMN client_msg_id INTEGER DEFAULT NULL")
            await db.commit()
        except Exception:
            pass

        # Migration: add photo_file_id to clients if missing
        try:
            await db.execute("ALTER TABLE clients ADD COLUMN photo_file_id TEXT DEFAULT NULL")
            await db.commit()
        except Exception:
            pass

        # Migration: add description to services
        try:
            await db.execute("ALTER TABLE services ADD COLUMN description TEXT DEFAULT ''")
            await db.commit()
        except Exception:
            pass

        # Migration: add price_type and price_to to services
        try:
            await db.execute("ALTER TABLE services ADD COLUMN price_type TEXT DEFAULT 'fixed'")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE services ADD COLUMN price_to REAL DEFAULT NULL")
            await db.commit()
        except Exception:
            pass

        # Migration: add reminder flags to appointments
        try:
            await db.execute("ALTER TABLE appointments ADD COLUMN reminder_day_sent INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE appointments ADD COLUMN reminder_hour_sent INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass


# ─── Settings ───────────────────────────────────────────────────────────────

async def get_settings() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT key, value FROM settings") as cur:
            rows = await cur.fetchall()
        return {r['key']: r['value'] for r in rows}


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        await db.commit()


# ─── Services ────────────────────────────────────────────────────────────────

async def get_services(active_only=True) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM services"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY sort_order, id"
        async with db.execute(q) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_service(service_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM services WHERE id = ?", (service_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def add_service(name: str, price: float, duration_min: int, prepayment: float = 0,
                      price_type: str = 'fixed', price_to: float | None = None,
                      description: str = '') -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO services (name, price, duration_min, prepayment_amount, price_type, price_to, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, price, duration_min, prepayment, price_type, price_to, description)
        )
        await db.commit()
        return cur.lastrowid


async def update_service(service_id: int, **kwargs):
    fields = ', '.join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [service_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE services SET {fields} WHERE id = ?", values)
        await db.commit()


async def delete_service(service_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE services SET active = 0 WHERE id = ?", (service_id,))
        await db.commit()


# ─── Working Hours ────────────────────────────────────────────────────────────

async def get_working_hours() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM working_hours WHERE active = 1 ORDER BY day_of_week"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def set_working_hours(day_of_week: int, start_time: str, end_time: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM working_hours WHERE day_of_week = ?", (day_of_week,))
        await db.execute(
            "INSERT INTO working_hours (day_of_week, start_time, end_time) VALUES (?, ?, ?)",
            (day_of_week, start_time, end_time)
        )
        await db.commit()


async def delete_working_hours(day_of_week: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM working_hours WHERE day_of_week = ?", (day_of_week,))
        await db.commit()


# ─── Blocked Dates ────────────────────────────────────────────────────────────

async def get_blocked_dates() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM blocked_dates ORDER BY date") as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def block_date(date_str: str, reason: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO blocked_dates (date, reason) VALUES (?, ?)",
            (date_str, reason)
        )
        await db.commit()


async def unblock_date(date_str: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM blocked_dates WHERE date = ?", (date_str,))
        await db.commit()


# ─── Blocked Periods (admin UI: days off + breaks) ───────────────────────────

async def add_blocked_period(date_str: str, start_time: str | None, end_time: str | None, reason: str = '') -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO blocked_periods (date, start_time, end_time, reason) VALUES (?, ?, ?, ?)",
            (date_str, start_time, end_time, reason)
        )
        await db.commit()
        return cur.lastrowid


async def get_all_blocked_periods() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM blocked_periods ORDER BY date, start_time") as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_blocked_periods_for_date(date_str: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM blocked_periods WHERE date = ?", (date_str,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def delete_blocked_period(period_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM blocked_periods WHERE id = ?", (period_id,))
        await db.commit()


# ─── Clients ─────────────────────────────────────────────────────────────────

async def upsert_client(telegram_id: int, username: str, first_name: str, last_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO clients (telegram_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name
        """, (telegram_id, username, first_name, last_name))
        await db.commit()


async def save_client_photo(telegram_id: int, file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE clients SET photo_file_id = ? WHERE telegram_id = ?",
            (file_id, telegram_id)
        )
        await db.commit()


async def get_client(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clients WHERE telegram_id = ?", (telegram_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def get_all_clients() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*,
                COUNT(CASE WHEN a.status != 'cancelled' THEN 1 END) as visit_count,
                COUNT(a.id) as ever_booked,
                MAX(a.date) as last_visit,
                COALESCE(SUM(CASE WHEN a.status != 'cancelled' THEN a.total_price ELSE 0 END), 0) as total_spent
            FROM clients c
            LEFT JOIN appointments a ON a.client_id = c.telegram_id
            GROUP BY c.telegram_id
            ORDER BY last_visit DESC NULLS LAST
        """) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_appointments_for_reminders(target_date: str, kind: str) -> list:
    """kind = 'day' or 'hour'"""
    col = f"reminder_{kind}_sent"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"""
            SELECT * FROM appointments
            WHERE date = ? AND status IN ('confirmed','pending','new')
              AND client_id IS NOT NULL AND {col} = 0
        """, (target_date,)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def mark_reminder_sent(appt_id: int, kind: str):
    col = f"reminder_{kind}_sent"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE appointments SET {col} = 1 WHERE id = ?", (appt_id,))
        await db.commit()


async def ban_client(telegram_id: int, reason: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE clients SET banned = 1, ban_reason = ? WHERE telegram_id = ?",
            (reason, telegram_id)
        )
        await db.commit()


async def unban_client(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE clients SET banned = 0, ban_reason = '' WHERE telegram_id = ?",
            (telegram_id,)
        )
        await db.commit()


async def is_client_banned(telegram_id: int) -> tuple[bool, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT banned, ban_reason FROM clients WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
        if row and row['banned']:
            return True, row['ban_reason'] or ''
        return False, ''


async def get_active_appointments_count(telegram_id) -> int:
    """Count future/today appointments that are not cancelled or completed."""
    from datetime import date
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT COUNT(*) as c FROM appointments
               WHERE client_id = ? AND date >= ?
               AND status NOT IN ('cancelled', 'completed')""",
            (telegram_id, today)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0


# ─── Appointments ─────────────────────────────────────────────────────────────

async def create_appointment(
    date_str: str, time_str: str,
    service_ids: list, total_price: float, prepayment_amount: float,
    name: str = '', phone: str = '', client_id: int = None, notes: str = ''
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO appointments
                (client_id, name, phone, date, time, service_ids, total_price, prepayment_amount, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            client_id, name, phone, date_str, time_str,
            json.dumps(service_ids), total_price, prepayment_amount,
            'pending', notes
        ))
        await db.commit()
        return cur.lastrowid


async def get_appointment(appointment_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        appt = dict(row)
        appt['service_ids'] = json.loads(appt['service_ids'])
        return appt


async def get_appointments_by_tg_id(tg_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        today = date.today().isoformat()
        async with db.execute(
            "SELECT * FROM appointments WHERE client_id = ? AND date >= ? AND status != 'cancelled' ORDER BY date, time",
            (tg_id, today)
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            appt = dict(r)
            appt['service_ids'] = json.loads(appt['service_ids'])
            result.append(appt)
        return result


async def get_appointments_by_phone(phone: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        today = date.today().isoformat()
        async with db.execute(
            "SELECT * FROM appointments WHERE phone = ? AND date >= ? AND status != 'cancelled' ORDER BY date, time",
            (phone, today)
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            appt = dict(r)
            appt['service_ids'] = json.loads(appt['service_ids'])
            result.append(appt)
        return result


async def get_appointments_by_date(date_str: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM appointments WHERE date = ? AND status != 'cancelled' ORDER BY time",
            (date_str,)
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            appt = dict(r)
            appt['service_ids'] = json.loads(appt['service_ids'])
            result.append(appt)
        return result


async def auto_cancel_unconfirmed(cutoff_dt: str) -> list:
    """Cancel pending appointments created before cutoff_dt. Returns list of cancelled appts."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM appointments
               WHERE status IN ('pending', 'new')
               AND created_at <= ?""",
            (cutoff_dt,)
        ) as cur:
            rows = await cur.fetchall()
        cancelled = []
        for r in rows:
            appt = dict(r)
            appt['service_ids'] = json.loads(appt['service_ids'])
            await db.execute(
                "UPDATE appointments SET status = 'cancelled' WHERE id = ?", (appt['id'],)
            )
            cancelled.append(appt)
        await db.commit()
    return cancelled


async def get_pending_payments() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM appointments WHERE status = 'pending' AND prepayment_amount > 0 ORDER BY created_at"
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            appt = dict(r)
            appt['service_ids'] = json.loads(appt['service_ids'])
            result.append(appt)
        return result


async def save_client_msg_id(appointment_id: int, msg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE appointments SET client_msg_id = ? WHERE id = ?",
            (msg_id, appointment_id)
        )
        await db.commit()


async def update_appointment_status(appointment_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE appointments SET status = ? WHERE id = ?",
            (status, appointment_id)
        )
        await db.commit()


async def confirm_payment(appointment_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE appointments SET prepayment_paid = 1, status = 'confirmed' WHERE id = ?",
            (appointment_id,)
        )
        await db.commit()


async def get_booked_slots(date_str: str) -> list:
    """Returns list of booked time slots for a date."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT time, service_ids FROM appointments "
            "WHERE date = ? AND status NOT IN ('cancelled')",
            (date_str,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_available_slots(date_str: str, service_duration: int) -> list:
    """Calculate available time slots for a given date."""
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    day_of_week = target_date.weekday()  # 0=Mon

    # Full-day blocks from bot /block_date command
    blocked = await get_blocked_dates()
    if date_str in {b['date'] for b in blocked}:
        return []

    hours = await get_working_hours()
    day_hours = next((h for h in hours if h['day_of_week'] == day_of_week), None)
    if not day_hours:
        return []

    # Full-day blocks from admin UI
    periods = await get_blocked_periods_for_date(date_str)
    if any(p['start_time'] is None for p in periods):
        return []

    settings = await get_settings()
    slot_dur = int(settings.get('slot_duration', '30'))

    start = datetime.strptime(day_hours['start_time'], "%H:%M")
    end = datetime.strptime(day_hours['end_time'], "%H:%M")

    all_slots = []
    current = start
    while current + timedelta(minutes=service_duration) <= end:
        all_slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=slot_dur)

    services_list = await get_services(active_only=False)
    svc_dur_map = {s['id']: s['duration_min'] for s in services_list}

    occupied = set()

    # Block slots that overlap with existing appointments
    booked = await get_booked_slots(date_str)
    for b in booked:
        btime = datetime.strptime(b['time'], "%H:%M")
        try:
            ids = json.loads(b['service_ids'])
            b_dur = sum(svc_dur_map.get(i, 60) for i in ids) or 60
        except Exception:
            b_dur = 60
        b_end = btime + timedelta(minutes=b_dur)
        for slot_str in all_slots:
            slot_time = datetime.strptime(slot_str, "%H:%M")
            if slot_time < b_end and slot_time + timedelta(minutes=service_duration) > btime:
                occupied.add(slot_str)

    # Block slots that overlap with admin-defined break periods
    for p in periods:
        if p['start_time'] is None:
            continue
        p_start = datetime.strptime(p['start_time'], "%H:%M")
        p_end   = datetime.strptime(p['end_time'],   "%H:%M")
        for slot_str in all_slots:
            slot_time = datetime.strptime(slot_str, "%H:%M")
            slot_end  = slot_time + timedelta(minutes=service_duration)
            if slot_time < p_end and slot_end > p_start:
                occupied.add(slot_str)

    now = datetime.now()
    result = []
    for s in all_slots:
        slot_dt = datetime.strptime(f"{date_str} {s}", "%Y-%m-%d %H:%M")
        if slot_dt <= now:
            continue
        if s not in occupied:
            result.append(s)
    return result


async def get_available_dates(year: int, month: int, service_duration: int) -> list:
    """Return list of dates that have at least one available slot."""
    from calendar import monthrange
    _, days_in_month = monthrange(year, month)
    today = date.today()
    result = []

    hours = await get_working_hours()
    working_days = {h['day_of_week'] for h in hours}
    blocked_full_days = {b['date'] for b in await get_blocked_dates()}
    # Also collect full-day blocks from blocked_periods
    all_periods = await get_all_blocked_periods()
    for p in all_periods:
        if p['start_time'] is None:
            blocked_full_days.add(p['date'])

    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        if d < today:
            continue
        date_str = d.isoformat()
        if date_str in blocked_full_days:
            continue
        if d.weekday() not in working_days:
            continue
        slots = await get_available_slots(date_str, service_duration)
        if slots:
            result.append(date_str)
    return result


# ─── Waitlist ─────────────────────────────────────────────────────────────────

async def add_to_waitlist(name: str, phone: str, service_ids: list):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO waitlist (name, phone, service_ids) VALUES (?, ?, ?)",
            (name, phone, json.dumps(service_ids))
        )
        await db.commit()


async def get_waitlist() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM waitlist ORDER BY created_at") as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ─── Admin tokens ────────────────────────────────────────────────────────────

async def create_admin_token(user_id: int = 0) -> str:
    token = secrets.token_urlsafe(24)
    expires = (datetime.now() + timedelta(hours=24)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # Remove only this user's old tokens + all expired tokens
        await db.execute(
            "DELETE FROM admin_tokens WHERE user_id = ? OR expires_at <= datetime('now')",
            (user_id,)
        )
        await db.execute(
            "INSERT INTO admin_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires)
        )
        await db.commit()
    return token


async def verify_admin_token(token: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT token FROM admin_tokens WHERE token = ? AND expires_at > datetime('now')",
            (token,)
        ) as cur:
            row = await cur.fetchone()
        return row is not None


# ─── User tokens ─────────────────────────────────────────────────────────────

async def create_user_token(user_id: int, first_name: str = '', last_name: str = '', username: str = '') -> str:
    token = secrets.token_urlsafe(24)
    expires = (datetime.now() + timedelta(hours=24)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_tokens WHERE user_id = ?", (user_id,))
        await db.execute(
            "INSERT INTO user_tokens (token, user_id, first_name, last_name, username, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (token, user_id, first_name, last_name, username, expires)
        )
        await db.commit()
    return token


async def verify_user_token(token: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, first_name, last_name, username FROM user_tokens WHERE token = ? AND expires_at > datetime('now')",
            (token,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {'id': row['user_id'], 'first_name': row['first_name'], 'last_name': row['last_name'], 'username': row['username']}


# ─── Stats ────────────────────────────────────────────────────────────────────

async def get_revenue_details(year: int, month: int) -> list:
    first_day = f"{year}-{month:02d}-01"
    if month == 12:
        last_day = f"{year+1}-01-01"
    else:
        last_day = f"{year}-{month+1:02d}-01"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT id, name, phone, date, time, service_ids, total_price, prepayment_amount, client_id
            FROM appointments
            WHERE date >= ? AND date < ?
              AND status NOT IN ('cancelled', 'pending')
              AND date <= date('now')
            ORDER BY date DESC, time DESC
        """, (first_day, last_day)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        today = date.today().isoformat()
        first_day = date.today().replace(day=1).isoformat()

        async with db.execute(
            "SELECT COUNT(*) as c FROM appointments WHERE date = ? AND status != 'cancelled'",
            (today,)
        ) as cur:
            today_count = (await cur.fetchone())['c']

        async with db.execute(
            "SELECT COUNT(*) as c, SUM(total_price) as s FROM appointments "
            "WHERE date >= ? AND date <= ? AND status NOT IN ('cancelled', 'pending')",
            (first_day, today)
        ) as cur:
            row = await cur.fetchone()
            month_count = row['c']
            month_revenue = row['s'] or 0

        async with db.execute(
            "SELECT COUNT(DISTINCT COALESCE(NULLIF(client_id,''), phone)) as c "
            "FROM appointments WHERE status != 'cancelled' AND (client_id IS NOT NULL OR phone != '')"
        ) as cur:
            clients_total = (await cur.fetchone())['c']

        async with db.execute(
            "SELECT COUNT(*) as c FROM appointments WHERE status = 'pending' AND prepayment_amount > 0"
        ) as cur:
            pending_payments = (await cur.fetchone())['c']

        return {
            'today_count': today_count,
            'month_count': month_count,
            'month_revenue': month_revenue,
            'clients_total': clients_total,
            'pending_payments': pending_payments,
        }
