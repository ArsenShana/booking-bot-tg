import asyncio
import json
import logging
from datetime import date, datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppInfo, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    MenuButtonWebApp, BotCommand, BotCommandScopeChat, BotCommandScopeDefault,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode

import database as db
from config import BOT_TOKEN, ADMIN_ID, ADMIN_IDS, WEBAPP_URL

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ConversationHandler states
(
    ADMIN_MENU, ADMIN_SERVICE_NAME, ADMIN_SERVICE_PRICE,
    ADMIN_SERVICE_DURATION, ADMIN_SERVICE_PREPAYMENT,
    ADMIN_SCHEDULE_DAY, ADMIN_SCHEDULE_START, ADMIN_SCHEDULE_END,
    ADMIN_BLOCK_DATE, ADMIN_SETTINGS_KEY, ADMIN_SETTINGS_VALUE,
    ADMIN_EDIT_SERVICE_ID, ADMIN_EDIT_SERVICE_FIELD, ADMIN_EDIT_SERVICE_VALUE,
) = range(14)

DAYS_RU = {0: 'Пн', 1: 'Вт', 2: 'Ср', 3: 'Чт', 4: 'Пт', 5: 'Сб', 6: 'Вс'}
DAYS_FULL = {0: 'Понедельник', 1: 'Вторник', 2: 'Среда', 3: 'Четверг',
             4: 'Пятница', 5: 'Суббота', 6: 'Воскресенье'}
STATUS_RU = {
    'pending': '⏳ Ожидает оплаты',
    'confirmed': '✅ Подтверждена',
    'completed': '✔️ Завершена',
    'cancelled': '❌ Отменена',
}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def notify_all_admins(context, text: str, reply_markup=None):
    settings = await db.get_settings()
    if settings.get('admin_notifications', '1') != '1':
        return
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id, text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
            )
        except Exception:
            pass


def format_price(price: float) -> str:
    return f"{int(price):,}".replace(',', ' ') + " ₸"


def format_duration(mins: int) -> str:
    if mins < 60:
        return f"{mins} мин"
    h, m = divmod(mins, 60)
    return f"{h} ч {m} мин" if m else f"{h} ч"


async def format_appointment_text(appt: dict) -> str:
    services = await db.get_services(active_only=False)
    svc_map = {s['id']: s for s in services}
    svc_names = [svc_map[i]['name'] for i in appt['service_ids'] if i in svc_map]

    date_obj = datetime.strptime(appt['date'], "%Y-%m-%d")
    months_ru = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
                 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
    date_str = f"{date_obj.day} {months_ru[date_obj.month - 1]} {date_obj.year}"
    day_ru = DAYS_RU[date_obj.weekday()]

    status = STATUS_RU.get(appt['status'], appt['status'])
    text = (
        f"📋 *Запись №{appt['id']}*\n"
        f"📅 {date_str} ({day_ru}), {appt['time']}\n"
        f"✂️ {', '.join(svc_names)}\n"
        f"💰 {format_price(appt['total_price'])}"
    )
    if appt['prepayment_amount'] > 0:
        paid = "✅" if appt['prepayment_paid'] else "❌"
        text += f"\n💳 Предоплата: {format_price(appt['prepayment_amount'])} {paid}"
    text += f"\n{status}"
    return text


