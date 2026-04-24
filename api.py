import json
import os
import asyncio
import shutil
import httpx
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional

import database as db
from config import BOT_TOKEN, ADMIN_ID, ADMIN_IDS


async def auto_cancel_loop():
    """Every 5 min: cancel unconfirmed appointments older than 2h (only 10:00–22:00)."""
    await asyncio.sleep(30)  # small delay on startup
    while True:
        try:
            now = datetime.now()
            now_utc = datetime.utcnow()
            hour = now.hour
            if 10 <= hour < 22:
                cutoff = (now_utc - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
                cancelled = await db.auto_cancel_unconfirmed(cutoff)
                for appt in cancelled:
                    from_dt = datetime.strptime(appt['date'], '%Y-%m-%d')
                    date_s = _fmt_date_short(from_dt)
                    # Notify admins
                    await tg_send_all_admins(
                        f"⏰ *Авто-отмена записи*\n\n"
                        f"👤 {appt.get('name','—')} · {appt.get('phone','—')}\n"
                        f"📅 {date_s} · {appt['time']}\n\n"
                        f"_Запись не была подтверждена в течение 2 часов._"
                    )
                    # Notify client
                    client_id = appt.get('client_id')
                    if client_id:
                        msg_id = appt.get('client_msg_id')
                        text = (
                            f"❌ *Запись автоматически отменена*\n\n"
                            f"📅 {date_s} · {appt['time']}\n\n"
                            f"Администратор не подтвердил запись в течение 2 часов.\n"
                            f"Запишитесь снова или свяжитесь с нами."
                        )
                        if msg_id:
                            edited = await tg_edit(int(client_id), msg_id, text)
                            if not edited:
                                await tg_send(int(client_id), text)
                        else:
                            await tg_send(int(client_id), text)
        except Exception as e:
            print(f"[auto_cancel_loop] error: {e}")
        await asyncio.sleep(300)  # check every 5 minutes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    asyncio.create_task(auto_cancel_loop())
    yield


app = FastAPI(title="Zaman Booking API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Telegram notifications ──────────────────────────────────────────────────
LOCATION_NOTE = "📍 Абдирова 26/6, 6 этаж, каб. 609\n💳 Kaspi QR или наличка (желательно без сдачи)"


async def tg_send_all_admins(text: str):
    settings = await db.get_settings()
    if settings.get('admin_notifications', '1') != '1':
        return
    for admin_id in ADMIN_IDS:
        await tg_send(admin_id, text)


async def tg_send(chat_id: int, text: str, reply_markup: dict = None) -> int | None:
    if not BOT_TOKEN or not chat_id:
        return None
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json=payload,
            )
            data = r.json()
            return data.get("result", {}).get("message_id")
    except Exception:
        return None


async def tg_edit(chat_id: int, message_id: int, text: str) -> bool:
    if not BOT_TOKEN or not chat_id or not message_id:
        return False
    async with httpx.AsyncClient(timeout=5) as client:
        for method, payload in [
            ("editMessageCaption", {"caption": text}),
            ("editMessageText",    {"text": text}),
        ]:
            try:
                r = await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
                    json={"chat_id": chat_id, "message_id": message_id,
                          "parse_mode": "Markdown", **payload},
                )
                if r.json().get("ok"):
                    return True
            except Exception:
                pass
    return False


async def tg_send_photo(chat_id: int, photo_id: str, caption: str, reply_markup: dict = None) -> int | None:
    if not BOT_TOKEN or not chat_id:
        return None
    try:
        payload = {"chat_id": chat_id, "photo": photo_id, "caption": caption, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                json=payload,
            )
            return r.json().get("result", {}).get("message_id")
    except Exception:
        return None


_MONTHS_LONG  = ['января','февраля','марта','апреля','мая','июня',
                  'июля','августа','сентября','октября','ноября','декабря']
_MONTHS_SHORT = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек']
_DAYS_SHORT   = ['пн','вт','ср','чт','пт','сб','вс']


def _fmt_date_long(d) -> str:
    return f"{d.day} {_MONTHS_LONG[d.month - 1]}"

def _fmt_date_short(d) -> str:
    return f"{d.day} {_MONTHS_SHORT[d.month - 1]}, {_DAYS_SHORT[d.weekday()]}"


