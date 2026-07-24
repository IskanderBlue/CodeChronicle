# Interactive-element affordances

Every clickable text element uses one of the shared affordance roles below —
never a hand-copied Tailwind utility string. The classes are defined in
`templates/base.html`'s inline always-present `<style>` block (not Tailwind
utilities, which get purged), and all colours are role tokens, so light and
dark themes resolve automatically. All roles share one `:focus-visible` ring.

| Class | Role | Treatment |
|---|---|---|
| `.ui-link` | inline prose link | solid underline, accent, hover deepens |
| `.ui-cite` | quiet metadata-citation link | faint 35% underline at rest, strengthens on hover |
| `.ui-action` | interactive mono/uppercase label | dotted underline + `.ui-caret` (rotates on `[aria-expanded="true"]`) + optional `.ui-hint` |
| `.ui-btn` | primary filled action | accent bg, Inter Tight 600 |
| `.ui-btn-ghost` | bordered/chip action | frame + hover only; **type-agnostic** (inherits font/case) |

## The governing rule

**No interactive text may rely on colour alone at rest.** Variety of weight is
fine (hierarchy); ambiguity — a hidden or false affordance — is the enemy. An
accent-coloured label with only a hover-state underline is indistinguishable
from a static accent heading; give it a persistent at-rest signal (underline,
caret, glyph, or frame).

## Valid idioms outside the taxonomy

Not every clickable must carry a `.ui-*` class, provided it has its own
non-colour at-rest signal:

- **Footer chrome** — muted (`text-ink-3`, no accent) with a persistent faint
  underline.
- **Muted helper toggles** — e.g. the search "How it works" `?`/`–` toggle:
  `text-ink-3` plus a glyph is a non-colour signal.
- **Structural full-card / row clickables** — history cards, the result
  accordion row toggle, the mobile "previous version" disclosure. These are
  layout components with their own borders, not text/button roles.
- **BYOD PDF toolbar** — a self-consistent outline-accent cluster behind the
  open-fate BYOD feature (`tasks/n-byod-pdf-viewer-fate.md`); fold into
  `.ui-btn-ghost` + an outline-accent variant if that feature ships.

Origin and migration history: `tasks/complete/interactive-element-taxonomy.md`.
