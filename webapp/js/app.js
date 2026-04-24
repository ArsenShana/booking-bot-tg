const tg = window.Telegram?.WebApp;
const API = window.API_URL || '';

// Single persistent back-button handler (Telegram adds, not replaces, on each onClick call)
let _backHandler = null;

// State
const state = {
  page: 'home',
  services: [],
  masterInfo: {},
  selectedServiceIds: [],
  selectedDate: null,
  selectedTime: null,
  calYear: new Date().getFullYear(),
  calMonth: new Date().getMonth() + 1,
  availableDates: [],
  availableSlots: [],
  appointments: [],
};

// ─── Init ─────────────────────────────────────────────────────────────────────
const TG_ID = parseInt(new URLSearchParams(window.location.search).get('tg_id') || '0') || null;

document.addEventListener('DOMContentLoaded', async () => {
  if (tg) {
    tg.ready();
    tg.expand();
    tg.enableClosingConfirmation();
  }
  await loadInfo();
  // Auto-fill name from Telegram
  if (tg?.initDataUnsafe?.user) {
    const u = tg.initDataUnsafe.user;
    const fullName = [u.first_name, u.last_name].filter(Boolean).join(' ');
    const el = document.getElementById('client-name');
    if (el && fullName) el.value = fullName;
  }
  showPage('home');
});

// ─── API ──────────────────────────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Load data ────────────────────────────────────────────────────────────────
async function loadInfo() {
  try {
    const data = await apiFetch('/api/info');
    state.masterInfo = data;
    state.services = data.services;
    renderProfile();
    renderServices();
  } catch (e) {
    console.error('Failed to load info:', e);
  }
}

async function loadAppointmentsByPhone(phone) {
  try {
    const data = await apiFetch(`/api/appointments?phone=${encodeURIComponent(phone)}`);
    return data.appointments || [];
  } catch (e) {
    return [];
  }
}

async function loadAvailableDates() {
  const maxDuration = getTotalDuration();
  document.getElementById('cal-loading').style.display = 'flex';
  try {
    const data = await apiFetch(
      `/api/available-dates?year=${state.calYear}&month=${state.calMonth}&duration=${maxDuration}`
    );
    state.availableDates = data.dates;
    renderCalendar();
  } catch (e) {
    state.availableDates = [];
    renderCalendar();
  } finally {
    document.getElementById('cal-loading').style.display = 'none';
  }
}

async function loadAvailableSlots(dateStr) {
  const maxDuration = getTotalDuration();
  document.getElementById('slots-content').innerHTML =
    '<div class="loading"><div class="spinner"></div></div>';
  try {
    const data = await apiFetch(`/api/available-slots?date=${dateStr}&duration=${maxDuration}`);
    state.availableSlots = data.slots;
    renderSlots();
  } catch (e) {
    state.availableSlots = [];
    renderSlots();
  }
}

// ─── Pages ────────────────────────────────────────────────────────────────────
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const el = document.getElementById(`page-${name}`);
  if (el) el.classList.add('active');
  state.page = name;
  window.scrollTo(0, 0);

  if (tg) {
    if (_backHandler) {
      tg.BackButton.offClick(_backHandler);
      _backHandler = null;
    }
    if (name !== 'home') {
      _backHandler = () => goBack(name);
      tg.BackButton.show();
      tg.BackButton.onClick(_backHandler);
    } else {
      tg.BackButton.hide();
    }
    tg.MainButton.hide();
  }

  if (name === 'appointments') {
    loadAppointments();
  } else if (name === 'notes') {
    renderBookingStrip('notes-booking-strip');
  } else if (name === 'calendar') {
    state.selectedDate = null;
    state.selectedTime = null;
    state.calYear = new Date().getFullYear();
    state.calMonth = new Date().getMonth() + 1;
    loadAvailableDates();
    updateCalendarHeader();
    document.getElementById('slots-section').style.display = 'none';
  } else if (name === 'review') {
    renderReview();
  }
}

