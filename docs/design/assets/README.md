# Stacks — Design Assets

This directory contains all official logo and favicon assets for the Stacks project.

For usage rules, colour values, and typography guidance, see the [style guide](../style-guide.md).

---

## Directory Structure

```
assets/
├── logo/
│   ├── svg/
│   │   ├── stacks-logo-light.svg     Full lockup, light background
│   │   ├── stacks-logo-dark.svg      Full lockup, dark background
│   │   ├── stacks-icon-light.svg     Icon mark only, light background
│   │   └── stacks-icon-dark.svg      Icon mark only, dark background
│   └── png/
│       ├── stacks-logo-light-1x.png  480×160
│       ├── stacks-logo-light-2x.png  960×320
│       ├── stacks-logo-light-3x.png  1440×480
│       ├── stacks-logo-dark-1x.png   480×160
│       ├── stacks-logo-dark-2x.png   960×320
│       ├── stacks-logo-dark-3x.png   1440×480
│       ├── stacks-icon-light-1x.png  80×80
│       ├── stacks-icon-light-2x.png  160×160
│       ├── stacks-icon-light-3x.png  240×240
│       ├── stacks-icon-dark-1x.png   80×80
│       ├── stacks-icon-dark-2x.png   160×160
│       ├── stacks-icon-dark-3x.png   240×240
│       └── stacks-og-image.png       1200×630 Open Graph image
└── favicon/
    ├── favicon.svg                   Transparent background, scalable
    ├── favicon-16x16.png
    ├── favicon-32x32.png
    ├── favicon-48x48.png
    └── favicon-64x64.png
```

## Which File to Use

| Context | File |
|---|---|
| README header, documentation | `logo/svg/stacks-logo-light.svg` |
| Dark background (slides, footer) | `logo/svg/stacks-logo-dark.svg` |
| GitHub social preview / OG meta tag | `logo/png/stacks-og-image.png` |
| Browser favicon | `favicon/favicon.svg` (modern) or `favicon/favicon-32x32.png` (legacy) |
| App icon, avatar | `logo/svg/stacks-icon-light.svg` |
| Retina displays | Use the `-2x` or `-3x` PNG variants |

## Deployed Locations

The following files are copied into the frontend at build time and should be kept in sync with the source SVGs here:

| Source | Frontend destination |
|---|---|
| `logo/svg/stacks-logo-light.svg` | `frontend/public/logo.svg` |
| `favicon/favicon.svg` | `frontend/public/favicon.svg` |
| `favicon/favicon-32x32.png` | `frontend/public/favicon.png` |

## Regenerating PNGs

If the SVGs are updated, regenerate all PNGs by running:

```bash
python3 scripts/generate-logos.py
```

The source script lives at `scripts/generate-logos.py` in the repository root.
