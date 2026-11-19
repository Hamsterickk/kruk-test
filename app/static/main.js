// ===== ИКОНКИ =====
const svg = (body, size = 18, sw = 1.8) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
const ICONS = {
  copy: svg('<rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15"/>', 15),
  check: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 15, 2),
  trash: svg('<path d="M4 7h16"/><path d="M9.5 7V5a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 5v2"/><path d="M6.5 7l.8 11.2A2 2 0 0 0 9.3 20h5.4a2 2 0 0 0 2-1.8L17.5 7"/><path d="M10.5 11v5M13.5 11v5"/>', 15),
  pencil: svg('<path d="M14.5 5.5l4 4"/><path d="M4 20l1-4.5L15.8 4.7a1.4 1.4 0 0 1 2 0l1.5 1.5a1.4 1.4 0 0 1 0 2L8.5 19 4 20z"/>', 15),
  close: svg('<path d="M6 6l12 12M18 6L6 18"/>', 18, 2),
  plus: svg('<path d="M12 5v14M5 12h14"/>', 16, 2),
  left: svg('<path d="M15 5l-7 7 7 7"/>', 18, 2),
  right: svg('<path d="M9 5l7 7-7 7"/>', 18, 2),
  down: svg('<path d="M6 9l6 6 6-6"/>', 18, 2),
  send: svg('<path d="M5 12h13"/><path d="M13 6l6 6-6 6"/>', 20, 2.2),
  home: svg('<path d="M4 11l8-6.5 8 6.5"/><path d="M6 10v9h12v-9"/>', 20),
  food: svg('<path d="M7 3v8a2 2 0 0 0 2 2v8"/><path d="M11 3v8a2 2 0 0 1-2 2"/><path d="M17 21V3c-1.7 1-3 3.3-3 7 0 2 1 3 3 3"/>', 20),
  body: svg('<path d="M3 17l5-6 4 4 5-7 4 5"/><path d="M3 21h18"/>', 20),
  club: svg('<rect x="4" y="5" width="16" height="15" rx="2.5"/><path d="M4 10h16M9 3v4M15 3v4"/>', 20),
  chat: svg('<path d="M20 12a8 8 0 0 1-11.5 7.2L4 20l1-4A8 8 0 1 1 20 12z"/>', 20),
  trainer: svg('<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 4.8a3.2 3.2 0 0 1 0 6.4M17.5 14a5.5 5.5 0 0 1 3 5"/>', 20),
};

function iconButton(icon, title, cls = '') {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = `icon-btn ${cls}`.trim();
  b.title = title;
  b.setAttribute('aria-label', title);
  b.innerHTML = ICONS[icon];
  return b;
}

// ===== ТЕЛЕГРАМ =====
const tg = window.Telegram ? window.Telegram.WebApp : null;
try {
  tg.ready();
  tg.expand();
  tg.setHeaderColor('#0b110e');
  tg.setBackgroundColor('#0b110e');
  tg.disableVerticalSwipes();
} catch (e) { /* старые клиенты */ }

const WD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n, d = 1) => (n === null || n === undefined ? '–' : (Math.round(n * 10 ** d) / 10 ** d).toString().replace('.', ','));
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const ddmm = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
const wdOf = (iso) => WD[(new Date(`${iso}T12:00:00`).getDay() + 6) % 7];

function toast(text) {
  const t = document.getElementById('toast');
  t.textContent = text;
  t.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove('show'), 3000);
}

function confirmDialog(text, okText = 'Да') {
  return new Promise((resolve) => {
    const overlay = document.getElementById('confirmOverlay');
    document.getElementById('confirmText').textContent = text;
    const ok = document.getElementById('confirmOk');
    const cancel = document.getElementById('confirmCancel');
    ok.textContent = okText;
    overlay.classList.remove('hidden');
    const done = (r) => { overlay.classList.add('hidden'); ok.onclick = null; cancel.onclick = null; resolve(r); };
    ok.onclick = () => done(true);
    cancel.onclick = () => done(false);
  });
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch (e) { /* запасной путь ниже */ }
  const a = document.createElement('textarea');
  a.value = text; a.style.position = 'fixed'; a.style.opacity = '0';
  document.body.appendChild(a); a.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  a.remove();
  return ok;
}

// ===== API =====
async function api(path, options = {}) {
  const opts = { ...options, headers: { 'X-Telegram-Init-Data': tg ? tg.initData : '', ...(options.headers || {}) } };
  if (options.json !== undefined) {
    opts.method = opts.method || 'POST';
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(options.json);
  }
  let res;
  try { res = await fetch(path, opts); } catch (e) { toast('Нет связи с сервером'); return null; }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    const err = data && data.error;
    if (err === 'not_registered' || err === 'onboarding' || err === 'unauthorized') { showGate(err); return null; }
    toast(err || `Ошибка ${res.status}`);
    return null;
  }
  return data;
}

function showGate(reason) {
  const text = {
    not_registered: 'Это тестовое приложение клуба Kruk Team. Вход по приглашению тренера: открой ссылку от него в Телеграме.',
    onboarding: 'Сначала закончи короткую анкету в чате с ботом – потом всё откроется здесь.',
    unauthorized: 'Открой приложение из Телеграма – кнопка «Приложение» в чате с ботом.',
  }[reason];
  document.getElementById('gateText').textContent = text;
  document.getElementById('gate').classList.remove('hidden');
}

// ===== НАВИГАЦИЯ =====
let me = null;
const loaders = {};
document.querySelectorAll('.nav-ico').forEach((el) => { el.innerHTML = ICONS[el.dataset.icon]; });
document.querySelectorAll('.nav-btn').forEach((btn) => btn.addEventListener('click', () => openScreen(btn.dataset.screen)));

