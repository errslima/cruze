/* City-coordinate counts only. No identities, IPs, or visit times reach this map. */
(() => {
  const layer = document.getElementById('world'), svg = document.getElementById('world-map');
  const note = document.getElementById('world-note');
  const ns = 'http://www.w3.org/2000/svg';
  function element(name, attributes = {}) {
    const node = document.createElementNS(ns, name);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    return node;
  }
  function project(latitude, longitude) {
    const theta = Math.asin(Math.sqrt(3) / 2 * Math.sin(latitude * Math.PI / 180));
    const t2 = theta ** 2, t6 = theta ** 6;
    const a = 1.340264, b = -.081106, c = .000893, d = .003796;
    return [500 + 180 * 2 * Math.sqrt(3) * longitude * Math.PI / 180 * Math.cos(theta) / (3 * (a + 3*b*t2 + t6*(7*c+9*d*t2))),
      260 - 180 * theta * (a + b*t2 + t6*(c+d*t2))];
  }
  const dots = element('g', {id: 'visitor-dots'});
  const gradients = element('defs');
  function renderDots(points) {
    dots.replaceChildren(); gradients.replaceChildren();
    const counts = new Map();
    for (const point of points) {
      const {latitude, longitude, count} = point;
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180 || !Number.isSafeInteger(count) || count < 1) continue;
      if (!counts.has(count)) {
        const id = `visitor-glow-${counts.size}`;
        counts.set(count, id);
        const gradient = element('radialGradient', {id});
        // Exactly the alpha composition of count identical soft visitor dots.
        // Combine overlaps instead of adding thousands of duplicate SVG nodes.
        for (let i = 0; i <= 24; i++) {
          const radius = i / 24;
          const single = .6 * Math.exp(-7 * radius * radius) * (1 - radius);
          const opacity = -Math.expm1(count * Math.log1p(-single));
          gradient.append(element('stop', {offset: radius, 'stop-color': i < 5 ? '#edffc8' : '#c7f779', 'stop-opacity': opacity}));
        }
        gradients.append(gradient);
      }
      const [cx, cy] = project(latitude, longitude);
      dots.append(element('circle', {cx, cy, r: 9, fill: `url(#${counts.get(count)})`, 'data-visitors': count}));
    }
  }
  let shapes, visible = false, pending = false, lastUpdate = 0;
  async function refresh() {
    if (pending || Date.now() - lastUpdate < 60000) return;
    pending = true;
    try {
      if (!shapes) {
        const response = await fetch('/world.json');
        if (!response.ok) throw new Error();
        const geometry = await response.json();
        shapes = geometry.map(country => {
          const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          path.setAttribute('d', country.path); path.setAttribute('fill-rule', 'evenodd');
          path.dataset.country = country.code; svg.append(path); return path;
        });
        svg.append(gradients, dots);
      }
      const response = await fetch('/api/visitor-map');
      if (!response.ok) throw new Error();
      const {points} = await response.json();
      if (!Array.isArray(points)) throw new Error();
      renderDots(points);
      note.textContent = points.length ? 'One soft dot per visitor · estimated cities' : 'No visitor cities available yet';
      lastUpdate = Date.now();
    } catch {
      note.textContent = 'Visitor map temporarily unavailable';
    } finally { pending = false; }
  }
  window.cruzeWorld = {
    show(show, message = 'Finding someone') {
      visible = show;
      layer.classList.toggle('is-visible', show);
      layer.setAttribute('aria-hidden', String(!show));
      document.getElementById('world-status').textContent = message;
      if (show && !document.hidden) refresh();
    }
  };
  setInterval(() => { if (visible && !document.hidden) refresh(); }, 60000);
  document.addEventListener('visibilitychange', () => { if (visible && !document.hidden) refresh(); });
})();
