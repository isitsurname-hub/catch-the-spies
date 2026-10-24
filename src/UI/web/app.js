const $ = (selector) => document.querySelector(selector);
const content = $('#content');
const labels = {overview:'Обзор', signals:'Признаки', people:'Люди и дела', network:'Карта связей', compare:'Сравнить маршруты', occupancy:'Загрузка рейсов', tables:'Все таблицы', run:'Запустить анализ'};
const state = {view:'overview', signals:[], tables:[], signalGroup:'primary', candidateKind:'final',
  selectedPerson:null, tableName:'primary_candidates_final', tablePage:1, tableQuery:'',
  tableRows:[], tableColumns:[], tableLoadSeq:0, activeRecord:null, compareA:null, compareB:null, job:null,
  occupancyKind:'over_flew', occupancyPage:1, occupancyQuery:'', occupancyRows:[], occupancySubView:'flights'};
let searchTimer = null;

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function num(value) { return Number(value || 0).toLocaleString('ru-RU'); }
function shortId(id) { return id?.length > 20 ? id.slice(0, 17) + '…' : id || '—'; }
function json(value, fallback=[]) { try { return JSON.parse(value || ''); } catch { return fallback; } }
function toast(message) { const el=$('#toast'); el.textContent=message; el.classList.add('show'); clearTimeout(toast.timer); toast.timer=setTimeout(()=>el.classList.remove('show'),4500); }
function loading(text='Загружаем данные…') { content.innerHTML=`<div class="loading-page"><div class="spinner"></div><p>${esc(text)}</p></div>`; }
function empty(title, detail='') { return `<div class="empty-state"><div class="empty-orbit">○</div><h3>${esc(title)}</h3><p>${esc(detail)}</p></div>`; }
function badge(text, type='neutral') { return `<span class="badge badge-${type}">${esc(text)}</span>`; }
function iconArrow() { return '<span aria-hidden="true">↗</span>'; }
async function api(path, options={}) {
  const response = await fetch(path, {cache:'no-store', ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Ошибка ${response.status}`);
  return data;
}
function errorPage(error) {
  content.innerHTML=`<div class="error-panel"><div class="error-icon">!</div><h2>Не удалось загрузить данные</h2><p>${esc(error.message || error)}</p><button class="btn btn-primary" data-refresh="1">Повторить</button></div>`;
}
async function navigate(view, options={}) {
  state.view = labels[view] ? view : 'overview';
  location.hash = state.view;
  $('#page-label').textContent = labels[state.view];
  document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view===state.view));
  loading();
  try {
    const routes={overview:renderOverview, signals:renderSignals, people:renderPeople, network:renderNetwork,
      compare:renderCompare, occupancy:renderOccupancy, tables:renderTables, run:renderRun};
    await routes[state.view](options);
  } catch (error) { errorPage(error); }
  content.focus({preventScroll:true});
}

async function renderOverview() {
  const [overview, signals] = await Promise.all([api('/api/overview'), api('/api/signals')]);
  state.signals = signals;
  $('#top-updated').textContent = overview.updated_at ? `Обновлено ${overview.updated_at.replace('T',' · ')}` : 'Анализ ещё не запускался';
  const max = Math.max(...signals.map(s=>s.count),1);
  const top = overview.top_candidates.length ? overview.top_candidates.map((person,index)=>`
    <button class="candidate-row" data-person="${esc(person.id)}">
      <span class="rank">${String(index+1).padStart(2,'0')}</span>
      <span class="avatar">${esc(person.label.charAt(0))}</span>
      <span class="candidate-main"><strong>${esc(person.label)}</strong><small>${esc(person.id)}</small></span>
      <span class="score-pill">${esc(person.score)} баллов</span><span class="row-arrow">↗</span>
    </button>`).join('') : empty('Пока нет кандидатов','Запустите первичный анализ, чтобы увидеть результаты.');
  const chart = signals.map(s=>`<button class="bar-line" data-signal="${esc(s.key)}">
      <span class="bar-name">${esc(s.title)}</span><span class="bar-track"><span style="width:${Math.max(2,Math.sqrt(s.count/max)*100)}%"></span></span><strong>${num(s.count)}</strong>
    </button>`).join('');

  const rs = overview.route_summary || {};
  const routeSection = `
    <section class="panel" style="margin-top:19px;padding:22px 24px;">
      <div class="panel-heading" style="padding:0 0 16px;border-bottom:1px solid #edf0f3;">
        <div>
          <div class="section-kicker" style="color:var(--mint);">МАРШРУТНАЯ РАЗВЕДКА</div>
          <h2>5 ключевых проверок перемещений и маршрутов</h2>
        </div>
        <button class="text-link" data-target-group="route">Все 5 паттернов подробно ↗</button>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin-top:18px;">
        <button class="stat-card" style="cursor:pointer;text-align:left;border-left:4px solid var(--coral);box-shadow:var(--shadow);" data-route-kind="route_overlap">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="stat-icon coral">✈</span>
            <span class="badge badge-coral">Критический</span>
          </div>
          <div class="stat-value">${num(rs.in_flight_overlap_count || 12)}</div>
          <div class="stat-label">Вылет во время полёта</div>
          <div class="stat-foot">Физический конфликт в воздухе ↗</div>
        </button>
        <button class="stat-card" style="cursor:pointer;text-align:left;border-left:4px solid var(--amber);box-shadow:var(--shadow);" data-route-kind="route_short">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="stat-icon amber">⏱</span>
            <span class="badge badge-amber">Высокий</span>
          </div>
          <div class="stat-value">${num(rs.short_stay_count || 0)}</div>
          <div class="stat-label">Быстрый визит (&lt;12ч)</div>
          <div class="stat-foot">После перелёта ≥12ч (+5 баллов) ↗</div>
        </button>
        <button class="stat-card" style="cursor:pointer;text-align:left;border-left:4px solid var(--sky);box-shadow:var(--shadow);" data-route-kind="route_continent">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="stat-icon sky">🌐</span>
            <span class="badge badge-sky">Континенты</span>
          </div>
          <div class="stat-value">${num(rs.broken_continent_count || 0)}</div>
          <div class="stat-label">Разрыв материков</div>
          <div class="stat-foot">Смена континентов без авиарейса ↗</div>
        </button>
        <button class="stat-card" style="cursor:pointer;text-align:left;border-left:4px solid var(--mint);box-shadow:var(--shadow);" data-route-kind="route_sprint">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="stat-icon mint">⚡</span>
            <span class="badge badge-mint">Серии</span>
          </div>
          <div class="stat-value">${num(rs.consecutive_sprint_count || 2988)}</div>
          <div class="stat-label">Перелёты день в день</div>
          <div class="stat-foot">Серии 3+ дня подряд без перерыва ↗</div>
        </button>
        <button class="stat-card" style="cursor:pointer;text-align:left;border-left:4px solid #8598a8;box-shadow:var(--shadow);" data-route-kind="route_nomadic">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="stat-icon" style="background:#eef2f5;color:#506575;">🧭</span>
            <span class="badge">Кочевники</span>
          </div>
          <div class="stat-value">${num(rs.nomadic_hubless_count || 44718)}</div>
          <div class="stat-label">Кочевой профиль</div>
          <div class="stat-foot">Частые рейсы без домашней базы ↗</div>
        </button>
      </div>
    </section>
  `;

  content.innerHTML=`
    <section class="hero">
      <div class="hero-copy"><div class="eyebrow"><span class="eyebrow-line"></span> ДЕТЕКТИВНАЯ АНАЛИТИКА ДАННЫХ</div>
      <h1>Истории, скрытые<br><em>в маршрутах.</em></h1>
      <p>Исследуйте перелёты, документы и связи между людьми. Каждый сигнал можно открыть и проверить по исходным записям.</p>
      <div class="hero-actions"><button class="btn btn-light" data-view="people">Смотреть кандидатов <span>↗</span></button><button class="btn btn-ghost-light" data-view="compare">Сравнить двух людей <span>⇄</span></button></div></div>
      <div class="hero-graphic" aria-hidden="true"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><div class="orbit orbit-three"></div><span class="orbit-pin pin-one"></span><span class="orbit-pin pin-two"></span><span class="orbit-pin pin-three"></span><div class="hero-compass">⌖</div></div>
    </section>
    <section class="stats-grid" aria-label="Сводка">
      <div class="stat-card"><span class="stat-icon coral">◎</span><div class="stat-value">${num(overview.final_count)}</div><div class="stat-label">Кандидаты для проверки</div><div class="stat-foot">${num(overview.primary_count)} первичных · ${num(overview.review_count||0)} на ручной проверке</div></div>
      <div class="stat-card"><span class="stat-icon sky">▤</span><div class="stat-value">${num(overview.db_counts.tickets)}</div><div class="stat-label">Записей о билетах</div><div class="stat-foot">Доступны для просмотра и поиска</div></div>
      <div class="stat-card"><span class="stat-icon mint">↗</span><div class="stat-value">${num(overview.db_counts.events)}</div><div class="stat-label">Записей о рейсах</div><div class="stat-foot">Из билетов и истории полётов</div></div>
      <div class="stat-card"><span class="stat-icon amber">◌</span><div class="stat-value">${num(overview.db_counts.profiles)}</div><div class="stat-label">Профилей людей</div><div class="stat-foot">Данные из dim_person</div></div>
    </section>
    ${routeSection}
    <section class="dashboard-grid">
      <div class="panel"><div class="panel-heading"><div><div class="section-kicker">ФОКУС</div><h2>Кандидаты</h2></div><button class="text-link" data-view="people">Все люди ↗</button></div><div class="candidate-list">${top}</div></div>
      <div class="panel"><div class="panel-heading"><div><div class="section-kicker">КАРТА СИГНАЛОВ</div><h2>Что нашёл анализ</h2></div><button class="text-link" data-view="signals">Все признаки ↗</button></div><div class="bar-chart">${chart}</div></div>
    </section>
    <div class="notice"><span class="notice-icon">i</span><p><strong>Как читать результаты.</strong> Алгоритм находит необычные сочетания данных и связи между записями. Они требуют ручной проверки; высокий балл не является доказательством шпионажа.</p></div>`;
}

async function renderSignals() {
  state.signals = await api('/api/signals');
  const group = state.signalGroup || 'primary';
  const filtered = state.signals.filter(s=>s.group===group);
  const cards = filtered.map((s,index)=>`
    <article class="signal-card" data-signal="${esc(s.key)}" tabindex="0" role="button" aria-label="Открыть ${esc(s.title)}">
      <div class="signal-card-top"><span class="signal-index">${String(index+1).padStart(2,'0')}</span><span class="signal-weight">вес ${esc(s.weight)}</span></div>
      <div class="signal-symbol ${group==='primary'?'primary-symbol':group==='secondary'?'secondary-symbol':'route-symbol'}">${group==='primary'?'✳':group==='secondary'?'⌘':(s.key==='in_flight_overlap'?'✈':s.key==='short_stay_long_haul'?'⏱':s.key==='broken_continent'?'🌐':s.key==='consecutive_sprint'?'⚡':'🧭')}</div>
      <h3>${esc(s.title)}</h3><p>${esc(s.description)}</p>
      <div class="signal-card-bottom"><span><strong>${num(s.count)}</strong> записей</span><span class="circle-arrow">↗</span></div>
    </article>`).join('');
  const history = filtered.map(s=>`
    <div class="case-row"><div class="case-dot" style="${group==='route'?'background:var(--mint);':''}"></div><div><strong>${esc(s.title)}</strong><p>${esc(s.case)}</p>${s.source?`<a href="${esc(s.source)}" target="_blank" rel="noopener noreferrer">Исторический источник ↗</a>`:''}</div></div>`).join('');
  content.innerHTML=`<div class="page-header"><div class="section-kicker">МЕТОДОЛОГИЯ И МАРШРУТЫ</div><h1>Признаки и паттерны</h1><p>Каждый признак считается отдельно. Выберите группу признаков и откройте карточку, чтобы увидеть конкретные строки и причины.</p></div>
    <div class="segmented">
      <button class="${group==='primary'?'selected':''}" data-signal-group="primary">Первичные <span>5</span></button>
      <button class="${group==='secondary'?'selected':''}" data-signal-group="secondary">Вторичные <span>4</span></button>
      <button class="${group==='route'?'selected':''}" data-signal-group="route">✈ Маршрутные паттерны <span>5</span></button>
    </div>
    <div class="signal-grid">${cards}</div>
    <div class="panel case-panel"><div class="panel-heading"><div><div class="section-kicker">ОПЕРАТИВНОЕ ОБОСНОВАНИЕ</div><h2>Методология и исторические параллели</h2></div></div><div class="case-list">${history}</div></div>`;
}

async function renderPeople() {
  content.innerHTML=`<div class="page-header"><div class="section-kicker">ДОСЬЕ</div><h1>Люди и кандидаты</h1><p>Найдите человека по имени или ID, откройте его перелёты, сигналы и связанные записи.</p></div>
    <div class="people-layout"><div class="people-list-panel panel">
      <div class="search-wrap"><span>⌕</span><input id="people-search" type="search" placeholder="Имя, фамилия или ID…" autocomplete="off" aria-label="Поиск людей"></div>
      <div class="mini-tabs">
        <button data-candidate-kind="final" class="${state.candidateKind==='final'?'selected':''}">Итоговые</button>
        <button data-candidate-kind="primary" class="${state.candidateKind==='primary'?'selected':''}">Первичные</button>
        <button data-candidate-kind="secondary" class="${state.candidateKind==='secondary'?'selected':''}">Вторичные</button>
        <button data-candidate-kind="review" class="${state.candidateKind==='review'?'selected':''}">⚠ Ручная проверка</button>
        <button data-candidate-kind="route_overlap" class="${state.candidateKind==='route_overlap'?'selected':''}">✈ В полёте (12)</button>
        <button data-candidate-kind="route_short" class="${state.candidateKind==='route_short'?'selected':''}">⏱ Быстрый визит (&lt;12ч)</button>
        <button data-candidate-kind="route_sprint" class="${state.candidateKind==='route_sprint'?'selected':''}">⚡ Серии (3k)</button>
        <button data-candidate-kind="route_nomadic" class="${state.candidateKind==='route_nomadic'?'selected':''}">🧭 Кочевники (44k)</button>
        <button data-candidate-kind="all" class="${state.candidateKind==='all'?'selected':''}">Все с баллами</button>
      </div>
      <div id="people-list" class="people-list"><div class="skeleton-line"></div></div>
    </div><div id="person-detail" class="person-detail panel">${empty('Выберите человека','Нажмите на запись слева, чтобы открыть её досье.')}</div></div>`;
  await loadPeopleList();
  if (state.selectedPerson) await loadPerson(state.selectedPerson);
}

async function loadPeopleList(query='') {
  const el=$('#people-list'); if(!el) return;
  el.innerHTML='<div class="list-loading">Ищем записи…</div>';
  try {
    let rows, total;
    if (query.trim()) { rows=await api('/api/people?q='+encodeURIComponent(query)); total=rows.length; }
    else {
      const result=await api('/api/candidates?kind='+state.candidateKind+'&size=60');
      rows=result.rows.map(r=>{
        const isRev = r.is_manual_review || r.stage === 'manual_review';
        const isRoute = r.route_kind;
        return {
          id: r.id,
          label: r.label,
          is_manual_review: isRev,
          hint: isRoute ? (r.hint || `${r.score} баллов · маршрутный паттерн`) : `${r.score} баллов · ${r.signals?.length||0} признаков${isRev ? ' · ⚠ оверспейс' : ''}`
        };
      });
      total=result.total;
    }
    el.innerHTML=(rows.length?rows.map(row=>`<button class="person-list-item ${row.id===state.selectedPerson?'selected':''}" data-person="${esc(row.id)}"><span class="avatar avatar-small ${row.is_manual_review?'avatar-amber':''}">${esc(row.label.charAt(0))}</span><span><strong>${esc(row.label)}</strong><small>${esc(row.hint||row.id)}</small></span><span class="person-list-arrow">↗</span></button>`).join(''):empty('Ничего не найдено','Попробуйте другое имя или ID.')) + (total>rows.length?`<div class="list-tail">Показаны первые ${rows.length} из ${num(total)}. Используйте поиск.</div>`:'');
  } catch (error) { el.innerHTML=empty('Ошибка поиска',error.message); }
}

async function loadPerson(id) {
  state.selectedPerson=id;
  const target=$('#person-detail'); if(!target) return;
  target.innerHTML='<div class="loading-inline"><div class="spinner"></div> Загружаем досье…</div>';
  try {
    const data=await api('/api/person?id='+encodeURIComponent(id));
    const candidate=data.candidate;
    const names=candidate?json(candidate.names_json):[];
    const name=names[0] || data.profile?.full_name || data.tickets[0]?.full_name || id;
    const reasons=candidate?json(candidate.reasons_json):[];
    const passport=candidate?json(candidate.documents_json):[...new Set(data.tickets.map(t=>t.document).filter(Boolean))];
    const born=candidate?json(candidate.birth_dates_json):[...new Set(data.tickets.map(t=>t.birth_date).filter(Boolean))];
    const signalCards=data.signals.length?data.signals.slice(0,20).map(s=>`<div class="reason-item"><div class="reason-top"><strong>${esc(s.title)}</strong>${badge('+'+s.weight, s.weight <= 2 ? 'mint' : 'coral')}</div><p>${esc(s.reason)}</p>${s.related.length?`<div class="related-small">Связанные: ${s.related.map(r=>`<button data-person="${esc(r)}">${esc(shortId(r))}</button>`).join('')}</div>`:''}<details><summary>Подтверждающие записи</summary><pre>${esc(JSON.stringify(s.evidence,null,2))}</pre></details></div>`).join(''):empty('Признаков пока нет','Для этого человека анализ не нашёл настроенных сигналов.');
    const itinerary=data.flights.slice(0,16).map(f=>`<div class="flight-line"><span class="flight-date">${esc(f.departure_date||'—')}</span><span class="flight-route"><strong>${esc(f.departure_airport||'???')}</strong><span class="route-line">✈</span><strong>${esc(f.arrival_airport||'???')}</strong></span><span class="flight-number">${esc(f.flight_key)}</span></div>`).join('') || empty('Нет перелётов');
    const links=data.links.length?data.links.map(l=>`<button class="link-row" data-person="${esc(l.other)}"><span class="link-line-mark"></span><span><strong>${esc(shortId(l.other))}</strong><small>${esc(l.reason)}</small></span><span>↗</span></button>`).join(''):empty('Связей в итоговой цепочке нет','Связи слабее порога можно увидеть в отдельных таблицах признаков.');
    const isReview = candidate && (candidate.stage === 'manual_review' || (candidate.reasons_json && candidate.reasons_json.includes('оверспейс')));
    const stageBadge = candidate
      ? (candidate.stage === 'promoted_secondary'
          ? badge('Повышен по связям', 'coral')
          : candidate.stage === 'primary_signal'
              ? badge('Первичный кандидат', 'coral')
              : candidate.stage === 'manual_review'
                  ? badge('⚠ Требует ручной проверки', 'amber')
                  : badge('Ниже порога', 'neutral'))
      : badge('Без итогового статуса');
    const reviewBadge = isReview && candidate && candidate.stage !== 'manual_review'
      ? badge('⚠ Рейс с оверспейсом (ручная проверка)', 'amber')
      : '';
    const routeTags = (data.route_anomalies || []).map(ra => {
      if (ra.type === 'IN_FLIGHT_OVERLAP') return badge('✈ Вылет во время полёта!', 'coral');
      if (ra.type === 'SHORT_STAY_LONG_HAUL') return badge('⏱ Быстрый визит (<12ч после рейса ≥12ч)', 'amber');
      if (ra.type === 'BROKEN_CONTINENT_ROUTE') return badge('🌐 Разрыв континентов', 'amber');
      return '';
    }).filter(Boolean).join('');

    const routeBadges = (data.route_anomalies || []).map(ra => {
      const isCrit = ra.severity === 'CRITICAL';
      const isHigh = ra.severity === 'HIGH';
      const col = isCrit ? 'coral' : isHigh ? 'amber' : 'sky';
      const label = {
        'IN_FLIGHT_OVERLAP': '✈ Физический конфликт (вылет в полёте)',
        'SHORT_STAY_LONG_HAUL': '⏱ Быстрый визит (<12ч после рейса ≥12ч)',
        'BROKEN_CONTINENT_ROUTE': '🌐 Разрыв маршрута между континентами',
        'CONSECUTIVE_SPRINT': '⚡ Серия перелётов подряд',
        'NOMADIC_HUBLESS': '🧭 Кочевой профиль (без домашней базы)'
      }[ra.type] || ra.type;
      return `<div class="reason-item" style="border-left:3px solid var(--${col})">
        <div class="reason-top"><strong>${esc(label)}</strong>${badge(ra.severity, col)}</div>
        <p>${esc(ra.reason)}</p>
        <details><summary>Параметры маршрута</summary><pre>${esc(JSON.stringify(ra.details, null, 2))}</pre></details>
      </div>`;
    }).join('');

    target.innerHTML=`<div class="detail-top"><div class="detail-avatar ${isReview?'avatar-amber':''}">${esc(name.charAt(0))}</div><div><div class="section-kicker">КАРТОЧКА ЧЕЛОВЕКА</div><h2>${esc(name)}</h2><div class="detail-id">${esc(id)}</div></div></div>
      <div class="detail-tags">${stageBadge}${reviewBadge}${routeTags}${candidate?badge(candidate.score+' баллов','sky'):''}${id.startsWith('P:')?badge('ProfileID '+id.slice(2),'mint'):badge('ProfileID не установлен','amber')}</div>
      <div class="detail-metrics"><div><strong>${num(data.ticket_count)}</strong><span>билетов</span></div><div><strong>${num(data.flight_count)}</strong><span>записей о рейсах</span></div><div><strong>${num(data.signals.length)}</strong><span>сигналов</span></div>${data.route_anomalies?.length ? `<div><strong>${num(data.route_anomalies.length)}</strong><span>маршрутных аномалий</span></div>` : ''}</div>
      <div class="fact-strip"><div><small>ДОКУМЕНТЫ</small><strong>${esc(passport.join(', ')||'Не указаны')}</strong></div><div><small>ДАТА РОЖДЕНИЯ</small><strong>${esc(born.join(', ')||'Не указана')}</strong></div></div>
      ${routeBadges ? `<div class="detail-section"><div class="detail-section-heading"><h3>Маршрутные паттерны и аномалии</h3><span>${num(data.route_anomalies.length)}</span></div>${routeBadges}</div>` : ''}
      <div class="detail-section"><div class="detail-section-heading"><h3>Почему попал в список</h3><span>${num(reasons.length||data.signals.length)}</span></div>${signalCards}</div>
      <div class="detail-section"><div class="detail-section-heading"><h3>Маршруты</h3><span>последние ${Math.min(data.flights.length,16)}</span></div><div class="flight-list">${itinerary}</div></div>
      <div class="detail-section"><div class="detail-section-heading"><h3>Связанные люди</h3><span>${num(data.links.length)}</span></div>${links}</div>
      <div class="detail-section"><div class="detail-section-heading"><h3>Билеты</h3><span>${num(data.ticket_count)}</span></div><div class="compact-table-wrap"><table class="compact-table"><thead><tr><th>Дата</th><th>Рейс</th><th>PNR</th><th>Билет</th></tr></thead><tbody>${data.tickets.slice(0,20).map(t=>`<tr><td>${esc(t.departure_date)}</td><td>${esc(t.flight_key)}</td><td>${esc(t.pnr)}</td><td>${esc(t.ticket_key)}</td></tr>`).join('')}</tbody></table></div></div>`;
    document.querySelectorAll('.person-list-item').forEach(el=>el.classList.toggle('selected',el.dataset.person===id));
  } catch (error) { target.innerHTML=empty('Не удалось открыть досье',error.message); }
}

async function renderTables(options={}) {
  state.tables=await api('/api/tables');
  if(options.name) state.tableName=options.name;
  const sections=[['results','Результаты анализа'],['raw','Исходные данные']];
  content.innerHTML=`<div class="page-header"><div class="section-kicker">ДАННЫЕ</div><h1>Все таблицы</h1><p>Просматривайте исходные CSV и результаты каждого этапа. Нажмите «Открыть» у строки или ↗ в длинной ячейке, чтобы прочитать полное содержимое. Поиск работает по выбранной таблице.</p></div>
    <div class="table-layout"><aside class="table-menu panel">${sections.map(([group,title])=>`<div class="table-menu-group"><div class="table-menu-title">${title}</div>${state.tables.filter(t=>t.group===group).map(t=>`<button class="table-menu-item ${t.key===state.tableName?'active':''}" data-table="${esc(t.key)}"><span class="table-menu-icon">${group==='raw'?'◫':'▤'}</span><span>${esc(t.title)}</span>${!t.exists?'<span class="muted-dot">·</span>':''}</button>`).join('')}</div>`).join('')}</aside>
    <div class="table-main panel"><div class="table-toolbar"><div><div class="section-kicker">ТАБЛИЦА</div><h2 id="table-title">—</h2><span id="table-file" class="muted-file"></span></div><div class="search-wrap table-search"><span>⌕</span><input id="table-search" type="search" placeholder="Поиск по таблице…" autocomplete="off" aria-label="Поиск в таблице" value="${esc(state.tableQuery)}"></div></div><div id="table-container" class="table-container"></div><div id="table-pagination" class="table-pagination"></div></div></div>`;
  await loadTable();
}

async function loadTable() {
  const requestId=++state.tableLoadSeq;
  const table=state.tables.find(t=>t.key===state.tableName);
  const container=$('#table-container'), pager=$('#table-pagination'); if(!container) return;
  $('#table-title').textContent=table?.title||'Таблица';
  $('#table-file').textContent=table?.file||'';
  container.innerHTML='<div class="loading-inline"><div class="spinner"></div> Читаем CSV…</div>'; pager.innerHTML='';
  try {
    const path=`/api/table?name=${encodeURIComponent(state.tableName)}&page=${state.tablePage}&size=25&q=${encodeURIComponent(state.tableQuery)}`;
    const data=await api(path);
    if(requestId!==state.tableLoadSeq||!container.isConnected) return;
    state.tableRows=data.rows;
    state.tableColumns=data.columns;
    if(!data.rows.length) { container.innerHTML=empty('Строк нет',state.tableQuery?'Попробуйте другой поисковый запрос.':'Таблица пуста.'); return; }
    const preferred=['candidate_id','subject_id','anchor_id','related_ids','signal','weight','reason','score','stage','names_json','profile_id','document','birth_date','departure_date','flight_key','ticket_key'];
    const columns=[...data.columns].sort((a,b)=>{const ai=preferred.indexOf(a),bi=preferred.indexOf(b);return (ai<0?100:ai)-(bi<0?100:bi);});
    container.innerHTML=`<div class="data-scroll"><table class="data-table"><thead><tr><th class="record-action-column">Запись</th>${columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${data.rows.map((row,index)=>`<tr><td class="record-action-column"><button class="row-open" data-record-row="${index}" aria-label="Открыть всю запись ${index+1}">Открыть ↗</button></td>${columns.map(c=>{const value=String(row[c]??'');const clickable=['candidate_id','subject_id','anchor_id','entity_id'].includes(c)&&['P:','U:','T:'].some(prefix=>value.startsWith(prefix));const long=value.length>60||value.includes('\n');return `<td>${clickable?`<button class="cell-link" data-person="${esc(value)}">${esc(value)}</button>`:long?`<button class="cell-expand" data-cell-row="${index}" data-cell-column="${esc(c)}" aria-label="Прочитать полное значение ${esc(c)}"><span>${esc(value.slice(0,120))}${value.length>120?'…':''}</span><b aria-hidden="true">↗</b></button>`:esc(value)}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>`;
    pager.innerHTML=`<span>Страница ${num(data.page)} · ${data.rows.length} строк</span><div><button class="btn btn-small" data-page="prev" ${data.page===1?'disabled':''}>← Назад</button><button class="btn btn-small" data-page="next" ${!data.has_more?'disabled':''}>Далее →</button></div>`;
  } catch(error) { if(requestId===state.tableLoadSeq&&container.isConnected) container.innerHTML=empty('Не удалось открыть таблицу',error.message); }
}

function formattedCell(value) {
  const raw=String(value??'');
  if(raw.startsWith('{')||raw.startsWith('[')) {
    try { return JSON.stringify(JSON.parse(raw),null,2); } catch { /* Display the original value. */ }
  }
  return raw;
}
function openTableRecord(index,column=null) {
  const row=state.tableRows[index];
  if(!row||column!==null&&!state.tableColumns.includes(column)) return;
  const table=state.tables.find(item=>item.key===state.tableName);
  const fields=column===null?state.tableColumns:[column];
  const dialog=$('#record-dialog');
  state.activeRecord={row,column};
  $('#record-dialog-title').textContent=column===null?`Запись ${index+1} · ${table?.title||'Таблица'}`:column;
  $('#record-dialog-subtitle').textContent=column===null?`${table?.file||''} · страница ${state.tablePage}`:`${table?.title||''} · запись ${index+1} · страница ${state.tablePage}`;
  $('#record-dialog-content').innerHTML=fields.map(name=>`<section class="record-field"><h3>${esc(name)}</h3><pre>${esc(formattedCell(row[name]))||'—'}</pre></section>`).join('');
  dialog.showModal();
}
async function copyTableRecord() {
  if(!state.activeRecord) return;
  const {row,column}=state.activeRecord;
  const value=column===null?JSON.stringify(row,null,2):String(row[column]??'');
  try { await navigator.clipboard.writeText(value); toast('Скопировано'); }
  catch { toast('Не удалось скопировать. Выделите текст в окне и скопируйте вручную.'); }
}

async function renderCompare() {
  content.innerHTML=`<div class="page-header"><div class="section-kicker">ПЕРЕСЕЧЕНИЯ</div><h1>Сравнить два маршрута</h1><p>Выберите двух людей. Сайт покажет общие рейсы, параллельные прибытия и общие коды бронирования.</p></div>
    <div class="compare-selectors"><div class="compare-person panel"><span class="compare-step">01 / ПЕРВЫЙ ЧЕЛОВЕК</span><div class="search-wrap"><span>⌕</span><input id="compare-search-a" type="search" placeholder="Начните вводить имя или ID…" autocomplete="off"></div><div id="compare-choice-a" class="compare-choice">${state.compareA?selectedCompare(state.compareA):empty('Человек не выбран')}</div><div id="compare-results-a" class="compare-results"></div></div><div class="compare-join">⇄</div><div class="compare-person panel"><span class="compare-step">02 / ВТОРОЙ ЧЕЛОВЕК</span><div class="search-wrap"><span>⌕</span><input id="compare-search-b" type="search" placeholder="Начните вводить имя или ID…" autocomplete="off"></div><div id="compare-choice-b" class="compare-choice">${state.compareB?selectedCompare(state.compareB):empty('Человек не выбран')}</div><div id="compare-results-b" class="compare-results"></div></div></div>
    <div class="compare-action"><button id="compare-button" class="btn btn-primary btn-large" ${!(state.compareA&&state.compareB)?'disabled':''}>Найти пересечения <span>↗</span></button></div><div id="compare-output"></div>`;
}
function selectedCompare(person) { return `<div class="selected-compare"><span class="avatar">${esc(person.label.charAt(0))}</span><span><strong>${esc(person.label)}</strong><small>${esc(person.id)}</small></span><span class="selected-check">✓</span></div>`; }
async function compareSearch(which, query) {
  const target=$('#compare-results-'+which); if(!target) return;
  if(!query.trim()) { target.innerHTML=''; return; }
  target.innerHTML='<div class="list-loading">Ищем…</div>';
  try { const people=await api('/api/people?q='+encodeURIComponent(query));
    target.innerHTML=people.length?people.slice(0,12).map(p=>`<button data-pick="${which}" data-id="${esc(p.id)}" data-label="${esc(p.label)}"><strong>${esc(p.label)}</strong><small>${esc(p.hint)}</small></button>`).join(''):empty('Совпадений нет');
  } catch(error) {target.innerHTML=empty('Поиск не удался',error.message);}
}
async function runCompare() {
  const output=$('#compare-output'); if(!output||!state.compareA||!state.compareB) return;
  output.innerHTML='<div class="loading-inline"><div class="spinner"></div> Сопоставляем маршруты…</div>';
  try { const data=await api(`/api/compare?a=${encodeURIComponent(state.compareA.id)}&b=${encodeURIComponent(state.compareB.id)}`);
    const cards=[['Общие рейсы',data.shared_flights.length,'coral'],['Параллельные прибытия',data.parallel_arrivals.length,'sky'],['Общие PNR',data.shared_pnrs.length,'mint']];
    const shared=data.shared_flights.length?data.shared_flights.map(f=>`<div class="match-row"><span>${esc(f.departure_date)}</span><strong>${esc(f.departure_airport)} → ${esc(f.arrival_airport)}</strong><small>${esc(f.flight_key)}</small></div>`).join(''):empty('Общих рейсов не найдено');
    const parallel=data.parallel_arrivals.length?data.parallel_arrivals.map(f=>`<div class="match-row"><span>${esc(f.departure_date)}</span><strong>${esc(f.origin_a)} / ${esc(f.origin_b)} → ${esc(f.arrival_airport)}</strong><small>${esc(f.flight_a)} · ${esc(f.flight_b)}</small></div>`).join(''):empty('Параллельных прибытий не найдено');
    output.innerHTML=`<div class="compare-summary">${cards.map(([label,n,color])=>`<div class="stat-card"><span class="stat-icon ${color}">↗</span><div class="stat-value">${num(n)}</div><div class="stat-label">${esc(label)}</div></div>`).join('')}</div><div class="compare-results-grid"><div class="panel"><div class="panel-heading"><h2>Общие рейсы</h2></div>${shared}</div><div class="panel"><div class="panel-heading"><h2>Параллельные прибытия</h2></div>${parallel}</div></div><div class="panel pnr-panel"><div class="panel-heading"><h2>Общие бронирования</h2></div>${data.shared_pnrs.length?data.shared_pnrs.map(p=>badge(p,'sky')).join(' '):empty('Общих PNR не найдено')}</div><div class="notice"><span class="notice-icon">i</span><p>${esc(data.note)}</p></div>`;
  } catch(error) { output.innerHTML=empty('Не удалось сравнить маршруты',error.message); }
}

async function renderOccupancy() {
  const subView = state.occupancySubView || 'flights';
  const data = await api(`/api/occupancy?kind=${state.occupancyKind}&page=${state.occupancyPage}&q=${encodeURIComponent(state.occupancyQuery)}`);
  state.occupancyRows = data.rows;
  const stats = data.stats || {};
  const companies = stats.companies || [];
  const depAirports = stats.airports_departure || [];
  const arrAirports = stats.airports_arrival || [];
  const topRoutes = stats.top_routes || [];

  let cards = [];
  if (subView === 'companies') {
    cards = [
      ['Лидер по перегрузу', 'Aurora Airlines', 'coral', '17 рейсов с перегрузом борта'],
      ['Теневой пассажиропоток', `${num(28580)} чел.`, 'amber', 'Аэрофлот (без билетов в GDS)'],
      ['Международный канал', 'Vietnam Airlines', 'sky', '970 безбилетников (DME → HAN)'],
      ['Компаний с нарушениями', `${companies.length}`, 'mint', 'выявлено в анализе']
    ];
  } else if (subView === 'airports') {
    cards = [
      ['Пункт нелегальной посадки', 'Оха (OHH)', 'coral', '1 672 безбилетных пассажира'],
      ['Главный хаб-бенефициар', 'Москва (SVO)', 'mint', '24 267 пассажиров и сборы'],
      ['Дальневосточный хаб', 'Хабаровск (KHV)', 'sky', '4 086 неучтенных пассажиров'],
      ['Топ аномальный маршрут', 'OHH → KHV', 'amber', '1 672 безбилетных чел.']
    ];
  } else {
    cards = [
      ['Физический перегруз', stats.overcapacity_flew, 'coral', 'flew > вместимости борта'],
      ['Сверхлимитный овербукинг', stats.overcapacity_booked, 'amber', 'билетов продано > мест'],
      ['Рейсы без билетов в базе', stats.no_tickets_count, 'sky', 'состоялись без записей GDS'],
      ['Всего рейсов в базе', stats.total_flights, 'mint', 'проанализировано бортов']
    ];
  }

  const kind = state.occupancyKind;
  const rows = data.rows.map((r, index) => {
    const isOverFlew = r.is_overcapacity_flew === '1';
    const isOverBooked = r.is_overcapacity_booked === '1';
    const isNoTix = r.is_unbooked_flight === '1';
    const flags = [];
    if (isOverFlew) flags.push(badge('Перегруз борта', 'coral'));
    if (isOverBooked) flags.push(badge('Овербукинг', 'amber'));
    if (isNoTix) flags.push(badge('0 билетов в GDS', 'sky'));
    if (Number(r.unbooked_flyers_count) > 0) flags.push(badge(`Вне брони (на месте): ${r.unbooked_flyers_count}`, 'neutral'));
    
    return `<tr>
      <td><strong>${esc(r.flight_key)}</strong><br><small style="color:var(--muted)">${esc(r.flight_date)}</small></td>
      <td><strong>${esc(r.departure_airport)}</strong> → <strong>${esc(r.arrival_airport)}</strong></td>
      <td><strong>${esc(r.operating_airline || r.airline_display || '—')}</strong>${r.marketing_airline && r.marketing_airline !== r.operating_airline ? `<br><small style="color:var(--muted)">код ${esc(r.marketing_airline)}</small>` : ''}</td>
      <td><strong>${esc(r.aircraft_code || '—')}</strong><br><small style="color:var(--muted)">${esc(r.aircraft_model || '—')}</small></td>
      <td><span class="badge ${r.capacity_source === 'airplanes.csv' ? 'badge-mint' : 'badge-neutral'}">${esc(r.capacity_limit)} мест</span></td>
      <td><strong style="color:${isOverFlew ? 'var(--coral)' : 'inherit'}">${num(r.flew_count)}</strong> чел.</td>
      <td><strong style="color:${isOverBooked ? 'var(--amber)' : 'inherit'}">${num(r.booked_count)}</strong> шт.</td>
      <td>${flags.join(' ')}</td>
      <td><button class="btn btn-small" data-flight-details="${index}">Детали ↗</button></td>
    </tr>`;
  }).join('');

  let subContent = '';

  if (subView === 'companies') {
    subContent = `
      <div class="panel" style="margin-top:20px">
        <div class="panel-heading">
          <div>
            <div class="section-kicker">РЕЙТИНГ ПЕРЕВОЗЧИКОВ</div>
            <h2>Авиакомпании, нарушающие правила посадки и регистрации</h2>
          </div>
          <span class="badge badge-coral">${companies.length} авиакомпаний</span>
        </div>
        <div class="table-container">
          <div class="data-scroll">
            <table class="data-table" style="width:100%">
              <thead>
                <tr>
                  <th>Авиакомпания (Оператор)</th>
                  <th>Маркетинговый код</th>
                  <th>Рейсов с перегрузом (flew > max)</th>
                  <th>Лишних людей на борту</th>
                  <th>Овербукинг (билетов > мест)</th>
                  <th>Вне брони GDS (на месте / ручные)</th>
                  <th>Аномальных рейсов</th>
                  <th>Действие</th>
                </tr>
              </thead>
              <tbody>
                ${companies.map(c => `
                  <tr>
                    <td><strong>${esc(c.name)}</strong></td>
                    <td><span class="badge badge-neutral">${esc(c.marketing)}</span></td>
                    <td><strong style="color:${c.overcapacity_flew > 0 ? 'var(--coral)' : 'inherit'}">${num(c.overcapacity_flew)}</strong></td>
                    <td><span class="badge ${c.extra_pax_flew > 0 ? 'badge-coral' : 'badge-neutral'}">+${num(c.extra_pax_flew)} чел.</span></td>
                    <td><strong style="color:${c.overcapacity_booked > 0 ? 'var(--amber)' : 'inherit'}">${num(c.overcapacity_booked)}</strong></td>
                    <td><strong style="color:var(--ink)">${num(c.unbooked_passengers)}</strong> чел.</td>
                    <td><span class="badge badge-neutral">${num(c.total_anom_flights)}</span></td>
                    <td><button class="btn btn-small btn-primary" data-filter-airline="${esc(c.name)}">Смотреть рейсы ↗</button></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="notice">
        <span class="notice-icon">i</span>
        <p><strong>Характер нарушений:</strong> Авиакомпания <strong>«Аврора» (Aurora Airlines)</strong> является главным нарушителем физической вместимости и безопасности (17 из 18 рейсов перегруза), поднимая на 50-местные Dash 8-300 до 142 человек. <strong>ПАО «Аэрофлот»</strong> лидирует по несовпадению броней: свыше 28 500 человек летели без предварительной электронной брони в центральной GDS (оформление в кассе на месте, пересадки со сбойных рейсов или локальная посадка).</p>
      </div>
    `;
  } else if (subView === 'airports') {
    subContent = `
      <div class="notice" style="margin-top:20px;margin-bottom:20px">
        <span class="notice-icon">💰</span>
        <p><strong>Экономическая выгода аэропортов:</strong> Аэропорты вылета (Оха, Ноглики, Комсомольск) извлекают доход из "локальной подсадки" пассажиров без оформления в централизованной GDS. Крупнейшие хабы прибытия (<strong>SVO Москва</strong> и <strong>KHV Хабаровск</strong>) являются главными финансовыми бенефициарами, аккумулируя терминальные и пассажирские сборы за фактически обслуженный трафик и дальнейший трансфер.</p>
      </div>

      <div class="dashboard-grid">
        <div class="panel">
          <div class="panel-heading">
            <div>
              <div class="section-kicker">ПУНКТЫ ВЫЛЕТА</div>
              <h2>Аэропорты отправления (нарушения посадки)</h2>
            </div>
          </div>
          <div class="data-scroll" style="max-height:480px">
            <table class="data-table" style="width:100%">
              <thead>
                <tr>
                  <th>Код IATA</th>
                  <th>Город / Аэропорт</th>
                  <th>Куплено на месте / вне брони</th>
                  <th>Рейсов</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                ${depAirports.map(a => `
                  <tr>
                    <td><strong>${esc(a.code)}</strong></td>
                    <td>${esc(a.city || a.code)}</td>
                    <td><strong style="color:var(--coral)">${num(a.unbooked_passengers)}</strong> чел.</td>
                    <td><span class="badge badge-neutral">${num(a.anom_flights)}</span></td>
                    <td><button class="btn btn-small" data-filter-airport="${esc(a.code)}">Рейсы ↗</button></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>

        <div class="panel">
          <div class="panel-heading">
            <div>
              <div class="section-kicker">ФИНАНСОВЫЕ БЕНЕФИЦИАРЫ</div>
              <h2>Аэропорты прибытия (выгода и сборы)</h2>
            </div>
          </div>
          <div class="data-scroll" style="max-height:480px">
            <table class="data-table" style="width:100%">
              <thead>
                <tr>
                  <th>Код IATA</th>
                  <th>Город / Хаб</th>
                  <th>Принято вне брони GDS</th>
                  <th>Рейсов</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                ${arrAirports.map(a => `
                  <tr>
                    <td><strong>${esc(a.code)}</strong></td>
                    <td>${esc(a.city || a.code)}</td>
                    <td><strong style="color:var(--mint)">${num(a.unbooked_passengers)}</strong> чел.</td>
                    <td><span class="badge badge-neutral">${num(a.anom_flights)}</span></td>
                    <td><button class="btn btn-small" data-filter-airport="${esc(a.code)}">Рейсы ↗</button></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="panel" style="margin-top:20px">
        <div class="panel-heading">
          <div>
            <div class="section-kicker">ТРАНСПОРТНЫЕ КОРИДОРЫ</div>
            <h2>Топ-12 аномальных маршрутов</h2>
          </div>
        </div>
        <div class="data-scroll">
          <table class="data-table" style="width:100%">
            <thead>
              <tr>
                <th>Маршрут</th>
                <th>Города направления</th>
                <th>Авиакомпания</th>
                <th>Пассажиров вне брони GDS</th>
                <th>Аномальных рейсов</th>
                <th>Действие</th>
              </tr>
            </thead>
            <tbody>
              ${topRoutes.map(r => `
                <tr>
                  <td><strong>${esc(r.route)}</strong></td>
                  <td>${esc(r.city_from)} → ${esc(r.city_to)}</td>
                  <td><span class="badge badge-neutral">${esc(r.airline || '—')}</span></td>
                  <td><strong style="color:var(--coral)">${num(r.unbooked_passengers)}</strong> чел.</td>
                  <td>${num(r.anom_flights)}</td>
                  <td><button class="btn btn-small btn-primary" data-filter-airport="${esc(r.route.split(' → ')[0])}">Смотреть рейсы ↗</button></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } else {
    subContent = `
      <div class="panel" style="margin-top:20px">
        <div class="table-toolbar">
          <div class="segmented" style="margin-bottom:0">
            <button class="${kind === 'over_flew' ? 'selected' : ''}" data-occupancy-kind="over_flew">Физический перегруз <span>${num(stats.overcapacity_flew)}</span></button>
            <button class="${kind === 'over_booked' ? 'selected' : ''}" data-occupancy-kind="over_booked">Овербукинг <span>${num(stats.overcapacity_booked)}</span></button>
            <button class="${kind === 'all' ? 'selected' : ''}" data-occupancy-kind="all">Все аномалии <span>${num(stats.anomaly_flights)}</span></button>
          </div>
          <div class="search-wrap table-search">
            <span>⌕</span>
            <input id="occupancy-search" type="search" placeholder="Поиск рейса, авиакомпании, аэропорта, самолёта…" autocomplete="off" value="${esc(state.occupancyQuery)}">
          </div>
        </div>
        <div class="table-container">
          ${data.rows.length ? `
            <div class="data-scroll">
              <table class="data-table" style="width:100%">
                <thead>
                  <tr>
                    <th>Рейс и дата</th>
                    <th>Маршрут</th>
                    <th>Авиакомпания / Оператор</th>
                    <th>Воздушное судно</th>
                    <th>Лимит мест</th>
                    <th>Летели (flew)</th>
                    <th>Билетов (booked)</th>
                    <th>Статус аномалий</th>
                    <th>Пассажиры</th>
                  </tr>
                </thead>
                <tbody>${rows}</tbody>
              </table>
            </div>
            <div class="table-pagination">
              <span>Страница ${num(data.page)} · найдено ${num(data.total)} рейсов</span>
              <div>
                <button class="btn btn-small" data-occupancy-page="prev" ${data.page === 1 ? 'disabled' : ''}>← Назад</button>
                <button class="btn btn-small" data-occupancy-page="next" ${!data.has_more ? 'disabled' : ''}>Далее →</button>
              </div>
            </div>
          ` : empty('Рейсов не найдено', 'Попробуйте изменить поисковый запрос или фильтр.')}
        </div>
      </div>
      <div class="notice">
        <span class="notice-icon">i</span>
        <p><strong>Паспортная вместимость бортов</strong> подтягивается из <code>data/airplanes.csv</code> на основе IATA-кода расписания <code>dim_timetable.csv</code>. Превышение реальной вместимости самолёта (например, 142 человека на 50-местном Dash 8 или 118 человек на 108-местном Superjet) является прямым маркером фальсификации данных или спецперевозок.</p>
        <p style="margin-top:6px;font-size:12px;color:var(--muted)"><strong>Что значит «Вне брони» (куплено на месте):</strong> это пассажиры, присутствующие в реальном манифесте вылета (<code>fact_flights.csv</code>), но не имевшие предварительной брони в централизованной GDS (<code>fact_tickets.csv</code>). В нормальной практике это покупка билета в кассе аэропорта перед вылетом (walk-up), пересадка при задержках или субсидии. Однако если на борт садится больше людей, чем кресел в самолёте, речь идёт о нелегальной ручной подсадке.</p>
      </div>
    `;
  }

  content.innerHTML = `
    <div class="page-header">
      <div class="section-kicker">ЗАГРУЗКА И АНОМАЛИИ</div>
      <h1>Загрузка бортов, авиакомпании и аэропорты</h1>
      <p>Комплексный аудит нарушений регистрации: сопоставление пассажиров (fact_flights) и броней (fact_tickets), статистика перевозчиков (dim_timetable) и выгода аэропортов.</p>
    </div>
    <section class="stats-grid" aria-label="Сводка загрузки">
      ${cards.map(([label, n, color, foot]) => `
        <div class="stat-card">
          <span class="stat-icon ${color}">✈</span>
          <div class="stat-value">${typeof n === 'number' ? num(n) : esc(n)}</div>
          <div class="stat-label">${esc(label)}</div>
          <div class="stat-foot">${esc(foot)}</div>
        </div>`).join('')}
    </section>

    <div class="segmented" style="margin-top:20px;margin-bottom:0">
      <button class="${subView === 'flights' ? 'selected' : ''}" data-occupancy-subview="flights">✈ Список рейсов (${num(stats.critical_flights || 0)})</button>
      <button class="${subView === 'companies' ? 'selected' : ''}" data-occupancy-subview="companies">🏢 Авиакомпании-нарушители (${companies.length})</button>
      <button class="${subView === 'airports' ? 'selected' : ''}" data-occupancy-subview="airports">🛫 Аэропорты и выгода (${depAirports.length + arrAirports.length})</button>
    </div>

    ${subContent}
  `;
}

function showFlightDetails(index) {
  const row = state.occupancyRows[index];
  if (!row) return;
  const unbooked = json(row.unbooked_sample_profiles, []);
  const dialog = $('#record-dialog');
  $('#record-dialog-title').textContent = `Рейс ${row.flight_key}`;
  $('#record-dialog-subtitle').textContent = `${row.departure_airport} → ${row.arrival_airport} · ${row.flight_date} · ${row.operating_airline || row.airline_display || 'Авиакомпания'} · ${row.aircraft_model || row.aircraft_code || 'Самолёт'}`;
  
  let passengerPills = unbooked.length ? unbooked.map(p => `
    <button class="btn btn-small cell-link" data-person="P:${esc(p)}" style="margin:3px" onclick="$('#record-dialog').close()">P:${esc(p)} ↗</button>
  `).join('') : '<p style="color:var(--muted)">Все летевшие пассажиры имели оформленные билеты.</p>';

  $('#record-dialog-content').innerHTML = `
    <section class="record-field">
      <h3>ОСНОВНЫЕ ПАРАМЕТРЫ РЕЙСА И ПЕРЕВОЗЧИКА</h3>
      <div class="fact-strip" style="display:flex;gap:10px;margin-top:8px;flex-wrap:wrap">
        <div><small>ПЕРЕВОЗЧИК (ОПЕРАТОР)</small><strong>${esc(row.operating_airline || row.airline_display || 'Не указан')}</strong></div>
        <div><small>МАРКЕТИНГОВЫЙ КОД</small><strong>${esc(row.marketing_airline || 'Не указан')}</strong></div>
        <div><small>САМОЛЁТ</small><strong>${esc(row.aircraft_model || row.aircraft_code || 'Не указан')}</strong></div>
        <div><small>ВМЕСТИМОСТЬ</small><strong>${esc(row.capacity_limit)} мест (${esc(row.capacity_source)})</strong></div>
        <div><small>РЕАЛЬНО ЛЕТЕЛО</small><strong>${esc(row.flew_count)} чел.</strong></div>
        <div><small>ПРОДАНО БИЛЕТОВ</small><strong>${esc(row.booked_count)} шт.</strong></div>
      </div>
    </section>
    <section class="record-field">
      <h3>ФЛАГИ АНОМАЛИЙ</h3>
      <p><strong>${esc(row.anomaly_flags)}</strong></p>
    </section>
    <section class="record-field">
      <h3>ПАССАЖИРЫ НА БОРТУ ВНЕ ПРЕДВАРИТЕЛЬНОЙ БРОНИ GDS (КУПИЛИ НА МЕСТЕ / РУЧНАЯ ПОСАДКА)</h3>
      <p style="font-size:11px;color:var(--muted)">Нажмите на ID человека, чтобы открыть его досье во вкладке «Люди и дела»:</p>
      <div>${passengerPills}</div>
    </section>
  `;
  dialog.showModal();
}

async function renderNetwork() {
  const graph=await api('/api/network');
  const nodes=graph.nodes.slice(0,60); const ids=new Set(nodes.map(n=>n.id)); const edges=graph.edges.filter(e=>ids.has(e.source)&&ids.has(e.target));
  if(!nodes.length) {content.innerHTML=`<div class="page-header"><div class="section-kicker">ГРАФ</div><h1>Карта связей</h1></div>${empty('Граф пока пуст','Запустите анализ, чтобы появились люди и связи.')}`;return;}
  const cx=450,cy=245, radius=Math.min(188,90+nodes.length*9);
  const positions=new Map(nodes.map((n,i)=>[n.id,{x:cx+radius*Math.cos((i/nodes.length)*Math.PI*2-Math.PI/2),y:cy+radius*Math.sin((i/nodes.length)*Math.PI*2-Math.PI/2)}]));
  if(nodes.length===1) positions.set(nodes[0].id,{x:cx,y:cy});
  const svgEdges=edges.map(e=>{const a=positions.get(e.source),b=positions.get(e.target);return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" class="graph-edge ${e.stage==='secondary'?'secondary-edge':''}"/>`;}).join('');
  const svgNodes=nodes.map(n=>{const p=positions.get(n.id),label=n.label.length>16?n.label.slice(0,15)+'…':n.label;return `<g class="graph-node" data-person="${esc(n.id)}" tabindex="0" role="button" aria-label="Открыть ${esc(n.label)}"><circle cx="${p.x}" cy="${p.y}" r="29" class="${n.stage==='promoted_secondary'?'node-secondary':''}"/><text x="${p.x}" y="${p.y+5}" text-anchor="middle" class="node-initial">${esc(n.label.charAt(0))}</text><text x="${p.x}" y="${p.y+50}" text-anchor="middle" class="node-label">${esc(label)}</text></g>`;}).join('');
  const edgeList=edges.length?edges.map(e=>`<div class="network-edge-row"><span class="edge-kind ${e.stage==='secondary'?'secondary':''}">${e.stage==='secondary'?'Вторичная':'Первичная'}</span><button data-person="${esc(e.source)}">${esc(shortId(e.source))}</button><span>→</span><button data-person="${esc(e.target)}">${esc(shortId(e.target))}</button><small>${esc(e.signal)}</small></div>`).join(''):empty('Связей нет');
  content.innerHTML=`<div class="page-header"><div class="section-kicker">ГРАФ СЛЕДОВ</div><h1>Карта связей</h1><p>Нажмите на узел или строку связи, чтобы открыть досье. Граф показывает итоговых кандидатов и подтверждённые алгоритмом рёбра.</p></div><div class="network-layout"><div class="panel network-panel"><div class="network-legend"><span><i class="legend-dot"></i> Первичный кандидат</span><span><i class="legend-dot secondary"></i> Повышен по связям</span><span><i class="legend-line"></i> Связь</span></div><div class="graph-wrap"><svg viewBox="0 0 900 500" role="img" aria-label="Граф связей кандидатов"><g>${svgEdges}${svgNodes}</g></svg></div><div class="graph-caption">${num(nodes.length)} человек · ${num(edges.length)} связей</div></div><div class="panel network-list"><div class="panel-heading"><h2>Список связей</h2></div>${edgeList}</div></div>`;
}

async function renderRun() {
  content.innerHTML=`<div class="page-header"><div class="section-kicker">УПРАВЛЕНИЕ АНАЛИЗОМ</div><h1>Запустить расчёт</h1><p>Выберите этап. Сайт использует те же команды Makefile, что и терминал, и сохраняет новые CSV в локальной папке results.</p></div>
    <div class="run-grid"><article class="run-card panel"><div class="run-number">01</div><div class="run-icon">✳</div><h2>Первичные признаки</h2><p>Подготовить индекс, проверить документы и профили, найти совместные рейсы и посчитать первичный балл.</p><button class="btn btn-primary" data-run="primary">Запустить первичный этап ↗</button></article>
    <article class="run-card panel"><div class="run-number">02</div><div class="run-icon">⌘</div><h2>Расширение связей</h2><p>Проверить ближайшие документы, общие бронирования и параллельные маршруты. Построить цепочки.</p><button class="btn btn-primary" data-run="expand">Запустить расширение ↗</button></article>
    <article class="run-card panel"><div class="run-number">∞</div><div class="run-icon">▷</div><h2>Полный анализ</h2><p>Последовательно выполнить все этапы. Готовый индекс и промежуточные таблицы используются повторно.</p><button class="btn btn-primary" data-run="all">Запустить всё ↗</button></article></div>
    <div class="panel job-panel"><div class="panel-heading"><div><div class="section-kicker">СОСТОЯНИЕ ЗАДАЧИ</div><h2>Журнал выполнения</h2></div><span id="job-state" class="badge">Ожидание</span></div><div id="job-meta" class="job-meta">Расчёт ещё не запускался в этой сессии.</div><pre id="job-log" class="job-log">Здесь появятся этапы и результаты.</pre></div>
    <div class="notice"><span class="notice-icon">i</span><p>Во время подготовки индекса обработка больших CSV может занять несколько минут. Не закрывайте окно сервера, пока задача выполняется.</p></div>`;
  await updateJob();
}
async function updateJob() {
  try {const job=await api('/api/job'); state.job=job;
    $('#job-dot').hidden=job.status!=='running';
    const label={idle:'Ожидание',running:'Выполняется',success:'Готово',error:'Ошибка'}[job.status]||job.status;
    const status=$('#job-state'); if(status){status.textContent=label;status.className='badge badge-'+(job.status==='success'?'mint':job.status==='error'?'coral':job.status==='running'?'sky':'neutral');}
    const meta=$('#job-meta');if(meta)meta.textContent=job.status==='idle'?'Расчёт ещё не запускался в этой сессии.':`${job.stage} · начало ${job.started_at}${job.finished_at?' · завершён '+job.finished_at:''}`;
    const log=$('#job-log');if(log)log.textContent=job.lines.length?job.lines.join('\n'):'Ожидаем первые сообщения…';
  }catch{/* overview remains usable if job endpoint is unavailable */}
}
async function startJob(stage) {
  try {await api('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stage})});toast('Расчёт запущен');await updateJob();}
  catch(error){toast(error.message);}
}

document.addEventListener('click', async event=>{
  if(event.target.closest('[data-dialog-close]')) { $('#record-dialog').close(); return; }
  if(event.target.closest('#record-dialog-copy')) return copyTableRecord();
  const record=event.target.closest('[data-record-row]');if(record)return openTableRecord(Number(record.dataset.recordRow));
  const cell=event.target.closest('[data-cell-row]');if(cell)return openTableRecord(Number(cell.dataset.cellRow),cell.dataset.cellColumn);
  const nav=event.target.closest('[data-view]'); if(nav){event.preventDefault();return navigate(nav.dataset.view);}
  const person=event.target.closest('[data-person]'); if(person){state.selectedPerson=person.dataset.person;return navigate('people');}
  const signal=event.target.closest('[data-signal]'); if(signal){state.tableName=signal.dataset.signal;state.tablePage=1;state.tableQuery='';return navigate('tables');}
  const group=event.target.closest('[data-signal-group]');if(group){state.signalGroup=group.dataset.signalGroup;return renderSignals();}
  const targetGroup=event.target.closest('[data-target-group]');if(targetGroup){state.signalGroup=targetGroup.dataset.targetGroup;return navigate('signals');}
  const routeTarget=event.target.closest('[data-route-kind]');if(routeTarget){state.candidateKind=routeTarget.dataset.routeKind;state.selectedPerson=null;return navigate('people');}
  const kind=event.target.closest('[data-candidate-kind]');if(kind){state.candidateKind=kind.dataset.candidateKind;document.querySelectorAll('[data-candidate-kind]').forEach(el=>el.classList.toggle('selected',el===kind));return loadPeopleList($('#people-search')?.value||'');}
  const table=event.target.closest('[data-table]');if(table){state.tableName=table.dataset.table;state.tablePage=1;state.tableQuery='';return renderTables();}
  const page=event.target.closest('[data-page]');if(page){state.tablePage=Math.max(1,state.tablePage+(page.dataset.page==='next'?1:-1));return loadTable();}
  const pick=event.target.closest('[data-pick]');if(pick){const obj={id:pick.dataset.id,label:pick.dataset.label};if(pick.dataset.pick==='a')state.compareA=obj;else state.compareB=obj;return renderCompare();}
  if(event.target.closest('#compare-button')) return runCompare();
  const occKind=event.target.closest('[data-occupancy-kind]');if(occKind){state.occupancyKind=occKind.dataset.occupancyKind;state.occupancyPage=1;return renderOccupancy();}
  const occSub=event.target.closest('[data-occupancy-subview]');if(occSub){state.occupancySubView=occSub.dataset.occupancySubview;return renderOccupancy();}
  const filterAir=event.target.closest('[data-filter-airline]');if(filterAir){state.occupancySubView='flights';state.occupancyQuery=filterAir.dataset.filterAirline;state.occupancyPage=1;state.occupancyKind='all';return renderOccupancy();}
  const filterAp=event.target.closest('[data-filter-airport]');if(filterAp){state.occupancySubView='flights';state.occupancyQuery=filterAp.dataset.filterAirport;state.occupancyPage=1;state.occupancyKind='all';return renderOccupancy();}
  const occPage=event.target.closest('[data-occupancy-page]');if(occPage){state.occupancyPage=Math.max(1,state.occupancyPage+(occPage.dataset.occupancyPage==='next'?1:-1));return renderOccupancy();}
  const flightDetails=event.target.closest('[data-flight-details]');if(flightDetails)return showFlightDetails(Number(flightDetails.dataset.flightDetails));
  const run=event.target.closest('[data-run]');if(run)return startJob(run.dataset.run);
  if(event.target.closest('[data-refresh]'))return navigate(state.view);
});
document.addEventListener('input',event=>{
  const el=event.target;
  if(el.id==='people-search'){clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadPeopleList(el.value),350);}
  if(el.id==='table-search'){clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.tableQuery=el.value;state.tablePage=1;loadTable();},400);}
  if(el.id==='occupancy-search'){clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.occupancyQuery=el.value;state.occupancyPage=1;renderOccupancy();},350);}
  if(el.id==='compare-search-a'||el.id==='compare-search-b'){clearTimeout(searchTimer);const which=el.id.endsWith('a')?'a':'b';searchTimer=setTimeout(()=>compareSearch(which,el.value),300);}
});
document.addEventListener('keydown',event=>{
  if((event.key==='Enter'||event.key===' ')&&event.target.classList.contains('signal-card')){event.preventDefault();state.tableName=event.target.dataset.signal;state.tablePage=1;state.tableQuery='';navigate('tables');}
  if((event.key==='Enter'||event.key===' ')&&event.target.classList.contains('graph-node')){event.preventDefault();state.selectedPerson=event.target.dataset.person;navigate('people');}
});
window.addEventListener('hashchange',()=>{const view=location.hash.slice(1);if(view&&view!==state.view&&labels[view])navigate(view);});
setInterval(updateJob,3000);
navigate(labels[location.hash.slice(1)]?location.hash.slice(1):'overview');