function openScreen(name) {
  document.querySelectorAll('.screen').forEach((s) => s.classList.toggle('active', s.id === `screen-${name}`));
  document.querySelectorAll('.nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.screen === name));
  window.scrollTo(0, 0);
  if (loaders[name]) loaders[name]();
}

document.getElementById('homeBody').addEventListener('click', () => openScreen('body'));

// ===== СЕГОДНЯ =====
function kcalBlock(prefix, totals, target, proteinTarget) {
  document.getElementById(`${prefix}Kcal`).textContent = totals.kcal;
  document.getElementById(`${prefix}KcalOf`).textContent = target ? ` из ${target} ккал` : ' ккал';
  const pct = target ? Math.min(100, (totals.kcal / target) * 100) : 0;
  const bar = document.getElementById(`${prefix}KcalBar`);
  bar.style.width = `${pct}%`;
  bar.classList.toggle('over', target && totals.kcal > target * 1.1);
  document.getElementById(`${prefix}Macros`).innerHTML = `
    <span><b>${totals.protein}</b>${proteinTarget ? `/${proteinTarget}` : ''} белки</span>
    <span><b>${totals.fat}</b> жиры</span><span><b>${totals.carbs}</b> углеводы</span>`;
}

function sessionRow(s, onMark) {
  const row = document.createElement('div');
  row.className = `session${s.cancelled ? ' cancelled' : ''}`;
  const today = s.date === isoDay(new Date());
  const when = today ? 'Сегодня' : `${s.weekday} ${ddmm(s.date)}`;
  row.innerHTML = `
    <div class="session-time"><b>${esc(s.start)}</b><span>${esc(when)}</span></div>
    <div class="session-info"><div>${esc(s.group)}</div><div class="muted small">${esc(s.location)}${s.address ? ` · ${esc(s.address)}` : ''}</div>
    ${s.cancelled ? `<div class="tag tag-red">Отменено${s.note ? `: ${esc(s.note)}` : ''}</div>` : ''}</div>`;
  if (onMark && s.started && !s.cancelled) {
    const box = document.createElement('div');
    box.className = 'mark-btns';
    [['Был', true], ['Не был', false]].forEach(([label, val]) => {
      const b = document.createElement('button');
      b.className = `chip${s.present === val ? ' active' : ''}`;
      b.textContent = label;
      b.addEventListener('click', () => onMark(s, val));
      box.appendChild(b);
    });
    row.querySelector('.session-info').appendChild(box);
  }
  return row;
}

async function markAttendance(s, present) {
  const r = await api('/api/club/attendance', { json: { group_id: s.group_id, date: s.date, present } });
  if (r) { toast(present ? 'Отметил: был 💪' : 'Отметил: не был'); loaders.home(); }
}

function renderGoals(container, list, onToggle, onDelete, allowAll = false) {
  container.innerHTML = '';
  if (!list.length) { container.innerHTML = '<div class="empty">Целей пока нет – добавь ниже</div>'; return; }
  list.forEach((g) => {
    const row = document.createElement('div');
    row.className = `check-row${g.done ? ' done' : ''}`;
    row.innerHTML = `<span class="checkbox${g.done ? ' checked' : ''}"></span><span class="check-title">${esc(g.title)}</span>
      ${g.by_trainer ? '<span class="tag">от тренера</span>' : ''}${g.daily ? '' : '<span class="tag">сегодня</span>'}`;
    row.addEventListener('click', () => onToggle(g));
    if (onDelete && (allowAll || !g.by_trainer)) {
      const del = iconButton('trash', 'Удалить', 'danger');
      del.addEventListener('click', (e) => { e.stopPropagation(); onDelete(g); });
      row.appendChild(del);
    }
    container.appendChild(row);
  });
}

loaders.home = async () => {
  const d = await api('/api/today');
  if (!d) return;
  kcalBlock('home', d.food, d.kcal_target, d.protein_target);
  const left = d.kcal_target ? d.kcal_target - d.food.kcal : null;
  document.getElementById('homeKcalNote').textContent = left === null ? '' : left > 0 ? `осталось ${left}` : `перебор ${-left}`;
  const sess = document.getElementById('homeSessions');
  sess.innerHTML = '';
  if (!d.sessions.length) sess.innerHTML = '<div class="empty">Тренер ещё не поставил тебе группы</div>';
  d.sessions.forEach((s) => sess.appendChild(sessionRow(s, markAttendance)));
  document.getElementById('homeWeek').textContent = d.week.total ? `на неделе ${d.week.present} из ${d.week.total}` : '';
  const done = d.goals.filter((g) => g.done).length;
  document.getElementById('homeGoalsCount').textContent = d.goals.length ? `${done} из ${d.goals.length}` : '';
  renderGoals(document.getElementById('homeGoals'), d.goals, async (g) => {
    if (await api(`/api/goals/${g.id}/toggle`, { method: 'POST' })) loaders.home();
  }, async (g) => {
    if (!(await confirmDialog(`Удалить цель «${g.title}»?`, 'Удалить'))) return;
    if (await api(`/api/goals/${g.id}`, { method: 'DELETE' })) loaders.home();
  });
  document.getElementById('homeWeight').textContent = fmt(d.weight);
  document.getElementById('homeSleep').textContent = fmt(d.sleep);
  document.getElementById('homeSteps').textContent = d.steps ?? '–';
};

async function addGoal() {
  const input = document.getElementById('goalInput');
  const title = input.value.trim();
  if (!title) return;
  const r = await api('/api/goals', { json: { title, daily: document.getElementById('goalDaily').checked } });
  if (r) { input.value = ''; loaders.home(); }
}
document.getElementById('goalAddBtn').addEventListener('click', addGoal);
document.getElementById('goalInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') addGoal(); });

// ===== ЕДА =====
function gramsPrompt(container, food, onSave) {
  container.querySelectorAll('.grams-box').forEach((el) => el.remove());
  const box = document.createElement('div');
  box.className = 'grams-box';
  box.innerHTML = `<input type="number" inputmode="decimal" value="${food.portion || 100}"><span class="muted">г</span>
    <button class="btn-small accent">Записать</button>`;
  const input = box.querySelector('input');
  const go = async () => {
    const grams = parseFloat(input.value.replace(',', '.'));
    if (!grams) { toast('Сколько грамм?'); return; }
    await onSave(grams);
  };
  box.querySelector('button').addEventListener('click', go);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  return box;
}

