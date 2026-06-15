# Pantera SPA — Design System & Screen Specs (Spec 010)

The concrete visual + interaction spec for the frontend. Built on shadcn/ui + Tailwind. This is the
source of truth for look-and-feel; `frontend-architecture.md` owns structure/routing, this owns design.
**Tone:** professional life-sciences / drug-safety — calm, clinical, trustworthy, information-dense but
not cramped. Desktop-first.

---

## 1. Design principles

1. **Evidence first.** The reviewer's job is to verify claims against sources — citations, passages,
   and provenance are visually prominent, never buried.
2. **Calm by default, loud only for risk.** Neutral slate UI; saturated color is reserved for severity
   (emergency/urgent) and overdue SLAs so urgency reads instantly.
3. **No dead ends, no surprises.** Every screen has breadcrumbs/back, explicit empty/loading/error
   states, and confirmation toasts that fire **only after** the backend confirms (never optimistic).
4. **One scope at a glance.** The acting client (staff) or own client (client-user) is always visible
   in the top bar; nothing is ambiguous about whose data you're seeing.
5. **Accessible enough.** Keyboard operable, visible focus rings, ARIA labels, AA contrast in both
   themes. (Full WCAG audit + mobile layouts are out of scope per FR-028.)

---

## 2. Color tokens (shadcn CSS variables, HSL)

Define in `globals.css` under `:root` (light) and `.dark`. Values are HSL triplets (Tailwind/shadcn
convention). Brand = clinical blue; secondary = safety teal.

### Light (`:root`)
```
--background:        210 40% 98%;   /* app bg (slate-50-ish)           */
--foreground:        222 47% 11%;   /* primary text (slate-900)        */
--card:              0 0% 100%;     /* surfaces/cards                  */
--card-foreground:   222 47% 11%;
--muted:             210 40% 96%;   /* subtle fills                    */
--muted-foreground:  215 16% 47%;   /* secondary text (slate-500)      */
--border:            214 32% 91%;   /* hairlines (slate-200)           */
--input:             214 32% 91%;
--ring:              211 80% 40%;   /* focus ring = primary            */

--primary:           211 80% 38%;   /* clinical blue                   */
--primary-foreground:0 0% 100%;
--secondary:         173 58% 39%;   /* safety teal                     */
--secondary-foreground:0 0% 100%;
--accent:            173 58% 39%;
--accent-foreground: 0 0% 100%;
--destructive:       0 72% 51%;     /* red-600                         */
--destructive-foreground:0 0% 100%;
```

### Dark (`.dark`)
```
--background:        222 47% 7%;    /* slate-950                       */
--foreground:        210 40% 96%;
--card:              222 40% 11%;   /* slate-900                       */
--card-foreground:   210 40% 96%;
--muted:             217 33% 17%;
--muted-foreground:  215 20% 65%;
--border:            217 33% 20%;
--input:             217 33% 20%;
--ring:              211 90% 60%;
--primary:           211 90% 60%;   /* lighter blue for contrast       */
--primary-foreground:222 47% 11%;
--secondary:         173 58% 45%;
--secondary-foreground:222 47% 11%;
--destructive:       0 72% 56%;
```

### Semantic scales (theme-invariant intent; use Tailwind classes or extra vars)
| Intent | Light | Dark | Used by |
|---|---|---|---|
| **emergency** | red-600 `#dc2626` | red-500 | severity bucket, emergency reports |
| **urgent** | amber-600 `#d97706` | amber-500 | severity bucket, SLA due-soon |
| **overdue** | red-700 `#b91c1c` | red-500 | SLA passed |
| **minor** | slate-500 | slate-400 | severity bucket |
| **positive** | emerald-600 `#059669` | emerald-500 | positive valence, approved, delivered |
| **info** | primary blue | primary | sent, drafted-grounded |
| **neutral** | slate-400 | slate-500 | discarded, pending-delivery |

> Severity color is the one place we go saturated. Everything else stays neutral.

---

## 3. Typography

- **UI font:** `Inter` (variable), system-ui fallback. **Mono:** `ui-monospace, "JetBrains Mono"` for
  IDs, chunk refs (`#123`), external IDs (`PMID:…`), token counts.
- **Scale** (rem / line-height):

