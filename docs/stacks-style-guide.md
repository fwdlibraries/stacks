# Stacks — Design & Style Guide

This document is the reference for the visual identity and design language of Stacks. It covers the logo, colour palette, typography, and UI component principles. Contributors building the frontend or creating project assets should use this as their source of truth.

---

## Table of Contents

1. [Logo](#1-logo)
2. [Colour Palette](#2-colour-palette)
3. [Typography](#3-typography)
4. [Iconography & Illustration Principles](#4-iconography--illustration-principles)
5. [UI Component Principles](#5-ui-component-principles)
6. [Voice & Tone](#6-voice--tone)
7. [Asset Locations](#7-asset-locations)

---

## 1. Logo

### Concept

The Stacks logo combines two elements: a **wordmark** set in Playfair Display, and a **custom icon mark** depicting book spines viewed from above. Two of the spines carry small digital details — a dot matrix row and a set of indicator lights — that hint at the platform's digital nature without abandoning the library aesthetic.

The underlying idea is a stack of books that has quietly become infrastructure.

### Icon Mark

The icon is built from five horizontal bars of varying width and colour, representing individual book spines. Two spines carry digital details:

- **Bottom spine (Ink Navy):** Three small circles at the right end, coloured green, amber, and dim navy. These read as system indicator lights — active, idle, off.
- **Third spine from bottom (Brass):** A row of eight dots at varying opacity across the face of the spine. The opacity pattern (low → high → low) suggests a data signal or barcode. It is intentionally ambiguous.

The remaining three spines are plain, ensuring the digital details read as accents rather than the dominant motif.

### Wordmark

Set in **Playfair Display SemiBold** at a tracking of −1. The capital S is the natural anchor; no modifications to the letterforms are made.

### Tagline

**COURSE READING LISTS** — set in **Libre Baskerville Regular** at 11.5px, tracked at +2.8 (approximately `letter-spacing: 2.8px`). Always in all-caps. Always in Warm Grey (`#8A7B68`).

The tagline is part of the full lockup only. It is omitted from the icon mark and from any application where space is constrained.

### Variants

| Variant | Use |
|---|---|
| Full lockup, light | Default. White/parchment backgrounds. README, documentation, website header. |
| Full lockup, dark | Dark backgrounds. Footer, dark-mode UI, presentation slides on dark backgrounds. |
| Icon mark only | Favicon, app icon, avatar, small UI contexts where the wordmark would be illegible. |

### Clear Space

Maintain a minimum clear space equal to the height of the letter "S" in the wordmark on all four sides of the full lockup. For the icon mark alone, use the height of one book spine as the minimum clear space unit.

### What Not To Do

- Do not recolour the logo outside the defined palette.
- Do not use the wordmark without the icon mark unless the icon has appeared in close proximity on the same surface.
- Do not place the light variant on a dark background or vice versa.
- Do not stretch, rotate, or apply drop shadows to the logo.
- Do not reproduce the logo smaller than 24px in height (icon mark) or 120px in width (full lockup).

---

## 2. Colour Palette

The palette is drawn from physical library materials — aged paper, ink, cloth bindings, brass hardware — with two functional additions (Active green, Deep Night) for UI use.

### Primary Colours

| Name | Hex | Usage |
|---|---|---|
| **Ink Navy** | `#2C3E5A` | Primary text, primary UI elements, main spine colour |
| **Parchment** | `#F7F4EF` | Default background, light variant logo background |
| **Warm Grey** | `#8A7B68` | Secondary text, captions, tagline, borders |

### Secondary / Accent Colours

| Name | Hex | Usage |
|---|---|---|
| **Brass** | `#B5843A` | Accent colour, highlights, the narrow accent spine in the logo |
| **Slate** | `#5C7A8C` | Secondary UI elements, links, top spine in the logo |
| **Forest** | `#4A6741` | Tertiary accent, success-adjacent contexts |

### Functional Colours

| Name | Hex | Usage |
|---|---|---|
| **Active** | `#5DBE7E` | Published/live status, success states, active indicator light |
| **Deep Night** | `#1C2A3A` | Dark mode background, dark variant logo background |
| **Sand** | `#D6C9B0` | Subtle borders, dividers, hover backgrounds, depth shadow in logo |

### Colour Usage Principles

**Dominance:** Ink Navy and Parchment carry the majority of any surface. Brass is the accent — it should appear sparingly and purposefully, never as a background fill for large areas.

**Status semantics:** Active green (`#5DBE7E`) is reserved for published/live states. Brass (`#B5843A`) naturally reads as "pending" or "in progress" given its amber character — lean into this in UI status indicators. Avoid introducing new semantic colours without updating this guide.

**Accessibility:** All text colour pairings must meet WCAG AA contrast (4.5:1 for normal text, 3:1 for large text). Approved pairings:
- Ink Navy on Parchment ✓
- Parchment on Ink Navy ✓
- Parchment on Deep Night ✓
- Warm Grey on Parchment — acceptable for secondary/caption text (large or UI context only, verify at intended size)

---

## 3. Typography

### Typefaces

| Role | Typeface | Weight | Source |
|---|---|---|---|
| Display / Wordmark | Playfair Display | SemiBold (600) | Google Fonts |
| Body / UI | Libre Baskerville | Regular (400), Bold (700) | Google Fonts |

Both typefaces are open source (OFL licence) and available via Google Fonts. They are also included as web font imports in the frontend.

**Rationale:** Playfair Display is a transitional serif with strong classical associations — used by academic publishers, literary journals, and institutional print. Libre Baskerville is a web-optimised version of Baskerville, highly legible at body sizes with good screen rendering. Together they read as authoritative and considered without being stiff.

### Type Scale

The frontend uses a modular scale based on a 1.25 ratio (Major Third) with a 16px base.

| Label | Size | Usage |
|---|---|---|
| `xs` | 11px | Badges, metadata labels, all-caps captions |
| `sm` | 13px | Secondary text, staff notes, timestamps |
| `base` | 16px | Body text, citation details |
| `lg` | 20px | Section headings |
| `xl` | 25px | Page headings |
| `2xl` | 31px | Display headings (used sparingly) |

### Tracking

- All-caps labels: `letter-spacing: 2.5px` to `3px` — opens up the letterspacing to improve legibility of capitalised text.
- Wordmark: `letter-spacing: -1px` — tightens the display-size text for a more refined, press-like appearance.
- Body and UI text: default (no tracking applied).

### Line Height

- Body text: `1.7` — generous leading for reading comfort.
- UI labels and headings: `1.3` — tighter, as these are short strings not reading text.

---

## 4. Iconography & Illustration Principles

### UI Icons

Use **Phosphor Icons** (the `phosphor-react` package). Phosphor is a flexible, consistent icon family with multiple weights (Thin, Light, Regular, Bold, Fill, Duotone). Default to **Regular** weight for most UI contexts; use **Bold** for primary actions; use **Duotone** for empty states.

Do not mix Phosphor with other icon libraries. Do not use emoji as UI icons.

### Illustration Style

If illustration is needed (empty states, onboarding, error pages), follow these principles:

- **Geometric, not figurative.** Shapes and abstract forms rather than characters or people.
- **Library-referential.** Books, shelves, cards, catalog drawers — the physical library is the visual vocabulary.
- **Sparse.** One or two elements with generous white space. Not diagrammatic, not decorative.
- **Colour-constrained.** Use two colours maximum from the palette, plus Parchment as the background. The Brass + Ink Navy combination is the natural first choice.

### The Digital Detail Principle

The logo establishes a design language where physical library objects quietly contain digital details. This principle can extend to illustrations and UI decoration — a data pattern on a spine, indicator dots on a shelf edge — but should always be:

- **Subtle.** The detail is discovered, not announced.
- **Purposeful.** It refers to something real (status, data, connectivity).
- **Restrained.** One digital detail per composition, not many.

---

## 5. UI Component Principles

Stacks uses React Bootstrap as its component library. The following principles govern how components are used and extended.

### General

- **Density:** Prefer comfortable density over compact. This is a tool used by librarians and instructors doing focused work, not a dashboard scanned at a glance. Give elements room to breathe.
- **Borders over shadows:** Use `#D6C9B0` (Sand) borders rather than box shadows for card and panel separation. Shadows are reserved for elevated elements (modals, dropdowns).
- **Rounded corners:** `border-radius: 4px` for cards, inputs, and badges. `border-radius: 2px` for small chips and tags. Never fully pill-shaped (`border-radius: 9999px`) except for status indicator dots.

### Cards (CitationCard)

The citation card is the primary UI unit of the product. It should:
- Display the resource type badge top-left.
- Display the title as the dominant element, linked if a URL is resolvable.
- Show bibliographic metadata in a single compact line (author · year · publisher), not a vertical stack of label/value pairs.
- Carry a clear visual hierarchy: title > metadata > notes > actions.
- In editor view only: show Edit/Delete actions, staff notes, and a drag handle.

### Badges

| Badge type | Colour |
|---|---|
| Book | Ink Navy (`primary`) |
| Book Chapter | Slate (`info`) |
| Journal Article | Forest (`success`) |
| eBook | Ink Navy (`primary`) |
| AV / Media | Brass (`warning`) |
| Website | Warm Grey (`secondary`) |
| Uploaded File | Muted red (`danger`) |
| Optional | Light with dark text |
| Published | Active green |
| Draft | Warm Grey |

### Status Indicators

Three-dot status indicators (modelled on the logo's indicator lights) are the preferred pattern for system status, import progress, and connection state. Use the Active (`#5DBE7E`) / Brass (`#B5843A`) / dim (`#3A5068`) colour set to maintain consistency with the logo.

### Forms

- Labels above inputs, always. No floating labels.
- Required fields: mark with a small asterisk in Warm Grey, not red.
- Error messages: below the input in a small (`13px`) red-adjacent colour. Do not use inline toast notifications for form validation errors.
- Submit buttons: full-width on mobile, auto-width on desktop, Ink Navy fill.

### Empty States

Every empty state needs:
1. A Phosphor icon (Duotone weight) in Warm Grey.
2. A single short heading in Playfair Display.
3. One sentence of body text explaining what goes here and how to add it.
4. A primary action button if one is available.

No illustration required for v0.1 empty states — the icon + text pattern is sufficient.

---

## 6. Voice & Tone

Stacks is used by librarians and instructors — professionals who are precise with language and sceptical of marketing copy. The UI text should reflect that.

### Principles

**Clear over clever.** Label things what they are. "Add citation" not "Add resource." "Reading list" not "list." "Import from catalog" not "Discover sources."

**Respectful of expertise.** Don't over-explain. A librarian knows what Z39.50 is. An instructor knows what a syllabus is. Avoid condescending tooltips and excessive onboarding copy.

**Specific over vague.** Error messages should say what went wrong and what to do. "DOI not found in CrossRef" is better than "Something went wrong." "3 of 12 citations need review" is better than "Import complete."

**Calm.** Even for errors. No exclamation marks in UI copy. No urgent language. No "Oops!" No "Uh oh!"

### Terminology

Use these terms consistently throughout the UI and documentation:

| Use | Not |
|---|---|
| Reading list | Course list, resource list, bibliography |
| Citation | Resource, item, record |
| Section | Group, module, week (unless user-named) |
| Import | Upload (for file imports), Fetch, Sync |
| Publish | Release, Share, Make live |
| Staff note | Internal note, Private note |
| Student note | Public note, Annotation |
| Organization | Institution, School, University |
| Librarian | (role name — use as-is) |
| Instructor | Teacher, Faculty, Professor |

---

## 7. Asset Locations

| Asset | Location in repository |
|---|---|
| Primary logo SVG (light, full lockup) | `frontend/public/logo.svg` |
| Logo preview HTML (all variants) | `docs/design/logo-preview.html` |
| Favicon (icon mark, 32×32) | `frontend/public/favicon.svg` |
| This style guide | `docs/design/style-guide.md` |

### Exporting the Logo for Other Uses

The SVG files are the master source. For contexts requiring raster formats:

- **PNG at 2× and 3×:** Export from the SVG at 960×320 (2×) and 1440×480 (3×) for high-DPI contexts.
- **Favicon ICO:** Generate from the 80×80 icon mark SVG at 16, 32, and 48px sizes.
- **Open Graph image:** 1200×630px, full lockup on Parchment background, centred with generous padding.

The fonts (Playfair Display, Libre Baskerville) must be embedded or the text converted to outlines for any export intended for use outside a web browser — otherwise the SVG will fall back to Georgia.