let searchTimer = null;
document.getElementById('foodSearch').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => runSearch(e.target.value.trim()), 250);
});

async function runSearch(q) {
  const list = document.getElementById('foodResults');
  if (q.length < 2) { list.innerHTML = ''; return; }
  const items = await api(`/api/food/search?q=${encodeURIComponent(q)}`);
  if (!items) return;
  list.innerHTML = '';
  if (!items.length) {
    list.innerHTML = '<div class="empty">Не нашёл. Добавь в «Мою базу» ниже или напиши в чат – посчитает ИИ.</div>';
    return;
  }
  items.forEach((f) => {
    const row = document.createElement('div');
    row.className = 'food-item';
    row.innerHTML = `<div><div>${esc(f.name)}${f.personal ? ' <span class="tag">моё</span>' : ''}</div>
      <div class="muted small">${fmt(f.kcal, 0)} ккал · Б ${fmt(f.protein)} Ж ${fmt(f.fat)} У ${fmt(f.carbs)} на 100 г${f.portion ? ` · порция ${fmt(f.portion, 0)} г` : ''}</div></div>`;
    row.addEventListener('click', () => {
      const existing = row.nextElementSibling;
      if (existing && existing.classList.contains('grams-box')) { existing.remove(); return; }
      row.after(gramsPrompt(list, f, async (grams) => {
        const r = await api('/api/food/log', { json: { food_id: f.id, grams } });
        if (r) {
          toast(`Записал: ${r.name} ${r.grams} г – ${r.kcal} ккал`);
          document.getElementById('foodSearch').value = '';
          list.innerHTML = '';
          loaders.food();
        }
      }));
      row.nextElementSibling.querySelector('input').focus();
    });
    list.appendChild(row);
  });
}

function mealRow(m) {
  const row = document.createElement('div');
  row.className = 'meal';
  row.innerHTML = `<div class="meal-main"><div>${esc(m.name)}${m.estimated ? ' <span class="tag" title="КБЖУ оценил ИИ">≈</span>' : ''}</div>
    <div class="muted small">${m.kcal} ккал · Б ${fmt(m.protein)} Ж ${fmt(m.fat)} У ${fmt(m.carbs)}</div></div>
    <button class="grams-btn">${m.grams} г</button>`;
  const del = iconButton('trash', 'Удалить', 'danger');
  del.addEventListener('click', async () => {
    if (!(await confirmDialog(`Удалить «${m.name}»?`, 'Удалить'))) return;
    if (await api(`/api/food/meal/${m.id}`, { method: 'DELETE' })) loaders.food();
  });
  row.appendChild(del);
  row.querySelector('.grams-btn').addEventListener('click', () => {
    const next = row.nextElementSibling;
    if (next && next.classList.contains('grams-box')) { next.remove(); return; }
    row.after(gramsPrompt(row.parentElement, { portion: m.grams }, async (grams) => {
      if (await api(`/api/food/meal/${m.id}`, { json: { grams } })) loaders.food();
    }));
  });
  return row;
}

loaders.food = async () => {
  const [d, y] = await Promise.all([api('/api/food/today'), api('/api/food/yesterday')]);
  if (!d) return;
  kcalBlock('food', d.totals, d.kcal_target, d.protein_target);
  document.getElementById('foodNorm').textContent = d.kcal_target ? `норма ${d.kcal_target}` : '';
  const list = document.getElementById('mealsList');
  list.innerHTML = '';
  if (!d.meals.length) list.innerHTML = '<div class="empty">Пока пусто. Найди продукт выше или напиши в чат: «гречка 200, курица 150»</div>';
  d.meals.forEach((m) => list.appendChild(mealRow(m)));
  const yw = document.getElementById('yesterdayWidget');
  if (y && y.meals.length) {
    yw.classList.remove('hidden');
    const yl = document.getElementById('yesterdayList');
    yl.innerHTML = '';
    y.meals.forEach((m) => {
      const row = document.createElement('div');
      row.className = 'food-item compact';
      row.innerHTML = `<div>${esc(m.name)} <span class="muted small">${m.grams} г · ${m.kcal} ккал</span></div>`;
      const add = iconButton('plus', 'Записать сегодня');
      add.addEventListener('click', async () => {
        const r = await api('/api/food/repeat', { json: { ids: [m.id] } });
        if (r) { toast(`Записал: ${m.name}`); loaders.food(); }
      });
      row.appendChild(add);
      yl.appendChild(row);
    });
    const btn = document.getElementById('repeatAllBtn');
    btn.textContent = y.done ? '✓ Повторено' : `Повторить всё · ${y.kcal}`;
    btn.onclick = async () => {
      if (y.done && !(await confirmDialog('Вчерашнее уже записано сегодня. Записать ещё раз?', 'Записать'))) return;
      const r = await api('/api/food/repeat', { json: {} });
      if (r) { toast(`Записал ${r.count} шт. как вчера`); loaders.food(); }
    };
  } else yw.classList.add('hidden');
  loadBase();
};

async function loadBase() {
  const items = await api('/api/food/base');
  if (!items) return;
  const list = document.getElementById('baseList');
  list.innerHTML = '';
  if (!items.length) list.innerHTML = '<div class="empty">Здесь будут твои продукты: с упаковки или те, что ИИ предложит запомнить</div>';
  items.forEach((f) => {
    const row = document.createElement('div');
    row.className = 'food-item compact';
    row.innerHTML = `<div><div>${esc(f.name)}</div><div class="muted small">${fmt(f.kcal, 0)} ккал · Б ${fmt(f.protein)} Ж ${fmt(f.fat)} У ${fmt(f.carbs)}${f.portion ? ` · порция ${fmt(f.portion, 0)} г` : ''}</div></div>`;
    const del = iconButton('trash', 'Удалить из базы', 'danger');
    del.addEventListener('click', async () => {
      if (!(await confirmDialog(`Удалить «${f.name}» из базы?`, 'Удалить'))) return;
      if (await api(`/api/food/base/${f.id}`, { method: 'DELETE' })) loadBase();
    });
    row.appendChild(del);
    list.appendChild(row);
  });
}

