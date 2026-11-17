/** @type {import('tailwindcss').Config} */
// Tailwind + DaisyUI config for the htmx web frontend.
//
// The CSS is compiled ahead of time, never by a runtime CDN JIT: identical
// visual result, zero runtime compile cost, and classes the `content`
// scanner cannot see fail loudly in dev instead of silently in prod. If you
// put Tailwind classes anywhere outside the globs below (a Python string, a
// new template directory), add that path here or they will not be emitted.
//
// THEMES: the single rebrand point.
//
// Three axes. A MODE is a color palette (dark, light). A THEME is a voice,
// a shape and a type: a file under app/components/web_frontend/themes/
// (its shape, type and tints), read here and by the server. A FINISH is how
// surfaces are lit (matte, lustre). The DaisyUI themes below are generated
// from those, named `<theme>-<mode>-<finish>`, and applied as
// `<html data-theme>` by static/js/theme.js. See
// docs/components/web-frontend/styling.md.
//
// Every `aegis-*` color name reads a DaisyUI variable, so `bg-aegis-card`
// follows whatever theme is on <html> and no value is written twice. Charts
// read the same variables (see charts.js).

// The palette is a JSON file so Overseer (Flet) builds its light and dark
// schemes from the same values (app/components/frontend/theme.py).
const PALETTES = require("./app/core/palette.json");

// A FINISH is how surfaces are lit, read by `.raised` and `.floating` in
// input.css. matte switches each effect off with a value that is still
// valid CSS, so no component ever asks which finish is on; lustre lights
// them, per mode: a white top edge is the highlight on a dark card and
// invisible on a white one. Any theme takes either finish.
//
// Gloss what floats, keep data matte: raised panels get a sheen, a lit
// edge and a soft layered shadow; menus, dialogs and toasts get more lift,
// a frosted see-through fill; the accent glows on the assistant button and
// the chosen chip. Table rows are never touched.
const MATTE = {
  "--aegis-sheen": "none", // raised: a gradient laid over the fill
  "--aegis-edge": "0 0 #0000", // inset top highlight, light catching an edge
  "--aegis-elevation": "0 0 #0000", // raised: resting shadow
  "--aegis-lift": "0 25px 50px -12px rgb(0 0 0 / 0.25)", // floating shadow
  "--aegis-glow": "0 0 #0000", // the accent's halo
  "--aegis-frost": "none", // floating: backdrop-filter
  "--aegis-float-alpha": "1", // floating: fill opacity, <1 lets frost show
};

const FINISHES = {
  matte: { dark: MATTE, light: MATTE },
  lustre: {
    dark: {
      "--aegis-sheen": "linear-gradient(180deg, rgb(255 255 255 / 0.035), transparent 40%)",
      "--aegis-edge": "inset 0 1px 0 rgb(255 255 255 / 0.06)",
      "--aegis-elevation": "0 1px 2px rgb(0 0 0 / 0.3), 0 8px 24px rgb(0 0 0 / 0.25)",
      "--aegis-lift": "0 2px 4px rgb(0 0 0 / 0.3), 0 12px 32px rgb(0 0 0 / 0.4), 0 32px 64px -16px rgb(0 0 0 / 0.5)",
      "--aegis-glow": "0 0 16px oklch(var(--p) / 0.3)",
      "--aegis-frost": "blur(14px) saturate(1.4)",
      "--aegis-float-alpha": "0.82",
    },
    light: {
      "--aegis-sheen": "linear-gradient(180deg, rgb(255 255 255 / 0.9), rgb(0 0 0 / 0.012))",
      "--aegis-edge": "inset 0 -1px 0 rgb(0 0 0 / 0.04)",
      "--aegis-elevation": "0 1px 2px rgb(16 24 40 / 0.06), 0 6px 16px rgb(16 24 40 / 0.06)",
      "--aegis-lift": "0 2px 4px rgb(16 24 40 / 0.06), 0 12px 32px rgb(16 24 40 / 0.12)",
      "--aegis-glow": "0 0 14px oklch(var(--p) / 0.25)",
      "--aegis-frost": "blur(14px) saturate(1.6)",
      "--aegis-float-alpha": "0.85",
    },
  },
};

const fs = require("fs");
const path = require("path");

const THEMES_DIR = path.join(__dirname, "app/components/web_frontend/themes");
const THEMES = fs
  .readdirSync(THEMES_DIR)
  .filter((file) => file.endsWith(".json"))
  .sort()
  .map((file) => ({
    name: path.basename(file, ".json"),
    ...JSON.parse(fs.readFileSync(path.join(THEMES_DIR, file), "utf8")),
  }));

const themes = THEMES.flatMap((theme) =>
  Object.entries(PALETTES).flatMap(([mode, palette]) =>
    Object.entries(FINISHES).map(([finish, lit]) => ({
      [`${theme.name}-${mode}-${finish}`]: {
        ...palette,
        ...(theme.tints?.[mode] ?? {}),
        ...theme.shape,
        "--aegis-font-display": theme.type.display,
        "--aegis-font-body": theme.type.body,
        ...MATTE,
        ...lit[mode],
      },
    })),
  ),
);

// DaisyUI stores each theme color as an oklch triplet in a short variable.
const daisy = (name) => `oklch(var(--${name}) / <alpha-value>)`;

module.exports = {
  content: [
    "./app/components/web_frontend/templates/**/*.html",
    "./app/components/web_frontend/static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        aegis: {
          bg: daisy("b2"),
          card: daisy("b1"),
          border: daisy("b3"),
          text: daisy("bc"),
          muted: daisy("n"),
          teal: daisy("p"),
          amber: daisy("wa"),
          accent: daisy("a"),
          error: daisy("er"),
          scrim: "rgb(0 0 0 / <alpha-value>)",
        },
      },
      borderRadius: {
        DEFAULT: "var(--rounded-btn)",
        lg: "var(--rounded-box)",
      },
      // A theme's type: `font-display` for titles, `font-body` for the rest
      // (the body's default); never a family name in a template.
      fontFamily: {
        display: "var(--aegis-font-display)",
        body: "var(--aegis-font-body)",
      },
      fontSize: {
        xxs: ["0.625rem", "0.875rem"],
      },
      // A voice control's "speaking" equalizer (components/macros/chat.html).
      keyframes: {
        "voice-bar": {
          "0%, 100%": { transform: "scaleY(0.3)" },
          "50%": { transform: "scaleY(1)" },
        },
      },
      animation: {
        "voice-bar": "voice-bar 0.9s ease-in-out infinite",
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: { themes, logs: false },
};
