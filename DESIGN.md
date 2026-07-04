---
version: alpha
name: DockLiner
description: A self-hosted Docker deployment manager with a warm industrial slate-and-amber identity. Designed for both desktop web dashboards and installed PWA/native shell use.
colors:
  # Brand / logo (Slate Ember)
  logo-text: "#f8fafc"
  logo-accent: "#f97316"

  # Primary action colors
  primary: "#f97316"
  primary-active: "#fb923c"
  primary-disabled: "#94a3b8"
  on-primary: "#0f172a"

  # Text colors
  ink: "#f8fafc"
  body: "#cbd5e1"
  body-strong: "#e2e8f0"
  muted: "#94a3b8"
  muted-soft: "#64748b"

  # Surface / background colors
  canvas: "#0f172a"
  surface-soft: "#1e293b"
  surface-card: "#334155"
  surface-cream-strong: "#475569"
  surface-dark: "#0f172a"
  surface-dark-elevated: "#1e293b"
  surface-dark-soft: "#1e293b"

  # Border / divider colors
  hairline: "#475569"
  hairline-soft: "#64748b"

  # Semantic colors
  success: "#22c55e"
  warning: "#f59e0b"
  error: "#ef4444"
  accent-teal: "#2dd4bf"
  accent-amber: "#f97316"

  # On-dark text (for dark surfaces)
  on-dark: "#f8fafc"
  on-dark-soft: "#94a3b8"

  # Derived component-specific
  danger-bg: "rgba(239, 68, 68, 0.15)"
  danger-bg-hover: "rgba(239, 68, 68, 0.25)"
  danger-border: "rgba(239, 68, 68, 0.3)"
  status-running-bg: "rgba(34, 197, 94, 0.12)"
  status-stopped-bg: "rgba(148, 163, 184, 0.12)"
  status-error-bg: "rgba(239, 68, 68, 0.12)"
  status-deploying-bg: "rgba(245, 158, 11, 0.12)"
  focus-glow: "rgba(249, 115, 22, 0.2)"
  toast-shadow: "rgba(0, 0, 0, 0.35)"
  modal-backdrop: "rgba(15, 23, 42, 0.6)"

  # Light-mode overrides (filled by theme layer)
  light-canvas: "#f8fafc"
  light-surface-soft: "#e2e8f0"
  light-surface-card: "#ffffff"
  light-ink: "#0f172a"
  light-body: "#334155"
  light-hairline: "#cbd5e1"

typography:
  display:
    fontFamily: "\"Cormorant Garamond\", \"Tiempos Headline\", Garamond, \"Times New Roman\", serif"
    fontWeight: 400
    lineHeight: 1.15
  h1:
    fontFamily: "{typography.display.fontFamily}"
    fontSize: 48px
    fontWeight: 400
    letterSpacing: "-1px"
  h2:
    fontFamily: "{typography.display.fontFamily}"
    fontSize: 28px
    fontWeight: 400
    letterSpacing: "-0.3px"
  body-md:
    fontFamily: "\"Inter\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.55
  body-sm:
    fontFamily: "{typography.body-md.fontFamily}"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
  label-caps:
    fontFamily: "{typography.body-md.fontFamily}"
    fontSize: 11px
    fontWeight: 500
    letterSpacing: "0.8px"
    textTransform: uppercase
  mono:
    fontFamily: "\"JetBrains Mono\", ui-monospace, monospace"
    fontSize: 12px
    lineHeight: 1.6

rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  app: 18px
  full: 9999px

spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  section: 32px

layout:
  max-width: 1200px
  sidebar-width: 64px
  sidebar-expanded: 180px
  nav-height: 64px
  bottom-nav-height: 64px
  app-radius: "{rounded.app}"

components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: "10px 18px"
  button-primary-hover:
    backgroundColor: "{colors.primary-active}"
  button-secondary:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.md}"
    padding: "10px 18px"
  button-danger:
    backgroundColor: "{colors.danger-bg}"
    textColor: "{colors.error}"
    border: "1px solid {colors.danger-border}"
    rounded: "{rounded.md}"
    padding: "10px 18px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.md}"
    padding: "10px 18px"
  card:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.body}"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.lg}"
    padding: 24px
  card-title:
    typography: "{typography.h2}"
    textColor: "{colors.ink}"
  metric-card:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.lg}"
    padding: 20px
  status-pill:
    typography: "{typography.label-caps}"
    rounded: "{rounded.full}"
    padding: "3px 10px"
  status-running:
    backgroundColor: "{colors.status-running-bg}"
    textColor: "#16a34a"
  status-stopped:
    backgroundColor: "{colors.status-stopped-bg}"
    textColor: "{colors.muted}"
  status-error:
    backgroundColor: "{colors.status-error-bg}"
    textColor: "{colors.error}"
  status-deploying:
    backgroundColor: "{colors.status-deploying-bg}"
    textColor: "#d97706"
  sidebar:
    backgroundColor: "rgba(15,23,42,0.98)"
    border: "1px solid rgba(100,116,139,0.25)"
    width: "{layout.sidebar-width}"
  sidebar-hover:
    width: "{layout.sidebar-expanded}"
  bottom-nav:
    backgroundColor: "rgba(15,23,42,0.92)"
    borderTopColor: "rgba(100,116,139,0.25)"
    height: "{layout.bottom-nav-height}"
  top-bar:
    backgroundColor: "rgba(15,23,42,0.92)"
    borderBottomColor: "rgba(100,116,139,0.25)"
    height: "{layout.nav-height}"
  modal-overlay:
    backgroundColor: "rgba(0,0,0,0.55)"
    backdropFilter: "blur(4px)"
  modal-box:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.body}"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.xl}"
    padding: 24px
    max-width: 360px
  input:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.md}"
    padding: "10px 14px"
    focusGlow: "{colors.focus-glow}"
  tag:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.muted}"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.full}"
    padding: "3px 10px"
  toast:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-dark}"
    border: "1px solid {colors.surface-dark-elevated}"
    rounded: "{rounded.md}"
    shadow: "0 4px 12px {colors.toast-shadow}"
