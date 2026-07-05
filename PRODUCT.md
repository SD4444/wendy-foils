# Product

## Register

product

## Users

One user: Simon. A brand-new wing foiler but a lifelong wave surfer (strong balance, water confidence, reads wind and water well). He checks this before deciding whether to drop everything and drive to a lake near Amsterdam to foil. His context when using it: a quick morning or evening glance, often on his phone, wanting one thing fast: is today (or this week) worth going, where, and when. The job to be done is a go / no-go call he can trust, with enough backing detail to sanity-check it himself.

## Product Purpose

Wendy Foils is a personal wind-forecast watchdog. It pulls multi-model wind (plus waves for coastal spots), applies a beginner-safe good-day rule tuned to Simon's gear and skill, and surfaces GO / MAYBE / SKIP calls per spot across a 7-day outlook. The dashboard is the visual half of that system: a hosted page (GitHub Pages) the scheduled alerts link to. Success is Simon never missing a genuinely good day, never being sent out in unsafe wind, and being able to read the whole week's picture in a few seconds without reading prose. The tool should disappear into that decision.

## Brand Personality

Voice is "Wendy": a laid-back local surfer girl who reads wind and water well and calls it straight. Casual, plain-spoken, first person, chill. No sass, no flirt, no hype. Three words: calm, credible, direct. The headline carries the voice ("Sunday's looking good." / "Nothing this week."); everything else stays terse and factual. The emotional goal is quiet trust, the feeling of a knowledgeable friend telling you the honest call, not a weather brand performing excitement.

## Anti-references

- **Generic weather app** (Weather.com, phone weather): gradient sky cards, big emoji glyphs, cluttered rows of every metric, ad-density. Avoid.
- **Enterprise SaaS dashboard**: KPI hero-metric tile walls, chart-junk, cold Inter-on-white admin panels. Avoid.
- **Toy / cutesy**: surf clipart, playful rounded-everything, emoji-heavy tone. It undercuts trust in a safety call. Avoid.
- Not on the avoid list: expressive, editorial visual craft. The designed hero and Wendy's voice are wanted; the ban is on drama that fights legibility, not on beauty.

## Design Principles

- **The call comes first.** GO / MAYBE / SKIP and the number that drives it must be the loudest thing on any surface. Everything else is support Simon reads only when he wants to double-check.
- **Scannable in seconds, verifiable on demand.** The week reads at a glance; the why, the model spread, and the hourly detail are one tap deeper for when he wants to trust-but-verify.
- **Honest over reassuring.** Show model disagreement, low-confidence far days, and stale-data states plainly. Never dress up a weak forecast or hide uncertainty. Safety blocks (offshore, overpowered) are never softened.
- **Terse and specific.** Spot, time window, wind speed, direction. No filler, no em dashes (standing rule), no decorative copy.
- **Earned familiarity, one expressive moment.** Standard, trustworthy affordances everywhere; the hero is the single place personality is allowed to be loud.

## Accessibility & Inclusion

- Dark marine theme; body and data text must meet WCAG AA (>=4.5:1 body, >=3:1 large). The muted `--soft` / `--faint` ramp is the contrast risk to watch, especially on the tinted panel surfaces.
- Color is never the only signal for GO / MAYBE / SKIP: pair every state color with its text label (already the pattern) so it survives color-blindness and grayscale.
- Honor `prefers-reduced-motion` for the live-dot pulse and any reveal or chart animation.
- Primary read target is mobile (morning phone glance), so touch targets, tap-to-expand day cells, and legibility at small widths are first-class, not an afterthought.