function setBaseOpen(open) {
  document.getElementById('baseToggle').classList.toggle('open', open);
  document.getElementById('baseBody').classList.toggle('hidden', !open);
}
document.getElementById('baseToggle').addEventListener('click', () => setBaseOpen(document.getElementById('baseBody').classList.contains('hidden')));
document.getElementById('baseAddBtn').addEventListener('click', (e) => {
  e.stopPropagation();
  setBaseOpen(true);
  const form = document.getElementById('baseForm');
  form.classList.toggle('hidden');
  if (!form.classList.contains('hidden')) document.getElementById('baseName').focus();
});
document.getElementById('baseSaveBtn').addEventListener('click', async () => {
  const v = (id) => document.getElementById(id).value.trim();
  const r = await api('/api/food/base', { json: { name: v('baseName'), kcal: v('baseKcal'), protein: v('baseP'), fat: v('baseF'), carbs: v('baseC'), portion: v('basePortion') } });
  if (!r) return;
  ['baseName', 'baseKcal', 'baseP', 'baseF', 'baseC', 'basePortion'].forEach((id) => { document.getElementById(id).value = ''; });
  document.getElementById('baseForm').classList.add('hidden');
  toast(`Сохранил: ${r.name}`);
  loadBase();
});

// ===== ТЕЛО =====
let weekOffset = 0;
let bodyDay = null;
document.getElementById('weekPrev').innerHTML = ICONS.left;
document.getElementById('weekNext').innerHTML = ICONS.right;
document.getElementById('weekPrev').addEventListener('click', () => { weekOffset += 1; loaders.body(); });
document.getElementById('weekNext').addEventListener('click', () => { if (weekOffset > 0) { weekOffset -= 1; loaders.body(); } });

function bars(containerId, days, key, opts) {
  const el = document.getElementById(containerId);
  const vals = days.map((d) => d[key]).filter((v) => v !== null && v !== undefined);
  const max = Math.max(...vals, opts.min || 1);
  const min = opts.floor ? Math.min(...vals, max) * 0.97 : 0;
  const today = isoDay(new Date());
  const minDay = isoDay(new Date(Date.now() - 6 * 864e5));
  el.innerHTML = '';
  days.forEach((d, i) => {
    const v = d[key];
    const h = v === null || v === undefined ? 0 : Math.max(6, ((v - min) / (max - min || 1)) * 100);
    const col = document.createElement('button');
    const editable = !d.future && d.date >= minDay;
    col.className = `bar-col${d.date === today ? ' today' : ''}${d.date === bodyDay ? ' selected' : ''}${editable ? '' : ' locked'}`;
    col.innerHTML = `<span class="bar-val">${v === null || v === undefined ? '' : opts.label(v)}</span>
      <span class="bar-track"><span class="bar-in${opts.low && v !== null && v < opts.low ? ' low' : ''}" style="height:${h}%"></span></span>
      <span class="bar-day">${WD[i]}</span>`;
    if (editable) col.addEventListener('click', () => selectBodyDay(d));
    el.appendChild(col);
  });
}