| Token | Size | LH | Weight | Use |
|---|---|---|---|---|
| `display` | 1.875 (30px) | 2.25 | 700 | dashboard headline numbers |
| `h1` | 1.5 (24px) | 2 | 700 | page title |
| `h2` | 1.25 (20px) | 1.75 | 600 | section / card title |
| `h3` | 1.0 (16px) | 1.5 | 600 | sub-section, claim field label |
| `body` | 0.875 (14px) | 1.5 | 400 | default text |
| `small` | 0.8125 (13px) | 1.25 | 400 | meta, table cells |
| `caption` | 0.75 (12px) | 1 | 500 | chips, badges, timestamps |

Base body is 14px (dense, power-user appropriate). Numbers in tables/dashboards use `tabular-nums`.

---

## 4. Spacing, radius, elevation, motion

- **Spacing:** 4px base scale (`1`=4 … `6`=24, `8`=32). Page gutter 24px; card padding 16–20px;
  control gap 8–12px.
- **Radius:** `sm` 6px (chips/inputs), `md` 8px (buttons/cards), `lg` 12px (drawers/dialogs).
- **Elevation:** flat by default; cards = 1px border + `shadow-sm`. Drawer/dialog = `shadow-lg`.
  Avoid heavy shadows — this is a clinical, flat aesthetic.
- **Motion:** 150–200ms ease-out for drawer/sheet/toast; respect `prefers-reduced-motion`. No
  decorative animation.
- **Density:** tables 36–40px rows; sidebar items 40px; primary buttons 36px height.

---

## 5. Core components (specs)

### Buttons
- **Primary** (filled blue) — the safe/expected action (Approve, Save). One per context.
- **Secondary** (outline) — Edit, secondary actions.
- **Destructive** (red, filled or outline) — Discard, Reject. Reject/Discard always require confirm.
- **Ghost** (text) — tertiary, toolbar icons.
- All: visible focus ring (`--ring`), disabled = 50% + `not-allowed`. Loading = spinner + disabled,
  label stays ("Approving…").

### Chips / badges (12px caption, 6px radius, subtle tinted bg + colored text/border)
- **Severity:** Emergency (red, filled) · Urgent (amber) · Minor (slate) · Positive (emerald).
- **Status:** drafted (blue-outline) · under_review (blue) · approved (emerald) · rejected (red) ·
  discarded (slate) · needs_manual_revision (amber, with ⚠).
- **Delivery:** pending-delivery (slate, "Approved · pending delivery") · sent (blue) ·
  delivered (emerald) · delivery-failed (red). *(non-pending states light up via spec 13)*
- **Provenance** (on each claim): `grounded` (blue, link icon ⛓, shows `#chunk`) · `attested`
  (teal, person icon) · `aggregated` (slate, Σ icon). Tooltip explains each.

### SLA countdown
- Pill with clock icon. **>2h** neutral; **≤2h** amber ("due soon"); **passed** red ("overdue NNh").
  Live-ticks (min granularity). Reads from `sla_deadline`.

### Cards (dashboard)
- Title (h3 muted) + big `display` number + delta/sub-line + optional sparkline. Empty state inside
  the card ("No data yet"). Delivery cards show a "Pending delivery layer" ghost state.

### Passage drawer (right sheet, 420px)
- Header: external id (mono) + source-reliability chip + ✕. Body: full passage text (`body`, generous
  line-height, selectable), section label. Footer: `‹ prev  n of N  next ›` across the finding's
  sources. Unavailable → metadata + a muted "Passage unavailable" panel.

### Table (queue / all-reports / lists)
- Sticky header; zebra off (use hairlines); row hover = `--muted`. Columns right-sized; IDs mono;
  chips for type/severity/status; row-click opens detail. Keyboard: arrow-nav + Enter.

### Toast / banner
- **Toast** (bottom-right): success (emerald check) / error (red). Fires **after** server confirm.
  e.g. "Report #1042 approved." / "Couldn't approve — it was already actioned. Refreshing…"
- **Banner** (top of content): persistent context, e.g. an overdue-SLA warning, or "Viewing a
  suspended client (read-only)."
- **Inline hint** (muted, info icon): guidance like "Review all citations before approving."

### Empty / loading / error (every surface — FR-026)
- **Empty:** centered icon + title + 1-line guidance + optional CTA. e.g. "No reports pending — the
  queue is clear."
