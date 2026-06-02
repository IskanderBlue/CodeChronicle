/** @type {import('tailwindcss').Config} */
const colors = require('tailwindcss/colors')
module.exports = {
  content: ['templates/**/*.html'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // ── Legacy palette ──
        // Kept during the incremental redesign so the existing `*-<shade>`
        // usages keep their colours. Remove once every template is migrated
        // to the role tokens below.
        primary: colors.teal,
        accent: colors.yellow,
        neutral: colors.slate,
        danger: colors.red,
        success: colors.green,
        // Brick/terracotta spine for amended provisions — "something
        // changed" without alarm.  See tasks/provenance/4-display.md
        // §"Color Coding".
        amended: '#b45c3d',
        // ── Design role tokens ──
        // Resolve against the CSS vars defined in base.html's always-present
        // <style> block; `.dark` flips light → dark. MUST mirror the inline
        // CDN config in base.html (dev) — this file drives the prod build.
        ink: {
          DEFAULT: 'rgb(var(--ink) / <alpha-value>)',
          2: 'rgb(var(--ink-2) / <alpha-value>)',
          3: 'rgb(var(--ink-3) / <alpha-value>)',
        },
        surface: {
          DEFAULT: 'rgb(var(--surface) / <alpha-value>)',
          2: 'rgb(var(--surface-2) / <alpha-value>)',
        },
        panel: 'rgb(var(--panel) / <alpha-value>)',
        rule: {
          DEFAULT: 'rgb(var(--rule) / <alpha-value>)',
          2: 'rgb(var(--rule-2) / <alpha-value>)',
        },
        secondary: {
          DEFAULT: 'rgb(var(--secondary) / <alpha-value>)',
          2: 'rgb(var(--secondary-2) / <alpha-value>)',
          soft: 'rgb(var(--secondary-soft) / <alpha-value>)',
          contrast: 'rgb(var(--secondary-contrast) / <alpha-value>)',
        },
        highlight: {
          DEFAULT: 'rgb(var(--highlight) / <alpha-value>)',
          soft: 'var(--highlight-soft)',
        },
        // Legal-redline functional colours (deletions / additions). Resolve
        // against --strike / --insert in base.html; .dark flips them. Use only
        // on amendment redlines + action tags, never as UI chrome.
        strike: 'rgb(var(--strike) / <alpha-value>)',
        insert: 'rgb(var(--insert) / <alpha-value>)',
      },
      fontFamily: {
        serif: ['"Source Serif 4"', 'Literata', 'Georgia', 'serif'],
        sans: ['"Inter Tight"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      // Global square edges — the no-radius aesthetic is the authority signal.
      borderRadius: { DEFAULT: '0' },
    }
  }
}