# ─── /start ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.upsert_client(
        user.id, user.username or '',
        user.first_name or '', user.last_name or ''
    )
    try:
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            file_id = photos.photos[0][-1].file_id
            await db.save_client_photo(user.id, file_id)
    except Exception:
        pass

    settings = await db.get_settings()
    master_name = settings.get('master_name', 'Мастер')

    base_url = WEBAPP_URL.replace('/index.html', '').rstrip('/') if WEBAPP_URL else ''
    booking_url = f"{base_url}/index.html" if base_url else ''

    # Set persistent menu button for this chat
    if booking_url:
        try:
            await context.bot.set_chat_menu_button(
                chat_id=update.effective_chat.id,
                menu_button=MenuButtonWebApp(
                    text="Открыть",
                    web_app=WebAppInfo(url=f"{booking_url}?tg_id={user.id}"),
                ),
            )
        except Exception:
            pass

    if is_admin(user.id):
        token = await db.create_admin_token(user.id)
        admin_url = f"{base_url}/admin.html?token={token}" if base_url else ''

        row1 = []
        row2 = []
        if admin_url:
            row1.append(KeyboardButton("⚙️ Панель управления", web_app=WebAppInfo(url=admin_url)))
        if booking_url:
            row2.append(KeyboardButton("✂️ Записаться", web_app=WebAppInfo(url=f"{booking_url}?tg_id={user.id}")))

        keyboard = ReplyKeyboardMarkup([row1, row2] if row2 else [row1], resize_keyboard=True)
        await update.message.reply_text(
            f"👋 Добро пожаловать, *{user.first_name}*!\n\nВы вошли как администратор.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        return

    user_booking_url = f"{booking_url}?tg_id={user.id}" if booking_url else ''

    row1 = []
    if user_booking_url:
        row1.append(KeyboardButton("✂️ Записаться", web_app=WebAppInfo(url=user_booking_url)))
    else:
        row1.append(KeyboardButton("✂️ Записаться"))

    row2 = [KeyboardButton("📅 Мои записи"), KeyboardButton("❓ Вопросы")]
    keyboard = ReplyKeyboardMarkup([row1, row2], resize_keyboard=True)

    services = await db.get_services()
    services_text = ""
    for s in services:
        services_text += f"• {s['name']} — {format_price(s['price'])} · {format_duration(s['duration_min'])}\n"

    instagram_url = settings.get('instagram_url', '')
    inline_buttons = []
    if instagram_url:
        inline_buttons.append(InlineKeyboardButton("📸 Instagram", url=instagram_url))

    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

    if inline_buttons:
        await update.message.reply_text(
            "📸 Смотрите наши работы в Instagram:",
            reply_markup=InlineKeyboardMarkup([inline_buttons])
        )


# ─── My appointments (paginated) ──────────────────────────────────────────────

_MONTHS_LONG_RU = ['января','февраля','марта','апреля','мая','июня',
                   'июля','августа','сентября','октября','ноября','декабря']
_DAYS_SHORT_RU  = ['пн','вт','ср','чт','пт','сб','вс']
_STATUS_LABELS  = {
    'pending':   '🟡 Ожидает подтверждения',
    'new':       '🟡 Ожидает подтверждения',
    'confirmed': '🟢 Подтверждена',
    'completed': '✅ Завершена',
    'cancelled': '🔴 Отменена',
}


def _build_appt_card(appointments: list, idx: int, svc_map: dict, settings: dict = None):
    appt  = appointments[idx]
    total = len(appointments)

    d = datetime.strptime(appt['date'], '%Y-%m-%d')
    date_str = f"{d.day} {_MONTHS_LONG_RU[d.month-1]}, {_DAYS_SHORT_RU[d.weekday()]}"

    svc_ids   = appt.get('service_ids') or []
    svc_names = ', '.join(svc_map[i]['name'] for i in svc_ids if i in svc_map) or '—'
    status    = _STATUS_LABELS.get(appt['status'], appt['status'])
    counter   = f"  {idx+1} / {total}" if total > 1 else ""

    text = (
        f"📅 *Мои записи*{counter}\n\n"
        f"🗓 {date_str} · *{appt['time']}*\n"
        f"✂️ {svc_names}\n"
        f"💰 {format_price(appt['total_price'])}\n"
        f"{status}"
    )
    prepay = appt.get('prepayment_amount') or 0
    if prepay > 0 and not appt.get('prepayment_paid'):
        text += f"\n💳 Предоплата: {format_price(prepay)} — не оплачена"

    pay_url = (settings or {}).get('payment_button_url', '')
    pay_label = (settings or {}).get('payment_button_text', '') or 'Оплатить'

    buttons = []
    if appt['status'] in ('pending', 'new', 'confirmed'):
        buttons.append([InlineKeyboardButton(
            "❌ Отменить запись", callback_data=f"cancel_appt:{appt['id']}"
        )])
    if appt['status'] in ('pending', 'new') and prepay > 0 and not appt.get('prepayment_paid'):
        row = []
        if pay_url:
            row.append(InlineKeyboardButton(f"💳 {pay_label}", url=pay_url))
        else:
            row.append(InlineKeyboardButton("💳 Оплатить предоплату", callback_data=f"pay_appt:{appt['id']}"))
        buttons.append(row)

    if total > 1:
        noop = "appts_noop"
        nav  = []
        nav.append(InlineKeyboardButton(
            "◀️", callback_data=f"appts_nav:{idx-1}") if idx > 0 else InlineKeyboardButton(" ", callback_data=noop)
        )
        nav.append(InlineKeyboardButton(f"{idx+1} / {total}", callback_data=noop))
        nav.append(InlineKeyboardButton(
            "▶️", callback_data=f"appts_nav:{idx+1}") if idx < total-1 else InlineKeyboardButton(" ", callback_data=noop)
        )
        buttons.append(nav)

    return text, InlineKeyboardMarkup(buttons) if buttons else None


async def _load_appts(user_id: int, context):
    appointments = await db.get_appointments_by_tg_id(user_id)
    appointments = [a for a in appointments if a['status'] != 'cancelled']
    services = await db.get_services(active_only=False)
    svc_map  = {s['id']: s for s in services}
    context.user_data['appts']   = appointments
    context.user_data['svc_map'] = svc_map
    return appointments, svc_map


async def show_my_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    appointments, svc_map = await _load_appts(update.effective_user.id, context)

    if not appointments:
        await update.message.reply_text(
            "📭 У вас нет активных записей.\n\nЗапишитесь через кнопку «Записаться» 👇",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    settings = await db.get_settings()
    text, kb = _build_appt_card(appointments, 0, svc_map, settings)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def handle_appts_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "appts_noop":
        await query.answer()
        return

    await query.answer()
    idx          = int(query.data.split(':')[1])
    appointments = context.user_data.get('appts')
    svc_map      = context.user_data.get('svc_map', {})

    if appointments is None:
        appointments, svc_map = await _load_appts(query.from_user.id, context)

    if not appointments:
        await query.edit_message_text("📭 *Записей нет*", parse_mode=ParseMode.MARKDOWN)
        return

    idx  = max(0, min(idx, len(appointments) - 1))
    settings = await db.get_settings()
    text, kb = _build_appt_card(appointments, idx, svc_map, settings)
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def handle_cancel_appt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    appt_id = int(query.data.split(':')[1])

    appt = await db.get_appointment(appt_id)
    if not appt or appt['client_id'] != query.from_user.id:
        await query.answer("Запись не найдена.", show_alert=True)
        return

    await db.update_appointment_status(appt_id, 'cancelled')

    # Notify all admins
    client = await db.get_client(query.from_user.id)
    name = f"{client['first_name']} {client['last_name']}".strip() if client else str(query.from_user.id)
    await notify_all_admins(
        context,
        f"❌ *Запись отменена клиентом*\n\n"
        f"👤 {name}\n"
        f"📅 {appt['date']} · {appt['time']}",
    )

    # Reload and show updated list
    appointments, svc_map = await _load_appts(query.from_user.id, context)
    if not appointments:
        await query.edit_message_text(
            "✅ Запись отменена.\n\n📭 Активных записей больше нет.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    settings = await db.get_settings()
    text, kb = _build_appt_card(appointments, 0, svc_map, settings)
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def handle_pay_appt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    appt_id = int(query.data.split(':')[1])

    appt = await db.get_appointment(appt_id)
    if not appt:
        return

    settings = await db.get_settings()
    card = settings.get('payment_card', '')
    phone = settings.get('payment_phone', '')
    bank = settings.get('payment_bank', 'Сбербанк')

    amount = format_price(appt['prepayment_amount'])
    text = (
        f"💳 *Предоплата*\n\n"
        f"Сумма: *{amount}*\n\n"
        f"🏦 {bank}\n"
    )
    if card:
        text += f"💳 `{card}`\n"
    if phone:
        text += f"📱 `{phone}`\n"
    text += (
        f"\n"
        f"После оплаты нажмите кнопку ниже — администратор подтвердит запись.\n\n"
        f"⚠️ _Предоплата не возвращается при отмене записи._"
    )

    # Notify all admins about pending payment
    client = await db.get_client(query.from_user.id)
    name = f"{client['first_name']} {client['last_name']}".strip() if client else str(query.from_user.id)
    await notify_all_admins(
        context,
        f"💳 *Клиент запрашивает реквизиты*\n\n"
        f"👤 {name}\n"
        f"💰 {amount}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Оплата получена", callback_data=f"admin_confirm_pay:{appt_id}"),
            InlineKeyboardButton("❌ Отменить запись", callback_data=f"admin_cancel:{appt_id}"),
        ]])
    )

    await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ─── WebApp data handler ──────────────────────────────────────────────────────