- **Loading:** skeleton rows/cards (not spinners) for lists; spinner only for in-place actions.
- **Error:** inline card "Couldn't load data" + Retry; never a blank screen.

---

## 6. Shell layout (FR-039)

```
┌────────┬─────────────────────────────────────────────────────────────┐
│ ☰ PANT │ Home › Reviewer Queue › #1042        [◧ Acme Pharma ▾] ☾ ⏻▾ │  56px top bar
│        ├─────────────────────────────────────────────────────────────┤
│ ▣ Queue│                                                             │
│ ▤ All  │   page content (max-width none; gutter 24px)                │
│ ⚙ Admin│                                                             │
│ 📊 Dash │                                                             │
│ 🗎 Audit│                                                             │
│ ────── │                                                             │
│ ⏻ Out  │                                                             │
└────────┴─────────────────────────────────────────────────────────────┘
 sidebar: 240px expanded / 56px icon-rail (toggle ☰); auto-collapses on /queue/:id
 top bar: breadcrumbs (left) · acting-client switcher + theme toggle + user menu (right)
```
- **Sidebar is a deep brand-navy panel** (not a gray/white rail) in BOTH themes — a subtle vertical
  gradient `#0C2B47 → #0A2236` (light) / `#0A1F35 → #081A2C` (dark) — to anchor the layout and add
  brand color against the light content area. Wordmark in white with a teal accent (`PAN`+`TERA`).
  Nav text = slate-200; hover = `white/10`; **active item** = `white/10` fill + a **teal inset
  left-accent bar** (`#2BB3A0`). Add `--sidebar`, `--sidebar-foreground`, `--sidebar-accent` tokens.
- Sidebar items show only role-permitted destinations.
- Acting-client switcher = searchable popover (staff only); shows current client; "Switch client".
  On suspended/lost-access → switcher opens a chooser (FR-004a).
- Theme toggle = sun/moon; persists.

---

## 7. Screen specs

### 7.1 Sign-in (`/login`)
Centered card (max 380px) on a calm split or plain `--background`. Brand mark + "Sign in to Pantera".
Email, password, Sign-in button (loading state). Error (non-enumerating): "Email or password is
incorrect." Rate-limited: "Too many attempts — try again in a moment." No "forgot password" in v1
(out of scope). Footer: small product/version.

### 7.2 Reviewer Queue (`/queue`)
- Page title "Approval queue" + count. Inline hint on first load: "Expedited reports are shown first."
- **Two groups**: *Expedited* (sorted SLA-asc, overdue first) then *Batch* (created-at). Group headers
  with counts.
- Table columns: `Type` (chip) · `Severity` (chip) · `Drug → Reaction` (or "Batch · N findings") ·
  `Corrob.` (count) · `SLA` (countdown pill, expedited only) · `Updated`. Row → detail.
- Pagination: "Load older" (limit/offset). Empty: "No reports pending — the queue is clear."

### 7.3 Report Detail (`/queue/:id`) — **layout C**
```
┌──┬──────────────┬─────────────────────────────────┬──────────────────┐
│☰ │ FINDINGS (6) │ ‹breadcrumb›  #1042 ·EXPEDITED   │ SOURCE PASSAGE  ✕│
│▣ │▶atorva    ✓ │  urgent  ⏱03:58  [⭳][Approve ▾]  │ PMID:3999 ·high  │
│▤ │ metform   ✓ │                                  │ "A 67-y/o male   │
│⚙ │ lisino    ⚠ │ Drug: atorvastatin  [⛓grounded·#123]│  on atorva…"    │
│📊│ warfarin  ✓ │ Reaction: rhabdo    [⛓grounded·#128]│ §Adverse Rxns   │
│🗎│ ...        │ Causality: probable [person attested]│                 │
│  │            │                                  │ ‹ 1 of 3 ›       │
│  │[drop][disc]│ Narrative ─────────────────────  │                  │
│  │ (selected) │ A 67-year-old male…              │                  │
│  │            │ Corroboration: 3 sources ──────  │                  │
│  │            │  ⛓#123 PMID3999 high ▸           │                  │
│  │            │  ⛓#441 EMA       med  ▸           │                  │
│  │            │  ⛓#502 FAERS     low  ▸           │                  │
│  │            │ ─────────────────────────────────│                  │
│  │            │ [Discard] [Reject…] [Edit] [Approve]                 │
└──┴──────────────┴─────────────────────────────────┴──────────────────┘
```
- **Findings rail** only for batch (hidden for expedited); drop/discard act on selected finding;
  confirm dialogs. Top action = "Approve batch" for batch.
