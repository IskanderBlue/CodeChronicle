# A block tag for the modal shell

## The idea

Two dialogs share their whole wrapper, and share it by copy:

- the relevance control, `templates/partials/search_results_partial.html`
- the BUILDING control, `templates/partials/_search_form.html`

Both write `class="cc-modal"`, `x-show`, `x-cloak`, `@click.self`,
`@keydown.escape.window`, `role="dialog"`, `aria-modal="true"`,
`aria-labelledby`, then `cc-modal-panel`, then a header row with the same class
string and the same `ESC` button. Only the Alpine state name and the title
differ.

A block tag gives the wrapper one definition:

```django
{% modal state="buildingOpen" title="The building you are asking about" %}
    ...the dialog's own fields, as ordinary template markup...
{% endmodal %}
```

About fifteen lines: a `@register.tag` that calls
`parser.parse(('endmodal',))`, renders the inner nodelist, and wraps it.

## Why a block tag, and not the two easier things

**Not `{% include %}`.** It cannot wrap child markup. A shell partial would
have to receive the body as a variable, which means building HTML outside a
template — losing autoescaping, losing template tags inside the body, and
putting markup somewhere no tool reads as markup.

**Not two partials per dialog** (an open half and a close half). That splits
one element across two files and makes an unbalanced tag invisible.

## Why it is not done

Two dialogs do not pay for a custom tag. The duplication is real but static:
neither copy has changed since it was written, and a wrong copy shows itself
immediately on screen.

## What would have to become true

- **A third dialog.** At three the tag clearly pays.
- **An accessibility change.** The attributes worth sharing are `role`,
  `aria-modal`, `aria-labelledby`, the escape handler and the click-outside
  handler. If a review asks for a focus trap or a change to any of those, it
  has to land in two files today, and that is the point at which the copy
  starts to cost something.
- **A visual change to the panel.** The CSS is already shared in `base.html`;
  only the markup is not.

## Where the code is

- `templates/partials/search_results_partial.html` — the datum dialog.
- `templates/partials/_search_form.html` — the BUILDING dialog.
- `templates/base.html` — `.cc-modal` and `.cc-modal-panel`, already shared.
- `core/templatetags/` — where the tag would live.
