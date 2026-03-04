"""
Generate all Stacks logo PNG variants from scratch using PIL.
Replicates the SVG geometry exactly, with font fallback to a system serif.
"""

from PIL import Image, ImageDraw, ImageFont
import os

# ── Colour palette ────────────────────────────────────────────────────────────
PARCHMENT  = (247, 244, 239)
INK_NAVY   = ( 44,  62,  90)
SLATE      = ( 92, 122, 140)
FOREST     = ( 74, 103,  65)
BRASS      = (181, 132,  58)
WARM_GREY  = (138, 123, 104)
SAND       = (214, 201, 176)
ACTIVE     = ( 93, 190, 126)
AMBER      = (201, 154,  74)
DIM_NAVY   = ( 58,  80, 104)
DEEP_NIGHT = ( 28,  42,  58)

# Light slate variants for dark background
SLATE_LT   = (123, 163, 192)
FOREST_LT  = (106, 148,  96)
BRASS_LT   = (201, 154,  74)
NAVY_LT    = (123, 163, 192)
SLATE_LLT  = (168, 196, 212)

OUT = "/home/claude/stacks-assets/docs/design/assets/logo"


def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def blend(colour, alpha, bg):
    """Alpha-composite colour onto bg."""
    a = alpha
    return tuple(int(c * a + b * (1 - a)) for c, b in zip(colour, bg))