- **Center**: claim rows = field label + value + provenance badge; grounded badge is a link → opens
  the drawer to that chunk. Narrative below. Corroboration list = all N (FR-009), each row opens drawer.
- **Edit** → inline edit mode: claims + body become editable; "Save & Approve" (attested provenance;
  grounding gate not applied). **Reject** → dialog with required comment + a note of the redraft cap
  ("Round 2 of 3"); 4th → moves to needs_manual_revision (stays, banner explains).
- **Passage drawer** opens on any citation click; closed by default.
- Header chips: severity, delivery-status ("Approved · pending delivery" after approve), `⭳ Download`.
- Edge states: stale → "This report was already actioned. Refreshing." + refetch; mid-redraft → center
  shows an in-progress state, actions disabled.

### 7.4 All Reports (`/reports`) — reviewer read-only history
Same table as queue but `status=all`, status + delivery chips per row, status filter dropdown. Row →
read-only detail (action bar hidden, drawer + download present).

### 7.5 Admin Console (`/admin`)
Tabbed: **Clients** (list + create/edit: cadence, severity thresholds) · **Watchlists** (per client:
drugs/keywords + custom severity keywords) · **Triggers** (per-watchlist "Run cycle" → 202 "Queued"
toast). Contextual help text per tab. Forms = shadcn inputs with validation + save toast.

### 7.6 Manager Dashboard (`/admin/dashboard`) — FR-021a
Grid of cards:
```
┌ Pipeline ───────┐ ┌ Queue load ─────┐ ┌ SLA health ─────┐
│ drafted     12  │ │ pending     18  │ │ overdue      2  │
│ under review 4  │ │ expedited    5  │ │ due soon     3  │
│ approved   140  │ │ batch       13  │ │ met         95% │
│ rejected     6  │ └─────────────────┘ └─────────────────┘
│ discarded    9  │ ┌ Redraft health ─┐ ┌ Cost (USD) ─────┐
│ needs revis. 3  │ │ avg revisions 0.6│ │ this cycle $0.41│
└─────────────────┘ │ hit cap        3 │ │ triage   $0.10  │
┌ Delivery (pending delivery layer) ─┐  │ agent    $0.31  │
│ sent / delivered / failed  —  spec │  └─────────────────┘
│ 13 will populate these.            │
└────────────────────────────────────┘
```
Delivery card is a muted "pending delivery layer" ghost until spec 13. Each card has an empty state.

### 7.7 Client Portal (`/portal`, `/portal/watchlists/:id`, `/portal/reports/:id`)
- `/portal`: cards/list of the client's watchlists; each shows count of approved+sent reports. Empty:
  "No reports available yet."
- watchlist page: that watchlist's approved+sent reports (table; type/severity/status/delivery + date),
  read-only. Row → read-only report detail (layout C center+drawer, **no** rail actions, download
  present). No decision/config controls anywhere.
- Client-user has no sidebar admin/reviewer items; no acting-client switcher.

### 7.8 Audit export (`/admin/audit`) — FR-037
Explainer paragraph (compliance purpose) + format toggle (CSV/JSON) + **Export** button rendered
**disabled** with "Export not yet available" until the backend endpoint ships (forward dependency).

---

## 8. Microcopy / guidance (examples)
- Queue empty: "No reports pending — the queue is clear."
- Before approve (inline hint): "Review every citation before approving — all N sources are listed."
- Reject dialog: "A comment is required. The report will be redrafted (round {n} of 3)."
- 4th reject: "Redraft limit reached — flagged for manual revision. It stays in the queue."
- Stale conflict toast: "This report was already actioned by someone else. Refreshing the view."
- Passage unavailable: "Passage unavailable — showing citation details only."
- Suspended acting-client banner: "This client is suspended — data is read-only."
- Trigger success toast: "Monitoring cycle queued for {watchlist}."

---

