# Design

Visual system for the Wendy Foils dashboard. The source of truth is the `TEMPLATE` string inside `gen_dashboard.py`. Never hand-edit `docs/index.html` (it is regenerated every forecast run). This file documents what is shipped and the rules that keep it coherent, amped with the Impeccable product-register discipline. Read [PRODUCT.md](PRODUCT.md) first for the who/what/why.

Register: **product**. This is a tool that serves a decision (go / no-go), with one deliberately expressive surface (the hero). The bar is earned trust and instant scanning, not marketing polish.

---

## Theme

Dark marine. One sentence of scene: Simon, phone in hand, early morning or dusk, low ambient light, deciding whether to grab the gear and drive to a lake. Dark is not "because tools look cool dark", it is the physical read: a glanceable, low-glare surface for dawn/dusk phone checks, with the water-and-wind palette the subject itself lives in. Deep teal-black base, cyan as the single accent, semantic go/maybe/skip signal colors.

Color strategy: **Restrained** (product floor). Tinted-neutral surfaces plus one accent, with three semantic state colors that carry meaning, never decoration.

---

## Color

Committed hex tokens (identity-preserving; do not swap the hue family). All defined in `:root`.

### Surfaces (teal-tinted neutrals, dark to light)
| Token | Value | Use |
|---|---|---|
| `--bg` | `#050d12` | Page background |
| `--bg2` | `#081820` | Deeper hero gradient stop |
| `--panel` | `#0c1c24` | Cards, tiles, source chips |
| `--panel2` | `#0f232c` | Modal sheet, raised panels |
| `--hair` | `#183038` | Hairline borders, dividers |
| `--hair2` | `#1f3b45` | Stronger border, hover border |

### Ink (text ramp)
| Token | Value | Use | Contrast note |
|---|---|---|---|
| `--ink` | `#eef6f7` | Primary text, values | ~16:1 on `--bg`, safe |
| `--soft` | `#93b0b7` | Secondary text, sublabels | ~6:1 on `--bg`, AA body OK; **recheck on `--panel2` / tinted panels** |
| `--faint` | `#5f7a82` | Tertiary, meta, eyebrows | ~3:1, **large/non-essential text only**, never body |

### Accent + state
| Token | Value | Use |
|---|---|---|
| `--accent` / `--accent-dim` | `#39d7df` / `#1c9aa2` | Primary accent: current selection, links, quality bar, live dot, focus ring. Not decoration. |
| `--go` / `--go-bg` | `#3fd29a` / 13% tint | GO calls |
| `--maybe` / `--maybe-bg` | `#f4b73f` / 13% tint | MAYBE / "models split" |
| `--skip` / `--skip-bg` | `#6f8990` / 10% tint | SKIP / too light |

**Rules**
- **The call is the loudest thing.** GO/MAYBE/SKIP tags and the driving wind number outrank everything visually. Support detail (why, spread, meta) recedes to `--soft` / `--faint`.
- **State color is never the only signal.** Every state pairs its color with a text label (GO / MAYBE / SKIP). Survives grayscale and color-blindness. Non-negotiable.
- Accent is reserved: selection, links, focus, live/quality indicators. Never a decorative wash.
- **Verify contrast (Impeccable):** body >=4.5:1, large/bold >=3:1. The known risk here is `--soft` and `--faint` on the lighter tinted panels (`--panel2`, feature-card gradient). When in doubt, bump toward `--ink`. Light gray "for elegance" is the number-one AI legibility failure; do not drift there.
- Gray text on the colored state tints: use the state color itself or a darker shade of the tint's hue, not neutral gray.

---

## Typography

Three IBM Plex cuts (loaded via Google Fonts; GitHub Pages has no CSP so webfonts are fine). One superfamily, paired on a width/contrast axis (condensed display vs regular sans vs mono), which is legitimate. Do not add a fourth family.

| Token | Family | Role |
|---|---|---|
| `--disp` | IBM Plex Sans Condensed (600/700) | Display: h1, section headings, big wind numbers, values |
| `--sans` | IBM Plex Sans (400-700) | Body, verdict prose, card text |
| `--mono` | IBM Plex Mono (400-600) | Data, labels, eyebrows, meta, pills, units |

**Rules**
- Mono is the data/label voice; it signals "this is a measured value or a field label." Keep it there. Do not set body prose in mono.
- Display (condensed) is for numbers and headings only. **Never set UI labels, pills, or data field names in the display face** (product ban); those are mono.
- Hero h1 is the one place fluid type is allowed: `clamp(38px, 7.5vw, 76px)`, `letter-spacing: -.015em` (respects the -0.04em floor), `text-wrap: balance`, `max-width: 16ch`. Ceiling stays well under 6rem.
- Everything below the hero uses a tight, near-fixed scale (product discipline): section h2 `clamp(22px,3vw,30px)`, values ~23-24px, body 13-14px, labels 10.5-12px. Do not introduce new fluid clamps in the grid or cards.
- Prose (verdict, notes) capped at 60-70ch. Data rows and the matrix may run denser.