function goBack(currentPage) {
  const flow = {
    'calendar': 'home',
    'notes':    'calendar',
    'review':   'notes',
    'payment':  'review',
    'appointments': 'home',
  };
  showPage(flow[currentPage] || 'home');
}

// ─── Render Profile ───────────────────────────────────────────────────────────
function renderProfile() {
  const m = state.masterInfo;
  const el = document.getElementById('profile-name');
  if (el) el.textContent = m.master_name || 'Мастер';
  const bio = document.getElementById('profile-bio');
  if (bio) bio.textContent = m.master_bio || '';
  const loc = document.getElementById('profile-location');
  if (loc) loc.textContent = m.master_location || '';
  const avatarEl = document.getElementById('profile-avatar');
  if (avatarEl) {
    if (m.master_avatar_url) {
      avatarEl.innerHTML = `<img src="${m.master_avatar_url}" alt="avatar" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">`;
    } else {
      avatarEl.innerHTML = `<svg width="32" height="32" viewBox="0 0 24 24" fill="none"><path d="M12 3C9.24 3 7 5.24 7 8s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zm0 12c-5.33 0-8 2.67-8 4v1h16v-1c0-1.33-2.67-4-8-4z" fill="currentColor" opacity="0.6"/></svg>`;
    }
  }
}

// ─── Render Services ──────────────────────────────────────────────────────────
function renderServices() {
  const container = document.getElementById('services-list');
  if (!container) return;
  if (!state.services.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">✂️</div><p>Услуги пока не добавлены</p></div>';
    return;
  }

  container.innerHTML = state.services.map(s => `
    <div class="service-card ${state.selectedServiceIds.includes(s.id) ? 'selected' : ''}"
         onclick="toggleService(${s.id})" id="svc-${s.id}">
      <div class="service-check">
        <svg class="service-check-icon" width="12" height="10" viewBox="0 0 12 10" fill="none">
          <path d="M1 5L4.5 8.5L11 1.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <div class="service-info">
        <div class="service-name">${escHtml(s.name)}</div>
        ${s.description ? `<div class="service-desc">${escHtml(s.description)}</div>` : ''}
        <div class="service-duration">${formatDuration(s.duration_min)}</div>
      </div>
      <div class="service-price">
        <div class="service-price-value">${formatSvcPrice(s)}</div>
      </div>
    </div>
  `).join('');
}

function toggleService(id) {
  if (state.selectedServiceIds[0] === id) {
    state.selectedServiceIds = [];
  } else {
    state.selectedServiceIds = [id];
    tg?.HapticFeedback?.selectionChanged();
  }
  renderServices();
  updateBookButton();
}

function updateBookButton() {
  const btn = document.getElementById('book-btn');
  if (!btn) return;
  const count = state.selectedServiceIds.length;
  if (count === 0) {
    btn.disabled = true;
    btn.textContent = 'Выберите услугу';
  } else {
    btn.disabled = false;
    const total = state.selectedServiceIds.reduce((sum, id) => {
      const s = state.services.find(x => x.id === id);
      return sum + (s ? s.price : 0);
    }, 0);
    const dur = state.selectedServiceIds.reduce((sum, id) => {
      const s = state.services.find(x => x.id === id);
      return sum + (s ? s.duration_min : 0);
    }, 0);
    btn.textContent = `Записаться — ${formatPrice(total)} · ${formatDuration(dur)}`;
  }
}

// ─── Calendar ─────────────────────────────────────────────────────────────────
const MONTHS_RU = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
const WEEKDAYS_RU = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

