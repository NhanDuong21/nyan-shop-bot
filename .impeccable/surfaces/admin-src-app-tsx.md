---
version: 1
slug: "admin-src-app-tsx"
primary_target: "admin/src/App.tsx"
related_targets: ["admin/index.html","admin/src/theme.ts","admin/src/styles.css","admin/src/features/catalog-visibility/CatalogVisibility.tsx"]
---

# Admin catalog surface

## Scope

- Primary target: `admin/src/App.tsx`
- Related targets: `admin/index.html`, `admin/src/theme.ts`, `admin/src/styles.css`, and `admin/src/features/catalog-visibility/**`
- Mode: Operate

## Task and constraints

The shop operator must identify the environment, scan the catalog, understand loading/error/empty/success state, retry a failed read, and deliberately choose a theme. Backend data and callbacks remain injected through Codex-owned contracts. The surface stays mock-only, localhost-only, and read-only.

## Direction contract

**THESIS:** A quiet operator console puts environment and catalog state ahead of decoration. It refuses the landing-page hero, oversized editorial headline, and card-gallery framing that make an admin tool feel promotional.

**OWN-WORLD:** Neutral canvas and raised work surfaces use one restrained blue action accent, cool slate text, one-pixel borders, modest 10–12px radii, and a system UI sans. Light is the first-load default; dark is a complete deliberate alternative using the same semantic tokens and hierarchy.

**STORY:** The operator immediately sees Nyan Shop Bot, MOCK/READ-ONLY safety, and the active catalog state; they inspect backend-derived items or take one clear recovery action. A compact theme control is persistent but secondary to the task.

**FIRST VIEWPORT:** A compact top bar holds product identity, safety badges, and the theme toggle. A short local-only notice precedes the catalog workspace. Headings stay fixed and workmanlike, content fills the available width, and the primary action appears only in the error state.

**FORM:** User-pinned basic admin console, code-led as a narrow foundation change; concept roll intentionally omitted because the brief fixes the mode and rejects alternate visual worlds. Seed key: `user-pinned-basic-admin`.

**FINISH:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