def rounded_rect(draw, x, y, w, h, r, fill):
    """Draw a rounded rectangle, clamping r to avoid degenerate geometry."""
    r = min(r, w // 2, h // 2)
    if r <= 0:
        draw.rectangle([x, y, x + w, y + h], fill=fill)
        return
    draw.rectangle([x + r, y, x + w - r, y + h], fill=fill)
    draw.rectangle([x, y + r, x + w, y + h - r], fill=fill)
    draw.ellipse([x, y, x + 2*r, y + 2*r], fill=fill)
    draw.ellipse([x + w - 2*r, y, x + w, y + 2*r], fill=fill)
    draw.ellipse([x, y + h - 2*r, x + 2*r, y + h], fill=fill)
    draw.ellipse([x + w - 2*r, y + h - 2*r, x + w, y + h], fill=fill)


def draw_icon(draw, ox, oy, scale, bg, dark=False):
    """
    Draw the icon mark.
    ox, oy: top-left origin offset
    scale: multiplier (SVG icon viewBox is 80×80)
    dark: use light-on-dark palette
    """
    s = scale

    def rr(x, y, w, h, r, fill):
        rounded_rect(draw,
            ox + int(x*s), oy + int(y*s),
            int(w*s), int(h*s),
            max(1, int(r*s)), fill)

    def dot(cx, cy, r, colour, opacity=1.0):
        actual_colour = blend(colour, opacity, bg)
        x0 = ox + int((cx - r) * s)
        y0 = oy + int((cy - r) * s)
        x1 = ox + int((cx + r) * s)
        y1 = oy + int((cy + r) * s)
        draw.ellipse([x0, y0, x1, y1], fill=actual_colour)

    if dark:
        c5 = NAVY_LT;   c4 = FOREST_LT; c3 = BRASS_LT
        c2 = NAVY_LT;   c1 = SLATE_LLT
        dm_dot = DEEP_NIGHT
        dm_bg  = bg
    else:
        c5 = INK_NAVY;  c4 = FOREST;    c3 = BRASS
        c2 = INK_NAVY;  c1 = SLATE
        dm_dot = PARCHMENT
        dm_bg  = bg

    # Book 5 — bottom, widest, indicator dots
    rr(12, 54, 56, 10, 2, c5)
    dot(59, 59, 2.2, ACTIVE)
    dot(53, 59, 2.2, AMBER)
    dot(47, 59, 2.2, DIM_NAVY if not dark else (44, 74, 100))

    # Book 4 — forest
    rr(14, 42, 48, 9, 2, c4)

    # Book 3 — brass, dot matrix
    rr(17, 32, 30, 8, 2, c3)
    opacities = [0.5, 0.5, 0.9, 0.9, 0.3]
    xs = [22, 27, 32, 37, 42]
    for cx, op in zip(xs, opacities):
        dot(cx, 36, 1.2, dm_dot, op)

    # Book 2 — navy
    rr(14, 21, 44, 9, 2, c2)

    # Book 1 — slate, top
    rr(12, 10, 52, 9, 2, c1)


def try_font(size):
    """Try to load a serif font, fall back gracefully."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def try_font_regular(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def draw_wordmark(draw, x, y, scale, colour, tagline_colour):
    """Draw wordmark and tagline text."""
    font_size = max(8, int(58 * scale))
    tag_size  = max(6, int(11.5 * scale))

    font_word = try_font(font_size)
    font_tag  = try_font_regular(tag_size)

    draw.text((x, y - int(font_size * 0.85)), "Stacks",
              font=font_word, fill=colour)
    draw.text((x + int(2 * scale), y + int(6 * scale)),
              "COURSE READING LISTS",
              font=font_tag, fill=tagline_colour)


# ── 1. Full lockup — light, 1× (480×160) ─────────────────────────────────────
def make_full_light(scale=1):
    W, H = int(480 * scale), int(160 * scale)
    img = Image.new("RGB", (W, H), PARCHMENT)
    draw = ImageDraw.Draw(img)

    # Depth shadow
    shadow_colour = blend(SAND, 0.4, PARCHMENT)
    rounded_rect(draw,
        int(32*scale), int(42*scale),
        int(72*scale), int(76*scale),
        max(1, int(3*scale)), shadow_colour)

    # Icon (80×80 space, offset to match SVG at 28,58 origin area)
    draw_icon(draw, int(0*scale), int(42*scale), scale, PARCHMENT, dark=False)

    # Wordmark
    draw_wordmark(draw, int(132*scale), int(102*scale), scale,
                  INK_NAVY, WARM_GREY)

    return img


# ── 2. Full lockup — dark, 1× (480×160) ──────────────────────────────────────
def make_full_dark(scale=1):
    W, H = int(480 * scale), int(160 * scale)
    img = Image.new("RGB", (W, H), DEEP_NIGHT)
    draw = ImageDraw.Draw(img)

    shadow_colour = blend((58, 80, 104), 0.4, DEEP_NIGHT)
    rounded_rect(draw,
        int(32*scale), int(42*scale),
        int(72*scale), int(76*scale),
        max(1, int(3*scale)), shadow_colour)

    draw_icon(draw, int(0*scale), int(42*scale), scale, DEEP_NIGHT, dark=True)

    PARCHMENT_TEXT = (238, 232, 223)
    MUTED_SLATE    = (138, 155, 170)
    draw_wordmark(draw, int(132*scale), int(102*scale), scale,
                  PARCHMENT_TEXT, MUTED_SLATE)

    return img


# ── 3. Icon mark — light (80×80) ─────────────────────────────────────────────
def make_icon_light(scale=1):
    W, H = int(80*scale), int(80*scale)
    img = Image.new("RGB", (W, H), PARCHMENT)
    draw = ImageDraw.Draw(img)
    draw_icon(draw, 0, 0, scale, PARCHMENT, dark=False)
    return img


# ── 4. Icon mark — dark (80×80) ──────────────────────────────────────────────
def make_icon_dark(scale=1):
    W, H = int(80*scale), int(80*scale)
    img = Image.new("RGB", (W, H), DEEP_NIGHT)
    draw = ImageDraw.Draw(img)
    draw_icon(draw, 0, 0, scale, DEEP_NIGHT, dark=True)
    return img


# ── 5. Favicon — transparent bg, icon only (80×80 → various sizes) ────────────
def make_favicon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # Draw on a parchment bg first, then composite
    bg_img = Image.new("RGB", (size, size), PARCHMENT)
    draw = ImageDraw.Draw(bg_img)
    scale = size / 80
    draw_icon(draw, 0, 0, scale, PARCHMENT, dark=False)
    return bg_img


# ── Generate all variants ─────────────────────────────────────────────────────

svg_dir = f"{OUT}/svg"
png_dir = f"{OUT}/png"
fav_dir = "/home/claude/stacks-assets/docs/design/assets/favicon"

print("Generating PNGs...")

# Full lockup light — 1×, 2×, 3×
for scale, suffix in [(1, "1x"), (2, "2x"), (3, "3x")]:
    img = make_full_light(scale)
    img.save(f"{png_dir}/stacks-logo-light-{suffix}.png")
    print(f"  ✓ stacks-logo-light-{suffix}.png  {img.size}")

# Full lockup dark — 1×, 2×, 3×
for scale, suffix in [(1, "1x"), (2, "2x"), (3, "3x")]:
    img = make_full_dark(scale)
    img.save(f"{png_dir}/stacks-logo-dark-{suffix}.png")
    print(f"  ✓ stacks-logo-dark-{suffix}.png   {img.size}")

# Icon mark light — 1×, 2×, 3×
for scale, suffix in [(1, "1x"), (2, "2x"), (3, "3x")]:
    img = make_icon_light(scale)
    img.save(f"{png_dir}/stacks-icon-light-{suffix}.png")
    print(f"  ✓ stacks-icon-light-{suffix}.png  {img.size}")

# Icon mark dark — 1×, 2×, 3×
for scale, suffix in [(1, "1x"), (2, "2x"), (3, "3x")]:
    img = make_icon_dark(scale)
    img.save(f"{png_dir}/stacks-icon-dark-{suffix}.png")
    print(f"  ✓ stacks-icon-dark-{suffix}.png   {img.size}")

# Favicon sizes
for size in [16, 32, 48, 64]:
    img = make_favicon(size)
    img.save(f"{fav_dir}/favicon-{size}x{size}.png")
    print(f"  ✓ favicon-{size}x{size}.png")

# OG image — 1200×630, full lockup centred on parchment
og = Image.new("RGB", (1200, 630), PARCHMENT)
logo = make_full_light(scale=2)  # 960×320
x = (1200 - logo.width) // 2
y = (630 - logo.height) // 2
og.paste(logo, (x, y))
og.save(f"{png_dir}/stacks-og-image.png")
print(f"  ✓ stacks-og-image.png  {og.size}")

print("\nAll PNGs done.")
