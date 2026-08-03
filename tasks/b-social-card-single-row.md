# Social card: draw the editions as one row

**Prefix:** `b-` — medium priority, actionable now, but deliberately deferred.

**Trigger: the next edition load.** `make_social_card` refuses to draw a card
that would overflow, so the failure is a loud `CommandError`, not a clipped
image. Do this when you see it, or before loading a fourth edition.

## Why the staircase runs out

Each edition costs 46px (36px band + 10px gap) in a 600px frame that cannot
grow, because 2:1 is the ratio every platform renders whole.

| Editions | Ink height | Fits 600? |
|---|---|---|
| 3 | 591px | yes |
| 4 | 637px | no |
| 5 | 683px | no |
| 7 | 775px | no |

The date axis breaks first. An ISO date needs about 124px. Over a 1975-2025
span the 1980s editions fall 63px and 92px apart, so their labels overlap at
any type size:

```
1983-08-08 -> 1986-07-07:   63px
1986-07-07 -> 1990-10-01:   92px
```

## The shape that holds

**One row of contiguous segments.** The editions abut at edition level, so the
corpus is one continuous line; separate rows were only ever needed for
overlaps that do not exist at this granularity. Seven editions fit in 94px,
and that height is constant however many you add.

- One band, split by oxblood ticks at every boundary.
- The edition year inside its segment **when it fits**, dropped when it does
  not. Do not shrink the type to fit; a 3-year edition on a 50-year axis is
  63px wide and no size helps.
- Date labels only at the two ends. Every interior boundary keeps its tick.

The staircase encodes succession twice — once by vertical position, once by
horizontal — and only the horizontal one carries information. Removing the
redundant axis is what makes it scale, and the 1980s cluster then reads as
visibly dense, which is true about Ontario's amendment history.

## What this costs

A single row cannot show an overlap between two editions. None exists today at
edition level. If one ever does, that is a reason to revisit, not a reason to
keep the staircase now.

## Done when

- Seven simulated editions draw inside the frame.
- The year is omitted, not shrunk, on a segment too narrow to hold it.
- `make_social_card` no longer needs its overflow guard, or the guard moves to
  whatever the new limit is.
