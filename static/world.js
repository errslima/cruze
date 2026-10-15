/* Country totals only. No visitor identifiers or precise locations reach this map. */
(() => {
  const layer = document.getElementById('world'), svg = document.getElementById('world-map');
  const note = document.getElementById('world-note');
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
      }
      const response = await fetch('/api/visitor-map');
      if (!response.ok) throw new Error();
      const {countries} = await response.json();
      const maximum = Math.max(1, ...Object.values(countries));
      for (const path of shapes) {
        const count = countries[path.dataset.country] || 0;
        const heat = Math.log1p(count) / Math.log1p(maximum);
        const low = [70, 84, 46], high = [212, 252, 113];
        path.style.fill = count ? `rgb(${low.map((n, i) => Math.round(n + (high[i] - n) * heat)).join(',')})` : '#242c29';
        path.classList.toggle('visited', count > 0);
      }
      note.textContent = Object.keys(countries).length ? 'Brighter countries have welcomed more visitors' : 'No visitor locations available yet';
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