async def notify_confirmation(appt: dict):
    from datetime import datetime
    d = datetime.strptime(appt['date'], '%Y-%m-%d')
    date_long = _fmt_date_long(d)

    client_id = appt.get('client_id')
    if not client_id:
        return

    prepayment = appt.get('prepayment_amount', 0) or 0
    prepayment_paid = appt.get('prepayment_paid', 0)
    prepayment_line = f"\n💳 Предоплата {prepayment:,.0f} ₸ — оплачена ✓" if (prepayment > 0 and prepayment_paid) else ''

    new_text = (
        f"✅ *Запись подтверждена!*\n\n"
        f"📅 {date_long} · *{appt['time']}*"
        f"{prepayment_line}\n\n"
        f"{LOCATION_NOTE}\n\n"
        f"Ждём вас! Приходите вовремя 💈"
    )

    msg_id = appt.get('client_msg_id')
    if msg_id:
        edited = await tg_edit(client_id, msg_id, new_text)
        if not edited:
            await tg_send(client_id, new_text)
    else:
        await tg_send(client_id, new_text)


async def notify_cancellation(appt: dict, cancelled_by: str = "client"):
    from datetime import datetime
    d = datetime.strptime(appt['date'], '%Y-%m-%d')
    date_short = _fmt_date_short(d)

    who = "клиентом" if cancelled_by == "client" else "администратором"
    admin_text = (
        f"❌ *Запись отменена {who}*\n\n"
        f"👤 {appt.get('name', '—')} · {appt.get('phone', '—')}\n"
        f"📅 {date_short} · {appt['time']}"
    )
    await tg_send_all_admins(admin_text)

    client_id = appt.get('client_id')
    if client_id and cancelled_by == "admin":
        reason = appt.get('cancel_reason', '')
        reason_line = f"\n\n📝 Причина: _{reason}_" if reason else ''
        await tg_send(client_id,
            f"😔 *Ваша запись отменена*\n\n"
            f"📅 {date_short} · {appt['time']}"
            f"{reason_line}\n\n"
            f"Запишитесь снова — кнопка «Открыть» внизу экрана."
        )
    elif client_id and cancelled_by == "client":
        await tg_send(client_id,
            f"✅ Запись на *{date_short} в {appt['time']}* отменена.\n\n"
            f"Будем ждать в следующий раз! 👋"
        )


# ─── Admin auth ───────────────────────────────────────────────────────────────

async def is_admin_request(token: str = "") -> bool:
    return bool(token and await db.verify_admin_token(token))


async def require_admin(token: str = ""):
    if not await is_admin_request(token):
        raise HTTPException(403, "Admin only")


# ─── Public endpoints ─────────────────────────────────────────────────────────

@app.get("/api/info")
async def get_info():
    settings = await db.get_settings()
    services = await db.get_services(active_only=True)
    return {
        "master_name": settings.get('master_name', 'Мастер'),
        "master_bio": settings.get('master_bio', ''),
        "master_location": settings.get('master_location', ''),
        "prepayment_required": settings.get('prepayment_required', '0') == '1',
        "prepayment_percent": float(settings.get('prepayment_percent', '30')),
        "prepayment_mode":    settings.get('prepayment_mode', 'manual'),
        "payment_button_text": settings.get('payment_button_text', 'Оплатить'),
        "payment_button_url":  settings.get('payment_button_url', ''),
        "master_avatar_url": settings.get('master_avatar_url', ''),
        "instagram_url":     settings.get('instagram_url', ''),
        "booking_weeks_ahead": int(settings.get('booking_weeks_ahead', '2')),
        "services": services,
    }


@app.get("/api/available-dates")
async def get_available_dates(
    year: int = Query(...),
    month: int = Query(...),
    duration: int = Query(60),
):
    return {"dates": await db.get_available_dates(year, month, duration)}


@app.get("/api/available-slots")
async def get_available_slots(date: str = Query(...), duration: int = Query(60)):
    return {"slots": await db.get_available_slots(date, duration)}


# ─── User endpoints ───────────────────────────────────────────────────────────

class BookingRequest(BaseModel):
    name: str
    phone: str
    tg_id: Optional[int] = None
    service_ids: list[int]
    date: str
    time: str
    notes: Optional[str] = ""


