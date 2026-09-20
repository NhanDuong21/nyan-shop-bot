---
name: Nyan Shop Bot Admin
description: A quiet, light-first operator console that keeps mock safety and catalog truth visible.
colors:
  accent-light: "#175cd3"
  accent-dark: "#8ab4ff"
  canvas-light: "#f4f6f8"
  canvas-dark: "#0f141b"
  surface-light: "#ffffff"
  surface-dark: "#171e28"
  surface-subtle-light: "#edf1f5"
  surface-subtle-dark: "#202936"
  text-light: "#17202c"
  text-dark: "#edf2f7"
  text-muted-light: "#596574"
  text-muted-dark: "#aeb9c6"
  border-light: "#cbd3dc"
  border-dark: "#354252"
  success-light: "#176b45"
  success-dark: "#83d7ae"
  warning-light: "#815400"
  warning-dark: "#f6ca75"
  danger-light: "#a32828"
  danger-dark: "#ffaaaa"
typography:
  headline:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 700
    lineHeight: 1.2
  body:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 750
    lineHeight: 1.2
    letterSpacing: "0.03em"
rounded:
  xs: "0.375rem"
  sm: "0.5rem"
  md: "0.625rem"
  lg: "0.75rem"
  pill: "999px"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "0.75rem"
  lg: "1rem"
  xl: "1.25rem"
  2xl: "2rem"
components:
  retry-button:
    backgroundColor: "{colors.accent-light}"
    textColor: "{colors.surface-light}"
    rounded: "{rounded.md}"
    padding: "0.625rem 0.875rem"
    height: "2.75rem"
  theme-toggle:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.text-light}"
    rounded: "{rounded.md}"
    padding: "0.625rem 0.875rem"
    height: "2.75rem"
  safety-badge:
    backgroundColor: "#fff3d6"
    textColor: "{colors.warning-light}"
    rounded: "{rounded.xs}"
    padding: "0.375rem 0.5rem"
  catalog-filter:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.text-light}"
    rounded: "{rounded.md}"
    padding: "0.625rem 0.75rem"
    height: "2.75rem"
---

# Design System: Nyan Shop Bot Admin

## Overview

**Creative North Star: "The Quiet Operator Console"**

The admin is a work surface for reading operational truth, not a promotional destination. Its first viewport establishes product identity, MOCK and READ-ONLY safety, the active environment, and catalog state before offering any secondary control.

Light is the deliberate first-load default. Dark is an equally complete operator choice that preserves the same semantic hierarchy. Decoration stays subordinate to scanning, recovery, and keyboard use.

**Key Characteristics:**

- Compact, workmanlike hierarchy with no hero treatment.
- Cool neutral surfaces with one restrained blue action accent.
- Persistent safety labels and concise Vietnamese operational copy.
- Flat-by-default containers, one-pixel borders, and modest corners.
- Labeled mobile data cards derived from the desktop table.

## Colors

The palette uses cool neutrals for the work surface, operational blue for action and focus, and semantic green, amber, and red only where state requires them.

### Primary

- **Operational Blue** (`accent-light` / `accent-dark`): focus, the product mark, and the single recovery action.

### Neutral

- **Cool Canvas** (`canvas-light` / `canvas-dark`): page ground behind the work surface.
- **Work Surface** (`surface-light` / `surface-dark`): app bar, controls, tables, cards, menus, and dialogs.
- **Quiet Surface** (`surface-subtle-light` / `surface-subtle-dark`): table headings, mobile item headers, and inactive badges.
- **Slate Ink** (`text-light` / `text-dark`): primary readable text.
- **Muted Slate** (`text-muted-light` / `text-muted-dark`): descriptions, metadata, and secondary labels.

### Named Rules

**The One Accent Rule.** Blue communicates action and focus; it does not decorate passive surfaces.

**The Light-First Rule.** A missing, invalid, unreadable, or unsavable preference resolves to light, independent of operating-system theme.

## Typography

**Display Font:** None; this operator surface has no display role.
**Body Font:** System UI sans with native platform fallbacks.

**Character:** Familiar, compact, and legible. Weight and spacing establish hierarchy without importing a decorative type personality.

### Hierarchy

