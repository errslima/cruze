/* Text lobby for everyone on the page. Connects only after the 18+ confirmation. */
(() => {
  const $ = id => document.getElementById(id);
  const panel = $('lobby'), toggle = $('lobby-toggle'), list = $('lobby-messages'), empty = $('lobby-empty');
  const form = $('lobby-form'), input = $('lobby-input'), sendButton = $('lobby-send'), error = $('lobby-error');
  let socket = null, retry = 0, errorTimer;
  const flag = code => /^[A-Z]{2}$/.test(code || '') ? String.fromCodePoint(...[...code].map(c => 127397 + c.charCodeAt(0))) : '';
  const clock = at => new Date(at * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});

  function setOpen(open, remember = true) {
    panel.hidden = !open; toggle.hidden = open;
    toggle.setAttribute('aria-expanded', String(open));
    if (open) { $('lobby-unread').hidden = true; list.scrollTop = list.scrollHeight; }
    if (remember) try { localStorage.setItem('cruze_lobby', open ? 'open' : 'closed'); } catch {}
  }
  function online(count) { $('lobby-count').textContent = count > 1 ? `${count} people here` : 'Just you right now'; }
  function connected(ready) {
    input.disabled = sendButton.disabled = !ready;
    if (!ready) $('lobby-count').textContent = 'Reconnecting…';
  }
  function showError(message) {
    error.textContent = message; error.hidden = false;
    clearTimeout(errorTimer); errorTimer = setTimeout(() => { error.hidden = true; }, 5000);
  }
  function render(message) {
    const item = document.createElement('li'), meta = document.createElement('div');
    const name = document.createElement('strong'), when = document.createElement('time'), text = document.createElement('p');
    item.dataset.id = message.id; item.classList.toggle('mine', message.mine);
    meta.className = 'lobby-meta';
    name.textContent = `${flag(message.country)} ${message.name}`.trim();
    when.dateTime = new Date(message.at * 1000).toISOString(); when.textContent = clock(message.at);
    text.textContent = message.text;
    meta.append(name, when); item.append(meta, text);
    return item;
  }
  function add(messages, replace = false) {
    const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
    if (replace) list.replaceChildren();
    list.append(...messages.map(render));
    while (list.children.length > 200) list.firstElementChild.remove();
    empty.hidden = list.children.length > 0;
    if (replace || atBottom || messages.some(message => message.mine)) list.scrollTop = list.scrollHeight;
  }
  function receive(message) {
    if (message.type === 'hello') {
      retry = 0; connected(true); online(message.online); add(message.history, true);
      $('lobby-me').textContent = ['You appear as', flag(message.country), message.name].filter(Boolean).join(' ');
    } else if (message.type === 'online') {
      online(message.count);
    } else if (message.type === 'message') {
      add([message]);
      if (panel.hidden && !message.mine) $('lobby-unread').hidden = false;
    } else if (message.type === 'removed') {
      list.querySelector(`li[data-id="${Number(message.id)}"]`)?.remove();
      empty.hidden = list.children.length > 0;
    } else if (message.type === 'error') {
      showError(message.message);
    }
  }
  function connect() {
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/lobby`);
    socket = ws;
    ws.onmessage = event => { try { receive(JSON.parse(event.data)); } catch {} };
    ws.onclose = () => {
      if (socket !== ws) return;
      socket = null; connected(false);
      setTimeout(connect, Math.min(30000, 1000 * 2 ** retry++));
    };
  }

  form.onsubmit = event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || socket?.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({type: 'say', text}));
    input.value = '';
  };
  toggle.onclick = () => { setOpen(true); input.focus(); };
  $('lobby-close').onclick = () => { setOpen(false); toggle.focus(); };
  let saved = null;
  try { saved = localStorage.getItem('cruze_lobby'); } catch {}
  setOpen(saved ? saved === 'open' : matchMedia('(min-width: 900px)').matches, false);

  // Mirrors a video block, so that person's new lobby messages are hidden too.
  window.cruzeLobby = {block: ip => { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type: 'block', ip})); }};
  if (document.cookie.split(';').some(cookie => cookie.trim() === 'cruze_adult=1')) connect();
  else window.addEventListener('cruze:adult', connect, {once: true});
})();