@app.post("/api/book")
async def create_booking(req: BookingRequest):
    name = req.name.strip()
    phone = req.phone.strip()
    if not name or not phone:
        raise HTTPException(400, "Введите имя и номер телефона")

    if req.tg_id:
        banned, ban_reason = await db.is_client_banned(req.tg_id)
        if banned:
            msg = "Вы заблокированы и не можете создавать записи"
            if ban_reason:
                msg += f": {ban_reason}"
            raise HTTPException(403, msg)

        active_count = await db.get_active_appointments_count(req.tg_id)
        if active_count >= 2:
            raise HTTPException(409, "У вас уже есть 2 активные записи. Дождитесь их завершения или отмените одну из них.")

    services = await db.get_services(active_only=False)
    svc_map = {s['id']: s for s in services}
    selected = [svc_map[i] for i in req.service_ids if i in svc_map]
    if not selected:
        raise HTTPException(400, "Услуги не выбраны")

    total_price = sum(s['price'] for s in selected)
    settings = await db.get_settings()
    prepayment_required = settings.get('prepayment_required', '0') == '1'
    prepayment_percent = float(settings.get('prepayment_percent', '30'))
    prepayment_amount = round(total_price * prepayment_percent / 100) if prepayment_required else 0

    slots = await db.get_available_slots(req.date, sum(s['duration_min'] for s in selected))
    if req.time not in slots:
        raise HTTPException(409, "Время уже занято")

    appt_id = await db.create_appointment(
        date_str=req.date, time_str=req.time,
        service_ids=req.service_ids, total_price=total_price,
        prepayment_amount=prepayment_amount,
        name=name, phone=phone, client_id=req.tg_id,
        notes=req.notes or '',
    )

    # Notifications
    from datetime import datetime as dt, date as date_cls
    d = dt.strptime(req.date, '%Y-%m-%d')
    date_long  = _fmt_date_long(d)
    date_short = _fmt_date_short(d)
    svc_names = ', '.join(s['name'] for s in selected)

    # Notify admin
    notes_line = f"\n💬 _{req.notes}_" if req.notes else ''
    prepay_line = f"\n💳 Предоплата: *{prepayment_amount:,.0f} ₸* — ожидает" if prepayment_amount > 0 else ''
    admin_text = (
        f"🆕 *Новая запись*\n\n"
        f"👤 {name} · {phone}\n"
        f"📅 {date_short} · *{req.time}*\n"
        f"✂️ {svc_names}\n"
        f"💰 {total_price:,.0f} ₸"
        f"{prepay_line}"
        f"{notes_line}"
    )
    await tg_send_all_admins(admin_text)

    # Extra alert if booking is for today
    if settings.get('same_day_notifications', '1') == '1' and req.date == date_cls.today().isoformat():
        urgent_text = (
            f"🔥 *Запись на сегодня!*\n\n"
            f"👤 {name} · в *{req.time}*\n"
            f"✂️ {svc_names}"
        )
        await tg_send_all_admins(urgent_text)

    # Notify client (text only — no photo, so the message can be edited when admin confirms)
    if req.tg_id:
        notes_client = f"\n💬 _{req.notes}_" if req.notes else ''
        warning_line = "\n\n⚠️ _Предоплата не возвращается при отмене записи._" if (prepayment_required and prepayment_amount > 0) else ''
        prepay_line = f"\n💳 Предоплата: *{prepayment_amount:,.0f} ₸*" if (prepayment_required and prepayment_amount > 0) else ''
        client_text = (
            f"📋 *Запись принята!*\n\n"
            f"📅 {date_long} · *{req.time}*\n"
            f"✂️ {svc_names}\n"
            f"💰 {total_price:,.0f} ₸"
            f"{prepay_line}"
            f"{notes_client}"
            f"{warning_line}\n\n"
            f"⏳ Ожидает подтверждения мастера."
        )
        msg_id = await tg_send(req.tg_id, client_text)
        if msg_id:
            await db.save_client_msg_id(appt_id, msg_id)

    return {
        "appointment_id": appt_id,
        "total_price": total_price,
        "prepayment_amount": prepayment_amount,
        "prepayment_required": prepayment_required,
        "payment_card":        settings.get('payment_card', '')        if prepayment_required else '',
        "payment_phone":       settings.get('payment_phone', '')       if prepayment_required else '',
        "payment_bank":        settings.get('payment_bank', '')        if prepayment_required else '',
        "payment_button_text": settings.get('payment_button_text', 'Оплатить') if prepayment_required else '',
        "payment_button_url":  settings.get('payment_button_url', '')  if prepayment_required else '',
        "prepayment_mode":     settings.get('prepayment_mode', 'manual') if prepayment_required else 'manual',
    }