function updateCalendarHeader() {
  const el = document.getElementById('cal-title');
  if (el) el.textContent = `${MONTHS_RU[state.calMonth - 1]} ${state.calYear}`;

  const today = new Date();
  const isPastMonth = state.calYear < today.getFullYear() ||
    (state.calYear === today.getFullYear() && state.calMonth <= today.getMonth() + 1);
  const prevBtn = document.getElementById('cal-prev');
  if (prevBtn) prevBtn.disabled = isPastMonth;

  const maxWeeks = state.masterInfo.booking_weeks_ahead || 2;
  const limitDate = new Date(today); limitDate.setDate(today.getDate() + maxWeeks * 7);
  const isMaxMonth = new Date(state.calYear, state.calMonth - 1, 1) > limitDate;
  const nextBtn = document.getElementById('cal-next');
  if (nextBtn) nextBtn.disabled = isMaxMonth;
}

function calPrev() {
  const today = new Date();
  if (state.calYear === today.getFullYear() && state.calMonth <= today.getMonth() + 1) return;
  state.calMonth--;
  if (state.calMonth < 1) { state.calMonth = 12; state.calYear--; }
  updateCalendarHeader();
  loadAvailableDates();
}

function calNext() {
  const today = new Date();
  const maxWeeks = state.masterInfo.booking_weeks_ahead || 2;
  const limitDate = new Date(today); limitDate.setDate(today.getDate() + maxWeeks * 7);
  if (new Date(state.calYear, state.calMonth - 1, 1) > limitDate) return;
  state.calMonth++;
  if (state.calMonth > 12) { state.calMonth = 1; state.calYear++; }
  updateCalendarHeader();
  loadAvailableDates();
}

