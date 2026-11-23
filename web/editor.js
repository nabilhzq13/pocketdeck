/* PocketDeck editor: add, change, move and delete buttons, panels and pages from the phone. */
(() => {
  'use strict';
  const D = window.Deck;
  const { esc } = D;
  const clone = (o) => JSON.parse(JSON.stringify(o));
  let appCache = null;

  const TYPES = [
    ['app', 'Open an app'], ['url', 'Open a website'], ['open', 'Open a file, folder or settings page'],
    ['hotkey', 'Press a keyboard shortcut'], ['text', 'Type text'], ['media', 'Media control'],
    ['volume', 'Volume'], ['mic', 'Microphone'], ['audio_device', 'Switch audio output'],
    ['brightness', 'Brightness'], ['display', 'Display mode'], ['theme', 'Dark or light mode'],
    ['power_mode', 'Power mode'], ['power', 'Lock, sleep or shut down'], ['command', 'Run a command'],
    ['sonar', 'SteelSeries Sonar'], ['page', 'Go to another page'], ['macro', 'Several steps (macro)'],
  ];
  const level = (cmds) => [
    { key: 'step', kind: 'number', label: 'Step (%)', def: cmds === 'b' ? 10 : 5, showIf: (a) => a.cmd === 'up' || a.cmd === 'down' },
    { key: 'value', kind: 'number', label: 'Level (%)', def: 50, showIf: (a) => a.cmd === 'set' },
  ];
  // Where a launched window goes. Apps ask by default; websites and files stay where Windows puts them.
  const screenFields = (first) => [
    { key: 'screen', kind: 'select', label: 'Open on screen', options: () => {
      const opts = [['ask', 'Ask me every time'], ['none', 'Where Windows puts it']];
      if (first === 'none') opts.reverse();
      opts.push(['laptop', 'Laptop screen'], ['primary', 'Main screen']);
      for (const s of D.S.status.screens || []) if (!s.internal) opts.push([s.name, s.name]);
      return opts;
    }, hint: 'Asking is skipped when only one screen is connected.' },
    { key: 'maximize', kind: 'check', label: 'Fill the screen (maximize)', showIf: (a) => a.screen && a.screen !== 'none' },
  ];
  const FIELDS = {
    app: [{ key: 'name', kind: 'app', label: 'App' }, ...screenFields('ask')],
    url: [{ key: 'url', kind: 'text', label: 'Web address', ph: 'youtube.com' }, ...screenFields('none')],
    open: [{ key: 'target', kind: 'text', label: 'Path or link', ph: 'C:\\Users\\me\\Downloads', hint: 'Works with files, folders, programs and settings pages such as ms-settings:display or ms-settings:bluetooth.' }, ...screenFields('none')],
    hotkey: [{ key: 'keys', kind: 'keys', label: 'Keys', ph: 'ctrl+shift+s', hint: 'Join keys with +. For a sequence, separate chords with spaces, like “ctrl+k ctrl+c”.' }],
    text: [{ key: 'text', kind: 'textarea', label: 'Text to type' }, { key: 'enter', kind: 'check', label: 'Press Enter afterwards' }],
    media: [{ key: 'cmd', kind: 'select', label: 'Control', options: [['playpause', 'Play or pause'], ['next', 'Next track'], ['prev', 'Previous track'], ['stop', 'Stop']] }],
    volume: [{ key: 'cmd', kind: 'select', label: 'Change', options: [['up', 'Turn up'], ['down', 'Turn down'], ['mute', 'Mute on or off'], ['set', 'Set to a level']] }, ...level('v')],
    mic: [{ key: 'cmd', kind: 'select', label: 'Change', options: [['toggle', 'Mute on or off'], ['mute', 'Mute'], ['unmute', 'Unmute']] }],
    audio_device: [{ key: 'cmd', kind: 'select', label: 'Change', options: [['next', 'Cycle to the next output'], ['set', 'Switch to one output']] },
      { key: 'id', kind: 'device', label: 'Output', showIf: (a) => a.cmd === 'set' }],
    brightness: [{ key: 'cmd', kind: 'select', label: 'Change', options: [['up', 'Brighter'], ['down', 'Dimmer'], ['set', 'Set to a level']] }, ...level('b'),
      { key: 'display', kind: 'select', label: 'Screen', options: () => [['all', 'All screens'], ...(D.S.status.displays || []).map((d) => [String(d.index), d.name])] }],
    display: [{ key: 'mode', kind: 'select', label: 'Mode', options: [['internal', 'Laptop screen only'], ['clone', 'Duplicate'], ['extend', 'Extend'], ['external', 'Second screen only']] }],
    theme: [{ key: 'mode', kind: 'select', label: 'Mode', options: [['toggle', 'Switch between dark and light'], ['dark', 'Dark'], ['light', 'Light']] }],
    power_mode: [{ key: 'mode', kind: 'select', label: 'Mode', options: [['efficiency', 'Battery saver'], ['balanced', 'Balanced'], ['performance', 'Performance']] }],
    power: [{ key: 'cmd', kind: 'select', label: 'Do', options: [['lock', 'Lock'], ['sleep', 'Sleep'], ['hibernate', 'Hibernate'], ['screen_off', 'Turn the screen off'], ['restart', 'Restart'], ['shutdown', 'Shut down'], ['signout', 'Sign out'], ['cancel', 'Cancel a pending shutdown']] }],
    command: [{ key: 'cmd', kind: 'textarea', label: 'Command', hint: 'Runs on the PC with your Windows account. Only add commands you trust.' },
      { key: 'shell', kind: 'select', label: 'Run with', options: [['cmd', 'Command Prompt'], ['powershell', 'PowerShell']] },
      { key: 'wait', kind: 'check', label: 'Wait and show the output' }],
    page: [{ key: 'page', kind: 'select', label: 'Page', options: () => D.S.config.pages.map((p) => [p.name, p.name]) }],
    sonar: [
      { key: 'cmd', kind: 'select', label: 'Change', options: [['preset', 'Switch to a preset'], ['volume', 'Channel volume or mute'], ['output', 'Switch speaker or headset']] },
      { key: 'device', kind: 'select', label: 'Channel', showIf: (a) => a.cmd === 'preset', options: [['game', 'Game'], ['media', 'Media'], ['chatRender', 'Chat'], ['aux', 'Aux'], ['chatCapture', 'Mic']] },
      { key: 'preset', kind: 'sonarPreset', label: 'Preset', showIf: (a) => a.cmd === 'preset' },
      { key: 'channel', kind: 'select', label: 'Channel', showIf: (a) => a.cmd === 'volume', options: [['master', 'Master'], ['game', 'Game'], ['chatRender', 'Chat'], ['media', 'Media'], ['aux', 'Aux'], ['chatCapture', 'Mic']] },
      { key: 'change', kind: 'select', label: 'Change', showIf: (a) => a.cmd === 'volume', options: [['up', 'Turn up'], ['down', 'Turn down'], ['mute', 'Mute on or off'], ['set', 'Set to a level']] },
      { key: 'step', kind: 'number', label: 'Step (%)', def: 10, showIf: (a) => a.cmd === 'volume' && (a.change === 'up' || a.change === 'down') },
      { key: 'value', kind: 'number', label: 'Level (%)', def: 50, showIf: (a) => a.cmd === 'volume' && a.change === 'set' },
      { key: 'output', kind: 'select', label: 'Speaker or headset', showIf: (a) => a.cmd === 'output', options: () => ((D.S.status.sonar || {}).outputs || []).map((o) => [o.name, o.name]),
        hint: 'Sends Sonar’s Game, Chat, Media and Aux channels to this output.' },
    ],
    macro: [{ key: 'steps', kind: 'json', label: 'Steps', hint: 'A list of actions that run in order. Add {"type": "delay", "ms": 500} to wait between steps. Any action type works, for example {"type": "app", "name": "Spotify"}.' }],
  };
  const KEY_CHIPS = ['ctrl', 'shift', 'alt', 'win', 'enter', 'esc', 'tab', 'space', 'up', 'down', 'left', 'right', 'f5', 'printscreen'];
  const WIDGET_LIST = [
    ['nowplaying', 'Now playing'], ['volume', 'Volume'], ['devices', 'Output device'], ['mixer', 'App volume'],
    ['brightness', 'Brightness'], ['powermode', 'Power mode'], ['stats', 'System'], ['windows', 'Open windows'],
    ['trackpad', 'Trackpad'], ['typer', 'Keyboard and clipboard'], ['sonar', 'SteelSeries Sonar'],
  ];

  async function commit(mutate, msg) {
    const cfg = clone(D.S.config);
    const ret = mutate(cfg);
    try {
      await D.send('save_config', { config: cfg });
      D.closeSheet();
      if (msg) D.toast(msg);
      return { ok: true, ret };
    } catch (e) {
      D.toast(e.message, true);
      return { ok: false };
    }
  }

  function h(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }

  function pageSelect(current) {
    const sel = document.createElement('select');
    D.S.config.pages.forEach((p, i) => sel.add(new Option(p.name, String(i))));
    sel.value = String(current);
    return sel;
  }

  function moveButtons(container, p, i, len) {
    const up = h(`<button class="btn" ${i === 0 ? 'disabled' : ''}>Move earlier</button>`);
    const down = h(`<button class="btn" ${i >= len - 1 ? 'disabled' : ''}>Move later</button>`);
    const swap = (j) => commit((cfg) => { const it = cfg.pages[p].items; [it[i], it[j]] = [it[j], it[i]]; });
    up.onclick = () => swap(i - 1);
    down.onclick = () => swap(i + 1);
    container.append(up, down);
  }

  function deleteButton(container, label, onDelete) {
    const del = h(`<button class="btn danger">${esc(label)}</button>`);
    let armed = false;
    del.onclick = () => {
      if (!armed) { armed = true; del.textContent = 'Tap again to delete'; setTimeout(() => { armed = false; del.textContent = label; }, 2500); return; }
      onDelete();
    };
    container.append(del);
  }

  // ------------------------------------------------------------------ button sheet
  function defaultsFor(type) {
    const a = { type };
    for (const f of FIELDS[type] || []) {
      if (f.kind === 'select') { const o = typeof f.options === 'function' ? f.options() : f.options; if (o[0]) a[f.key] = o[0][0]; }
      if (f.kind === 'number') a[f.key] = f.def;
      if (f.kind === 'json') a[f.key] = [];
    }
    if (type === 'command') a.shell = 'cmd';
    return a;
  }

  function buttonSheet(state) {
    const { item, p, i, isNew } = state;
    D.openSheet((s) => {
      s.innerHTML = `<h3>${isNew ? 'New button' : 'Edit button'}</h3>
        <div class="preview"><div class="pv"></div><div style="flex:1;min-width:0"><label for="lbl" style="margin-top:0">Label</label><input id="lbl" maxlength="40"></div></div>
        <label for="typ">What it does</label><select id="typ"></select>
        <div class="fields"></div>
        <label>Icon</label><div class="tabs icon-tabs"></div><div class="icon-pane"></div>
        <label>Colour</label><div class="swatches"></div>
        <label for="pg">Page</label><div class="pgsel"></div>
        <div class="actions"><span class="left"></span><span class="spacer"></span><button class="btn" data-cancel>Cancel</button><button class="btn primary" data-save>Save</button></div>`;
      const pv = s.querySelector('.pv');
      const preview = () => { pv.innerHTML = ''; pv.append(D.makeKey(item, -1, true)); };
      const lbl = s.querySelector('#lbl');
      lbl.value = item.label || '';
      lbl.oninput = () => { item.label = lbl.value; preview(); };

      const typ = s.querySelector('#typ');
      for (const [v, l] of TYPES) typ.add(new Option(l, v));
      typ.value = item.action.type;
      const fields = s.querySelector('.fields');
      const renderFields = () => { buildFields(fields, item, state, () => { renderFields(); preview(); }); preview(); };
      typ.onchange = () => { item.action = defaultsFor(typ.value); renderFields(); };
      renderFields();

      // icon
      const tabs = s.querySelector('.icon-tabs'), pane = s.querySelector('.icon-pane');
      const mode = () => { const ic = item.icon || 'auto'; return ic === 'auto' ? 'auto' : ic.startsWith('i:') ? 'glyph' : /^(https?:|data:)/.test(ic) ? 'image' : 'emoji'; };
      const renderIcon = (m) => {
        tabs.innerHTML = '';
        for (const [id, l] of [['auto', 'Automatic'], ['glyph', 'Symbol'], ['emoji', 'Emoji'], ['image', 'Image link']]) {
          const b = h(`<button class="${m === id ? 'sel' : ''}">${l}</button>`);
          b.onclick = () => {
            if (id === 'auto') item.icon = 'auto';
            if (id === 'glyph' && !String(item.icon).startsWith('i:')) item.icon = 'i:' + D.defaultGlyph(item.action);
            renderIcon(id); preview();
          };
          tabs.append(b);
        }
        pane.innerHTML = '';
        if (m === 'auto') pane.append(h('<p class="hint">Uses the app’s own icon or the website’s icon. Other actions get a matching symbol.</p>'));
        if (m === 'glyph') {
          const grid = h('<div class="glyph-grid"></div>');
          for (const name of Object.keys(window.GLYPHS)) {
            const b = h(`<button aria-label="${name}" class="${item.icon === 'i:' + name ? 'sel' : ''}">${glyph(name)}</button>`);
            b.onclick = () => { item.icon = 'i:' + name; grid.querySelectorAll('.sel').forEach((x) => x.classList.remove('sel')); b.classList.add('sel'); preview(); };
            grid.append(b);
          }
          pane.append(grid);
        }
        if (m === 'emoji' || m === 'image') {
          const inp = h(`<input placeholder="${m === 'emoji' ? 'Type or paste one emoji' : 'https://…/icon.png'}" style="margin-top:8px">`);
          inp.value = mode() === m ? item.icon : '';
          inp.oninput = () => { item.icon = inp.value.trim() || 'auto'; preview(); };
          pane.append(inp);
        }
      };
      renderIcon(mode());

      // colour
      const sw = s.querySelector('.swatches');
      for (const c of D.COLORS) {
        const b = h(`<button aria-label="${c}" class="${item.color === c ? 'sel' : ''}" style="--c:var(--${c})"></button>`);
        b.onclick = () => { item.color = c; sw.querySelectorAll('.sel').forEach((x) => x.classList.remove('sel')); b.classList.add('sel'); preview(); };
        sw.append(b);
      }

      const pg = pageSelect(p); pg.id = 'pg';
      s.querySelector('.pgsel').append(pg);

      const left = s.querySelector('.actions .left');
      if (!isNew) {
        deleteButton(left, 'Delete', () => commit((cfg) => { cfg.pages[p].items.splice(i, 1); }, 'Button deleted'));
        moveButtons(left, p, i, D.S.config.pages[p].items.length);
      }
      s.querySelector('[data-cancel]').onclick = D.closeSheet;
      s.querySelector('[data-save]').onclick = () => {
        const err = validate(item);
        if (err) { D.toast(err, true); return; }
        const target = +pg.value;
        commit((cfg) => {
          const clean = clone(item);
          if (isNew) cfg.pages[target].items.push(clean);
          else if (target === p) cfg.pages[p].items[i] = clean;
          else { cfg.pages[p].items.splice(i, 1); cfg.pages[target].items.push(clean); }
        }, isNew ? 'Button added' : 'Saved');
      };
      preview();
    });
  }

  function validate(item) {
    const a = item.action;
    if (!item.label || !item.label.trim()) return 'Give the button a label';
    if (a.type === 'app' && !a.name && !a.appid) return 'Choose an app';
    if (a.type === 'url' && !a.url) return 'Enter a web address';
    if (a.type === 'open' && !a.target) return 'Enter a path or link';
    if (a.type === 'hotkey' && !a.keys) return 'Enter the keys to press';
    if (a.type === 'command' && !a.cmd) return 'Enter a command';
    if (a.type === 'audio_device' && a.cmd === 'set' && !a.id) return 'Choose an output';
    if (a.type === 'macro' && (!Array.isArray(a.steps) || !a.steps.length)) return 'Add at least one step';
    if (a.type === 'sonar' && a.cmd === 'preset' && !a.preset) return 'Choose a Sonar preset';
    if (a.type === 'sonar' && a.cmd === 'output' && !a.output) return 'Choose a speaker or headset';
    if (a._invalid) return 'The steps are not valid JSON';
    return null;
  }

  function buildFields(box, item, state, refresh) {
    const a = item.action;
    box.innerHTML = '';
    for (const f of FIELDS[a.type] || []) {
      if (f.showIf && !f.showIf(a)) continue;
      const wrap = document.createElement('div');
      if (f.label && f.kind !== 'check') wrap.append(h(`<label>${esc(f.label)}</label>`));
      let el;
      if (f.kind === 'select') {
        el = document.createElement('select');
        const opts = typeof f.options === 'function' ? f.options() : f.options;
        for (const [v, l] of opts) el.add(new Option(l, v));
        if (a[f.key] == null && opts[0]) a[f.key] = opts[0][0];
        if (a[f.key] != null && !opts.some(([v]) => String(v) === String(a[f.key]))) {
          el.add(new Option(`${a[f.key]} (not connected)`, a[f.key]));  // e.g. a monitor that is unplugged
        }
        el.value = String(a[f.key]);
        el.onchange = () => { a[f.key] = el.value; refresh(); };
      } else if (f.kind === 'text' || f.kind === 'keys') {
        el = h(`<input autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="${esc(f.ph || '')}">`);
        el.value = a[f.key] || '';
        el.oninput = () => { a[f.key] = el.value.trim(); };
      } else if (f.kind === 'number') {
        el = h('<input type="number" min="0" max="100" inputmode="numeric">');
        if (a[f.key] == null) a[f.key] = f.def;
        el.value = a[f.key];
        el.oninput = () => { a[f.key] = Math.max(0, Math.min(100, +el.value || 0)); };
      } else if (f.kind === 'textarea') {
        el = document.createElement('textarea');
        el.value = a[f.key] || '';
        el.oninput = () => { a[f.key] = el.value; };
      } else if (f.kind === 'check') {
        el = h(`<label class="check"><input type="checkbox"> ${esc(f.label)}</label>`);
        const cb = el.querySelector('input');
        cb.checked = !!a[f.key];
        cb.onchange = () => { a[f.key] = cb.checked; };
      } else if (f.kind === 'json') {
        el = document.createElement('textarea');
        el.style.minHeight = '180px';
        el.value = JSON.stringify(a.steps || [], null, 2);
        el.oninput = () => { try { a.steps = JSON.parse(el.value); delete a._invalid; el.style.boxShadow = ''; } catch { a._invalid = true; el.style.boxShadow = 'inset 0 0 0 2px var(--bad)'; } };
      } else if (f.kind === 'device') {
        el = document.createElement('select');
        const devs = D.S.status.devices || [];
        el.add(new Option('Choose an output', ''));
        for (const d of devs) el.add(new Option(d.name, d.id));
        if (a.id && !devs.some((d) => d.id === a.id)) el.add(new Option((a.name || 'Saved output') + ' (not connected)', a.id));
        el.value = a.id || '';
        el.onchange = () => { a.id = el.value; a.name = (devs.find((d) => d.id === el.value) || {}).name || a.name; };
      } else if (f.kind === 'sonarPreset') {
        el = h(`<button class="row" type="button"><span class="ico">${glyph('settings')}</span><span class="grow"><div class="t1"></div><div class="t2">Tap to choose</div></span>${glyph('right')}</button>`);
        el.querySelector('.t1').textContent = a.preset || 'No preset chosen';
        el.onclick = () => {
          const names = { game: 'Game', media: 'Media', chatRender: 'Chat', aux: 'Aux', chatCapture: 'Mic' };
          D.sonarPresetPicker(a.device || 'game', names[a.device] || 'Game', null).then((p) => {
            if (p) {
              if (!state.item.label || state.item.label === a.preset) state.item.label = p.name;
              a.preset = p.name;
            }
            buttonSheet(state);
          });
        };
      } else if (f.kind === 'app') {
        el = h(`<button class="row" type="button"><span class="ico"></span><span class="grow"><div class="t1"></div><div class="t2">Tap to choose</div></span>${glyph('right')}</button>`);
        el.querySelector('.t1').textContent = a.name || 'No app chosen';
        el.querySelector('.ico').innerHTML = (a.name || a.appid) ? D.iconHTML({ icon: 'auto', label: a.name, action: a }) : glyph('grid');
        el.onclick = () => appPicker(state);
      }
      wrap.append(el);
      if (f.kind === 'keys') {
        const chips = h('<div class="tabs" style="margin-top:8px"></div>');
        for (const k of KEY_CHIPS) {
          const b = h(`<button type="button">${k}</button>`);
          b.onclick = () => { const v = el.value.trim(); el.value = v && !v.endsWith('+') && !v.endsWith(' ') ? v + '+' + k : v + k; a.keys = el.value; };
          chips.append(b);
        }
        wrap.append(chips);
      }
      if (f.hint) wrap.append(h(`<p class="hint">${esc(f.hint)}</p>`));
      box.append(wrap);
    }
  }

  async function appPicker(state) {
    D.openSheet((s) => {
      s.innerHTML = `<h3>Choose an app</h3><input id="q" placeholder="Search apps" autocapitalize="off" autocorrect="off">
        <div class="app-list"><div class="empty">Loading apps from the PC…</div></div>
        <div class="actions"><button class="btn" data-refresh>Reload list</button><span class="spacer"></span><button class="btn" data-back>Back</button></div>`;
      const list = s.querySelector('.app-list'), q = s.querySelector('#q');
      const draw = () => {
        const term = q.value.trim().toLowerCase();
        const apps = (appCache || []).filter((x) => !term || x.name.toLowerCase().includes(term)).slice(0, 120);
        list.innerHTML = apps.length ? '' : '<div class="empty">No matching apps</div>';
        for (const app of apps) {
          const r = h(`<button class="row"><span class="ico"></span><span class="grow"><div class="t1"></div></span></button>`);
          r.querySelector('.t1').textContent = app.name;
          r.firstElementChild.innerHTML = D.iconHTML({ icon: 'auto', label: app.name, action: { type: 'app', appid: app.appid } });
          r.firstElementChild.querySelector('img')?.setAttribute('loading', 'lazy');
          r.onclick = () => {
            const old = state.item.action.name;
            state.item.action = { ...state.item.action, type: 'app', name: app.name, appid: app.appid };
            if (!state.item.label || state.item.label === old) state.item.label = app.name;
            buttonSheet(state);
          };
          list.append(r);
        }
      };
      const load = (refresh) => D.send('apps', { refresh }).then((r) => { appCache = r.apps; draw(); }).catch((e) => { list.innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
      q.oninput = draw;
      s.querySelector('[data-back]').onclick = () => buttonSheet(state);
      s.querySelector('[data-refresh]').onclick = () => { list.innerHTML = '<div class="empty">Loading…</div>'; load(true); };
      if (appCache) draw(); else load(false);
    });
  }

  // ------------------------------------------------------------------ widget sheet
  function widgetSheet(p, i) {
    const item = clone(D.S.config.pages[p].items[i]);
    const def = D.WIDGETS[item.widget] || { title: item.widget };
    D.openSheet((s) => {
      s.innerHTML = `<h3>${esc(def.title)} panel</h3>
        <label for="wt">Title</label><input id="wt" placeholder="${esc(def.title)}">
        <label for="ws">Width</label><select id="ws"><option value="full">Full width</option><option value="half">Half width on wide screens</option></select>
        <label for="pg">Page</label><div class="pgsel"></div>
        <div class="actions"><span class="left"></span><span class="spacer"></span><button class="btn" data-cancel>Cancel</button><button class="btn primary" data-save>Save</button></div>`;
      const wt = s.querySelector('#wt'), ws = s.querySelector('#ws');
      wt.value = item.title || ''; ws.value = item.span || 'full';
      const pg = pageSelect(p); pg.id = 'pg'; s.querySelector('.pgsel').append(pg);
      const left = s.querySelector('.left');
      deleteButton(left, 'Remove panel', () => commit((cfg) => { cfg.pages[p].items.splice(i, 1); }, 'Panel removed'));
      moveButtons(left, p, i, D.S.config.pages[p].items.length);
      s.querySelector('[data-cancel]').onclick = D.closeSheet;
      s.querySelector('[data-save]').onclick = () => {
        item.title = wt.value.trim() || undefined; item.span = ws.value;
        const target = +pg.value;
        commit((cfg) => {
          if (target === p) cfg.pages[p].items[i] = item;
          else { cfg.pages[p].items.splice(i, 1); cfg.pages[target].items.push(item); }
        }, 'Saved');
      };
    });
  }

  // ------------------------------------------------------------------ add item
  function addItem(p) {
    D.openSheet((s) => {
      s.innerHTML = '<h3>Add to this page</h3><div class="kind-grid"></div><div class="actions"><span class="spacer"></span><button class="btn" data-cancel>Cancel</button></div>';
      const grid = s.querySelector('.kind-grid');
      const btn = h(`<button class="row">${glyph('plus')}<span class="grow"><div class="t1">Button</div><div class="t2">App, shortcut, action…</div></span></button>`);
      btn.onclick = () => buttonSheet({ item: { kind: 'button', label: '', icon: 'auto', color: 'blue', action: { type: 'app' } }, p, i: -1, isNew: true });
      grid.append(btn);
      for (const [id, title] of WIDGET_LIST) {
        const def = D.WIDGETS[id];
        const r = h(`<button class="row">${glyph(def.glyph)}<span class="grow"><div class="t1">${esc(title)}</div><div class="t2">Panel</div></span></button>`);
        r.onclick = () => commit((cfg) => { cfg.pages[p].items.push({ kind: 'widget', widget: id, span: 'full' }); }, title + ' added');
        grid.append(r);
      }
      s.querySelector('[data-cancel]').onclick = D.closeSheet;
    });
  }

  // ------------------------------------------------------------------ pages
  function pageSheet(i, isNew) {
    const page = isNew ? { name: '', icon: 'star', items: [] } : clone(D.S.config.pages[i]);
    D.openSheet((s) => {
      s.innerHTML = `<h3>${isNew ? 'New page' : 'Edit page'}</h3>
        <label for="pn">Name</label><input id="pn" maxlength="24" placeholder="Streaming">
        <label>Symbol</label><div class="glyph-grid"></div>
        <div class="actions"><span class="left"></span><span class="spacer"></span><button class="btn" data-cancel>Cancel</button><button class="btn primary" data-save>Save</button></div>`;
      const pn = s.querySelector('#pn'); pn.value = page.name;
      const grid = s.querySelector('.glyph-grid');
      for (const name of Object.keys(window.GLYPHS)) {
        const b = h(`<button aria-label="${name}" class="${page.icon === name ? 'sel' : ''}">${glyph(name)}</button>`);
        b.onclick = () => { page.icon = name; grid.querySelectorAll('.sel').forEach((x) => x.classList.remove('sel')); b.classList.add('sel'); };
        grid.append(b);
      }
      const left = s.querySelector('.left');
      const n = D.S.config.pages.length;
      if (!isNew) {
        if (n > 1) deleteButton(left, 'Delete page', () => commit((cfg) => { cfg.pages.splice(i, 1); }, 'Page deleted'));
        const l = h(`<button class="btn" ${i === 0 ? 'disabled' : ''}>Move left</button>`);
        const r = h(`<button class="btn" ${i >= n - 1 ? 'disabled' : ''}>Move right</button>`);
        const move = (j) => commit((cfg) => { [cfg.pages[i], cfg.pages[j]] = [cfg.pages[j], cfg.pages[i]]; }).then((r) => { if (r.ok) D.goPage(j); });
        l.onclick = () => move(i - 1); r.onclick = () => move(i + 1);
        left.append(l, r);
      }
      s.querySelector('[data-cancel]').onclick = D.closeSheet;
      s.querySelector('[data-save]').onclick = () => {
        page.name = pn.value.trim();
        if (!page.name) { D.toast('Give the page a name', true); return; }
        commit((cfg) => { if (isNew) cfg.pages.push(page); else cfg.pages[i] = page; return cfg.pages.length - 1; }, isNew ? 'Page added' : 'Saved')
          .then((r) => { if (r.ok && isNew) D.goPage(r.ret); });
      };
    });
  }

  window.Editor = {
    editItem(p, i) {
      const item = D.S.config.pages[p].items[i];
      if (!item) return;
      if (item.kind === 'widget') { widgetSheet(p, i); return; }
      const copy = clone(item);
      if (!copy.action || !copy.action.type) copy.action = { type: 'app' };
      buttonSheet({ item: copy, p, i, isNew: false });
    },
    addItem,
    editPage: (i) => pageSheet(i, false),
    addPage: () => pageSheet(-1, true),
  };
})();