function selectBodyDay(d) {
  bodyDay = d.date === isoDay(new Date()) ? null : d.date;
  document.getElementById('bodyFormTitle').textContent = bodyDay ? `Записать за ${wdOf(d.date)} ${ddmm(d.date)}` : 'Записать за сегодня';
  document.getElementById('inWeight').value = d.weight ?? '';
  document.getElementById('inSleep').value = d.sleep ?? '';
  document.getElementById('inSteps').value = d.steps ?? '';
  document.querySelectorAll('.bar-col').forEach((c) => c.classList.remove('selected'));
  loaders.body(true);
  document.getElementById('inWeight').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

let bodyData = null;
loaders.body = async (keepForm) => {
  const d = await api(`/api/body?week=${weekOffset}`);
  if (!d) return;
  bodyData = d;
  document.getElementById('weekLabel').textContent = weekOffset === 0 ? 'Эта неделя' : weekOffset === 1 ? 'Прошлая неделя'
    : `${ddmm(d.days[0].date)} – ${ddmm(d.days[6].date)}`;
  document.getElementById('weekNext').disabled = weekOffset === 0;
  bars('weightBars', d.days, 'weight', { floor: true, label: (v) => fmt(v) });
  bars('sleepBars', d.days, 'sleep', { min: 9, low: 7, label: (v) => fmt(v) });
  bars('stepsBars', d.days, 'steps', { min: 10000, low: 6000, label: (v) => (v >= 1000 ? `${fmt(v / 1000)}к` : v) });
  const s = d.summary;
  document.getElementById('weightNote').textContent = s.weight ? `сейчас ${fmt(s.weight)}${s.weight_change ? ` · за неделю ${s.weight_change > 0 ? '+' : ''}${fmt(s.weight_change)}` : ''}` : '';
  document.getElementById('sleepNote').textContent = s.sleep_avg ? `в среднем ${fmt(s.sleep_avg)}` : '';
  document.getElementById('stepsNote').textContent = s.steps_avg ? `в среднем ${s.steps_avg}` : '';
  if (!keepForm && !bodyDay) {
    const t = d.days.find((x) => x.date === isoDay(new Date()));
    if (t) {
      document.getElementById('inWeight').value = t.weight ?? '';
      document.getElementById('inSleep').value = t.sleep ?? '';
      document.getElementById('inSteps').value = t.steps ?? '';
    }
  }
  loadProfile();
};

document.getElementById('bodySaveBtn').addEventListener('click', async () => {
  const v = (id) => document.getElementById(id).value.trim();
  const r = await api('/api/body', { json: { date: bodyDay, weight: v('inWeight'), sleep: v('inSleep'), steps: v('inSteps') } });
  if (!r) return;
  toast(bodyDay ? `Записал за ${ddmm(bodyDay)}` : 'Записал');
  bodyDay = null;
  document.getElementById('bodyFormTitle').textContent = 'Записать за сегодня';
  loaders.body();
});

const morningSel = document.getElementById('pMorning');
for (let h = 5; h <= 12; h += 1) morningSel.insertAdjacentHTML('beforeend', `<option value="${h}">${String(h).padStart(2, '0')}:00</option>`);

async function loadProfile() {
  me = await api('/api/me');
  if (!me) return;
  document.getElementById('normText').textContent = me.kcal_target
    ? `Норма: ${me.kcal_target} ккал, белок ${me.protein_target} г. Считается по анкете и последнему весу.`
    : 'Норма появится, когда будут рост, возраст, вес и цель.';
  document.getElementById('pGoal').value = me.goal || 'keep';
  morningSel.value = me.morning_hour || 10;
  document.getElementById('pAge').value = me.age ?? '';
  document.getElementById('pHeight').value = me.height_cm ?? '';
}

document.getElementById('profileSaveBtn').addEventListener('click', async () => {
  const body = { goal: document.getElementById('pGoal').value, morning_hour: morningSel.value };
  const age = document.getElementById('pAge').value.trim();
  const height = document.getElementById('pHeight').value.trim();
  if (age) body.age = age;
  if (height) body.height_cm = height;
  const r = await api('/api/me', { json: body });
  if (r) { toast(r.kcal_target ? `Сохранил. Норма ${r.kcal_target} ккал` : 'Сохранил'); loadProfile(); }
});

// ===== КЛУБ =====
loaders.club = async () => {
  const d = await api('/api/club');
  if (!d) return;
  const gl = document.getElementById('myGroups');
  gl.innerHTML = '';
  if (!d.groups.length) gl.innerHTML = '<div class="empty">Групп пока нет. Тренер поставит их по твоему абонементу – бот сразу напишет.</div>';
  d.groups.forEach((g) => {
    gl.insertAdjacentHTML('beforeend', `<div class="group-card"><div class="group-name">${esc(g.name)}</div>
      <div class="muted small">${esc(g.days_text)}, ${esc(g.start)}–${esc(g.end)}</div>
      <div class="muted small">${esc(g.location)}${g.address ? ` · ${esc(g.address)}` : ''}</div></div>`);
  });
  document.getElementById('clubStats').textContent = d.stats.percent !== null ? `посещаемость ${d.stats.percent}%` : '';
  const up = document.getElementById('upcomingList');
  up.innerHTML = '';
  if (!d.upcoming.length) up.innerHTML = '<div class="empty">Ближайших занятий нет</div>';
  d.upcoming.forEach((s) => up.appendChild(sessionRow(s, async (x, val) => { await markAttendance(x, val); loaders.club(); })));
  const hl = document.getElementById('historyList');
  hl.innerHTML = '';
  if (!d.history.length) hl.innerHTML = '<div class="empty">Здесь появятся прошедшие занятия</div>';
  d.history.forEach((h) => hl.appendChild(historyRow(h, false, async (val, note) => {
    const body = { group_id: h.group_id, date: h.date };
    if (val !== undefined) body.present = val;
    if (note !== undefined) body.note = note;
    if (await api('/api/club/attendance', { json: body })) loaders.club();
  })));
};

function historyRow(h, trainerMode, onSet) {
  const row = document.createElement('div');
  row.className = `history-row${h.cancelled ? ' cancelled' : ''}`;
  const state = h.cancelled ? '<span class="tag">отменено</span>' : h.present === true ? '<span class="tag tag-green">был</span>'
    : h.present === false ? '<span class="tag tag-red">не был</span>' : '<span class="tag">не отмечено</span>';
  row.innerHTML = `<div class="history-main"><div><b>${wdOf(h.date)} ${ddmm(h.date)}</b> ${esc(h.time)} · ${esc(h.group)}</div>
    ${h.note ? `<div class="muted small">${esc(h.note)}</div>` : ''}${h.by_trainer && !trainerMode ? '<div class="muted small">отметил тренер</div>' : ''}</div>${state}`;
  if (h.cancelled) return row;
  const locked = !trainerMode && h.by_trainer;
  if (!locked) {
    row.classList.add('tap');
    row.addEventListener('click', () => {
      const next = row.nextElementSibling;
      if (next && next.classList.contains('history-edit')) { next.remove(); return; }
      const box = document.createElement('div');
      box.className = 'history-edit';
      const options = trainerMode ? [['Был', true], ['Не был', false], ['Сбросить', null]] : [['Был', true], ['Не был', false]];
      box.innerHTML = `<div class="chips"></div>${trainerMode ? '' : `<input type="text" placeholder="Что отрабатывали – необязательно" value="${esc(h.note || '')}" maxlength="500"><button class="btn-small accent">Сохранить заметку</button>`}`;
      options.forEach(([label, val]) => {
        const b = document.createElement('button');
        b.className = `chip${h.present === val ? ' active' : ''}`;
        b.textContent = label;
        b.addEventListener('click', () => onSet(val));
        box.querySelector('.chips').appendChild(b);
      });
      if (!trainerMode) box.querySelector('button.btn-small').addEventListener('click', () => onSet(undefined, box.querySelector('input').value.trim()));
      row.after(box);
    });
  }
  return row;
}

// ===== ЧАТ =====
function mdLite(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/(^|\s)_(.+?)_(?=\s|$|[.,!?])/g, '$1<i>$2</i>')
    .replace(/^#{1,6}\s+(.+)$/gm, '<b>$1</b>')
    .replace(/^[-*]\s+/gm, '• ')
    .replace(/\n/g, '<br>');
}

function appendMessage(role, content, id, actions) {
  const box = document.getElementById('chatMessages');
  const wrap = document.createElement('div');
  wrap.className = `msg-wrap ${role}`;
  const msg = document.createElement('div');
  msg.className = `msg ${role}`;
  msg.innerHTML = mdLite(content);
  wrap.appendChild(msg);
  if (actions && actions.length) {
    const row = document.createElement('div');
    row.className = 'msg-buttons';
    actions.forEach((a) => {
      const b = document.createElement('button');
      b.className = 'chip';
      b.textContent = a.label;
      b.addEventListener('click', async () => {
        row.remove();
        const r = await api('/api/chat/action', { json: { data: a.data } });
        if (r) { appendMessage('assistant', r.reply, r.id); scrollChat(); }
      });
      row.appendChild(b);
    });
    wrap.appendChild(row);
  }
  const tools = document.createElement('div');
  tools.className = 'msg-tools';
  const copy = iconButton('copy', 'Скопировать');
  copy.addEventListener('click', async () => {
    if (!(await copyText(content))) { toast('Не получилось скопировать'); return; }
    copy.innerHTML = ICONS.check; copy.classList.add('done');
    setTimeout(() => { copy.innerHTML = ICONS.copy; copy.classList.remove('done'); }, 1200);
  });
  tools.appendChild(copy);
  if (id) {
    const del = iconButton('trash', 'Удалить', 'danger');
    del.addEventListener('click', async () => {
      if (!(await confirmDialog('Удалить это сообщение из истории?', 'Удалить'))) return;
      if (await api(`/api/chat/${id}`, { method: 'DELETE' })) wrap.remove();
    });
    tools.appendChild(del);
  }
  wrap.appendChild(tools);
  box.appendChild(wrap);
  return wrap;
}

function scrollChat() {
  const box = document.getElementById('chatMessages');
  requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; updateScrollBtn(); });
}