function renderCalendar() {
  const container = document.getElementById('cal-days');
  if (!container) return;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const firstDay = new Date(state.calYear, state.calMonth - 1, 1);
  const daysInMonth = new Date(state.calYear, state.calMonth, 0).getDate();

  const maxWeeks = state.masterInfo.booking_weeks_ahead || 2;
  const limitDate = new Date(today); limitDate.setDate(today.getDate() + maxWeeks * 7);
  limitDate.setHours(23, 59, 59, 999);

  // Monday-based: getDay() 0=Sun, adjust to Mon=0
  let startDow = firstDay.getDay() - 1;
  if (startDow < 0) startDow = 6;

  const availSet = new Set(state.availableDates);

  let html = '';
  for (let i = 0; i < startDow; i++) {
    html += '<div class="cal-day empty"></div>';
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dateObj = new Date(state.calYear, state.calMonth - 1, d);
    const dateStr = `${state.calYear}-${String(state.calMonth).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    const isToday = dateObj.getTime() === today.getTime();
    const isPast = dateObj < today;
    const isBeyondLimit = dateObj > limitDate;
    const isAvailable = availSet.has(dateStr);
    const isSelected = state.selectedDate === dateStr;

    let cls = 'cal-day';
    if (isPast || isBeyondLimit) cls += ' past';
    else if (isAvailable) cls += ' available';
    else cls += ' unavailable';
    if (isToday) cls += ' today';
    if (isSelected) cls += ' selected';

    const onclick = (!isPast && !isBeyondLimit && isAvailable) ? `onclick="selectDate('${dateStr}')"` : '';
    html += `<button class="${cls}" ${onclick} ${isPast || isBeyondLimit || !isAvailable ? 'disabled' : ''}>${d}</button>`;
  }

  container.innerHTML = html;

  // Show "no slots" message
  const noSlots = document.getElementById('cal-no-slots');
  if (noSlots) {
    noSlots.style.display = state.availableDates.length === 0 ? 'block' : 'none';
  }
}

async function selectDate(dateStr) {
  state.selectedDate = dateStr;
  state.selectedTime = null;
  tg?.HapticFeedback?.selectionChanged();

  document.querySelectorAll('.cal-day.selected').forEach(el => el.classList.remove('selected'));
  document.querySelectorAll('.cal-day.available').forEach(el => {
    const d = el.textContent;
    const pad = String(parseInt(d)).padStart(2, '0');
    const thisDate = `${state.calYear}-${String(state.calMonth).padStart(2,'0')}-${pad}`;
    if (thisDate === dateStr) el.classList.add('selected');
  });

  const slotsSection = document.getElementById('slots-section');
  if (slotsSection) slotsSection.style.display = 'block';

  // Update slots date label
  const d = new Date(dateStr + 'T00:00:00');
  const months = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
  const lbl = document.getElementById('slots-date-label');
  if (lbl) lbl.textContent = `${d.getDate()} ${months[d.getMonth()]}`;

  await loadAvailableSlots(dateStr);
  slotsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSlots() {
  const container = document.getElementById('slots-content');
  if (!container) return;

  if (!state.availableSlots.length) {
    container.innerHTML = `
      <div class="cal-no-slots" style="display:block;padding:20px 20px 8px">
        <div class="no-slots-icon">🚫</div>
        <div class="no-slots-title">Нет свободных мест</div>
        <div class="no-slots-sub">На этот день всё занято.<br>Выберите другую дату.</div>
      </div>`;
    return;
  }

  container.innerHTML = `<div class="slots-grid">
    ${state.availableSlots.map(slot => `
      <button class="slot-btn ${state.selectedTime === slot ? 'selected' : ''}"
              onclick="selectSlot('${slot}')">${slot}</button>
    `).join('')}
  </div>`;

  updateNextBtn();
}

function selectSlot(time) {
  state.selectedTime = time;
  tg?.HapticFeedback?.selectionChanged();
  renderSlots();
  updateNextBtn();
}

function updateNextBtn() {
  const btn = document.getElementById('next-btn');
  if (btn) {
    btn.disabled = !state.selectedDate || !state.selectedTime;
    if (state.selectedDate && state.selectedTime) {
      const d = new Date(state.selectedDate);
      btn.textContent = `Продолжить — ${d.getDate()} ${MONTHS_RU[d.getMonth()].toLowerCase()}, ${state.selectedTime}`;
    } else {
      btn.textContent = 'Выберите время';
    }
  }
}

// ─── Review ───────────────────────────────────────────────────────────────────
function renderReview() {
  const selectedServices = state.services.filter(s => state.selectedServiceIds.includes(s.id));
  const totalPrice = selectedServices.reduce((s, x) => s + x.price, 0);
  const totalDuration = selectedServices.reduce((s, x) => s + x.duration_min, 0);

  const m = state.masterInfo;
  const prepaymentRequired = m.prepayment_required;
  const prepaymentAmount = prepaymentRequired ? Math.round(totalPrice * m.prepayment_percent / 100) : 0;

  const d = new Date(state.selectedDate);
  const dateStr = `${d.getDate()} ${MONTHS_RU[d.getMonth()]} ${d.getFullYear()}`;
  const dayRu = WEEKDAYS_RU[d.getDay() === 0 ? 6 : d.getDay() - 1];

  document.getElementById('review-content').innerHTML = `
    <div class="summary-card">
      <div class="summary-row">
        <span class="summary-row-label">Дата и время</span>
        <span class="summary-row-value">${dateStr} (${dayRu}), ${state.selectedTime}</span>
      </div>
      ${selectedServices.map(s => `
        <div class="summary-row">
          <span class="summary-row-label">${escHtml(s.name)}</span>
          <span class="summary-row-value">${formatSvcPrice(s)}</span>
        </div>
      `).join('')}
      <div class="summary-row">
        <span class="summary-row-label">Длительность</span>
        <span class="summary-row-value">${formatDuration(totalDuration)}</span>
      </div>
      <div class="summary-row">
        <span class="summary-row-label summary-total">Итого</span>
        <span class="summary-row-value summary-total">${formatPrice(totalPrice)}</span>
      </div>
    </div>
    ${prepaymentRequired ? `
      <div class="prepayment-box">
        <p>⚠️ Для подтверждения записи необходима <strong>предоплата ${Math.round(m.prepayment_percent)}%</strong> — <strong>${formatPrice(prepaymentAmount)}</strong></p>
      </div>
    ` : ''}
  `;
}

// ─── Book ─────────────────────────────────────────────────────────────────────
async function confirmBooking() {
  const name  = document.getElementById('client-name')?.value.trim() || '';
  const phone = document.getElementById('client-phone')?.value.trim() || '';

  if (!name)  { showToast('Введите ваше имя'); return; }
  if (!phone) { showToast('Введите номер телефона'); return; }

  // Save form data — booking is NOT created yet
  state.pendingBooking = {
    name,
    phone,
    tg_id: TG_ID,
    service_ids: state.selectedServiceIds,
    date: state.selectedDate,
    time: state.selectedTime,
    notes: document.getElementById('booking-notes')?.value.trim() || '',
  };

  const m = state.masterInfo;
  const selectedServices = state.services.filter(s => state.selectedServiceIds.includes(s.id));
  const totalPrice = selectedServices.reduce((s, x) => s + x.price, 0);
  const prepaymentRequired = m.prepayment_required;
  const prepaymentAmount = prepaymentRequired ? Math.round(totalPrice * (m.prepayment_percent || 50) / 100) : 0;

  if (prepaymentRequired && prepaymentAmount > 0) {
    showPaymentPage(prepaymentAmount);
  } else {
    // No prepayment — create appointment now
    await doBook();
  }
}

// Creates the appointment (used when no prepayment required)
async function doBook() {
  const btn = document.getElementById('confirm-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Создаём запись...'; }
  try {
    const result = await apiFetch('/api/book', {
      method: 'POST',
      body: JSON.stringify(state.pendingBooking),
    });
    state.bookingResult = result;
    showSuccessPage(result);
  } catch (e) {
    showToast('Ошибка: ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = 'Подтвердить запись'; }
  }
}

// Creates the appointment then opens payment link (used when prepayment required)
async function doBookThenPay(url, isAuto) {
  const btn = document.getElementById('pay-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Создаём запись...'; }
  try {
    const result = await apiFetch('/api/book', {
      method: 'POST',
      body: JSON.stringify(state.pendingBooking),
    });
    state.bookingResult = result;

    if (url) {
      if (tg) tg.openLink(url);
      else window.open(url, '_blank');
    }

    if (isAuto) {
      setTimeout(() => tg ? tg.close() : showSuccessPage(result), 300);
    } else {
      // Show "Я оплатил(а)" button
      if (btn) { btn.disabled = false; btn.textContent = '💸 Я оплатил(а)'; btn.onclick = notifyPaid; }
    }
  } catch (e) {
    showToast('Ошибка: ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = 'Оплатить'; }
  }
}

function showPaymentPage(prepaymentAmount) {
  const m = state.masterInfo;
  const isAuto = m.prepayment_mode === 'auto';
  const payUrl = m.payment_button_url || '';
  const payText = escHtml(m.payment_button_text || 'Оплатить');

  const hintHtml = isAuto
    ? `<p style="font-size:13px;color:var(--gray-5);margin-top:16px;line-height:1.6">После нажатия приложение<br>закроется автоматически</p>`
    : `<p style="font-size:13px;color:var(--gray-5);margin-top:16px;line-height:1.6">После оплаты нажмите<br>«Я оплатил(а)» ниже</p>`;

  document.getElementById('payment-content').innerHTML = `
    <div style="display:flex;flex-direction:column;align-items:center;padding:40px 24px 24px;text-align:center">
      <div style="font-size:13px;color:var(--gray-5);text-transform:uppercase;letter-spacing:0.1em;font-weight:700;margin-bottom:10px">Сумма предоплаты</div>
      <div class="payment-amount" style="margin-bottom:32px">${formatPrice(prepaymentAmount)}</div>
      <button id="pay-btn" class="btn-primary" style="width:100%;max-width:320px;font-size:16px;padding:18px"
              onclick="doBookThenPay('${escHtml(payUrl)}', ${isAuto})">
        ${payText}
      </button>
      ${hintHtml}
      <p style="font-size:11px;color:var(--gray-5);margin-top:12px;line-height:1.5">⚠️ Предоплата не возвращается<br>при отмене записи</p>
    </div>
  `;
  const bar = document.getElementById('payment-confirm-bar');
  if (bar) bar.style.display = 'none';
  showPage('payment');
}

function showSuccessPage(result) {
  const selectedServices = state.services.filter(s => state.selectedServiceIds.includes(s.id));
  const d = new Date(state.selectedDate);
  const dateStr = `${d.getDate()} ${MONTHS_RU[d.getMonth()]}`;

  document.getElementById('page-success').innerHTML = `
    <div class="success-screen confirmed">
      <div class="success-icon">⏳</div>
      <h2>Запись в обработке</h2>
      <p>Когда запись будет подтверждена —<br>придёт уведомление в Telegram</p>
      <div class="success-details">
        <div class="summary-row">
          <span class="summary-row-label">Дата и время</span>
          <span class="summary-row-value">${dateStr}, ${state.selectedTime}</span>
        </div>
        <div class="summary-row">
          <span class="summary-row-label">Услуга</span>
          <span class="summary-row-value">${escHtml(selectedServices.map(s => s.name).join(', '))}</span>
        </div>
        <div class="summary-row">
          <span class="summary-row-label">Сумма</span>
          <span class="summary-row-value summary-total">${formatPrice(result.total_price)}</span>
        </div>
      </div>
      <button class="btn-primary" style="width:100%" onclick="goHome()">На главную</button>
    </div>
  `;
  showPage('success');
  if (tg) tg.BackButton.hide();
}

async function notifyPaid() {
  const btn = document.getElementById('pay-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Отправляем...'; }

  try {
    await apiFetch(`/api/appointments/${state.bookingResult.appointment_id}/payment-sent`, {
      method: 'POST',
    });
  } catch(e) {}

  const selectedServices = state.services.filter(s => state.selectedServiceIds.includes(s.id));
  const d = new Date(state.selectedDate);
  const dateStr = `${d.getDate()} ${MONTHS_RU[d.getMonth()]}`;

  document.getElementById('page-success').innerHTML = `
    <div class="success-screen">
      <div class="success-icon" style="background:rgba(255,165,0,0.15);color:#f0a500">⏳</div>
      <h2>Оплата на проверке</h2>
      <p>Администратор проверит оплату и подтвердит запись.<br>Уведомление придёт в Telegram.</p>
      <div class="success-details">
        <div class="summary-row">
          <span class="summary-row-label">Дата и время</span>
          <span class="summary-row-value">${dateStr}, ${state.selectedTime}</span>
        </div>
        <div class="summary-row">
          <span class="summary-row-label">Услуга</span>
          <span class="summary-row-value">${escHtml(selectedServices.map(s => s.name).join(', '))}</span>
        </div>
        <div class="summary-row">
          <span class="summary-row-label">Предоплата</span>
          <span class="summary-row-value">${formatPrice(state.bookingResult.prepayment_amount)}</span>
        </div>
      </div>
      <button class="btn-primary" style="width:100%" onclick="if(tg)tg.close();else goHome()">Закрыть</button>
    </div>
  `;
  showPage('success');
  if (tg) tg.BackButton.hide();
}

// ─── Waitlist ─────────────────────────────────────────────────────────────────
function addToWaitlist() {
  document.getElementById('waitlist-form').style.display = 'block';
  document.getElementById('waitlist-name').value = '';
  document.getElementById('waitlist-phone').value = '';
  document.getElementById('waitlist-name').focus();
}

async function submitWaitlist() {
  const name  = document.getElementById('waitlist-name')?.value.trim() || '';
  const phone = document.getElementById('waitlist-phone')?.value.trim() || '';
  if (!name)  { showToast('Введите имя'); return; }
  if (!phone) { showToast('Введите телефон'); return; }
  try {
    await apiFetch('/api/waitlist', {
      method: 'POST',
      body: JSON.stringify({ name, phone, service_ids: state.selectedServiceIds }),
    });
    document.getElementById('waitlist-form').style.display = 'none';
    showToast('✅ Вы добавлены в лист ожидания');
  } catch (e) {
    showToast('Ошибка: ' + e.message);
  }
}

// ─── Booking strip ────────────────────────────────────────────────────────────
function renderBookingStrip(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const svcs = state.services.filter(s => state.selectedServiceIds.includes(s.id));
  const months = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
  const d = state.selectedDate ? new Date(state.selectedDate + 'T00:00:00') : null;
  const dateStr = d ? `${d.getDate()} ${months[d.getMonth()]}` : '';
  const items = [];
  if (svcs.length) items.push(`<span class="booking-strip-item">✂️ <strong>${svcs.map(s => s.name).join(', ')}</strong></span>`);
  if (dateStr)    items.push(`<span class="booking-strip-sep">·</span><span class="booking-strip-item">📅 <strong>${dateStr}</strong></span>`);
  if (state.selectedTime) items.push(`<span class="booking-strip-sep">·</span><span class="booking-strip-item">🕐 <strong>${state.selectedTime}</strong></span>`);
  el.innerHTML = items.length
    ? `<div class="booking-strip">${items.join('')}</div>`
    : '';
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function goHome() {
  state.selectedServiceIds = [];
  state.selectedDate = null;
  state.selectedTime = null;
  showPage('home');
}

function formatPrice(price) {
  return new Intl.NumberFormat('ru-RU').format(Math.round(price)) + ' ₸';
}
function formatSvcPrice(s) {
  const fmt = p => new Intl.NumberFormat('ru-RU').format(Math.round(p || 0));
  if (s.price_type === 'from')  return `от ${fmt(s.price)} ₸`;
  if (s.price_type === 'range') return `${fmt(s.price)} – ${fmt(s.price_to)} ₸`;
  return `${fmt(s.price)} ₸`;
}

function formatDuration(mins) {
  if (mins < 60) return `${mins} мин`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h} ч ${m} мин` : `${h} ч`;
}

function getTotalDuration() {
  if (!state.selectedServiceIds.length) return 60;
  return state.selectedServiceIds.reduce((sum, id) => {
    const s = state.services.find(x => x.id === id);
    return sum + (s ? s.duration_min : 0);
  }, 0) || 60;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function copyText(text) {
  navigator.clipboard.writeText(text).then(() => showToast('Скопировано!'));
}

function applyPhoneMask(input) {
  input.addEventListener('input', function(e) {
    let val = this.value.replace(/\D/g, '');
    if (val.startsWith('8')) val = '7' + val.slice(1);
    if (val.startsWith('7')) val = val.slice(0, 11);
    else val = val.slice(0, 10);

    let out = '';
    if (val.length === 0) { this.value = ''; return; }
    out = '+7';
    if (val.length > 1) out += ' (' + val.slice(1, 4);
    if (val.length >= 4) out += ') ' + val.slice(4, 7);
    if (val.length >= 7) out += '-' + val.slice(7, 9);
    if (val.length >= 9) out += '-' + val.slice(9, 11);
    this.value = out;
  });
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Backspace' && this.value.match(/\D$/)) {
      this.value = this.value.replace(/\D+$/, '');
      e.preventDefault();
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  ['client-phone', 'waitlist-phone', 'appt-phone-input'].forEach(id => {
    const el = document.getElementById(id);
    if (el) applyPhoneMask(el);
  });
});

function showToast(msg) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2500);
}