async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle booking data sent from the WebApp."""
    try:
        data = json.loads(update.effective_message.web_app_data.data)
    except Exception:
        await update.message.reply_text("Ошибка обработки данных.")
        return

    action = data.get('action')

    if action == 'booking_confirmed':
        await process_booking_confirmed(update, context, data)
    elif action == 'booking':
        await process_booking_from_webapp(update, context, data)
    elif action == 'waitlist':
        await process_waitlist_from_webapp(update, context, data)


async def handle_confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    appt_id = int(query.data.split(':')[1])

    appt = await db.get_appointment(appt_id)
    if not appt:
        await query.answer("Запись не найдена", show_alert=True)
        return

    # Verify it belongs to this user
    if appt.get('client_id') and appt['client_id'] != query.from_user.id:
        await query.answer("Нет доступа", show_alert=True)
        return

    await query.answer("✅ Запись подтверждена!")

    d = datetime.strptime(appt['date'], '%Y-%m-%d')
    months = ['января','февраля','марта','апреля','мая','июня',
              'июля','августа','сентября','октября','ноября','декабря']
    date_str = f"{d.day} {months[d.month-1]}"

    services = await db.get_services(active_only=False)
    svc_map  = {s['id']: s for s in services}
    svc_ids  = appt.get('service_ids') or []
    svc_names = ', '.join(svc_map[i]['name'] for i in svc_ids if i in svc_map) or '—'

    text = (
        f"✅ *Вы записались!*\n\n"
        f"📅 {date_str} · *{appt['time']}*\n"
        f"✂️ {svc_names}\n"
        f"💰 {format_price(appt['total_price'])}\n\n"
        f"Просим вас не опаздывать.\n"
        f"Если что-то случится — заранее напишите барберу 🙏"
    )

    try:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await context.bot.send_message(query.from_user.id, text, parse_mode=ParseMode.MARKDOWN)


async def process_booking_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE, data: dict):
    """Skip — api.py already sent the client notification."""
    return

    # (unused fallback kept for reference)
    date_str = data.get('date', '')
    time_str = data.get('time', '')
    services = data.get('services', [])
    total_price = data.get('total_price', 0)
    name = data.get('name', '')
    phone = data.get('phone', '')

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        months_ru = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                     'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        date_display = f"{date_obj.day} {months_ru[date_obj.month - 1]}"
    except Exception:
        date_display = date_str

    svc_names = ', '.join(services) if services else '—'
    text = (
        f"✅ *Запись подтверждена!*\n\n"
        f"📅 {date_display} · *{time_str}*\n"
        f"✂️ {svc_names}\n"
        f"💰 {format_price(total_price)}\n\n"
        f"Ждём вас! Если планы изменились — отмените запись заранее 🙏"
    )

    settings = await db.get_settings()
    photo_id = settings.get('master_photo_id', '')

    if photo_id:
        await update.message.reply_photo(photo=photo_id, caption=text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    # Notify all admins
    admin_text = (
        f"🆕 *Новая запись*\n\n"
        f"👤 {name} · {phone}\n"
        f"📅 {date_display} · {time_str}\n"
        f"✂️ {svc_names}\n"
        f"💰 {format_price(total_price)}"
    )
    await notify_all_admins(context, admin_text)


async def cmd_set_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sends a photo with /set_photo caption to set the confirmation photo."""
    if not is_admin(update.effective_user.id):
        return
    if not update.message.photo:
        await update.message.reply_text(
            "Отправьте фото с подписью /set_photo\n"
            "Это фото будет отправляться клиентам при подтверждении записи."
        )
        return
    file_id = update.message.photo[-1].file_id
    await db.set_setting('master_photo_id', file_id)
    await update.message.reply_text("✅ Фото сохранено! Теперь оно будет приходить клиентам при записи.")