function updateScrollBtn() {
  const box = document.getElementById('chatMessages');
  document.getElementById('scrollDownBtn').classList.toggle('hidden', box.scrollHeight - box.scrollTop - box.clientHeight < 120);
}
document.getElementById('chatMessages').addEventListener('scroll', updateScrollBtn);
document.getElementById('scrollDownBtn').innerHTML = ICONS.down;
document.getElementById('scrollDownBtn').addEventListener('click', scrollChat);
document.getElementById('chatSendBtn').innerHTML = ICONS.send;

loaders.chat = async () => {
  const items = await api('/api/chat');
  if (!items) return;
  const box = document.getElementById('chatMessages');
  box.innerHTML = '';
  if (!items.length) {
    appendMessage('assistant', 'Пиши сюда как в чат с ботом в Телеграме – это одна и та же переписка.\n\nНапример: «гречка 200, курица 150», «74.5 7», «8000 шагов».');
  }
  items.forEach((m) => appendMessage(m.role, m.content, m.id));
  scrollChat();
};

const chatInput = document.getElementById('chatInput');
chatInput.addEventListener('input', () => { chatInput.style.height = 'auto'; chatInput.style.height = `${Math.min(chatInput.scrollHeight, 120)}px`; });

async function sendChat() {
  const text = chatInput.value.trim();
  if (!text) return;
  const btn = document.getElementById('chatSendBtn');
  btn.disabled = true;
  chatInput.value = '';
  chatInput.style.height = 'auto';
  appendMessage('user', text);
  const typing = appendMessage('assistant', '…');
  typing.classList.add('typing');
  scrollChat();
  const r = await api('/api/chat', { json: { text } });
  typing.remove();
  btn.disabled = false;
  if (!r) { chatInput.value = text; return; }
  appendMessage('assistant', r.reply, r.id, r.actions);
  scrollChat();
}
document.getElementById('chatSendBtn').addEventListener('click', sendChat);

// ===== ТРЕНЕР =====
let trainerData = null;
['copyAthleteLink', 'copyTrainerLink'].forEach((id) => {
  const b = document.getElementById(id);
  b.innerHTML = ICONS.copy;
  b.addEventListener('click', async () => {
    const text = document.getElementById(id === 'copyAthleteLink' ? 'athleteLink' : 'trainerLink').textContent;
    toast((await copyText(text)) ? 'Ссылка скопирована' : 'Не получилось скопировать');
  });
});

loaders.trainer = async () => {
  const d = await api('/api/trainer/overview');
  if (!d) return;
  trainerData = d;
  document.getElementById('athleteLink').textContent = d.athlete_link;
  document.getElementById('trainerLinkBox').classList.toggle('hidden', !d.trainer_link);
  if (d.trainer_link) document.getElementById('trainerLink').textContent = d.trainer_link;
  renderAthletes();
  const reg = document.getElementById('registeringBox');
  reg.classList.toggle('hidden', !d.registering.length);
  reg.textContent = d.registering.length ? `Проходят анкету: ${d.registering.map((x) => x.name).join(', ')}` : '';
  renderGroups();
  const ll = document.getElementById('locList');
  ll.innerHTML = d.locations.map((l) => `<div class="loc-row"><b>${esc(l.name)}</b> <span class="muted small">${esc(l.address || '')}</span></div>`).join('');
};

document.getElementById('athleteSearch').addEventListener('input', renderAthletes);

function ago(iso) {
  if (!iso) return 'не заходил';
  const min = (Date.now() - new Date(`${iso}Z`).getTime()) / 60000;
  if (min < 60) return 'был недавно';
  if (min < 1440) return `был ${Math.round(min / 60)} ч назад`;
  return `был ${Math.round(min / 1440)} дн назад`;
}

function renderAthletes() {
  if (!trainerData) return;
  const q = document.getElementById('athleteSearch').value.trim().toLowerCase();
  const list = document.getElementById('athleteList');
  const items = trainerData.athletes.filter((a) => !q || a.name.toLowerCase().includes(q));
  document.getElementById('athleteCount').textContent = `${trainerData.athletes.length}`;
  list.innerHTML = '';
  if (!items.length) list.innerHTML = '<div class="empty">Пока никого. Отправь ссылку-приглашение выше.</div>';
  items.forEach((a) => {
    const row = document.createElement('div');
    row.className = 'athlete-row tap';
    row.innerHTML = `<div class="avatar">${esc(a.name.slice(0, 1).toUpperCase())}</div>
      <div class="athlete-main"><div>${esc(a.name)}${a.role !== 'athlete' ? ' <span class="tag">тренер</span>' : ''}</div>
      <div class="muted small">${a.groups.length ? esc(a.groups.join(', ')) : a.role === 'athlete' ? '<span class="warn">группы не назначены</span>' : 'без групп'}</div>
      <div class="muted small">${ago(a.last_seen)}${a.attendance !== null ? ` · посещаемость ${a.attendance}%` : ''}${a.weight ? ` · ${fmt(a.weight)} кг` : ''}</div></div>
      <span class="chevron">›</span>`;
    row.addEventListener('click', () => openAthlete(a.id));
    list.appendChild(row);
  });
}

