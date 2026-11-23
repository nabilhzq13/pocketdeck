/* PocketDeck phone/tablet client. Talks to server.py over one WebSocket. */
(() => {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
  };
  const buzz = (ms) => { try { navigator.vibrate && navigator.vibrate(ms); } catch { /* iOS */ } };
  const COLORS = ['orange', 'amber', 'green', 'blue', 'violet', 'pink', 'cyan', 'red', 'slate'];
  const CONFIRM = {
    shutdown: ['Shut down the PC?', 'It shuts down in 5 seconds. Tap “Cancel shutdown” to stop it.', 'Shut down'],
    restart: ['Restart the PC?', 'It restarts in 5 seconds. Unsaved work may be lost.', 'Restart'],
    signout: ['Sign out of Windows?', 'Open apps will close.', 'Sign out'],
    sleep: ['Put the PC to sleep?', 'PocketDeck disconnects until the PC wakes up.', 'Sleep'],
    hibernate: ['Hibernate the PC?', 'PocketDeck disconnects until the PC wakes up.', 'Hibernate'],
  };

  const S = {
    token: null, ws: null, config: null, status: {}, server: {}, page: 0, editing: false,
    pending: new Map(), nextId: 1, widgets: [], keys: [], retry: 0, everConnected: false,
  };
  const deck = $('#deck');

  // ------------------------------------------------------------------ token & connection
  function readToken() {
    const m = location.hash.match(/[#&]t=([^&]+)/);
    if (m) {
      const t = decodeURIComponent(m[1]);
      store.set('pd_token', t);
      history.replaceState(null, '', location.pathname);
      return t;
    }
    return store.get('pd_token');
  }

  function setConn(state, text) {
    const c = $('#conn');
    c.className = 'status ' + state;
    $('#host').textContent = text || (state === 'on' ? (S.server.name || 'Connected') : 'Offline');
  }

  async function connect() {
    clearTimeout(S.retryTimer);
    if (!S.token) return showPairing();
    if (S.ws && S.ws.readyState <= 1) return;
    setConn('', 'Connecting');
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(S.token)}`);
    S.ws = ws;
    ws.onopen = () => { S.retry = 0; S.everConnected = true; $('#offline').hidden = true; };
    ws.onmessage = (e) => { try { onMessage(JSON.parse(e.data)); } catch (err) { console.error(err); } };
    ws.onclose = async () => {
      if (S.ws !== ws) return;
      S.ws = null;
      for (const p of S.pending.values()) { clearTimeout(p.t); p.rej(new Error('Lost connection to the PC')); }
      S.pending.clear();
      setConn('err');
      // A rejected token looks like a plain close; ask the server directly.
      try {
        const r = await fetch('/api/ping?token=' + encodeURIComponent(S.token), { cache: 'no-store' });
        if (r.status === 401) { store.del('pd_token'); S.token = null; showPairing('That pairing code is no longer valid. Scan the QR code again.'); return; }
      } catch { /* server down */ }
      S.retry++;
      if (S.retry >= 2) { $('#offline').hidden = false; $('#offlineMsg').textContent = 'Trying again…'; }
      S.retryTimer = setTimeout(connect, Math.min(5000, 400 * 2 ** S.retry));
    };
  }

  function showPairing(msg) {
    $('#pairing').hidden = false;
    $('#offline').hidden = true;
    if (msg) $('#pairing p').textContent = msg;
  }
  $('#tokenForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const t = $('#tokenInput').value.trim();
    if (!t) return;
    S.token = t; store.set('pd_token', t);
    $('#pairing').hidden = true;
    connect();
  });
  $('#forgetBtn').addEventListener('click', () => { store.del('pd_token'); S.token = null; if (S.ws) S.ws.close(); showPairing(); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && (!S.ws || S.ws.readyState > 1)) { S.retry = 0; connect(); }
  });

  function onMessage(m) {
    switch (m.op) {
      case 'hello':
        S.server = m.server || {}; S.config = m.config; S.status = m.status || {};
        setConn('on');
        S.page = Math.min(+store.get('pd_page') || 0, S.config.pages.length - 1);
        renderPage();
        break;
      case 'status': S.status = m.status || {}; updateStatus(); break;
      case 'config':
        S.config = m.config;
        S.page = Math.min(S.page, S.config.pages.length - 1);
        renderPage();
        break;
      case 'result': {
        const p = S.pending.get(m.id);
        if (!p) return;
        S.pending.delete(m.id); clearTimeout(p.t);
        m.ok ? p.res(m) : p.rej(new Error(m.message || 'Something went wrong on the PC'));
        break;
      }
      case 'toast': toast(m.message, m.error); break;
      default: break;
    }
  }

  function send(op, data = {}, reply = true) {
    if (!S.ws || S.ws.readyState !== 1) return Promise.reject(new Error('Not connected to the PC'));
    const msg = { op, ...data };
    if (!reply) { S.ws.send(JSON.stringify(msg)); return Promise.resolve(); }
    const id = S.nextId++; msg.id = id;
    return new Promise((res, rej) => {
      const t = setTimeout(() => { S.pending.delete(id); rej(new Error('The PC did not answer in time')); }, 25000);
      S.pending.set(id, { res, rej, t });
      S.ws.send(JSON.stringify(msg));
    });
  }
  const sendAction = (action) => send('action', { action });
  const quiet = (p) => p.catch((e) => toast(e.message, true));

  // ------------------------------------------------------------------ toast & sheet
  let toastTimer;
  function toast(msg, bad = false) {
    if (!msg) return;
    const el = $('#toast');
    el.textContent = msg; el.classList.toggle('bad', !!bad); el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), bad ? 4000 : 1800);
  }

  function openSheet(build) {
    const wrap = $('#sheetWrap'), sheet = $('#sheet');
    sheet.innerHTML = '';
    build(sheet);
    wrap.hidden = false;
    const first = sheet.querySelector('input, select, textarea, button');
    if (first && matchMedia('(hover: hover)').matches) first.focus();
  }
  function closeSheet() { $('#sheetWrap').hidden = true; $('#sheet').innerHTML = ''; }
  $('#sheetWrap').addEventListener('click', (e) => { if (e.target.id === 'sheetWrap') closeSheet(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#sheetWrap').hidden) closeSheet(); });

  function confirmSheet(title, body, yes) {
    return new Promise((resolve) => {
      openSheet((s) => {
        s.innerHTML = `<h3>${esc(title)}</h3><p class="hint" style="font-size:15px">${esc(body)}</p>
          <div class="actions"><button class="btn" data-no>Keep running</button><span class="spacer"></span><button class="btn danger" data-yes>${esc(yes)}</button></div>`;
        s.querySelector('[data-no]').onclick = () => { closeSheet(); resolve(false); };
        s.querySelector('[data-yes]').onclick = () => { closeSheet(); resolve(true); };
      });
    });
  }

  // ------------------------------------------------------------------ icons
  const DEFAULT_GLYPH = {
    app: 'star', url: 'globe', open: 'folder', hotkey: 'keyboard', text: 'text-cursor', media: 'playpause',
    volume: 'volume', mic: 'mic', audio_device: 'headphones', brightness: 'sun', display: 'monitor',
    theme: 'moon', power_mode: 'zap', power: 'power', command: 'terminal', page: 'grid', macro: 'wand',
    clipboard: 'paste', sonar: 'settings',
  };
  const defaultGlyph = (a) => DEFAULT_GLYPH[(a || {}).type] || 'star';
  const tokenQS = () => '&token=' + encodeURIComponent(S.token || '');

  function autoIconURL(a) {
    a = a || {};
    if (a.type === 'app') {
      if (a.appid) return `/icon?src=${encodeURIComponent('app:' + a.appid)}${tokenQS()}`;
      if (a.name) return `/icon?app=${encodeURIComponent(a.name)}${tokenQS()}`;
    }
    if (a.type === 'url' && a.url) {
      try {
        const u = new URL(a.url.includes('://') ? a.url : 'https://' + a.url);
        return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(u.hostname)}&sz=128`;
      } catch { return null; }
    }
    if (a.type === 'open' && a.target && /^([a-z]:\\|\\\\|%)/i.test(a.target)) {
      return `/icon?src=${encodeURIComponent(a.target)}${tokenQS()}`;
    }
    return null;
  }
  const monogram = (item) => (item.label || '?').trim().charAt(0).toUpperCase();

  function iconHTML(item) {
    const a = item.action || {};
    const ic = item.icon || 'auto';
    if (ic.startsWith('i:')) return glyph(ic.slice(2)) || glyph(defaultGlyph(a));
    if (/^(https?:|data:image)/.test(ic)) return `<img src="${esc(ic)}" alt="" data-mono="${esc(monogram(item))}">`;
    if (ic !== 'auto') return `<span class="emoji">${esc(ic)}</span>`;
    const src = autoIconURL(a);
    if (src) return `<img src="${esc(src)}" alt="" data-mono="${esc(monogram(item))}">`;
    return glyph(defaultGlyph(a));
  }
  // Broken image (app uninstalled, offline favicon): fall back to a letter.
  document.addEventListener('error', (e) => {
    const img = e.target;
    if (img.tagName !== 'IMG') return;
    if (img.dataset.mono !== undefined) {
      const span = document.createElement('span');
      span.className = 'mono'; span.textContent = img.dataset.mono;
      img.replaceWith(span);
    } else if (img.classList.contains('app-ico')) {
      img.style.visibility = 'hidden';
    }
  }, true);

  // ------------------------------------------------------------------ layout
  function layout() {
    const w = deck.clientWidth || window.innerWidth;
    let cols = Math.max(4, Math.min(10, Math.floor(w / 110)));
    if (cols >= 6 && cols % 2) cols -= 1;
    const root = document.documentElement.style;
    root.setProperty('--cols', cols);
    root.setProperty('--half', cols >= 6 ? cols / 2 : cols);
    const cs = getComputedStyle(deck);
    const inner = deck.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const gap = parseFloat(cs.columnGap) || 12;
    root.setProperty('--keysize', Math.max(56, (inner - gap * (cols - 1)) / cols) + 'px');
  }
  window.addEventListener('resize', layout);

  // ------------------------------------------------------------------ rendering
  function renderBanks() {
    const nav = $('#banks');
    nav.innerHTML = '';
    S.config.pages.forEach((p, i) => {
      const b = document.createElement('button');
      b.className = 'bank' + (i === S.page ? ' cur' : '');
      const ic = p.icon || 'grid';
      b.innerHTML = (window.GLYPHS[ic] ? glyph(ic) : `<span class="emoji">${esc(ic)}</span>`) + `<span>${esc(p.name)}</span>`;
      b.setAttribute('aria-current', i === S.page ? 'page' : 'false');
      b.onclick = () => { if (S.editing && i === S.page) window.Editor.editPage(i); else goPage(i); };
      nav.append(b);
    });
    if (S.editing) {
      const add = document.createElement('button');
      add.className = 'bank add'; add.innerHTML = glyph('plus'); add.setAttribute('aria-label', 'Add page');
      add.onclick = () => window.Editor.addPage();
      nav.append(add);
    }
    const cur = nav.querySelector('.cur');
    if (cur) cur.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  function goPage(i, dir) {
    if (i < 0 || i >= S.config.pages.length || i === S.page) return;
    dir = dir || (i > S.page ? 'l' : 'r');
    S.page = i; store.set('pd_page', i);
    renderPage(dir);
  }

  function renderPage(dir) {
    if (!S.config) return;
    S.widgets.forEach((w) => w.destroy && w.destroy());
    S.widgets = []; S.keys = [];
    deck.innerHTML = '';
    deck.classList.toggle('editing', S.editing);
    $('#editToggle').classList.toggle('active', S.editing);
    $('#editToggle').innerHTML = glyph(S.editing ? 'check' : 'pencil');
    $('#editToggle').setAttribute('aria-label', S.editing ? 'Done editing' : 'Edit buttons');
    const page = S.config.pages[S.page];
    $('#pageTitle').textContent = page ? page.name : '';
    layout();
    (page.items || []).forEach((item, idx) => {
      if (item.kind === 'widget') mountWidget(item, idx);
      else deck.append(makeKey(item, idx));
    });
    if (S.editing) {
      deck.append(addTile());
    } else if (!page.items.length) {
      const e = document.createElement('div');
      e.className = 'module'; e.innerHTML = '<div class="empty">This page is empty. Tap the pencil to add buttons.</div>';
      deck.append(e);
    }
    renderBanks();
    if (dir) { deck.classList.remove('swipe-l', 'swipe-r'); void deck.offsetWidth; deck.classList.add('swipe-' + dir); }
    updateStatus();
  }

  function makeKey(item, idx, preview = false) {
    const el = document.createElement('button');
    el.className = 'key';
    el.style.setProperty('--c', `var(--${COLORS.includes(item.color) ? item.color : 'slate'})`);
    el.innerHTML = `<span class="pip"></span><span class="edit-badge">${glyph('pencil')}</span>
      <span class="face">${iconHTML(item)}</span><span class="label">${esc(item.label || '')}</span>`;
    el.setAttribute('aria-label', item.label || 'Button');
    if (!preview) {
      el.dataset.idx = idx;
      attachPress(el, item, idx);
      S.keys.push({ el, item });
    }
    return el;
  }

  function attachPress(el, item, idx) {
    let timer = null, long = false, moved = false, x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    el.addEventListener('pointerdown', (e) => {
      if (S.editing) return;
      long = false; moved = false; x0 = x1 = e.clientX; y0 = y1 = e.clientY;
      el.classList.add('pressed');
      // Long-press: icons start wiggling and this one is picked up, ready to drag.
      timer = setTimeout(() => { long = true; el.classList.remove('pressed'); setEditing(true); Drag.pickUp(el, x1, y1); }, 500);
    });
    el.addEventListener('pointermove', (e) => {
      x1 = e.clientX; y1 = e.clientY;
      if (timer && Math.hypot(e.clientX - x0, e.clientY - y0) > 12) { moved = true; clearTimeout(timer); timer = null; el.classList.remove('pressed'); }
    });
    const end = () => { clearTimeout(timer); timer = null; el.classList.remove('pressed'); };
    el.addEventListener('pointerup', () => {
      const fire = timer !== null && !long && !moved && !S.editing;
      end();
      if (fire) trigger(el, item);
    });
    el.addEventListener('pointercancel', end);
    el.addEventListener('click', () => { if (S.editing && !Drag.recent()) window.Editor.editItem(S.page, idx); });
    el.addEventListener('keydown', (e) => {
      if ((e.key === 'Enter' || e.key === ' ') && !S.editing) { e.preventDefault(); trigger(el, item); }
    });
    el.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  function flash(el, cls) { el.classList.remove('ok', 'err'); void el.offsetWidth; el.classList.add(cls); setTimeout(() => el.classList.remove(cls), 500); }

  async function trigger(el, item) {
    const a = item.action || {};
    buzz(8);
    if (a.type === 'page') {
      const i = typeof a.page === 'number' ? a.page : S.config.pages.findIndex((p) => p.name === a.page);
      if (i >= 0) goPage(i);
      return;
    }
    if (a.type === 'power' && CONFIRM[a.cmd]) {
      const [t, b, y] = CONFIRM[a.cmd];
      if (!(await confirmSheet(t, b, y))) return;
    }
    let action = a;
    if (LAUNCHERS.has(a.type)) {
      const mode = a.screen || (a.type === 'app' ? 'ask' : 'none');
      const list = S.status.screens || [];
      if (mode === 'ask' && list.length > 1) {
        const pick = await pickScreen(item, list);
        if (!pick) return;
        action = { ...a, screen: pick.screen, maximize: pick.maximize };
      }
    }
    el.classList.add('busy');
    try {
      const r = await sendAction(action);
      flash(el, 'ok');
      if (r.message) toast(r.message);
    } catch (e) {
      flash(el, 'err'); buzz([30, 40, 30]);
      toast(e.message, true);
    } finally {
      el.classList.remove('busy');
    }
  }

  // ------------------------------------------------------------------ choose a screen
  const LAUNCHERS = new Set(['app', 'url', 'open']);

  // A sheet that resolves with a choice, or null when cancelled or closed by tapping outside.
  function sheetChoice(build) {
    return new Promise((resolve) => {
      let done = false;
      const obs = new MutationObserver(() => { if ($('#sheetWrap').hidden) finish(null); });
      function finish(v) { if (done) return; done = true; obs.disconnect(); closeSheet(); resolve(v); }
      openSheet((s) => build(s, finish));
      obs.observe($('#sheetWrap'), { attributes: true, attributeFilter: ['hidden'] });
    });
  }

  // ------------------------------------------------------------------ SteelSeries Sonar pickers
  const sonarId = (c) => ({ chat: 'chatRender', mic: 'chatCapture', microphone: 'chatCapture' }[String(c).toLowerCase()] || c);

  function sonarPresetPicker(device, label, currentId) {
    return sheetChoice((s, finish) => {
      s.innerHTML = `<h3>${esc(label)} preset</h3><input id="q" placeholder="Search presets" autocapitalize="off" autocorrect="off">
        <div class="app-list"><div class="empty">Loading presets from Sonar…</div></div>
        <div class="actions"><span class="spacer"></span><button class="btn" data-cancel>Cancel</button></div>`;
      const list = s.querySelector('.app-list'), q = s.querySelector('#q');
      let all = [];
      const draw = () => {
        const term = q.value.trim().toLowerCase();
        const items = all.filter((p) => !term || p.name.toLowerCase().includes(term)).slice(0, 150);
        list.innerHTML = items.length ? '' : '<div class="empty">No matching presets</div>';
        for (const p of items) {
          const r = document.createElement('button');
          r.className = 'row' + (p.id === currentId ? ' sel' : '');
          r.innerHTML = `<span class="ico">${glyph(p.favorite ? 'star' : 'settings')}</span><span class="grow"><div class="t1"></div><div class="t2">${p.id === currentId ? 'In use' : p.favorite ? 'Favourite' : ''}</div></span>`;
          r.querySelector('.t1').textContent = p.name;
          r.onclick = () => finish(p);
          list.append(r);
        }
      };
      q.oninput = draw;
      s.querySelector('[data-cancel]').onclick = () => finish(null);
      send('sonar_presets', { device }).then((r) => { all = r.presets || []; draw(); })
        .catch((e) => { list.innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
    });
  }

  function sonarOutputPicker(so) {
    return sheetChoice((s, finish) => {
      s.innerHTML = `<h3>Sonar plays through</h3><p class="hint">Sends Game, Chat, Media and Aux to this speaker or headset.</p>
        <div class="list"></div><div class="actions"><span class="spacer"></span><button class="btn" data-cancel>Cancel</button></div>`;
      const list = s.querySelector('.list');
      for (const o of so.outputs || []) {
        const r = document.createElement('button');
        r.className = 'row' + (o.id === so.output ? ' sel' : '');
        r.innerHTML = '<span class="radio"></span><span class="grow"><div class="t1"></div><div class="t2"></div></span>';
        r.querySelector('.t1').textContent = shortName(o.name);
        r.querySelector('.t2').textContent = (o.name.match(/\((.*)\)/) || [])[1] || '';
        r.onclick = () => finish(o);
        list.append(r);
      }
      s.querySelector('[data-cancel]').onclick = () => finish(null);
    });
  }

  // Draws the screens as they are arranged in Windows; tap one to open the app there.
  function pickScreen(item, list) {
    return new Promise((resolve) => {
      let done = false;
      const finish = (v) => { if (done) return; done = true; obs.disconnect(); closeSheet(); resolve(v); };
      openSheet((s) => {
        s.innerHTML = `<h3>Open ${esc(item.label || 'it')} on</h3><div class="screen-map" role="group" aria-label="Screens"></div>
          <label class="check"><input type="checkbox" data-max> Fill the screen</label>
          <div class="actions"><button class="btn" data-cancel>Cancel</button><span class="spacer"></span><button class="btn" data-any>Where Windows puts it</button></div>`;
        const map = s.querySelector('.screen-map');
        const max = s.querySelector('[data-max]');
        max.checked = !!(item.action && item.action.maximize);
        const last = store.get('pd_last_screen');
        const minX = Math.min(...list.map((d) => d.x)), minY = Math.min(...list.map((d) => d.y));
        const spanW = Math.max(...list.map((d) => d.x + d.width)) - minX;
        const spanH = Math.max(...list.map((d) => d.y + d.height)) - minY;
        map.style.aspectRatio = `${spanW} / ${spanH}`;
        for (const d of list) {
          const b = document.createElement('button');
          b.className = 'screen-tile' + (d.id === last ? ' last' : '');
          b.style.left = ((d.x - minX) / spanW * 100) + '%';
          b.style.top = ((d.y - minY) / spanH * 100) + '%';
          b.style.width = (d.width / spanW * 100) + '%';
          b.style.height = (d.height / spanH * 100) + '%';
          b.innerHTML = `${glyph(d.internal ? 'laptop' : 'monitor')}<span class="nm">${esc(d.name)}</span>
            <span class="res">${d.width} × ${d.height}${d.primary ? ', main' : ''}</span>`;
          b.onclick = () => { buzz(8); store.set('pd_last_screen', d.id); finish({ screen: d.id, maximize: max.checked }); };
          map.append(b);
        }
        s.querySelector('[data-cancel]').onclick = () => finish(null);
        s.querySelector('[data-any]').onclick = () => finish({ screen: 'none', maximize: false });
      });
      // closing the sheet by tapping outside counts as cancel
      const obs = new MutationObserver(() => { if ($('#sheetWrap').hidden) finish(null); });
      obs.observe($('#sheetWrap'), { attributes: true, attributeFilter: ['hidden'] });
    });
  }

  // ------------------------------------------------------------------ live state on keys
  function keyState(a, st) {
    switch (a.type) {
      case 'volume': return a.cmd === 'mute' && st.volume ? !!st.volume.muted : null;
      case 'mic': return st.mic ? !!st.mic.muted : null;
      case 'theme': return typeof st.dark === 'boolean' ? (a.mode === 'light' ? !st.dark : st.dark) : null;
      case 'power_mode': return st.power_mode ? st.power_mode === a.mode : null;
      case 'media': return a.cmd === 'playpause' ? !!(st.media && st.media.playing) : null;
      case 'audio_device': {
        if (a.cmd !== 'set') return null;
        const d = (st.devices || []).find((x) => x.default);
        if (!d) return null;
        return a.id ? d.id === a.id : !!(a.name && d.name.toLowerCase().includes(a.name.toLowerCase()));
      }
      case 'sonar': {
        const so = st.sonar;
        if (!so || !so.available) return null;
        if (a.cmd === 'preset') {
          const cur = (so.presets || {})[sonarId(a.device || 'game')];
          return cur ? cur.id === a.preset || cur.name.toLowerCase() === String(a.preset || '').toLowerCase() : null;
        }
        if (a.cmd === 'volume' && a.change === 'mute') {
          const c = (so.channels || []).find((x) => x.id === sonarId(a.channel || 'master'));
          return c ? c.muted : null;
        }
        if (a.cmd === 'output') {
          const want = String(a.output || a.device || '').toLowerCase();
          const o = want && (so.outputs || []).find((x) => x.id.toLowerCase() === want || x.name.toLowerCase().includes(want));
          return o ? so.output === o.id : null;
        }
        return null;
      }
      default: return null;
    }
  }

  function updateStatus() {
    const st = S.status || {};
    for (const { el, item } of S.keys) {
      const a = item.action || {};
      const on = keyState(a, st);
      el.classList.toggle('stateful', on !== null);
      el.classList.toggle('on', !!on);
      // swap a few glyphs so the key shows what it will do
      let swap = null;
      if (item.icon === 'i:mic' && a.type === 'mic') swap = on ? 'mic-off' : 'mic';
      if (item.icon === 'i:playpause' && a.type === 'media') swap = on ? 'pause' : 'play';
      if (swap && el.dataset.glyph !== swap) {
        el.dataset.glyph = swap;
        el.querySelector('.face').innerHTML = glyph(swap);
      }
    }
    for (const w of S.widgets) { try { w.update(st); } catch (e) { console.error(e); } }
  }

  // ------------------------------------------------------------------ fader control
  function fader({ color = 'cyan', label = '', onSet, step = 5 }) {
    const el = document.createElement('div');
    el.className = 'fader';
    el.tabIndex = 0;
    el.setAttribute('role', 'slider');
    el.setAttribute('aria-valuemin', '0'); el.setAttribute('aria-valuemax', '100');
    el.style.setProperty('--c', `var(--${color})`);
    el.innerHTML = '<div class="fill"></div><div class="txt"><span></span><span></span></div>';
    const [lab, val] = el.querySelectorAll('.txt span');
    lab.textContent = label; el.setAttribute('aria-label', label);
    let value = 0, active = false, held = 0, x0 = 0, v0 = 0, lastSent = 0, timer = null;
    const draw = (v) => { el.style.setProperty('--v', v + '%'); val.textContent = Math.round(v) + '%'; el.setAttribute('aria-valuenow', Math.round(v)); };
    const emit = () => { lastSent = Date.now(); onSet(Math.round(value)); };
    function push(v) {
      value = Math.max(0, Math.min(100, v)); draw(value); held = Date.now();
      clearTimeout(timer);
      if (Date.now() - lastSent > 60) emit(); else timer = setTimeout(emit, 60);
    }
    // Relative drag: a stray tap never jumps the volume to 100%.
    el.addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      active = true; x0 = e.clientX; v0 = value; held = Date.now();
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener('pointermove', (e) => {
      if (!active) return;
      push(v0 + ((e.clientX - x0) / el.clientWidth) * 100);
    });
    const up = () => { if (!active) return; active = false; held = Date.now(); clearTimeout(timer); if (Math.round(value) !== Math.round(v0)) emit(); };
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    el.addEventListener('keydown', (e) => {
      const d = { ArrowRight: step, ArrowUp: step, ArrowLeft: -step, ArrowDown: -step }[e.key];
      if (d) { e.preventDefault(); push(value + d); }
    });
    return {
      el,
      set(v) {
        if (active || Date.now() - held < 1500) return;
        el.classList.toggle('disabled', v == null);
        if (v != null) { value = v; draw(v); }
      },
      label(t) { if (lab.textContent !== t) { lab.textContent = t; el.setAttribute('aria-label', t); } },
      muted(m) { el.classList.toggle('muted', !!m); },
    };
  }

  function chip(name, label, onClick) {
    const b = document.createElement('button');
    b.className = 'chip'; b.innerHTML = glyph(name); b.setAttribute('aria-label', label);
    b.onclick = (e) => { e.stopPropagation(); buzz(8); onClick(b); };
    return b;
  }

  // ------------------------------------------------------------------ widgets
  const fmtBytes = (b) => b > 1e6 ? (b / 1e6).toFixed(1) + ' MB/s' : b > 1e3 ? Math.round(b / 1e3) + ' KB/s' : Math.round(b) + ' B/s';
  const fmtDur = (s) => { const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? `${d} d ${h} h` : h ? `${h} h ${m} m` : `${m} m`; };
  const shortName = (n) => (n || '').replace(/\s*\([^)]*\)\s*$/, '') || n;
  const icoURL = (exe) => exe ? `/icon?src=${encodeURIComponent(exe)}${tokenQS()}` : '';
  const appIco = (exe, name) => exe ? `<img class="app-ico" src="${esc(icoURL(exe))}" alt="">` : `<span class="app-ico ph">${esc((name || '?').charAt(0))}</span>`;

  function meter(pct, mode) {
    const lit = Math.round(Math.max(0, Math.min(100, pct || 0)) / 5);
    let html = '';
    for (let i = 0; i < 20; i++) {
      let cls = '';
      if (i < lit) {
        if (mode === 'battery') cls = pct <= 20 ? 'l3' : pct <= 40 ? 'l2' : 'l1';
        else cls = i < 12 ? 'l1' : i < 16 ? 'l2' : 'l3';
      }
      html += `<i class="${cls}"></i>`;
    }
    return `<div class="meter" aria-hidden="true">${html}</div>`;
  }

  const WIDGETS = {
    nowplaying: {
      title: 'Now playing', glyph: 'music',
      mount(body) {
        body.innerHTML = `<div class="np"><div class="art">${glyph('music')}</div><div class="meta">
          <div class="title">Nothing playing</div><div class="artist">Start music or a video on the PC</div><div class="src"></div>
          <div class="ctrls"></div></div></div>`;
        const ctrls = body.querySelector('.ctrls');
        const prev = chip('prev', 'Previous', () => quiet(sendAction({ type: 'media', cmd: 'prev' })));
        const play = chip('play', 'Play or pause', () => quiet(sendAction({ type: 'media', cmd: 'playpause' })));
        const next = chip('next', 'Next', () => quiet(sendAction({ type: 'media', cmd: 'next' })));
        play.classList.add('main');
        ctrls.append(prev, play, next);
        let artKey = null, playing = null;
        return {
          update(st) {
            const m = st.media;
            body.querySelector('.title').textContent = m ? m.title : 'Nothing playing';
            body.querySelector('.artist').textContent = m ? (m.artist || m.album || '') : 'Start music or a video on the PC';
            body.querySelector('.src').textContent = m && m.app ? m.app : '';
            const p = !!(m && m.playing);
            if (p !== playing) { playing = p; play.innerHTML = glyph(p ? 'pause' : 'play'); }
            const key = m && m.art ? m.art : null;
            if (key !== artKey) {
              artKey = key;
              const art = body.querySelector('.art');
              if (key) { const img = document.createElement('img'); img.className = 'art'; img.alt = ''; img.src = `/art/${key}?${tokenQS().slice(1)}`; art.replaceWith(img); }
              else { const d = document.createElement('div'); d.className = 'art'; d.innerHTML = glyph('music'); art.replaceWith(d); }
            }
          },
        };
      },
    },

    volume: {
      title: 'Volume', glyph: 'volume',
      mount(body) {
        const out = fader({ color: 'cyan', label: 'Speakers', onSet: (v) => send('set', { target: 'volume', value: v }, false) });
        const mic = fader({ color: 'pink', label: 'Microphone', onSet: (v) => send('set', { target: 'mic', value: v }, false) });
        const mute = chip('volume', 'Mute speakers', () => quiet(sendAction({ type: 'volume', cmd: 'mute' })));
        const micBtn = chip('mic', 'Mute microphone', () => quiet(sendAction({ type: 'mic', cmd: 'toggle' })));
        const r1 = document.createElement('div'); r1.className = 'fader-row'; r1.append(mute, out.el);
        const r2 = document.createElement('div'); r2.className = 'fader-row'; r2.append(micBtn, mic.el);
        body.append(r1, r2);
        return {
          update(st) {
            const v = st.volume;
            out.set(v ? v.volume : null); out.muted(v && v.muted); out.label(v ? shortName(v.name) : 'No output device');
            mute.classList.toggle('on', !!(v && v.muted)); mute.innerHTML = glyph(v && v.muted ? 'mute' : 'volume');
            const m = st.mic;
            mic.set(m ? m.volume : null); mic.muted(m && m.muted); mic.label(m ? shortName(m.name) : 'No microphone');
            micBtn.classList.toggle('on', !!(m && m.muted)); micBtn.innerHTML = glyph(m && m.muted ? 'mic-off' : 'mic');
          },
        };
      },
    },

    devices: {
      title: 'Output device', glyph: 'headphones',
      mount(body) {
        const list = document.createElement('div'); list.className = 'list'; body.append(list);
        let sig = '';
        return {
          update(st) {
            const devs = st.devices || [];
            const s = JSON.stringify(devs);
            if (s === sig) return; sig = s;
            list.innerHTML = devs.length ? '' : '<div class="empty">No active outputs</div>';
            for (const d of devs) {
              const r = document.createElement('button');
              r.className = 'row' + (d.default ? ' sel' : '');
              r.innerHTML = `<span class="radio"></span><span class="grow"><div class="t1">${esc(d.name.replace(/\s*\(.*\)\s*$/, '') || d.name)}</div><div class="t2">${esc((d.name.match(/\((.*)\)/) || [])[1] || '')}</div></span>`;
              r.onclick = () => { buzz(8); quiet(sendAction({ type: 'audio_device', cmd: 'set', id: d.id }).then(() => toast('Output: ' + d.name))); };
              list.append(r);
            }
          },
        };
      },
    },

    sonar: {
      title: 'SteelSeries Sonar', glyph: 'settings',
      mount(body) {
        const COLORS_BY = { master: 'amber', game: 'orange', chatRender: 'green', media: 'blue', aux: 'violet', chatCapture: 'pink' };
        body.innerHTML = `<div class="empty sonar-msg" hidden></div>
          <button class="row sonar-out" type="button"><span class="ico">${glyph('headphones')}</span>
            <span class="grow"><div class="t2">Plays through</div><div class="t1">…</div></span>${glyph('right')}</button>
          <div class="sonar-strips"></div>`;
        const msg = body.querySelector('.sonar-msg'), out = body.querySelector('.sonar-out');
        const stripsBox = body.querySelector('.sonar-strips');
        const strips = new Map();
        let so = null, sig = '';
        out.onclick = async () => {
          if (!so) return;
          const o = await sonarOutputPicker(so);
          if (o) quiet(sendAction({ type: 'sonar', cmd: 'output', device: o.id }).then((r) => toast(r.message)));
        };
        const build = (s) => {
          stripsBox.innerHTML = ''; strips.clear();
          const presets = s.presets || {};
          const chans = (s.channels && s.channels.length) ? s.channels
            : Object.keys(presets).map((id) => ({ id, name: { game: 'Game', chatRender: 'Chat', media: 'Media', aux: 'Aux', chatCapture: 'Mic' }[id] || id }));
          for (const ch of chans) {
            const strip = document.createElement('div');
            strip.className = 'strip';
            strip.innerHTML = `<div class="strip-head"><span class="ch">${esc(ch.name)}</span></div>`;
            const st = { strip };
            if (ch.id in presets) {
              const pill = document.createElement('button');
              pill.className = 'preset-pill'; pill.type = 'button';
              pill.onclick = async () => {
                const cur = (so.presets || {})[ch.id];
                const p = await sonarPresetPicker(ch.id, ch.name, cur && cur.id);
                if (p) quiet(sendAction({ type: 'sonar', cmd: 'preset', preset: p.id, device: ch.id }).then((r) => toast(r.message)));
              };
              strip.querySelector('.strip-head').append(pill);
              st.pill = pill;
            }
            if (typeof ch.volume === 'number') {
              const mic = ch.id === 'chatCapture';
              // the channel name is already in the strip heading, so the slider shows only the level
              const f = fader({ color: COLORS_BY[ch.id] || 'cyan', label: '', onSet: (v) => send('set', { target: 'sonar', key: ch.id, value: v }, false) });
              f.el.setAttribute('aria-label', ch.name + ' volume');
              const m = chip(mic ? 'mic' : 'volume', 'Mute ' + ch.name, () => quiet(sendAction({ type: 'sonar', cmd: 'volume', channel: ch.id, change: 'mute' })));
              const row = document.createElement('div'); row.className = 'fader-row'; row.append(m, f.el);
              strip.append(row);
              Object.assign(st, { f, m, mic });
            }
            stripsBox.append(strip); strips.set(ch.id, st);
          }
        };
        return {
          update(st) {
            so = st.sonar;
            const ok = !!(so && so.available);
            msg.hidden = ok; out.hidden = !ok; stripsBox.hidden = !ok;
            if (!ok) {
              msg.textContent = so ? `${so.reason}. Open SteelSeries GG and turn on Sonar.` : 'Looking for SteelSeries Sonar…';
              return;
            }
            const cur = (so.outputs || []).find((o) => o.id === so.output);
            out.querySelector('.t1').textContent = cur ? shortName(cur.name) : so.output === 'mixed' ? 'Different outputs per channel' : 'Not set';
            const newSig = (so.channels || []).map((c) => c.id).join() + '|' + Object.keys(so.presets || {}).join();
            if (newSig !== sig) { sig = newSig; build(so); }
            for (const [id, s] of strips) {
              const p = (so.presets || {})[id];
              if (s.pill) s.pill.innerHTML = `${esc(p ? p.name : 'No preset')} ${glyph('right')}`;
              const ch = (so.channels || []).find((c) => c.id === id);
              if (s.f && ch) {
                s.f.set(ch.volume); s.f.muted(ch.muted);
                s.m.classList.toggle('on', ch.muted);
                s.m.innerHTML = glyph(ch.muted ? (s.mic ? 'mic-off' : 'mute') : (s.mic ? 'mic' : 'volume'));
              }
            }
            if (so.mode && so.mode !== 'classic') {
              msg.hidden = false;
              msg.textContent = 'Sonar is in Streamer mode, so volume sliders are hidden. Presets and output still work.';
            }
          },
        };
      },
    },

    mixer: {
      title: 'App volume', glyph: 'volume',
      mount(body) {
        const list = document.createElement('div'); body.append(list);
        const rows = new Map();
        return {
          update(st) {
            const sessions = st.sessions || [];
            const seen = new Set();
            if (!sessions.length) list.innerHTML = '<div class="empty">No apps are playing sound</div>';
            else list.querySelector('.empty')?.remove();
            for (const s of sessions) {
              seen.add(s.key);
              let r = rows.get(s.key);
              if (!r) {
                const f = fader({ color: 'green', label: s.name, onSet: (v) => send('set', { target: 'session', key: s.key, value: v }, false) });
                const m = chip('volume', 'Mute ' + s.name, () => quiet(send('session_mute', { key: s.key })));
                const row = document.createElement('div'); row.className = 'fader-row';
                const ico = document.createElement('span'); ico.innerHTML = s.key === 'system' ? `<span class="app-ico ph">${glyph('volume')}</span>` : appIco(s.exe, s.name);
                row.append(ico.firstElementChild || ico, f.el, m);
                list.append(row);
                r = { row, f, m }; rows.set(s.key, r);
              }
              r.f.set(s.volume); r.f.muted(s.muted); r.f.label(s.name);
              r.m.classList.toggle('on', s.muted); r.m.innerHTML = glyph(s.muted ? 'mute' : 'volume');
            }
            for (const [k, r] of rows) if (!seen.has(k)) { r.row.remove(); rows.delete(k); }
          },
        };
      },
    },

    brightness: {
      title: 'Brightness', glyph: 'sun',
      mount(body) {
        const wrap = document.createElement('div'); body.append(wrap);
        const faders = new Map(); let sig = '';
        return {
          update(st) {
            const ds = (st.displays || []);
            const s = ds.map((d) => d.index + d.name).join('|');
            if (s !== sig) {
              sig = s; wrap.innerHTML = ''; faders.clear();
              if (!ds.length) wrap.innerHTML = '<div class="empty">No adjustable screens found</div>';
              for (const d of ds) {
                const f = fader({ color: 'amber', label: d.name, onSet: (v) => send('set', { target: 'brightness', key: d.index, value: v }, false) });
                const row = document.createElement('div'); row.className = 'fader-row';
                const ic = document.createElement('span'); ic.className = 'chip'; ic.innerHTML = glyph(d.builtin ? 'laptop' : 'monitor'); ic.setAttribute('aria-hidden', 'true');
                row.append(ic, f.el); wrap.append(row); faders.set(d.index, f);
              }
            }
            for (const d of ds) faders.get(d.index)?.set(d.brightness);
          },
        };
      },
    },

    powermode: {
      title: 'Power mode', glyph: 'zap',
      mount(body) {
        const modes = [['efficiency', 'Battery saver', 'leaf', 'green'], ['balanced', 'Balanced', 'scale', 'blue'], ['performance', 'Performance', 'zap', 'red']];
        const seg = document.createElement('div'); seg.className = 'seg';
        const note = document.createElement('div'); note.className = 'hint empty';
        for (const [id, label, g, c] of modes) {
          const b = document.createElement('button');
          b.dataset.mode = id; b.style.setProperty('--c', `var(--${c})`);
          b.innerHTML = glyph(g) + `<span>${label}</span>`;
          b.onclick = () => { buzz(8); quiet(sendAction({ type: 'power_mode', mode: id }).then(() => toast(label))); };
          seg.append(b);
        }
        body.append(seg, note);
        return {
          update(st) {
            seg.querySelectorAll('button').forEach((b) => b.classList.toggle('sel', b.dataset.mode === st.power_mode));
            note.textContent = st.power_mode ? '' : 'Windows does not report a power mode with the current power plan. Buttons may still work.';
          },
        };
      },
    },

    stats: {
      title: 'System', glyph: 'cpu',
      mount(body) {
        const grid = document.createElement('div'); grid.className = 'stats'; body.append(grid);
        return {
          update(st) {
            const s = st.stats;
            if (!s) { grid.innerHTML = '<div class="empty">Reading sensors…</div>'; return; }
            const cells = [];
            cells.push(['Processor', s.cpu + '%', meter(s.cpu), s.cpu_freq ? (s.cpu_freq / 1000).toFixed(1) + ' GHz' : '']);
            cells.push(['Memory', s.ram + '%', meter(s.ram), `${s.ram_used} of ${s.ram_total} GB`]);
            if (s.gpu) cells.push(['Graphics', s.gpu.util + '%', meter(s.gpu.util), `${s.gpu.name} at ${s.gpu.temp} °C`]);
            if (s.battery) {
              const b = s.battery;
              cells.push(['Battery', b.percent + '%', meter(b.percent, 'battery'), b.plugged ? 'Plugged in' : b.secs ? fmtDur(b.secs) + ' left' : 'On battery']);
            }
            if (s.disk) cells.push(['Drive C:', s.disk.percent + '%', meter(s.disk.percent), `${s.disk.free_gb} GB free`]);
            cells.push(['Network', '', '', `Down ${fmtBytes(s.net_down)}<br>Up ${fmtBytes(s.net_up)}`]);
            cells.push(['Uptime', fmtDur(s.uptime), '', '']);
            grid.innerHTML = cells.map(([k, v, m, sub]) => `<div class="stat"><div class="k"><span>${k}</span><b>${esc(v)}</b></div>${m}<div class="sub">${sub.includes('<br>') ? sub : esc(sub)}</div></div>`).join('');
          },
        };
      },
    },

    windows: {
      title: 'Open windows', glyph: 'windows',
      mount(body) {
        const grid = document.createElement('div'); grid.className = 'win-grid'; body.append(grid);
        let sig = '';
        const winCmd = (hwnd, cmd) => quiet(sendAction({ type: 'window', hwnd, cmd }));
        // Many apps (Discord, Steam, Spotify…) only hide in the system tray when their window
        // closes. The PC reports that, and we offer to quit the app completely.
        const closeWin = (w, btn) => {
          btn.disabled = true;
          sendAction({ type: 'window', hwnd: w.hwnd, cmd: 'close' }).then(async (r) => {
            const bg = r.background;
            if (!bg) return;
            const yes = await confirmSheet(`${bg.name} is still running`,
              'Closing its window only hid it in the system tray, so it keeps running in the background. Quit it completely? Anything unsaved in it will be lost.',
              `Quit ${bg.name}`);
            if (yes) quiet(sendAction({ type: 'quit_app', pid: bg.pid, exe: bg.exe, name: bg.name }).then((q) => toast(q.message)));
          }).catch((e) => toast(e.message, true)).finally(() => { btn.disabled = false; });
        };
        return {
          update(st) {
            const ws = st.windows || [];
            const s = JSON.stringify(ws.map((w) => [w.hwnd, w.title, w.active, w.minimized]));
            if (s === sig) return; sig = s;
            grid.innerHTML = ws.length ? '' : '<div class="empty">No open windows</div>';
            for (const w of ws) {
              const r = document.createElement('div');
              r.className = 'row' + (w.active ? ' active-win' : '');
              r.setAttribute('role', 'button'); r.tabIndex = 0;
              r.innerHTML = `${appIco(w.exe, w.app)}<span class="grow"><div class="t1">${esc(w.title)}</div><div class="t2">${esc(w.app)}${w.minimized ? ' (minimized)' : ''}</div></span>`;
              const min = chip('minimize', 'Minimize', () => winCmd(w.hwnd, 'minimize')); min.classList.add('mini');
              const cls = chip('x', 'Close', (b) => closeWin(w, b)); cls.classList.add('mini');
              r.append(min, cls);
              r.onclick = () => { buzz(8); winCmd(w.hwnd, 'focus'); };
              r.onkeydown = (e) => { if (e.key === 'Enter') winCmd(w.hwnd, 'focus'); };
              grid.append(r);
            }
          },
        };
      },
    },

    trackpad: {
      title: 'Trackpad', glyph: 'pointer',
      mount(body) {
        body.innerHTML = `<div class="pad">Slide one finger to move the pointer. Tap to click.<br>Tap with two fingers to right-click, or drag two fingers to scroll.</div>
          <div class="pad-btns"><button data-b="left">Left click</button><button data-b="right">Right click</button></div>
          <div class="sens"><span>Speed</span><input type="range" min="0.5" max="4" step="0.1"></div>`;
        const pad = body.querySelector('.pad');
        const sens = body.querySelector('input');
        sens.value = store.get('pd_sens') || '1.8';
        sens.oninput = () => store.set('pd_sens', sens.value);
        const pts = new Map();
        let maxPts = 0, t0 = 0, travel = 0, accX = 0, accY = 0, accS = 0, raf = 0;
        const flush = () => {
          raf = 0;
          const dx = Math.trunc(accX), dy = Math.trunc(accY), ds = Math.trunc(accS);
          accX -= dx; accY -= dy; accS -= ds;
          if (dx || dy) send('mouse', { dx, dy }, false).catch(() => {});
          if (ds) send('scroll', { dy: ds }, false).catch(() => {});
        };
        const queue = () => { if (!raf) raf = requestAnimationFrame(flush); };
        pad.addEventListener('pointerdown', (e) => {
          e.stopPropagation(); pad.setPointerCapture(e.pointerId);
          if (!pts.size) { maxPts = 0; t0 = Date.now(); travel = 0; }
          pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
          maxPts = Math.max(maxPts, pts.size); pad.classList.add('touching');
        });
        pad.addEventListener('pointermove', (e) => {
          const p = pts.get(e.pointerId); if (!p) return;
          const dx = e.clientX - p.x, dy = e.clientY - p.y;
          p.x = e.clientX; p.y = e.clientY; travel += Math.abs(dx) + Math.abs(dy);
          if (pts.size === 1) {
            const k = +sens.value * (1 + Math.min(2.5, Math.hypot(dx, dy) / 10));
            accX += dx * k; accY += dy * k;
          } else if (e.pointerId === pts.keys().next().value) {
            accS += dy * 4;
          }
          queue();
        });
        const end = (e) => {
          if (!pts.delete(e.pointerId)) return;
          if (pts.size) return;
          pad.classList.remove('touching');
          if (Date.now() - t0 < 260 && travel < 10) {
            send('click', { button: maxPts >= 2 ? 'right' : 'left' }, false).catch(() => {});
            buzz(6);
          }
        };
        pad.addEventListener('pointerup', end); pad.addEventListener('pointercancel', end);
        body.querySelectorAll('.pad-btns button').forEach((b) => {
          const btn = b.dataset.b;
          b.addEventListener('pointerdown', (e) => { e.stopPropagation(); b.setPointerCapture(e.pointerId); b.classList.add('held'); buzz(6); send('mouse_button', { button: btn, pressed: true }, false).catch(() => {}); });
          const rel = () => { if (!b.classList.contains('held')) return; b.classList.remove('held'); send('mouse_button', { button: btn, pressed: false }, false).catch(() => {}); };
          b.addEventListener('pointerup', rel); b.addEventListener('pointercancel', rel);
        });
        return { update() {}, destroy() { if (raf) cancelAnimationFrame(raf); } };
      },
    },

    typer: {
      title: 'Keyboard and clipboard', glyph: 'keyboard',
      mount(body) {
        body.classList.add('typer');
        body.innerHTML = `<textarea placeholder="Type or paste text here, then send it to the PC"></textarea>
          <div class="btn-row"><button class="btn primary" data-a="type">Type on PC</button><button class="btn" data-a="copy">Copy to PC clipboard</button>
          <button class="btn" data-a="get">Get PC clipboard</button><button class="btn" data-a="clear">Clear</button></div>
          <div class="keys-row"></div>`;
        const ta = body.querySelector('textarea');
        ta.addEventListener('pointerdown', (e) => e.stopPropagation());
        body.querySelector('[data-a=type]').onclick = () => ta.value && quiet(sendAction({ type: 'text', text: ta.value }).then(() => toast('Typed on PC')));
        body.querySelector('[data-a=copy]').onclick = () => quiet(sendAction({ type: 'clipboard', text: ta.value }).then((r) => toast(r.message)));
        body.querySelector('[data-a=get]').onclick = () => quiet(send('clipboard_get').then((r) => { ta.value = r.text || ''; toast(r.text ? 'Got the PC clipboard' : 'PC clipboard has no text'); }));
        body.querySelector('[data-a=clear]').onclick = () => { ta.value = ''; };
        const keys = [['Esc', 'esc'], ['Tab', 'tab'], ['←', 'left'], ['↑', 'up'], ['↓', 'down'], ['→', 'right'], ['⌫', 'backspace'], ['Enter', 'enter']];
        const row = body.querySelector('.keys-row');
        for (const [label, k] of keys) {
          const b = document.createElement('button'); b.textContent = label; b.setAttribute('aria-label', k);
          b.onclick = () => { buzz(6); quiet(sendAction({ type: 'hotkey', keys: k })); };
          row.append(b);
        }
        return { update() {} };
      },
    },
  };

  function mountWidget(item, idx) {
    const def = WIDGETS[item.widget];
    const sec = document.createElement('section');
    sec.className = 'module' + (item.span === 'half' ? ' half' : '');
    if (!def) {
      sec.innerHTML = `<div class="empty">Unknown panel “${esc(item.widget)}”</div>`;
      deck.append(sec); return;
    }
    sec.innerHTML = `<span class="edit-badge">${glyph('pencil')}</span><h2>${glyph(def.glyph)}<span>${esc(item.title || def.title)}</span></h2>`;
    const body = document.createElement('div');
    sec.append(body);
    sec.dataset.idx = idx;
    sec.addEventListener('click', (e) => {
      if (!S.editing) return;
      e.stopPropagation();
      if (!Drag.recent()) window.Editor.editItem(S.page, idx);
    }, true);
    deck.append(sec);
    const inst = def.mount(body, item) || {};
    S.widgets.push({ update: inst.update || (() => {}), destroy: inst.destroy });
  }

  // ------------------------------------------------------------------ edit mode & drag to reorder
  function addTile() {
    const add = document.createElement('button');
    add.className = 'key add'; add.innerHTML = glyph('plus'); add.setAttribute('aria-label', 'Add a button or panel');
    add.onclick = () => window.Editor.addItem(S.page);
    return add;
  }

  // Switch wiggle mode on/off without rebuilding the page, so a long-press can become a drag.
  function setEditing(on) {
    if (S.editing === on) return;
    const page = S.config && S.config.pages[S.page];
    S.editing = on;
    if (!page || !page.items.length) { renderPage(); return; }
    deck.classList.toggle('editing', on);
    const t = $('#editToggle');
    t.classList.toggle('active', on);
    t.innerHTML = glyph(on ? 'check' : 'pencil');
    t.setAttribute('aria-label', on ? 'Done editing' : 'Edit buttons');
    const add = deck.querySelector('.key.add');
    if (add) add.remove();
    if (on) deck.append(addTile());
    renderBanks();
  }

  const Drag = (() => {
    let d = null;        // the drag in progress
    let pending = null;  // finger down in edit mode, not a drag yet
    let endedAt = 0;
    const slots = () => [...deck.children].filter((c) => c.dataset.idx != null);

    // Animate the other icons sliding to their new places (FLIP). Uses `translate` so it
    // doesn't fight the wiggle animation, which uses `transform`.
    function flip(mutate) {
      const kids = slots().filter((k) => k !== d.el);
      const before = kids.map((k) => k.getBoundingClientRect());
      mutate();
      kids.forEach((k, i) => {
        const b = k.getBoundingClientRect();
        const dx = before[i].left - b.left, dy = before[i].top - b.top;
        if (!dx && !dy) return;
        k.style.transition = 'none';
        k.style.translate = `${dx}px ${dy}px`;
        requestAnimationFrame(() => requestAnimationFrame(() => {
          k.style.transition = 'translate .2s ease';
          k.style.translate = '0px 0px';
        }));
        setTimeout(() => { k.style.transition = ''; k.style.translate = ''; }, 280);
      });
    }

    function place() { d.ghost.style.transform = `translate3d(${d.x - d.ox}px, ${d.y - d.oy}px, 0)`; }

    function pickUp(el, x, y) {
      if (d || !el.isConnected) return;
      const r = el.getBoundingClientRect();
      const ghost = el.cloneNode(true);
      ghost.classList.remove('pressed', 'ok', 'err');
      ghost.classList.add('drag-ghost');
      ghost.style.width = r.width + 'px';
      ghost.style.height = r.height + 'px';
      document.body.append(ghost);
      d = { el, ghost, ox: x - r.left, oy: y - r.top, x, y, lastMove: 0, bank: null, raf: 0 };
      el.classList.add('drag-src');
      place();
      buzz(20);
      d.raf = requestAnimationFrame(autoScroll);
    }

    function autoScroll() {
      if (!d) return;
      const banksTop = $('#banks').getBoundingClientRect().top;
      if (d.y < 70) window.scrollBy(0, -10);
      else if (d.y > banksTop - 60 && d.y < banksTop) window.scrollBy(0, 10);
      d.raf = requestAnimationFrame(autoScroll);
    }

    // Which icon/panel is under the finger, by layout position (ignores icons mid-slide).
    function slotAt(x, y) {
      const px = x + window.scrollX, py = y + window.scrollY;
      for (const c of deck.children) {
        if (c === d.el || !c.matches('.key, .module')) continue;
        const l = c.offsetLeft, t = c.offsetTop, w = c.offsetWidth, h = c.offsetHeight;
        if (px >= l && px < l + w && py >= t && py < t + h) return { el: c, l, t, w, h, px, py };
      }
      return null;
    }

    function move(x, y, force = false) {
      d.x = x; d.y = y; place();
      const under = document.elementFromPoint(x, y);
      // over a page tab: drop moves the item to that page
      const bank = under && under.closest('#banks .bank:not(.add)');
      const bankIdx = bank ? [...$('#banks').children].indexOf(bank) : -1;
      d.bank = bankIdx >= 0 && bankIdx !== S.page ? bankIdx : null;
      document.querySelectorAll('#banks .bank').forEach((b, i) => b.classList.toggle('drop', i === d.bank));
      if (bank) return;
      if (!force && Date.now() - d.lastMove < 120) return;
      const hit = slotAt(x, y);
      if (!hit) return;
      const target = hit.el;
      const wide = hit.w > deck.clientWidth * 0.6;
      const after = !target.classList.contains('add') &&
        (wide ? hit.py > hit.t + hit.h / 2 : hit.px > hit.l + hit.w / 2);
      const next = after ? target.nextSibling : target;
      if (next === d.el || next === d.el.nextSibling) return;
      flip(() => deck.insertBefore(d.el, next));
      d.lastMove = Date.now();
    }

    async function drop() {
      move(d.x, d.y, true);  // settle exactly where the finger let go
      const { el, ghost, bank } = d;
      cancelAnimationFrame(d.raf);
      d = null;
      endedAt = Date.now();
      document.querySelectorAll('#banks .bank.drop').forEach((b) => b.classList.remove('drop'));
      const r = el.getBoundingClientRect();
      ghost.style.transition = 'transform .16s ease, scale .16s ease, opacity .16s ease';
      ghost.style.transform = `translate3d(${r.left}px, ${r.top}px, 0)`;
      ghost.style.scale = '1';
      if (bank !== null) ghost.style.opacity = '0';
      setTimeout(() => { ghost.remove(); el.classList.remove('drag-src'); }, 170);

      const page = S.config.pages[S.page];
      const cfg = JSON.parse(JSON.stringify(S.config));
      if (bank !== null) {
        const [it] = cfg.pages[S.page].items.splice(+el.dataset.idx, 1);
        cfg.pages[bank].items.push(it);
      } else {
        const order = slots().map((c) => +c.dataset.idx);
        if (order.every((v, i) => v === i)) return;
        cfg.pages[S.page].items = order.map((i) => page.items[i]);
      }
      try {
        await send('save_config', { config: cfg });
        if (bank !== null) toast('Moved to ' + cfg.pages[bank].name);
      } catch (e) {
        toast(e.message, true);
        renderPage();
      }
    }

    deck.addEventListener('pointerdown', (e) => {
      if (!S.editing || d || e.button > 0) return;
      const el = e.target.closest('#deck > .key, #deck > .module');
      if (!el || el.dataset.idx == null) return;
      const touch = e.pointerType !== 'mouse';
      pending = { el, x: e.clientX, y: e.clientY, touch };
      // touch: hold briefly to pick up (moving sooner scrolls the page); mouse: hold or just drag
      pending.timer = setTimeout(() => {
        if (!pending) return;
        const p = pending; pending = null;
        pickUp(p.el, p.x, p.y);
      }, touch ? 200 : 400);
    });
    window.addEventListener('pointermove', (e) => {
      if (d) { move(e.clientX, e.clientY); return; }
      if (!pending || Math.hypot(e.clientX - pending.x, e.clientY - pending.y) < 8) return;
      clearTimeout(pending.timer);
      const p = pending; pending = null;
      if (!p.touch) { pickUp(p.el, p.x, p.y); move(e.clientX, e.clientY); }
    });
    const up = () => {
      if (pending) { clearTimeout(pending.timer); pending = null; }
      if (d) drop();
    };
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    // While dragging, the finger must not scroll the page.
    document.addEventListener('touchmove', (e) => { if (d) e.preventDefault(); }, { passive: false });

    return {
      pickUp,
      active: () => !!d,
      recent: () => !!d || Date.now() - endedAt < 450,
    };
  })();

  // ------------------------------------------------------------------ page swipe
  let sw = null;
  deck.addEventListener('pointerdown', (e) => { if (e.isPrimary && !S.editing) sw = { x: e.clientX, y: e.clientY, t: Date.now() }; });
  deck.addEventListener('pointerup', (e) => {
    if (!sw) return;
    if (Drag.recent()) { sw = null; return; }
    const dx = e.clientX - sw.x, dy = e.clientY - sw.y, dt = Date.now() - sw.t;
    sw = null;
    if (Math.abs(dx) > 70 && Math.abs(dy) < 50 && dt < 700) goPage(S.page + (dx < 0 ? 1 : -1), dx < 0 ? 'l' : 'r');
  });
  deck.addEventListener('pointercancel', () => { sw = null; });

  $('#editToggle').addEventListener('click', () => {
    if (!S.config) return;
    setEditing(!S.editing);
    if (S.editing) toast('Drag to move. Tap to change. Drop on a page tab to move it there.');
  });

  // ------------------------------------------------------------------ boot
  window.Deck = {
    S, send, sendAction, toast, openSheet, closeSheet, confirmSheet, renderPage, goPage,
    makeKey, iconHTML, COLORS, WIDGETS, defaultGlyph, esc, buzz, sonarPresetPicker,
    save: () => send('save_config', { config: S.config }),
  };
  layout();
  S.token = readToken();
  connect();
})();