## 9. Accessibility checklist (v1 scope, FR-028)
- All interactive elements keyboard-reachable; visible focus ring everywhere.
- Reviewer actions operable by keyboard (Tab + Enter); dialogs trap focus; Esc closes drawer/dialog.
- ARIA labels on icon-only controls (sidebar collapsed, drawer close, theme toggle).
- AA contrast in light + dark for text and chips. Color never the sole signal (chips carry text +
  icon, not just hue). Live regions announce toasts.
- Out of scope (declared): full WCAG audit, screen-reader certification, mobile/touch layouts.

---

## 10. Implementation mapping (shadcn/ui + Tailwind)

### 10.1 shadcn components to install
`button · card · table · badge · dialog · alert-dialog (destructive confirm) · sheet (passage drawer) ·
dropdown-menu (user/acting-client/status filter) · tabs (admin console) · input · textarea · label ·
select · tooltip · toast (sonner) · skeleton · breadcrumb · popover (client switcher) · separator ·
scroll-area · avatar · switch (theme) · command (⌘K palette, FR-041) · checkbox (citation-review
toggle, FR-040) · progress`. Don't hand-roll these — install and theme via the tokens.

### 10.2 Icons
**lucide-react** only (ships with shadcn). Canonical set: queue `inbox` · all-reports `list` · admin
`settings` · dashboard `bar-chart-3` · audit `file-text` · portal/client `building-2` · download
`download` · approve `check` · reject `x` / `undo-2` · discard `trash-2` · edit `pencil` · grounded
`link` · attested `user` · aggregated `sigma` · SLA `clock` · overdue `alarm-clock` · expand/collapse
`panel-left` · drawer close `x` · search `search`. Icon-only buttons MUST carry `aria-label`.

### 10.3 Tailwind theme mapping
Wire the §2 CSS variables into `tailwind.config.ts` as `hsl(var(--…))` colors (shadcn convention):
`background, foreground, card, muted, border, input, ring, primary, secondary, accent, destructive`.
Add brand-fixed semantic colors as plain Tailwind scale refs (`red-600`, `amber-600`, `emerald-600`,
`slate-*`) — they don't flip with theme except via the `dark:` variants used in the chip recipes.
`darkMode: "class"`. Fonts: `sans: Inter`, `mono: JetBrains Mono`. Radius from §4.

### 10.4 Chip recipes (single source — build as a `<Chip variant tone>` component)
Each chip = `inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-xs font-medium ring-1
ring-inset` + a tone class. Tones (light → dark via `dark:`): emergency=red, urgent=amber,
minor/neutral/aggregated=slate, positive/approved/delivered=emerald, info/sent/grounded=blue/brand,
attested=teal. Map `ReportStatus`, `severity bucket`, `delivery_status`, and `provenance` enums →
tone via a lookup table so colors are defined once.

### 10.5 Z-index scale
`base 0 · sticky table header 10 · sidebar 20 · top bar 30 · dropdown/popover 40 · drawer/sheet 50 ·
dialog 60 · toast 70`. Don't invent ad-hoc z values.

### 10.6 Desktop breakpoints (no mobile layout, but graceful narrowing)
Design target ≥ 1280px. 1024–1280: sidebar defaults to icon-rail; passage drawer overlays the center
(absolute, not push) instead of taking a third column. < 1024: show a one-line "Best viewed on a
desktop display" notice (we do not build a mobile layout — FR-028). The detail screen never shows
sidebar + rail + center + drawer all pushed below ~1280; the drawer overlays.