---

## Overview

DockLiner is a self-hosted deployment manager for personal Docker projects.
Its visual identity — **Slate Ember** — pairs deep slate surfaces with a warm
amber accent, evoking a control room that is serious, trustworthy, and quietly
energetic. The UI must feel equally at home in a browser tab and as an installed
PWA/native shell: dense information should be readable, actions should be
thumb-friendly on mobile, and navigation should never scroll away.

## Brand

- **Logo:** container-rack SVG (`/static/img/logo_dark.svg` / `logo_light.svg`)
- **Wordmark:** “DockLiner” set in `Cormorant Garamond` (display serif)
- **Tone:** industrial, calm, confident, no gradients unless for depth in
  frosted overlays.

## Colors

The palette is intentionally narrow. All interactive energy comes from amber;
everything else is slate neutrals.

- **Primary / `{colors.primary}` (#f97316):** CTA buttons, active nav states,
  status indicators, focus rings.
- **Ink / `{colors.ink}` (#f8fafc):** Headlines, card titles, primary text.
- **Body / `{colors.body}` (#cbd5e1):** Body copy and secondary text.
- **Muted / `{colors.muted}` (#94a3b8):** Labels, placeholders, idle icons.
- **Canvas / `{colors.canvas}` (#0f172a):** Page background (dark).
- **Surface Soft / `{colors.surface-soft}` (#1e293b):** Sidebars, top/bottom bars,
  input backgrounds.
- **Surface Card / `{colors.surface-card}` (#334155):** Cards, panels, modals.
- **Hairline / `{colors.hairline}` (#475569):** Dividers, borders, outlines.
- **Error / `{colors.error}` (#ef4444):** Destructive actions and error states.
- **Success / `{colors.success}` (#22c55e):** Running/completed states.

Light mode inverts the surface stack while preserving the amber accent and
logo geometry.

## Typography

- **Display:** Cormorant Garamond for all headings (H1, H2, section titles).
- **Body / UI:** Inter for labels, buttons, tables, forms, nav labels.
- **Mono:** JetBrains Mono for hashes, IDs, logs, build output.
- Hierarchy is carried by size and weight, not by mixing multiple font families.

## Layout

- **Desktop:** a fixed left sidebar (64 px, expands to 180 px on hover) carries
  the four primary routes (Dashboard, Projects, Downloads, Settings). The
  content area is inset by the sidebar width and capped at 1200 px.
- **Mobile:** a fixed top bar (logo + theme toggle) and a fixed bottom nav bar
  replace the sidebar. Content is inset for both safe areas and nav heights.
- **Spacing scale:** 4 px baseline. `md` (12 px) for intra-component gaps,
  `lg` (16 px) for card gutters, `section` (32 px) for page sections.

## Shapes

- Cards and panels use `lg` (12 px) radius.
- Interactive elements use `md` (8 px).
- Pills, status badges, and avatars use `full`.
- On mobile, cards and buttons are promoted to `app` (18 px) for a native feel.

## Elevation & Depth

- No drop shadows on desktop cards; borders separate surfaces.
- Frosted-glass bars on mobile use `backdrop-filter: blur(12px)` and translucent
  dark/light backgrounds to avoid harsh edges against scrollable content.
- Modal overlays use a dark translucent scrim with a small blur.

## Components

- `button-primary` is the single high-emphasis action. Use it for Deploy,
  Create project, Add Project.
- `button-secondary` is for neutral actions: Cancel, Back, Edit.
- `button-danger` is for destructive actions: Delete, Remove.
- `card` is the default surface for grouped content.
- `metric-card` is the compact stat tile used in the dashboard summary.
- `status-pill` communicates state at a glance; always include the colored dot.
- `sidebar` and `bottom-nav` use the same four routes and the same active
  treatment (amber icon + pill background).
- `modal-box` replaces browser-native `alert()` / `confirm()` for destructive
  or blocking confirmations.
- `input` uses the surface-soft background and amber focus glow.

## Responsiveness

- Below 768 px: sidebar hides, mobile top/bottom bars appear, touch targets
  enlarge to at least 40 px, cards use the app radius.
- Above 768 px: sidebar is visible; top bar and bottom nav are hidden.
- Above 1024 px: content area centers at the 1200 px max width.

## Accessibility

- Focus rings use a 3 px amber glow (`--focus-glow`).
- Active states in nav and bottom nav combine both color and background change.
- Destructive modals are keyboard dismissible (Esc) and have explicit
  Cancel / Delete actions.

## Do's and Don'ts

- **Do** mutate only fill/stroke colors of the logo SVG, never its path geometry.
- **Do** use token references (`{colors.primary}`) instead of literal hex in
  component definitions.
- **Do** update both desktop sidebar and mobile bottom nav when the theme changes.
- **Don't** use browser `confirm()` / `alert()` for user-facing confirmations;
  use `modal-box` instead.
- **Don't** introduce colors outside the palette; extend the palette first.
- **Don't** nest component variants. `button-primary-hover` is a sibling, not a
  child.
