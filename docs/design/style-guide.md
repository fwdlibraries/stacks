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

The interface is neutral and modern: cool greys, white panels and one blue accent. (The parchment, ink and brass palette from earlier versions now belongs to the logo only; see "Logo palette" below. Organizations can still recreate it under Look and feel › Custom, where the classic serif fonts remain available.)

### Interface colours

| Name | Hex | Usage | Contrast |
|---|---|---|---|
| **Ink** | `#1B2433` | Body text, headings | 14.5:1 on Page |
| **Muted** | `#5B6676` | Secondary text, captions, table headers, sidebar group labels | 5.4:1 on Page |
| **Page** | `#F5F7FA` | Page background | |
| **Surface** | `#FFFFFF` | Cards, panels, menus, the top bar and the admin sidebar | |
| **Line** | `#E3E7ED` | Borders and dividers between panels | |
| **Field line** | `#7D8797` | Form field borders | 3.6:1 on white (WCAG 1.4.11) |
| **Header fill** | `#F8F9FB` | Table header rows, notes, hover backgrounds | |
| **Accent** | `#1F62B8` | Links, primary buttons, active navigation, focus | 6.0:1 on white |

### Status colours

| Name | Hex | Bootstrap role | Used for |
|---|---|---|---|
| Green | `#1D7A46` | `success`, `published` | Published, completed, connected |
| Amber | `#A15C00` | `warning` | Needs attention, pending |
| Red | `#B42318` | `danger` | Failed, destructive actions |
| Teal | `#0E6F8A` | `info` | Informational |

### Colour Usage Principles

**One accent.** Blue carries everything interactive. Don't introduce a second accent colour; status colours are for status only.

**Never colour alone.** A status dot or tinted badge always comes with a word ("Failed", "Hidden in catalogue").

**Accessibility:** every text pairing meets WCAG 2.1 AA (4.5:1 for normal text), and form field borders meet 3:1. `backend/tests/test_theme.py` checks the default tokens and each Match LMS look; the Look and feel screen warns organizations whose own colours fall short.

### Logo palette

The logo keeps its original colours: Ink Navy `#2C3E5A`, Slate `#5C7A8C`, Brass `#B5843A`, Parchment `#F7F4EF`, Sand `#D6C9B0` and Deep Night `#1C2A3A`. Use them for the logo and brand assets, not for interface elements.

---

## 3. Typography

### Typefaces

| Role | Typeface | Weight | Source |
|---|---|---|---|
| Interface and headings | Inter | Variable (400–700; headings 650) | `@fontsource-variable/inter`, bundled |
| Logo wordmark | Playfair Display | SemiBold (600) | Logo artwork only |

Fonts are bundled with the frontend and never loaded from a font CDN: pages embedded in an LMS shouldn't tell third parties who is reading what, and the page policy blocks outside font requests anyway.

### Type Scale

16px base, so reading lists stay comfortable for students.

| Label | Size | Usage |
|---|---|---|
| `xs` | 12px | Badges, all-caps labels |
| `sm` | 14px | Secondary text, tables, navigation, notes |
| `base` | 16px | Body text, citation details |
| `h3` | 18px | Section headings on a reading list |
| `h2` | 22px | Panel and page sub-headings |
| `h1` | 28px | Page headings |

### Tracking and line height

- Headings: `letter-spacing: -0.01em`, line height 1.25.
- All-caps labels (`.text-caps`): `letter-spacing: 0.05em`, 12px, weight 600, in Muted.
- Body text: line height 1.55. Numbers in tables and stat tiles use tabular figures (`.tabular-nums`).

---

## 4. Iconography & Illustration Principles

### UI Icons

Use **Phosphor Icons** (the `@phosphor-icons/react` package, the maintained successor to `phosphor-react`). Phosphor is a flexible, consistent icon family with multiple weights (Thin, Light, Regular, Bold, Fill, Duotone). Default to **Regular** weight for most UI contexts; use **Bold** for primary actions; use **Duotone** for empty states.

Do not mix Phosphor with other icon libraries. Do not use emoji as UI icons.

### Illustration Style

If illustration is needed (empty states, onboarding, error pages), follow these principles:

- **Geometric, not figurative.** Shapes and abstract forms rather than characters or people.
- **Library-referential.** Books, shelves, cards, catalog drawers — the physical library is the visual vocabulary.
- **Sparse.** One or two elements with generous white space. Not diagrammatic, not decorative.
- **Colour-constrained.** Use the accent plus greys; at most one status colour where it means something.

### The Digital Detail Principle

The logo establishes a design language where physical library objects quietly contain digital details. This principle can extend to illustrations and UI decoration — a data pattern on a spine, indicator dots on a shelf edge — but should always be:

- **Subtle.** The detail is discovered, not announced.
- **Purposeful.** It refers to something real (status, data, connectivity).
- **Restrained.** One digital detail per composition, not many.

---

## 5. UI Component Principles

Stacks uses React Bootstrap as its component library. The following principles govern how components are used and extended.

### General

- **Density:** Prefer comfortable density over compact. Give elements room to breathe.
- **Borders over shadows:** White panels on the grey page, separated by 1px Line (`#E3E7ED`) borders, no shadows. Shadows are reserved for elevated elements (modals, dropdowns).
- **Rounded corners:** 6px for buttons and inputs, 8px for cards and panels. Badges are pills.
- **Layout:** Administration uses a left sidebar (grouped: Settings, Courses, People, Insights) that moves above the content on small screens. Reading lists are a single column of cards with an "On this list" section index beside them (above them on phones) when there is more than one section.
- **Stat tiles:** a small all-caps label, a large tabular number, and one line of context.

### Cards (CitationCard)

The citation card is the primary UI unit of the product. It should:
- Display the resource type badge top-left.
- Display the title as the dominant element, linked if a URL is resolvable.
- Show bibliographic metadata in a single compact line (author · year · publisher), not a vertical stack of label/value pairs.
- Carry a clear visual hierarchy: title > metadata > notes > actions.
- Show the student note in a Header fill box, and the link ("Find at library", "View via DOI", "View online") as a small primary button (an outline button in the editor, where clicks are previews).
- In editor view only: show Edit/Delete actions, staff notes, and a drag handle.

### Badges

Badges are soft pills: a light tint of the colour with dark text of the same hue, so each one passes AA. Organizations' own primary colours get matching tints from theme.css.

| Badge type | Bootstrap colour |
|---|---|
| Book, eBook | `primary` (blue) |
| Book Chapter | `info` (teal) |
| Journal Article | `success` (green) |
| AV / Media | `warning` (amber) |
| Website | `secondary` (grey) |
| Uploaded File | `danger` (red) |
| Optional, Library record | `light`: outlined, grey text |
| Published | `published` (green) |
| Draft | `secondary` |

### Status Indicators

Use a small status dot (`.stacks-dot` with `bg-success`, `bg-warning`, `bg-danger` or `bg-secondary`) beside a heading and a sentence that says the status in words, as on the Reports catalogue sync panel.

### Forms

- Labels above inputs, always. No floating labels.
- Required fields: mark with a small asterisk in Muted, not red.
- Error messages: below the input in a small (`13px`) red-adjacent colour. Do not use inline toast notifications for form validation errors.
- Submit buttons: full-width on mobile, auto-width on desktop, Accent fill.

### Empty States

Every empty state needs:
1. A Phosphor icon (Duotone weight) in Muted.
2. A single short heading.
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