@app.get("/api/appointments")
async def get_appointments(
    tg_id: Optional[int] = Query(default=None),
    phone: str = Query(default=""),
):
    if tg_id:
        appointments = await db.get_appointments_by_tg_id(tg_id)
    elif phone.strip():
        appointments = await db.get_appointments_by_phone(phone.strip())
    else:
        raise HTTPException(400, "Укажите tg_id или phone")

    services = await db.get_services(active_only=False)
    svc_map = {s['id']: s for s in services}
    result = [{**a, 'services': [svc_map[i] for i in a['service_ids'] if i in svc_map]}
              for a in appointments]
    return {"appointments": result}


class CancelRequest(BaseModel):
    tg_id: Optional[int] = None
    phone: str = ""


@app.post("/api/appointments/{appt_id}/cancel")
async def cancel_appointment(appt_id: int, req: CancelRequest):
    appt = await db.get_appointment(appt_id)
    if not appt:
        raise HTTPException(404, "Запись не найдена")
    if req.tg_id and appt.get('client_id') == req.tg_id:
        pass
    elif req.phone and appt.get('phone', '').strip() == req.phone.strip():
        pass
    else:
        raise HTTPException(403, "Нет доступа")
    if appt['status'] == 'cancelled':
        raise HTTPException(409, "Запись уже отменена")
    await db.update_appointment_status(appt_id, 'cancelled')
    await notify_cancellation(appt, cancelled_by="client")
    return {"success": True}


class WaitlistRequest(BaseModel):
    name: str
    phone: str
    service_ids: list[int]


@app.post("/api/waitlist")
async def add_to_waitlist(req: WaitlistRequest):
    if not req.name.strip() or not req.phone.strip():
        raise HTTPException(400, "Введите имя и телефон")
    await db.add_to_waitlist(req.name.strip(), req.phone.strip(), req.service_ids)
    return {"success": True}


# ─── Admin endpoints ──────────────────────────────────────────────────────────

@app.get("/api/admin/check")
async def admin_check(token: str = Query(default="")):
    return {"is_admin": await is_admin_request(token)}


@app.get("/api/admin/stats")
async def admin_stats(token: str = Query(default="")):
    await require_admin(token)
    return await db.get_stats()


@app.get("/api/admin/appointments")
async def admin_appointments(token: str = Query(default=""), date: str = Query(default=None)):
    await require_admin(token)
    from datetime import date as date_cls
    target = date or date_cls.today().isoformat()
    appointments = await db.get_appointments_by_date(target)
    services = await db.get_services(active_only=False)
    svc_map = {s['id']: s for s in services}
    result = []
    for a in appointments:
        client = await db.get_client(a['client_id']) if a.get('client_id') else None
        result.append({
            **a,
            'services': [svc_map[i] for i in a['service_ids'] if i in svc_map],
            'tg_username': client['username'] if client and client.get('username') else '',
        })
    return {"appointments": result, "date": target}


@app.get("/api/admin/pending-payments")
async def admin_pending_payments(token: str = Query(default="")):
    await require_admin(token)
    pending = await db.get_pending_payments()
    services = await db.get_services(active_only=False)
    svc_map = {s['id']: s for s in services}
    result = [{**a, 'services': [svc_map[i] for i in a['service_ids'] if i in svc_map]}
              for a in pending]
    return {"appointments": result}


class AdminActionRequest(BaseModel):
    token: str = ""
    reason: Optional[str] = ""


@app.get("/api/admin/settings/all")
async def admin_get_settings(token: str = Query(default="")):
    await require_admin(token)
    s = await db.get_settings()
    return {
        "master_name":         s.get("master_name", ""),
        "master_bio":          s.get("master_bio", ""),
        "master_location":     s.get("master_location", ""),
        "payment_bank":        s.get("payment_bank", ""),
        "payment_card":        s.get("payment_card", ""),
        "payment_phone":       s.get("payment_phone", ""),
        "prepayment_required":   s.get("prepayment_required", "0") == "1",
        "prepayment_percent":    float(s.get("prepayment_percent", "30")),
        "payment_button_text":   s.get("payment_button_text", "Оплатить"),
        "payment_button_url":    s.get("payment_button_url", ""),
        "admin_notifications":     s.get("admin_notifications", "1") == "1",
        "same_day_notifications":  s.get("same_day_notifications", "1") == "1",
        "client_reminders":        s.get("client_reminders", "1") == "1",
        "prepayment_mode":         s.get("prepayment_mode", "manual"),
        "master_avatar_url":       s.get("master_avatar_url", ""),
        "instagram_url":           s.get("instagram_url", ""),
        "booking_weeks_ahead":    int(s.get("booking_weeks_ahead", "2")),
    }


UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "webapp", "uploads")


@app.post("/api/admin/avatar")
async def admin_upload_avatar(
    token: str = Form(...),
    file: UploadFile = File(...),
):
    await require_admin(token)
    ext = os.path.splitext(file.filename or "")[-1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        raise HTTPException(400, "Unsupported file type")
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    dest = os.path.join(UPLOADS_DIR, f"master_avatar{ext}")
    # Remove old avatar files with other extensions
    for old_ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        old = os.path.join(UPLOADS_DIR, f"master_avatar{old_ext}")
        if old != dest and os.path.exists(old):
            os.remove(old)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    import time
    url = f"/uploads/master_avatar{ext}?v={int(time.time())}"
    await db.set_setting("master_avatar_url", url)
    return {"success": True, "url": url}


@app.delete("/api/admin/avatar")
async def admin_delete_avatar(token: str = Query(...)):
    await require_admin(token)
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        old = os.path.join(UPLOADS_DIR, f"master_avatar{ext}")
        if os.path.exists(old):
            os.remove(old)
    await db.set_setting("master_avatar_url", "")
    return {"success": True}


@app.post("/api/admin/appointments/{appt_id}/confirm")
async def admin_confirm(appt_id: int, req: AdminActionRequest):
    await require_admin(req.token)
    appt = await db.get_appointment(appt_id)
    if not appt:
        raise HTTPException(404, "Запись не найдена")
    if appt['status'] == 'cancelled':
        raise HTTPException(409, "Нельзя подтвердить отменённую запись")
    if appt['status'] == 'confirmed':
        return {"success": True}
    await db.update_appointment_status(appt_id, 'confirmed')
    await notify_confirmation(appt)
    return {"success": True}


@app.post("/api/admin/appointments/{appt_id}/cancel")
async def admin_cancel(appt_id: int, req: AdminActionRequest):
    await require_admin(req.token)
    appt = await db.get_appointment(appt_id)
    if not appt:
        raise HTTPException(404, "Запись не найдена")
    if appt['status'] == 'cancelled':
        raise HTTPException(409, "Запись уже отменена")
    await db.update_appointment_status(appt_id, 'cancelled')
    appt['cancel_reason'] = req.reason or ''
    await notify_cancellation(appt, cancelled_by="admin")
    return {"success": True}


@app.post("/api/appointments/{appt_id}/payment-sent")
async def client_payment_sent(appt_id: int):
    appt = await db.get_appointment(appt_id)
    if not appt:
        raise HTTPException(404, "Запись не найдена")
    # Notify admin
    from datetime import datetime as dt
    d = dt.strptime(appt['date'], '%Y-%m-%d')
    date_short = _fmt_date_short(d)
    admin_text = (
        f"💳 *Клиент отправил оплату*\n\n"
        f"👤 {appt.get('name', '—')} · {appt.get('phone', '—')}\n"
        f"📅 {date_short} · {appt['time']}\n"
        f"💰 {appt['prepayment_amount']:,.0f} ₸\n"
        f"💳 Предоплата"
    )
    await tg_send_all_admins(admin_text)
    return {"success": True}


@app.post("/api/admin/payments/{appt_id}/confirm")
async def admin_confirm_payment(appt_id: int, req: AdminActionRequest):
    await require_admin(req.token)
    appt = await db.get_appointment(appt_id)
    if not appt:
        raise HTTPException(404, "Запись не найдена")
    if appt['status'] == 'cancelled':
        raise HTTPException(409, "Нельзя подтвердить оплату отменённой записи")
    if appt.get('prepayment_paid'):
        return {"success": True}
    await db.confirm_payment(appt_id)
    # Notify client — edit original booking message if possible
    if appt.get('client_id'):
        from datetime import datetime as dt
        d = dt.strptime(appt['date'], '%Y-%m-%d')
        date_short = _fmt_date_short(d)
        text = (
            f"✅ *Оплата получена! Запись подтверждена.*\n\n"
            f"📅 {date_short} · *{appt['time']}*\n\n"
            f"{LOCATION_NOTE}\n\n"
            f"Ждём вас! Приходите вовремя 💈\n\n"
            f"⚠️ _Предоплата не возвращается при отмене записи._"
        )
        msg_id = appt.get('client_msg_id')
        if msg_id:
            edited = await tg_edit(appt['client_id'], msg_id, text)
            if not edited:
                await tg_send(appt['client_id'], text)
        else:
            await tg_send(appt['client_id'], text)
    return {"success": True}


class ServiceRequest(BaseModel):
    token: str = ""
    name: str
    price: float
    duration_min: int
    prepayment_amount: float = 0
    price_type: str = 'fixed'
    price_to: Optional[float] = None
    description: str = ''


@app.post("/api/admin/services")
async def admin_add_service(req: ServiceRequest):
    await require_admin(req.token)
    price_to = req.price_to if req.price_type == 'range' else None
    svc_id = await db.add_service(
        req.name, req.price, req.duration_min, req.prepayment_amount,
        price_type=req.price_type, price_to=price_to, description=req.description,
    )
    return {"id": svc_id}


@app.post("/api/admin/services/reorder")
async def admin_reorder_services(req: dict):
    await require_admin(req.get("token", ""))
    order: list[int] = req.get("order", [])
    for idx, svc_id in enumerate(order):
        await db.update_service(svc_id, sort_order=idx)
    return {"success": True}


@app.delete("/api/admin/services/{svc_id}")
async def admin_delete_service(svc_id: int, token: str = Query(default="")):
    await require_admin(token)
    await db.delete_service(svc_id)
    return {"success": True}


class SettingRequest(BaseModel):
    token: str = ""
    key: str
    value: str


@app.post("/api/admin/settings")
async def admin_set_setting(req: SettingRequest):
    await require_admin(req.token)
    allowed = {'master_name', 'master_bio', 'master_location', 'payment_card',
               'payment_phone', 'payment_bank', 'prepayment_required', 'prepayment_percent',
               'payment_button_text', 'payment_button_url', 'slot_duration',
               'admin_notifications', 'same_day_notifications', 'client_reminders',
               'prepayment_mode', 'instagram_url', 'booking_weeks_ahead'}
    if req.key not in allowed:
        raise HTTPException(400, "Unknown setting key")
    await db.set_setting(req.key, req.value)
    return {"success": True}


@app.get("/api/admin/revenue")
async def admin_revenue(
    year: int = Query(...),
    month: int = Query(...),
    token: str = Query(default=""),
):
    await require_admin(token)
    rows = await db.get_revenue_details(year, month)
    services = await db.get_services(active_only=False)
    svc_map = {s['id']: s for s in services}
    result = []
    for r in rows:
        try:
            ids = json.loads(r['service_ids'])
        except Exception:
            ids = []
        result.append({
            **r,
            'services': [svc_map[i] for i in ids if i in svc_map],
        })
    return {'items': result}


@app.get("/api/admin/calendar")
async def admin_calendar(
    year: int = Query(...),
    month: int = Query(...),
    token: str = Query(default=""),
):
    await require_admin(token)
    from calendar import monthrange
    from datetime import date as date_cls, datetime as dt, timedelta

    _, days_in_month = monthrange(year, month)
    hours = await db.get_working_hours()
    working_days = {h['day_of_week']: h for h in hours}
    settings = await db.get_settings()
    slot_dur = int(settings.get('slot_duration', '60'))
    blocked = {b['date'] for b in await db.get_blocked_dates()}

    result = []
    for day in range(1, days_in_month + 1):
        d = date_cls(year, month, day)
        date_str = d.isoformat()
        dow = d.weekday()

        total_slots = 0
        if dow in working_days and date_str not in blocked:
            wh = working_days[dow]
            start = dt.strptime(wh['start_time'], '%H:%M')
            end   = dt.strptime(wh['end_time'],   '%H:%M')
            cur = start
            while cur + timedelta(minutes=slot_dur) <= end:
                total_slots += 1
                cur += timedelta(minutes=slot_dur)

        appts = await db.get_appointments_by_date(date_str)
        booked = len(appts)
        percent = round(booked / total_slots * 100) if total_slots > 0 else (100 if booked > 0 else 0)
        percent = min(percent, 100)

        result.append({
            'date': date_str,
            'booked': booked,
            'total': total_slots,
            'percent': percent,
        })

    return {'days': result}


@app.get("/api/admin/schedule")
async def admin_get_schedule(token: str = Query(default="")):
    await require_admin(token)
    hours = await db.get_working_hours()
    settings = await db.get_settings()
    return {
        "hours": [dict(h) for h in hours],
        "slot_duration": int(settings.get("slot_duration", "60")),
    }


class DayScheduleRequest(BaseModel):
    token: str = ""
    days: list[dict]
    slot_duration: int = 60


@app.post("/api/admin/schedule")
async def admin_save_schedule(req: DayScheduleRequest):
    await require_admin(req.token)
    for day in req.days:
        dow = int(day.get("day_of_week", 0))
        active = day.get("active", False)
        start = day.get("start_time", "")
        end = day.get("end_time", "")
        if active and start and end:
            await db.set_working_hours(dow, start, end)
        else:
            await db.delete_working_hours(dow)
    await db.set_setting("slot_duration", str(req.slot_duration))
    return {"success": True}


class BlockedPeriodRequest(BaseModel):
    token: str = ""
    date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    reason: Optional[str] = ""


@app.get("/api/admin/blocked-periods")
async def admin_get_blocked_periods(token: str = Query(default="")):
    await require_admin(token)
    return {"periods": await db.get_all_blocked_periods()}


@app.post("/api/admin/blocked-periods")
async def admin_add_blocked_period(req: BlockedPeriodRequest):
    await require_admin(req.token)
    if not req.date:
        raise HTTPException(400, "Укажите дату")
    if (req.start_time is None) != (req.end_time is None):
        raise HTTPException(400, "Укажите оба времени или ни одного")
    if req.start_time and req.end_time and req.start_time >= req.end_time:
        raise HTTPException(400, "Начало должно быть раньше конца")
    pid = await db.add_blocked_period(req.date, req.start_time, req.end_time, req.reason or '')
    return {"id": pid}


@app.delete("/api/admin/blocked-periods/{period_id}")
async def admin_delete_blocked_period(period_id: int, token: str = Query(default="")):
    await require_admin(token)
    await db.delete_blocked_period(period_id)
    return {"success": True}


@app.get("/api/admin/clients")
async def admin_clients(token: str = Query(default="")):
    await require_admin(token)
    return {"clients": await db.get_all_clients()}


@app.get("/api/admin/clients/{tg_id}/avatar")
async def client_avatar(tg_id: int, token: str = Query(default="")):
    await require_admin(token)
    client = await db.get_client(tg_id)
    file_id = client.get('photo_file_id') if client else None
    if not file_id:
        raise HTTPException(404)
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
                params={"file_id": file_id},
            )
            data = r.json()
            if not data.get("ok"):
                raise HTTPException(404)
            file_path = data["result"]["file_path"]
        return RedirectResponse(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(404)


class BanRequest(BaseModel):
    token: str = ""
    reason: Optional[str] = ""


@app.post("/api/admin/clients/{tg_id}/ban")
async def admin_ban_client(tg_id: int, req: BanRequest):
    await require_admin(req.token)
    reason = req.reason or ''
    await db.ban_client(tg_id, reason)
    # Notify client
    reason_line = f"\n📝 Причина: {reason}" if reason else ''
    ban_text = (
        f"🚫 *Ваш доступ к записи заблокирован.*"
        f"{reason_line}\n\n"
        f"Для вопросов обратитесь к администратору."
    )
    settings = await db.get_settings()
    ban_photo = settings.get('ban_photo_id', '')
    if ban_photo:
        await tg_send_photo(tg_id, ban_photo, ban_text)
    else:
        await tg_send(tg_id, ban_text)
    return {"success": True}


@app.post("/api/admin/clients/{tg_id}/unban")
async def admin_unban_client(tg_id: int, req: BanRequest):
    await require_admin(req.token)
    await db.unban_client(tg_id)
    return {"success": True}


if __name__ == "__main__":
    import uvicorn
    import asyncio

    async def startup():
        await db.init_db()

    asyncio.run(startup())
    uvicorn.run(app, host="0.0.0.0", port=8002)