document.getElementById('sheetClose').innerHTML = ICONS.close;
document.getElementById('sheetClose').addEventListener('click', closeSheet);
document.getElementById('sheet').addEventListener('click', (e) => { if (e.target.id === 'sheet') closeSheet(); });
function closeSheet() { document.getElementById('sheet').classList.add('hidden'); document.body.classList.remove('locked'); loaders.trainer(); }

async function openAthlete(id) {
  const a = await api(`/api/trainer/athlete/${id}`);
  if (!a) return;
  document.getElementById('sheet').classList.remove('hidden');
  document.body.classList.add('locked');
  document.getElementById('sheetTitle').textContent = a.name;
  const goalText = { gain: 'набор', cut: 'сушка', keep: 'поддержание' }[a.goal] || '';
  document.getElementById('sheetSub').textContent = [a.age && `${a.age} лет`, a.height_cm && `${a.height_cm} см`, goalText].filter(Boolean).join(' · ');
  const body = document.getElementById('sheetBody');
  const s = a.summary;
  body.innerHTML = `
    <div class="sheet-section"><h3>Группы</h3><div class="chips wrap" id="sgGroups"></div>
      <div class="hint">Включи группы по его абонементу – бот сразу напишет ему расписание</div></div>
    <div class="sheet-section"><h3>Показатели</h3><div class="trio">
      <div><span class="trio-num">${fmt(s.weight)}</span><span class="trio-label">вес${s.weight_change ? `, ${s.weight_change > 0 ? '+' : ''}${fmt(s.weight_change)} за нед.` : ''}</span></div>
      <div><span class="trio-num">${fmt(s.sleep_avg)}</span><span class="trio-label">сон в ср.</span></div>
      <div><span class="trio-num">${s.steps_avg ?? '–'}</span><span class="trio-label">шаги в ср.</span></div></div>
      <div class="muted small center">Питание за 7 дней: ${a.kcal_avg ? `${a.kcal_avg} ккал в день` : 'не записывал'}${a.kcal_target ? ` при норме ${a.kcal_target}` : ''}. Питание тренер только видит.</div></div>
    <div class="sheet-section"><div class="widget-row"><h3>Посещаемость</h3><span class="muted small">${a.stats.percent !== null ? `${a.stats.present} из ${a.stats.sessions} · ${a.stats.percent}%` : ''}</span></div>
      <div id="sgHistory"></div></div>
    <div class="sheet-section"><h3>Цели</h3><div id="sgGoals"></div>
      <div class="inline-form"><input type="text" id="sgGoalInput" placeholder="Цель для спортсмена" maxlength="200"><button class="btn-plus" id="sgGoalAdd">+</button></div>
      <label class="switch-row"><input type="checkbox" id="sgGoalDaily" checked> <span>Каждый день</span></label></div>
    <button class="btn btn-danger" id="sgRemove">Убрать из клуба</button>`;
  const chips = body.querySelector('#sgGroups');
  trainerData.groups.forEach((g) => {
    const c = document.createElement('button');
    let on = a.group_ids.includes(g.id);
    c.className = `chip${on ? ' active' : ''}`;
    c.innerHTML = `${esc(g.name)}<small>${esc(g.location)} · ${esc(g.days_text)} ${esc(g.start)}</small>`;
    c.addEventListener('click', async () => {
      const r = await api(`/api/trainer/athlete/${a.id}/groups`, { json: { group_id: g.id, on: !on } });
      if (!r) return;
      on = !on;
      c.classList.toggle('active', on);
      toast(on ? `Поставил: ${g.name}. Бот написал спортсмену` : `Убрал: ${g.name}`);
      a.group_ids = r.group_ids;
      openAthlete(a.id);
    });
    chips.appendChild(c);
  });
  if (!trainerData.groups.length) chips.innerHTML = '<div class="empty">Сначала создай группы во вкладке «Тренер»</div>';
  const hist = body.querySelector('#sgHistory');
  if (!a.history.length) hist.innerHTML = '<div class="empty">Занятий за 30 дней не было</div>';
  a.history.forEach((h) => hist.appendChild(historyRow(h, true, async (val) => {
    const r = await api(`/api/trainer/athlete/${a.id}/attendance`, { json: { group_id: h.group_id, date: h.date, present: val } });
    if (r) openAthlete(a.id);
  })));
  const goalsBox = body.querySelector('#sgGoals');
  renderGoals(goalsBox, a.goals, () => {}, async (g) => {
    if (!(await confirmDialog(`Убрать цель «${g.title}»?`, 'Убрать'))) return;
    if (await api(`/api/trainer/goal/${g.id}`, { method: 'DELETE' })) openAthlete(a.id);
  }, true);
  body.querySelector('#sgGoalAdd').addEventListener('click', async () => {
    const title = body.querySelector('#sgGoalInput').value.trim();
    if (!title) return;
    const r = await api(`/api/trainer/athlete/${a.id}/goals`, { json: { title, daily: body.querySelector('#sgGoalDaily').checked } });
    if (r) { toast('Цель добавлена, бот написал спортсмену'); openAthlete(a.id); }
  });
  body.querySelector('#sgRemove').addEventListener('click', async () => {
    if (!(await confirmDialog(`Убрать ${a.name} из клуба? Он потеряет доступ, группы снимутся.`, 'Убрать'))) return;
    if (await api(`/api/trainer/athlete/${a.id}/remove`, { method: 'POST' })) { toast('Убрал из клуба'); closeSheet(); }
  });
}