### 10.7 Loading / skeleton specifics
- Lists/tables → `skeleton` rows (match column widths), 5–8 placeholder rows.
- Report detail → skeleton claim rows + a shimmer block for the narrative; citation list skeleton.
- Dashboard → per-card skeletons (don't block the whole grid on one slow card).
- In-place action (approve/reject) → button spinner + disable, label persists ("Approving…").
- Never a full-page spinner after first paint; never a blank region.

### 10.8 Forms & validation
Inputs use shadcn `input`/`select` with a `label` and helper/`error` text slot. Validate on blur +
submit; error state = red border + red helper text + `aria-invalid`. Save = optimistic-free: disable +
spinner, success toast on 2xx, inline error on 4xx (show the field-level message when the API returns
one). Required fields marked; destructive submits (Reject/Discard) always go through `alert-dialog`.

### 10.9 Formatting rules
- **IDs / refs**: mono, prefixed — chunk `#123`, `PMID:…`, `EMA-…`, `FAERS-…`.
- **Dates**: relative for recent ("2m ago", "1h ago"), absolute on hover/tooltip (ISO local). Cycle
  periods as "Jun 1–14".
- **Money**: `$0.41` (2-dp display; the API sends fixed-precision Decimal strings — render as-is, don't
  re-round). Tokens: grouped thousands, `tabular-nums`.
- **Counts/metrics**: `tabular-nums` everywhere they update.

### 10.10 Toasts (sonner)
Bottom-right, stack max 3, auto-dismiss 4s (errors 6s + manual close). One per user action, fired on
server confirmation. Copy = §8. Live-region announced for a11y.

### 10.11 Keyboard map (reviewer detail — the hot path)
`j/k` or ↑/↓ move finding selection (batch) · `Enter` open selected · `c` focus citation list ·
`a` approve (confirm) · `r` reject (opens dialog) · `e` edit · `Esc` close drawer/dialog. All also
reachable by Tab; shortcuts are additive, never the only path. Document them in a `?` help popover.

---

## 12. Safety-first interaction patterns (production hardening)

These are not polish — they shape the tool around the reviewer's safety job and map to constitution
principles. All are client-side (no backend cost) and scalable.

1. **Single primary action; Approve carries weight.** Exactly one Approve per context (in the sticky
   action bar, not duplicated in the header). Reject and Discard always confirm via `alert-dialog`.
   *(Principle I — the send authorization is deliberate.)*
2. **Citation-review tracking + soft approve gate (FR-040).** Each citation has a "reviewed" toggle;
   the detail shows "n of N sources reviewed". Approving with unreviewed sources triggers a soft
   confirm ("approve anyway? your decision is final") — never a hard block. Per-session, client-side.
   *(Principle II — grounding verification made explicit; Principle I — reviewer stays final.)*
3. **Provenance is three visibly distinct trust classes.** `grounded` = quiet/normal chip with link
   icon + `#chunk`; **`reviewer-added` (attested)** = dashed teal border + pencil icon + the words
   "reviewer-added" (must read as human-asserted, NOT AI-grounded); `aggregated` = slate Σ roll-up.
   A reviewer must never confuse AI-grounded with human-asserted content. *(Principle II.)*
4. **Revision/redraft history is visible on the detail (FR-008).** A compact "Revision history · round
   k of 3" panel lists prior rejection comments + who/when, so a reviewer on a redraft sees why it was
   sent back. Not hidden behind a click.
5. **Severity is loud in the queue.** Each row carries a severity-colored left bar (emergency red /
   urgent amber / minor slate / positive emerald); a persistent banner counts overdue expedited
   reports ("1 expedited report is overdue"). *(Principle III — a missed serious AE is the costliest
   error; it must be impossible to miss.)*
6. **Claim hierarchy.** Emphasize the load-bearing clinical fields (Drug, Reaction, Severity,
   Causality) above secondary fields; group rather than render one flat list.
7. **Disabled controls explain why.** Forward-dependency controls (Download FR-036, Audit export
   FR-037) render disabled with a tooltip stating the reason ("Available once the delivery layer
   ships"), never a bare greyed button that reads as broken.
8. **Batch summary header.** A batch report shows "N findings · x included · y dropped · z needs
   attention" so the reviewer knows the shape before stepping through findings.
9. **Trust stamps.** Show "drafted {ago} · last actioned by {who}" and data-freshness cues; this is a
   regulated audit context where provenance-of-action matters.
10. **Command palette (FR-041).** ⌘K to jump to a report by id, switch acting client, or navigate —
    an accelerator for high-volume reviewers, layered over (never replacing) normal nav. Build on the
    shadcn `command` component.

## 11. Static preview
`design-preview/index.html` — a throwaway single-file mockup (Tailwind Play CDN + lucide) showing the
shell, queue, **layout C** report detail (with working passage drawer + auto-collapsing sidebar),
manager dashboard, client portal, login, and dark-mode toggle. Open it directly in a browser to see
the design. It is NOT the build (the real SPA is React + shadcn/ui) and is excluded from the app.
