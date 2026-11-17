/* Appearance: theme x mode x finish.

   Loaded synchronously in <head>, ahead of the stylesheet, so the stored
   choice is on <html> before the first paint: a light-mode user never sees
   a dark flash. `theme` (a file under web_frontend/themes/) is voice, shape
   and type; `mode` (dark, light, system) is the palette; `finish` (matte,
   lustre) is how surfaces are lit. The three resolve to one DaisyUI theme
   name, `<theme>-<mode>-<finish>`, generated in tailwind.config.js. Charts
   listen for `theme-changed` and repaint from the new tokens.

   What each key may be is listed once on the server (rendering.py
   APPEARANCE) and carried on <html>; the first value is the default, but
   for the theme, which opens as this script's own tag says
   (appearance_head in components/macros/layout.html: data-theme, and
   data-fixed when the layout owns its theme and only the mode is the
   viewer's). */
(() => {
  const root = document.documentElement;
  const tag = document.currentScript?.dataset ?? {};
  const fixed = 'fixed' in tag;
  const CHOICES = JSON.parse(root.dataset.appearanceChoices);
  const DEFAULTS = Object.fromEntries(Object.entries(CHOICES).map(([key, values]) => [key, values[0]]));
  if (CHOICES.theme.includes(tag.theme)) DEFAULTS.theme = tag.theme;
  const media = window.matchMedia('(prefers-color-scheme: dark)');

  const read = (key) => {
    if (fixed && key === 'theme') return DEFAULTS.theme;
    let stored = null;
    try {
      stored = localStorage.getItem(key);
    } catch (_) {
      /* private mode or storage disabled: keep the default */
    }
    return CHOICES[key].includes(stored) ? stored : DEFAULTS[key];
  };

  // ``theme-changed`` only when the colours did: what listens (charts.js)
  // draws again in them, and the sidebar opening needs no redraw.
  const apply = () => {
    const theme = read('theme');
    const mode = read('mode');
    const resolved = mode === 'system' ? (media.matches ? 'dark' : 'light') : mode;
    root.dataset.assistant = read('assistant');
    root.dataset.sidebar = read('sidebar');
    const name = `${theme}-${resolved}-${read('finish')}`;
    if (root.dataset.theme === name) return;
    root.dataset.theme = name;
    document.dispatchEvent(new CustomEvent('theme-changed', { detail: { theme, mode } }));
  };

  /* The sidebar menu's Alpine state; what the user chose, not what resolved. */
  window.appearance = () => Object.fromEntries(Object.keys(CHOICES).map((key) => [key, read(key)]));
  // A choice the server draws the page by (a MenuChoice, Overseer's) names
  // its cookie: kept there, and the page redrawn.
  window.setAppearance = (key, value, cookie) => {
    if (cookie) {
      document.cookie = `${cookie}=${encodeURIComponent(value)}; path=/; max-age=31536000; samesite=lax`;
      location.reload();
      return;
    }
    if (!CHOICES[key]?.includes(value) || (fixed && key === 'theme')) return;
    try {
      localStorage.setItem(key, value);
    } catch (_) {
      /* not persisted; the switch still applies for this page */
    }
    apply();
  };

  media.addEventListener('change', () => {
    if (read('mode') === 'system') apply();
  });
  apply();
})();