---

## Layout

- Container: `--maxw: 1120px`, gutter `clamp(30px, 7.5vw, 56px)`.
- **Hero**: layered — background gradient (`z-index:0`) + animated wind canvas (`#wind`, `z-index:1`) + content (`z-index:2`). The single expressive surface. Feature card + 2x2 stat tiles in a `1.15fr .85fr` grid.
- **Outlook matrix**: CSS grid, `200px repeat(ndays, minmax(0,1fr))`, spots as rows, days as columns. This is the core scan target; it must read in seconds. Denser than prose is correct here.
- **Rules cards**: `repeat(auto-fit, minmax(220px, 1fr))` — breakpoint-free responsive grid. This is the one legitimate card grid (genuinely distinct content per card); do not clone the pattern elsewhere, and never nest cards.
- Responsive is **structural, not fluid type**: at `860/760/560/430px` the hero grid stacks, tiles collapse to one column, matrix cells reflow to labeled rows (`.dlabel` shows). Mobile is the primary target — verify every breakpoint; headings must not overflow.
- Vary vertical rhythm with `clamp()` section padding; avoid uniform spacing.

---

## Components

Product rule: every interactive element ships default + hover + focus states, and honest empty/stale states.

- **State pill / tag** (go/maybe/skip): mono, uppercase-ish tracking, tinted bg + inset ring. The atomic unit of the whole UI. One vocabulary, used identically in the feature card and the matrix.
- **Wind value**: display face, large, `--ink`/white, with a mono unit suffix (`kt`). Consistent everywhere a speed appears.
- **Quality bar** (`.qbar`): 4px accent-gradient meter for in-band quality. Accent gradient is allowed here (a meter), not as text or decoration.
- **Day cell**: bordered, `rgba(255,255,255,.012)` fill, hover lifts `-2px` + border brightens (150ms). Near-term cells are `.clickable` (open the hourly modal) with a visible expand affordance; far days are not clickable (no trustworthy hourly that far out) and must not fake the affordance.
- **`.best` / WATCH cell**: accent ring + soft glow + corner "WATCH" label. The one place a cell earns extra emphasis (a flagged standout day).
- **Modal** (`.sheet`): centered dialog (`z-index:50`), backdrop blur, closes on X / backdrop / Esc. Used only for the genuinely richer hourly view — the one justified modal. Do not reach for modals elsewhere; prefer inline/progressive disclosure (product ban on modal-as-first-thought).
- **Live nowcast** (`.live`): dashed-top row with a pulsing accent dot; the "reality check" against the models. Honest-uncertainty surface.
- **Stale state**: when the fetch is not from today, the system says so plainly rather than showing confident-but-old numbers (mirrors the alert routines' stale guard). Never dress up stale data as current.

**Z-index scale** (semantic, keep it): hero bg `0` -> wind canvas `1` -> hero content `2` -> modal `50`. No arbitrary 999/9999.

---

## Motion

Product cadence: motion conveys state, never decoration.

- Transitions 150ms `ease` on hover/interaction (cell lift, card lift, expand affordance). In the 150-250ms product band.
- Ambient: hero wind canvas (the subject, visualized) + a slow 2.4s live-dot pulse (a status heartbeat). Both are state/subject, not gratuitous choreography. No page-load entrance sequence.
- **Reduced motion is handled and must stay handled:** `@media (prefers-reduced-motion: reduce)` disables the wind canvas, neutralizes reveals, and stops the pulse. Any new animation needs its reduced-motion fallback in the same commit.

---

## Absolute bans (enforced here)

Shared Impeccable bans that specifically matter for this surface:
- No side-stripe borders (>1px colored left/right accents). Use full borders + tints (already the pattern).
- No gradient text (`background-clip:text`). Accent gradients are fine on meters/bars only.
- No decorative glassmorphism. The two blurs here (feature card, modal) are purposeful; do not add more.
- No hero-metric KPI-tile template as a content strategy (that is the enterprise-SaaS anti-reference). The stat tiles are real conditions (air/water temp, wetsuit), not vanity metrics.
- No em dashes anywhere user-facing (Simon's standing rule; also applies to generated copy).
- No weather-app tropes: gradient sky cards, big emoji glyphs, every-metric clutter. No cutesy surf clipart.

## The product slop test for this project

Would Simon trust this at a glance the way he trusts Linear or Stripe, and get the go/no-go call in seconds without reading prose? If a component looks subtly off, over-decorated, or invents an affordance for a standard task, it fails. The tool should disappear into the decision.