async def cmd_set_ban_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sends a photo with /set_ban_photo caption to set the ban notification photo."""
    if not is_admin(update.effective_user.id):
        return
    if not update.message.photo:
        await update.message.reply_text(
            "Отправьте фото с подписью /set_ban_photo\n"
            "Это фото будет отправляться клиентам при блокировке."
        )
        return
    file_id = update.message.photo[-1].file_id
    await db.set_setting('ban_photo_id', file_id)
    await update.message.reply_text("✅ Фото бана сохранено!")


async def process_booking_from_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE, data: dict):
    user = update.effective_user
    service_ids = data.get('service_ids', [])
    date_str = data.get('date')
    time_str = data.get('time')
    notes = data.get('notes', '')

    if not service_ids or not date_str or not time_str:
        await update.message.reply_text("Ошибка: неполные данные бронирования.")
        return

    services = await db.get_services(active_only=False)
    svc_map = {s['id']: s for s in services}
    selected = [svc_map[i] for i in service_ids if i in svc_map]

    if not selected:
        await update.message.reply_text("Ошибка: выбранные услуги не найдены.")
        return

    total_price = sum(s['price'] for s in selected)
    settings = await db.get_settings()
    prepayment_required = settings.get('prepayment_required', '0') == '1'
    prepayment_percent = float(settings.get('prepayment_percent', '30'))
    prepayment_amount = round(total_price * prepayment_percent / 100) if prepayment_required else 0

    appt_id = await db.create_appointment(
        user.id, date_str, time_str, service_ids, total_price, prepayment_amount
    )

    svc_names = ', '.join(s['name'] for s in selected)
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    months_ru = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
    date_display = f"{date_obj.day} {months_ru[date_obj.month - 1]}"

    if prepayment_required and prepayment_amount > 0:
        card = settings.get('payment_card', '')
        phone = settings.get('payment_phone', '')
        bank = settings.get('payment_bank', 'Kaspi')

        text = (
            f"📋 *Запись принята!*\n\n"
            f"📅 {date_display} · *{time_str}*\n"
            f"✂️ {svc_names}\n"
            f"💰 {format_price(total_price)}\n\n"
            f"💳 *Предоплата: {format_price(prepayment_amount)}*\n\n"
            f"🏦 {bank}\n"
        )
        if card:
            text += f"💳 `{card}`\n"
        if phone:
            text += f"📱 `{phone}`\n"
        text += f"\nПосле оплаты нажмите кнопку ниже."

        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Я оплатил(а)", callback_data=f"client_paid:{appt_id}")
            ]])
        )
    else:
        await update.message.reply_text(
            f"✅ *Запись подтверждена!*\n\n"
            f"📅 {date_display} · *{time_str}*\n"
            f"✂️ {svc_names}\n"
            f"💰 {format_price(total_price)}\n\n"
            f"Ждём вас! 👋",
            parse_mode=ParseMode.MARKDOWN
        )

    # Notify admin
    client = await db.get_client(user.id)
    client_name = f"{client['first_name']} {client['last_name']}".strip() if client else str(user.id)
    username_str = f" (@{client['username']})" if client and client.get('username') else ""

    admin_text = (
        f"🆕 *Новая запись*\n\n"
        f"👤 {client_name}{username_str}\n"
        f"📅 {date_display} · *{time_str}*\n"
        f"✂️ {svc_names}\n"
        f"💰 {format_price(total_price)}"
    )
    if prepayment_amount > 0:
        admin_text += f"\n💳 Предоплата: {format_price(prepayment_amount)} — ожидает"

    admin_buttons = [[
        InlineKeyboardButton("✅ Подтвердить", callback_data=f"admin_confirm:{appt_id}"),
        InlineKeyboardButton("❌ Отменить", callback_data=f"admin_cancel:{appt_id}"),
    ]]
    if prepayment_amount > 0:
        admin_buttons.insert(0, [
            InlineKeyboardButton("💳 Оплата получена", callback_data=f"admin_confirm_pay:{appt_id}")
        ])

    await notify_all_admins(
        context, admin_text,
        reply_markup=InlineKeyboardMarkup(admin_buttons)
    )


async def process_waitlist_from_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE, data: dict):
    user = update.effective_user
    service_ids = data.get('service_ids', [])
    await db.add_to_waitlist(user.id, service_ids)

    await update.message.reply_text(
        "📋 *Вы в листе ожидания!*\n\n"
        "Мы уведомим вас, как только появится свободное время.",
        parse_mode=ParseMode.MARKDOWN
    )

    client = await db.get_client(user.id)
    name = f"{client['first_name']} {client['last_name']}".strip() if client else str(user.id)
    await notify_all_admins(
        context,
        f"📋 *Новый в листе ожидания*\n👤 {name} (id: {user.id})",
    )


async def handle_client_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Спасибо! Ожидайте подтверждения администратора.")
    appt_id = int(query.data.split(':')[1])
    appt = await db.get_appointment(appt_id)
    if not appt:
        return

    client = await db.get_client(query.from_user.id)
    name = f"{client['first_name']} {client['last_name']}".strip() if client else str(query.from_user.id)

    await notify_all_admins(
        context,
        f"💳 *Клиент отправил оплату*\n\n"
        f"👤 {name}\n"
        f"💰 {format_price(appt['prepayment_amount'])}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Подтвердить оплату", callback_data=f"admin_confirm_pay:{appt_id}"),
            InlineKeyboardButton("❌ Отменить", callback_data=f"admin_cancel:{appt_id}"),
        ]])
    )


# ─── FAQ / Questions ──────────────────────────────────────────────────────────

async def show_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = await db.get_settings()
    location = settings.get('master_location', 'Уточняйте у мастера')

    await update.message.reply_text(
        "❓ *Часто задаваемые вопросы*\n\n"
        "📍 *Где вы находитесь?*\n"
        f"{location}\n\n"
        "💳 *Как оплатить?*\n"
        "Наличными на месте или через Kaspi Pay.\n\n"
        "⏰ *Что делать если опаздываю?*\n"
        "Пожалуйста, предупредите заранее. Отмените запись и создайте новую.\n\n"
        "🔄 *Как отменить запись?*\n"
        "Через раздел «📅 Мои записи» нажмите «Отменить».\n\n"
        "📞 *Другой вопрос?*\n"
        "Напишите администратору:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📸 Написать администратору",
                url=settings.get('instagram_url', f"tg://user?id={ADMIN_ID}") or f"tg://user?id={ADMIN_ID}"
            )
        ]])
    )


# ─── Admin Panel ──────────────────────────────────────────────────────────────

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    stats = await db.get_stats()
    text = (
        f"⚙️ *Панель администратора*\n\n"
        f"📊 Сегодня записей: {stats['today_count']}\n"
        f"📅 За месяц: {stats['month_count']} записей\n"
        f"💰 Выручка за месяц: {format_price(stats['month_revenue'])}\n"
        f"👥 Клиентов всего: {stats['clients_total']}\n"
        f"💳 Ожидают оплаты: {stats['pending_payments']}\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("📅 Расписание сегодня", callback_data="adm:today"),
            InlineKeyboardButton("📋 Все записи", callback_data="adm:all_appts"),
        ],
        [
            InlineKeyboardButton("💳 Ожидают оплаты", callback_data="adm:pending_pay"),
            InlineKeyboardButton("📋 Лист ожидания", callback_data="adm:waitlist"),
        ],
        [
            InlineKeyboardButton("✂️ Услуги", callback_data="adm:services"),
            InlineKeyboardButton("🕐 Расписание", callback_data="adm:schedule"),
        ],
        [
            InlineKeyboardButton("🚫 Выходные дни", callback_data="adm:blocked"),
            InlineKeyboardButton("⚙️ Настройки", callback_data="adm:settings"),
        ],
    ]
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Нет доступа.", show_alert=True)
        return
    await query.answer()

    data = query.data

    if data == "adm:today":
        await admin_show_today(query, context)
    elif data == "adm:all_appts":
        await admin_show_all_appointments(query, context)
    elif data == "adm:pending_pay":
        await admin_show_pending_payments(query, context)
    elif data == "adm:waitlist":
        await admin_show_waitlist(query, context)
    elif data == "adm:services":
        await admin_show_services(query, context)
    elif data == "adm:schedule":
        await admin_show_schedule(query, context)
    elif data == "adm:blocked":
        await admin_show_blocked(query, context)
    elif data == "adm:settings":
        await admin_show_settings(query, context)
    elif data.startswith("admin_confirm:"):
        appt_id = int(data.split(':')[1])
        await db.update_appointment_status(appt_id, 'confirmed')
        appt = await db.get_appointment(appt_id)
        client = await db.get_client(appt['client_id']) if appt else None
        await query.edit_message_text(f"✅ Запись подтверждена.")
        if appt and client:
            try:
                await context.bot.send_message(
                    appt['client_id'],
                    f"✅ *Запись подтверждена!*\n\n"
                    f"📅 {appt['date']} · *{appt['time']}*\n\n"
                    f"Ждём вас! Приходите вовремя 💈",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
    elif data.startswith("admin_confirm_pay:"):
        appt_id = int(data.split(':')[1])
        await db.confirm_payment(appt_id)
        appt = await db.get_appointment(appt_id)
        await query.edit_message_text(f"✅ Оплата подтверждена.")
        if appt:
            try:
                await context.bot.send_message(
                    appt['client_id'],
                    f"✅ *Оплата получена! Запись подтверждена.*\n\n"
                    f"📅 {appt['date']} · *{appt['time']}*\n\n"
                    f"Ждём вас! Приходите вовремя 💈",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
    elif data.startswith("admin_cancel:"):
        appt_id = int(data.split(':')[1])
        await db.update_appointment_status(appt_id, 'cancelled')
        appt = await db.get_appointment(appt_id)
        await query.edit_message_text(f"❌ Запись отменена.")
        if appt:
            try:
                await context.bot.send_message(
                    appt['client_id'],
                    f"😔 *Ваша запись отменена администратором*\n\n"
                    f"📅 {appt['date']} · {appt['time']}\n\n"
                    f"Запишитесь снова — кнопка «Открыть» внизу экрана.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
    elif data.startswith("adm:del_svc:"):
        svc_id = int(data.split(':')[2])
        await db.delete_service(svc_id)
        await query.edit_message_text("✅ Услуга удалена.")
    elif data.startswith("adm:unblock:"):
        date_str = data.split(':')[2]
        await db.unblock_date(date_str)
        await query.edit_message_text(f"✅ Дата {date_str} разблокирована.")
    elif data.startswith("adm:notify_waitlist:"):
        await admin_notify_waitlist(query, context)


async def admin_show_today(query, context):
    today = date.today().isoformat()
    appointments = await db.get_appointments_by_date(today)
    if not appointments:
        await query.edit_message_text("📅 Сегодня записей нет.")
        return

    services = await db.get_services(active_only=False)
    svc_map = {s['id']: s for s in services}

    text = f"📅 *Записи на сегодня ({today}):*\n\n"
    buttons = []
    for appt in appointments:
        svc_names = [svc_map[i]['name'] for i in appt['service_ids'] if i in svc_map]
        name = f"{appt['first_name']} {appt.get('last_name', '')}".strip()
        username = f" (@{appt['username']})" if appt.get('username') else ""
        status = STATUS_RU.get(appt['status'], appt['status'])
        text += f"🕐 {appt['time']} — {name}{username}\n   {', '.join(svc_names)} — {status}\n\n"

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)


async def admin_show_all_appointments(query, context):
    today = date.today().isoformat()
    appointments = []
    for i in range(7):
        from datetime import timedelta
        d = (date.today() + timedelta(days=i)).isoformat()
        day_appts = await db.get_appointments_by_date(d)
        appointments.extend(day_appts)

    if not appointments:
        await query.edit_message_text("📋 Нет предстоящих записей на 7 дней.")
        return

    services = await db.get_services(active_only=False)
    svc_map = {s['id']: s for s in services}

    text = "📋 *Записи на 7 дней:*\n\n"
    current_date = ""
    for appt in sorted(appointments, key=lambda x: (x['date'], x['time'])):
        if appt['date'] != current_date:
            current_date = appt['date']
            text += f"\n*{current_date}:*\n"
        svc_names = [svc_map[i]['name'] for i in appt['service_ids'] if i in svc_map]
        name = f"{appt['first_name']}".strip()
        text += f"  {appt['time']} — {name} — {', '.join(svc_names)}\n"

    if len(text) > 4000:
        text = text[:4000] + "..."
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)


async def admin_show_pending_payments(query, context):
    pending = await db.get_pending_payments()
    if not pending:
        await query.edit_message_text("✅ Нет записей, ожидающих оплаты.")
        return

    services = await db.get_services(active_only=False)
    svc_map = {s['id']: s for s in services}

    buttons = []
    text = "💳 *Ожидают оплаты:*\n\n"
    for appt in pending:
        name = f"{appt['first_name']} {appt.get('last_name', '')}".strip()
        svc_names = [svc_map[i]['name'] for i in appt['service_ids'] if i in svc_map]
        text += (
            f"📋 {name}\n"
            f"   {appt['date']} {appt['time']}\n"
            f"   {', '.join(svc_names)}\n"
            f"   💰 {format_price(appt['prepayment_amount'])}\n\n"
        )
        buttons.append([
            InlineKeyboardButton(
                f"✅ Подтвердить",
                callback_data=f"admin_confirm_pay:{appt['id']}"
            )
        ])

    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
    )


async def admin_show_waitlist(query, context):
    waitlist = await db.get_waitlist()
    if not waitlist:
        await query.edit_message_text("📋 Лист ожидания пуст.")
        return

    text = f"📋 *Лист ожидания ({len(waitlist)} чел.):*\n\n"
    for w in waitlist:
        name = f"{w['first_name']} {w.get('last_name', '')}".strip()
        username = f" (@{w['username']})" if w.get('username') else ""
        text += f"• {name}{username}\n"

    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Уведомить всех", callback_data="adm:notify_waitlist:")
        ]])
    )


async def admin_notify_waitlist(query, context):
    waitlist = await db.get_waitlist()
    count = 0
    for w in waitlist:
        try:
            await context.bot.send_message(
                w['client_id'],
                "🎉 *Появилось свободное время!*\n\n"
                "Нажмите «📋 Записаться» чтобы забронировать.",
                parse_mode=ParseMode.MARKDOWN
            )
            count += 1
        except Exception:
            pass
    await query.edit_message_text(f"✅ Уведомлено {count} человек из листа ожидания.")


async def admin_show_services(query, context):
    services = await db.get_services(active_only=False)
    if not services:
        text = "✂️ *Услуги*\n\nУслуг пока нет."
    else:
        text = "✂️ *Услуги:*\n\n"
        for s in services:
            status = "✅" if s['active'] else "❌"
            text += (
                f"{status} *{s['name']}*\n"
                f"   {format_price(s['price'])} • {format_duration(s['duration_min'])}"
            )
            if s['prepayment_amount'] > 0:
                text += f" • Предоплата: {format_price(s['prepayment_amount'])}"
            text += f"\n   /edit_svc_{s['id']}\n\n"

    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Добавить услугу", callback_data="adm:add_svc")
        ]])
    )


async def admin_show_schedule(query, context):
    hours = await db.get_working_hours()
    text = "🕐 *Расписание работы:*\n\n"
    for day in range(7):
        day_h = next((h for h in hours if h['day_of_week'] == day), None)
        if day_h:
            text += f"✅ {DAYS_FULL[day]}: {day_h['start_time']} – {day_h['end_time']}\n"
        else:
            text += f"❌ {DAYS_FULL[day]}: выходной\n"

    text += "\nДля изменения: /set_schedule"
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)


async def admin_show_blocked(query, context):
    blocked = await db.get_blocked_dates()
    text = "🚫 *Заблокированные даты:*\n\n"
    buttons = []
    if not blocked:
        text += "Нет заблокированных дат.\n"
    for b in blocked:
        text += f"• {b['date']}"
        if b.get('reason'):
            text += f" — {b['reason']}"
        text += "\n"
        buttons.append([InlineKeyboardButton(
            f"🔓 Разблокировать {b['date']}",
            callback_data=f"adm:unblock:{b['date']}"
        )])
    text += "\nДля блокировки: /block_date YYYY-MM-DD"
    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
    )


async def admin_show_settings(query, context):
    settings = await db.get_settings()
    text = (
        "⚙️ *Настройки:*\n\n"
        f"👤 Имя мастера: {settings.get('master_name', '')}\n"
        f"📍 Адрес: {settings.get('master_location', '')}\n"
        f"💳 Карта: {settings.get('payment_card', 'не задана')}\n"
        f"📱 СБП/Телефон: {settings.get('payment_phone', 'не задан')}\n"
        f"🏦 Банк: {settings.get('payment_bank', '')}\n"
        f"💰 Предоплата: {'включена' if settings.get('prepayment_required') == '1' else 'выключена'}\n"
        f"📊 % предоплаты: {settings.get('prepayment_percent', '30')}%\n\n"
        "Команды:\n"
        "/set_name — изменить имя\n"
        "/set_location — изменить адрес\n"
        "/set_card — номер карты\n"
        "/set_phone — телефон СБП\n"
        "/set_bank — название банка\n"
        "/toggle_prepayment — вкл/выкл предоплату\n"
        "/set_prepayment_percent — % предоплаты\n"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)


# ─── Admin commands ───────────────────────────────────────────────────────────

async def cmd_add_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data['adding_service'] = {}
    await update.message.reply_text(
        "✂️ *Добавление услуги*\n\nВведите название услуги:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
    )
    return ADMIN_SERVICE_NAME


async def admin_svc_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '❌ Отмена':
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    context.user_data['adding_service']['name'] = update.message.text
    await update.message.reply_text("Введите цену (в тенге, только цифры):")
    return ADMIN_SERVICE_PRICE


async def admin_svc_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.replace(' ', '').replace(',', '.'))
        context.user_data['adding_service']['price'] = price
        await update.message.reply_text("Введите длительность в минутах:")
        return ADMIN_SERVICE_DURATION
    except ValueError:
        await update.message.reply_text("Неверный формат. Введите число:")
        return ADMIN_SERVICE_PRICE


async def admin_svc_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        duration = int(update.message.text)
        context.user_data['adding_service']['duration'] = duration
        settings = await db.get_settings()
        if settings.get('prepayment_required') == '1':
            await update.message.reply_text(
                "Введите сумму предоплаты (0 = без предоплаты):"
            )
            return ADMIN_SERVICE_PREPAYMENT
        else:
            svc = context.user_data['adding_service']
            svc_id = await db.add_service(svc['name'], svc['price'], svc['duration'], 0)
            await update.message.reply_text(
                f"✅ Услуга добавлена (ID: {svc_id})",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Введите число:")
        return ADMIN_SERVICE_DURATION


async def admin_svc_prepayment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        prepayment = float(update.message.text.replace(' ', ''))
        svc = context.user_data['adding_service']
        svc_id = await db.add_service(svc['name'], svc['price'], svc['duration'], prepayment)
        await update.message.reply_text(
            f"✅ Услуга добавлена (ID: {svc_id})",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Введите число:")
        return ADMIN_SERVICE_PREPAYMENT


async def cmd_set_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    buttons = [[KeyboardButton(f"{DAYS_FULL[d]}")] for d in range(7)]
    buttons.append([KeyboardButton("❌ Отмена")])
    await update.message.reply_text(
        "🕐 *Настройка расписания*\n\nВыберите день недели:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return ADMIN_SCHEDULE_DAY


async def admin_schedule_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '❌ Отмена':
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    day_map = {v: k for k, v in DAYS_FULL.items()}
    if update.message.text not in day_map:
        await update.message.reply_text("Выберите день из кнопок.")
        return ADMIN_SCHEDULE_DAY
    context.user_data['schedule_day'] = day_map[update.message.text]
    await update.message.reply_text(
        "Введите время начала (формат HH:MM, например 10:00)\n"
        "или «выходной» чтобы убрать день:",
        reply_markup=ReplyKeyboardRemove()
    )
    return ADMIN_SCHEDULE_START


async def admin_schedule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == 'выходной':
        day = context.user_data['schedule_day']
        await db.delete_working_hours(day)
        await update.message.reply_text(f"✅ {DAYS_FULL[day]} — выходной.")
        return ConversationHandler.END
    try:
        datetime.strptime(text, "%H:%M")
        context.user_data['schedule_start'] = text
        await update.message.reply_text("Введите время окончания (HH:MM):")
        return ADMIN_SCHEDULE_END
    except ValueError:
        await update.message.reply_text("Неверный формат. Пример: 10:00")
        return ADMIN_SCHEDULE_START


async def admin_schedule_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        datetime.strptime(text, "%H:%M")
        day = context.user_data['schedule_day']
        start = context.user_data['schedule_start']
        await db.set_working_hours(day, start, text)
        await update.message.reply_text(
            f"✅ {DAYS_FULL[day]}: {start} – {text}"
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Неверный формат. Пример: 20:00")
        return ADMIN_SCHEDULE_END


async def cmd_block_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Формат: /block_date YYYY-MM-DD [причина]")
        return
    date_str = args[0]
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("Неверный формат даты. Пример: 2026-04-25")
        return
    reason = ' '.join(args[1:]) if len(args) > 1 else ''
    await db.block_date(date_str, reason)
    await update.message.reply_text(f"✅ Дата {date_str} заблокирована.")


def cmd_set_setting(key: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            return
        if not context.args:
            await update.message.reply_text(f"Формат: /{update.message.text.split()[0][1:]} значение")
            return
        value = ' '.join(context.args)
        await db.set_setting(key, value)
        await update.message.reply_text(f"✅ Обновлено: {key} = {value}")
    return handler


async def cmd_toggle_prepayment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    settings = await db.get_settings()
    current = settings.get('prepayment_required', '0')
    new_val = '0' if current == '1' else '1'
    await db.set_setting('prepayment_required', new_val)
    status = 'включена' if new_val == '1' else 'выключена'
    await update.message.reply_text(f"✅ Предоплата {status}.")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    stats = await db.get_stats()
    await update.message.reply_text(
        f"📊 *Статистика*\n\n"
        f"📅 Сегодня: {stats['today_count']} записей\n"
        f"📆 За месяц: {stats['month_count']} записей\n"
        f"💰 Выручка за месяц: {format_price(stats['month_revenue'])}\n"
        f"👥 Клиентов: {stats['clients_total']}\n"
        f"💳 Ожидают оплаты: {stats['pending_payments']}\n",
        parse_mode=ParseMode.MARKDOWN
    )


async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timedelta, date as date_cls
    settings = await db.get_settings()
    if settings.get('client_reminders', '1') != '1':
        return

    months_long = ['января','февраля','марта','апреля','мая','июня',
                   'июля','августа','сентября','октября','ноября','декабря']
    now = datetime.now()

    # ── Day reminder (send between 10:00 and 11:00) ──────────
    if 10 <= now.hour < 11:
        tomorrow = (date_cls.today() + timedelta(days=1)).isoformat()
        appts = await db.get_appointments_for_reminders(tomorrow, 'day')
        for a in appts:
            try:
                d = datetime.strptime(a['date'], '%Y-%m-%d')
                date_str = f"{d.day} {months_long[d.month - 1]}"
                await context.bot.send_message(
                    a['client_id'],
                    f"🗓 *Напоминание*\n\n"
                    f"Завтра, *{date_str}* в *{a['time']}*\n\n"
                    f"Ждём вас! Если планы изменились — отмените запись заранее 🙏",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            await db.mark_reminder_sent(a['id'], 'day')

    # ── Hour reminder (appointments in 55–65 min) ─────────────
    today = date_cls.today().isoformat()
    appts = await db.get_appointments_for_reminders(today, 'hour')
    for a in appts:
        try:
            appt_dt = datetime.strptime(f"{a['date']} {a['time']}", '%Y-%m-%d %H:%M')
            delta = (appt_dt - now).total_seconds() / 60
            if 55 <= delta <= 65:
                await context.bot.send_message(
                    a['client_id'],
                    f"⏰ *Уже через час!*\n\n"
                    f"Ваша запись сегодня в *{a['time']}*\n\n"
                    f"Не опаздывайте! Ждём вас 💈",
                    parse_mode=ParseMode.MARKDOWN,
                )
                await db.mark_reminder_sent(a['id'], 'hour')
        except Exception:
            pass


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📅 Мои записи":
        await show_my_appointments(update, context)
    elif text == "❓ Вопросы":
        await show_faq(update, context)
    elif text == "📋 Записаться" and not WEBAPP_URL:
        await update.message.reply_text(
            "Для записи используйте кнопку «📋 Записаться» внизу экрана.\n"
            "Если кнопка не работает, обратитесь к администратору."
        )


# ─── Main ─────────────────────────────────────────────────────────────────────

async def post_init(application):
    await db.init_db()

    # Commands for regular users
    await application.bot.set_my_commands(
        [BotCommand("start", "Открыть приложение")],
        scope=BotCommandScopeDefault(),
    )

    # Commands for all admins
    admin_commands = [
        BotCommand("start",         "Открыть приложение"),
        BotCommand("set_photo",     "Установить фото подтверждения записи"),
        BotCommand("set_ban_photo", "Установить фото блокировки"),
    ]
    for admin_id in ADMIN_IDS:
        try:
            await application.bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            pass

    logger.info("Database initialized.")


def build_app():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    add_svc_conv = ConversationHandler(
        entry_points=[CommandHandler("add_service", cmd_add_service)],
        states={
            ADMIN_SERVICE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_svc_name)],
            ADMIN_SERVICE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_svc_price)],
            ADMIN_SERVICE_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_svc_duration)],
            ADMIN_SERVICE_PREPAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_svc_prepayment)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    schedule_conv = ConversationHandler(
        entry_points=[CommandHandler("set_schedule", cmd_set_schedule)],
        states={
            ADMIN_SCHEDULE_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_schedule_day)],
            ADMIN_SCHEDULE_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_schedule_start)],
            ADMIN_SCHEDULE_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_schedule_end)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("block_date", cmd_block_date))
    app.add_handler(CommandHandler("toggle_prepayment", cmd_toggle_prepayment))
    app.add_handler(CommandHandler("set_name", cmd_set_setting('master_name')))
    app.add_handler(CommandHandler("set_location", cmd_set_setting('master_location')))
    app.add_handler(CommandHandler("set_card", cmd_set_setting('payment_card')))
    app.add_handler(CommandHandler("set_phone", cmd_set_setting('payment_phone')))
    app.add_handler(CommandHandler("set_bank", cmd_set_setting('payment_bank')))
    app.add_handler(CommandHandler("set_bio", cmd_set_setting('master_bio')))
    app.add_handler(CommandHandler("set_prepayment_percent", cmd_set_setting('prepayment_percent')))

    app.add_handler(add_svc_conv)
    app.add_handler(schedule_conv)

    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin_confirm"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin_cancel:"))
    app.add_handler(CallbackQueryHandler(handle_cancel_appt, pattern=r"^cancel_appt:"))
    app.add_handler(CallbackQueryHandler(handle_pay_appt, pattern=r"^pay_appt:"))
    app.add_handler(CallbackQueryHandler(handle_client_paid, pattern=r"^client_paid:"))
    app.add_handler(CallbackQueryHandler(handle_appts_nav, pattern=r"^appts_nav:"))
    app.add_handler(CallbackQueryHandler(handle_appts_nav, pattern=r"^appts_noop$"))
    app.add_handler(CallbackQueryHandler(handle_confirm_booking, pattern=r"^confirm_booking:"))

    app.add_handler(CommandHandler("set_photo", cmd_set_photo))
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.CaptionRegex(r'^/set_photo'), cmd_set_photo
    ))
    app.add_handler(CommandHandler("set_ban_photo", cmd_set_ban_photo))
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.CaptionRegex(r'^/set_ban_photo'), cmd_set_ban_photo
    ))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.job_queue.run_repeating(send_reminders, interval=60, first=15)

    logger.info("Bot started. Polling...")
    return app


if __name__ == "__main__":
    application = build_app()
    application.run_polling(drop_pending_updates=True)