function groupForm(g) {
  const box = document.createElement('div');
  box.className = 'group-form';
  const days = g ? g.days : [];
  box.innerHTML = `
    <input type="text" class="gf-name" placeholder="Название группы" value="${esc(g ? g.name : '')}" maxlength="120">
    <select class="gf-loc">${trainerData.locations.map((l) => `<option value="${l.id}"${g && g.location_id === l.id ? ' selected' : ''}>${esc(l.name)}</option>`).join('')}</select>
    <div class="day-picker">${WD.map((d, i) => `<button type="button" class="day${days.includes(i) ? ' active' : ''}" data-day="${i}">${d}</button>`).join('')}</div>
    <div class="grid2"><label class="field">Начало<input type="time" class="gf-start" value="${g ? g.start : '18:00'}"></label>
      <label class="field">Конец<input type="time" class="gf-end" value="${g ? g.end : '19:30'}"></label></div>
    <div class="grid2"><button class="btn btn-accent gf-save">${g ? 'Сохранить' : 'Создать группу'}</button>
      ${g ? '<button class="btn btn-danger gf-del">Удалить группу</button>' : '<button class="btn btn-ghost gf-cancel">Отмена</button>'}</div>`;
  box.querySelectorAll('.day').forEach((b) => b.addEventListener('click', () => b.classList.toggle('active')));
  box.querySelector('.gf-save').addEventListener('click', async () => {
    const payload = {
      name: box.querySelector('.gf-name').value.trim(), location_id: Number(box.querySelector('.gf-loc').value),
      days: [...box.querySelectorAll('.day.active')].map((b) => Number(b.dataset.day)),
      start: box.querySelector('.gf-start').value, end: box.querySelector('.gf-end').value,
    };
    const r = await api(g ? `/api/trainer/group/${g.id}` : '/api/trainer/group', { json: payload });
    if (r) { toast(g ? 'Группа сохранена' : 'Группа создана'); document.getElementById('groupForm').classList.add('hidden'); loaders.trainer(); }
  });
  const del = box.querySelector('.gf-del');
  if (del) del.addEventListener('click', async () => {
    if (!(await confirmDialog(`Удалить группу «${g.name}»? У всех спортсменов она снимется.`, 'Удалить'))) return;
    if (await api(`/api/trainer/group/${g.id}`, { method: 'DELETE' })) loaders.trainer();
  });
  const cancel = box.querySelector('.gf-cancel');
  if (cancel) cancel.addEventListener('click', () => document.getElementById('groupForm').classList.add('hidden'));
  return box;
}

document.getElementById('groupAddBtn').addEventListener('click', () => {
  const holder = document.getElementById('groupForm');
  holder.innerHTML = '';
  holder.appendChild(groupForm(null));
  holder.classList.toggle('hidden');
});

function renderGroups() {
  const list = document.getElementById('groupList');
  list.innerHTML = '';
  trainerData.groups.forEach((g) => {
    const row = document.createElement('div');
    row.className = 'group-card tap';
    row.innerHTML = `<div class="widget-row" style="margin:0"><div class="group-name">${esc(g.name)}</div><span class="muted small">${g.members} чел.</span></div>
      <div class="muted small">${esc(g.location)} · ${esc(g.days_text)}, ${esc(g.start)}–${esc(g.end)}</div>`;
    row.addEventListener('click', async () => {
      const next = row.nextElementSibling;
      if (next && next.classList.contains('group-detail')) { next.remove(); return; }
      list.querySelectorAll('.group-detail').forEach((el) => el.remove());
      const detail = document.createElement('div');
      detail.className = 'group-detail';
      detail.appendChild(groupForm(g));
      const sess = await api(`/api/trainer/group/${g.id}/sessions`);
      const sBox = document.createElement('div');
      sBox.innerHTML = '<h3 style="margin:12px 0 6px">Ближайшие занятия</h3>';
      (sess || []).forEach((s) => {
        const r = document.createElement('div');
        r.className = `session-mini${s.cancelled ? ' cancelled' : ''}`;
        r.innerHTML = `<span>${s.weekday} ${ddmm(s.date)} · ${s.start}${s.cancelled ? ' · отменено' : ''}</span>`;
        const b = document.createElement('button');
        b.className = `btn-small${s.cancelled ? ' accent' : ''}`;
        b.textContent = s.cancelled ? 'Вернуть' : 'Отменить';
        b.addEventListener('click', async () => {
          if (!s.cancelled && !(await confirmDialog(`Отменить занятие ${s.weekday} ${ddmm(s.date)}? Бот напишет всем в группе.`, 'Отменить'))) return;
          const res = await api(`/api/trainer/group/${g.id}/cancel`, { json: { date: s.date, cancel: !s.cancelled } });
          if (res) { toast(`Готово, написал ${res.notified} чел.`); row.click(); row.click(); }
        });
        r.appendChild(b);
        sBox.appendChild(r);
      });
      detail.appendChild(sBox);
      row.after(detail);
    });
    list.appendChild(row);
  });
  if (!trainerData.groups.length) list.innerHTML = '<div class="empty">Групп нет – создай первую плюсом</div>';
}

document.getElementById('locToggle').addEventListener('click', () => {
  document.getElementById('locToggle').classList.toggle('open');
  document.getElementById('locBody').classList.toggle('hidden');
});
document.getElementById('locAddBtn').addEventListener('click', async () => {
  const name = document.getElementById('locName').value.trim();
  const address = document.getElementById('locAddress').value.trim();
  const r = await api('/api/trainer/location', { json: { name, address } });
  if (r) { document.getElementById('locName').value = ''; document.getElementById('locAddress').value = ''; loaders.trainer(); }
});

// ===== СТАРТ =====
(async () => {
  me = await api('/api/me');
  if (!me) return;
  document.getElementById('helloName').textContent = me.name ? `Привет, ${me.name}` : 'Привет';
  document.getElementById('helloSub').textContent = me.club || '';
  if (me.is_trainer) document.getElementById('navTrainer').classList.remove('hidden');
  loaders.home();
})();