- **Headline** (700, 1.75rem, 1.2): the catalog workspace title.
- **Title** (700, 1rem, 1.2): product identity, item names, and state titles.
- **Body** (400, 1rem, 1.5): operator guidance and data descriptions, normally constrained near 68ch.
- **Label** (750, 0.75rem, 0.03em, uppercase where tabular): badges, table headings, and mobile field labels.

### Named Rules

**The Workmanlike Scale Rule.** Headings orient; they never grow into marketing copy or dominate the catalog data.

## Layout

The app bar and catalog workspace share a 72rem maximum width with 1rem minimum side gutters. The desktop catalog uses a conventional five-column table. At 640px and below, each row becomes a bordered detail card and repeats its labels so product, supplier, stock, mock price, and availability remain visible without horizontal hunting.

The app bar stacks at 520px and preserves MOCK, READ-ONLY, and the theme control. The catalog heading stacks at 640px; the filter expands to the available width. Spacing follows a compact 0.25rem–2rem rhythm, with 4rem reserved for workspace bottom breathing room.

**The Labels Travel With Data Rule.** Responsive reflow may change presentation, but it never separates a value from a visible label.

## Elevation & Depth

The system is flat by default. Borders and tonal surface changes define tables, cards, controls, menus, and dialogs; a soft ambient shadow is reserved for genuinely raised overlays such as dialogs, never combined with the catalog table border.

### Shadow Vocabulary

- **Raised Overlay** (`0 8px 24px rgb(23 32 44 / 8%)` in light; `0 10px 28px rgb(0 0 0 / 24%)` in dark): dialogs and equivalent overlays only.

### Named Rules

**The Single Elevation Rule.** A component uses border/tonal separation or raised shadow according to its role, not both for extra decoration.

## Shapes

Controls and compact notices use gently curved 0.625rem corners. Tables, cards, state panels, menus, and dialogs use 0.75rem corners. Small badges use 0.375rem corners; scrollbar thumbs alone use the pill radius. One-pixel borders remain the normal structural edge.

## Components

### Buttons

- **Shape:** compact rounded control (0.625rem) with a 2.75rem minimum height.
- **Primary:** operational-blue background with high-contrast text; used only for recovery such as retry.
- **Hover / Focus:** hover changes to the stronger accent; keyboard focus uses a three-pixel visible ring with a two-pixel offset.
- **Theme Toggle:** neutral surface and border; its label names the current explicit choice and its accessible name states the next action.

### Chips

- **Style:** MOCK uses amber; READ-ONLY uses a quiet neutral; availability uses green or red semantic surfaces.
- **State:** safety chips remain visible on every viewport and are never interactive.

### Cards / Containers

- **Corner Style:** modest 0.75rem rounding.
- **Background:** work surface at rest, quiet surface for mobile item headers.
- **Shadow Strategy:** none for catalog data and state panels.
- **Border:** one-pixel semantic border.
- **Internal Padding:** normally 0.75rem–1.25rem according to density.

### Inputs / Fields

- **Style:** work-surface fill, strong semantic border, 0.625rem radius, and 2.75rem minimum height.
- **Focus:** operational-blue three-pixel outline; caret uses the same accent.
- **Placeholder:** muted semantic text in both themes.
- **Error / Disabled:** semantic danger or disabled surface/text tokens, never opacity alone.

### Navigation

The compact app bar is identity and environment context rather than route promotion. At narrow widths it stacks into two rows while retaining every safety control.

### Responsive Catalog

Desktop uses a dense semantic table. Mobile keeps the same table semantics in markup while presenting each row as a labeled detail card; the content still comes only from the injected catalog state.

## Do's and Don'ts

### Do:

- **Do** show MOCK, READ-ONLY, localhost-only, and no-purchase truth before catalog actions.
- **Do** preserve loading, error, empty, filtered-empty, and success states in both themes.
- **Do** use concise Vietnamese labels, visible keyboard focus, and labeled responsive data.
- **Do** use semantic tokens for browser surfaces, including scrollbar, placeholder, and caret.

### Don't:

- **Don't** add a marketing hero, oversized editorial headline, 3D/neon treatment, heavy glass, or looping motion.
- **Don't** infer theme from the operating system or allow storage failure to leave a dark preference active.
- **Don't** hide safety state or operational fields to make a narrow layout look cleaner.
- **Don't** replace backend-injected catalog items with decorative hard-coded products.
