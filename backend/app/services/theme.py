"""Per-organization look and feel.

Three modes:
- stacks: the standard Stacks theme (compiled into the frontend), plus an optional logo
- lms:    match the LMS (Brightspace, Canvas or Moodle; "auto" uses the LMS people
          launch from), with the organization's own primary color on top
- custom: theme tokens (colors, fonts, corners) and, optionally, custom CSS

The frontend compiles the Stacks theme with Bootstrap; organizations restyle it at
runtime by overriding Bootstrap's CSS variables from /api/v1/tenant/theme.css, so
no per-organization build is needed. Generated selectors are prefixed with `html`
so they win over the bundled CSS wherever the stylesheet lands in <head>.

Custom CSS is contained: organization-wide admins only, size-limited, and refused
if it could load anything (@import, url(), legacy script hooks). Pages also carry a
Content-Security-Policy that only allows images, fonts and requests from Stacks
itself (tenancy.page_policy), so even CSS that slipped through couldn't send data
anywhere else.
"""
import base64
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FONTS: dict[str, tuple[str, str]] = {
    # key: (label, CSS font stack). Only self-hosted or system fonts: the page
    # policy blocks font downloads from anywhere else.
    "stacks-serif": ("Libre Baskerville (Stacks)", '"Libre Baskerville", Georgia, serif'),
    "stacks-display": ("Playfair Display (Stacks headings)", '"Playfair Display", Georgia, serif'),
    "system-sans": ("System sans-serif", 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'),
    "system-serif": ("System serif", 'Georgia, Cambria, "Times New Roman", Times, serif'),
    # Bundled with the frontend (OFL), for the LMS looks
    "lato": ("Lato", '"Lato", "Lucida Sans Unicode", "Lucida Grande", "Helvetica Neue", Helvetica, Arial, sans-serif'),
    "noto-sans": ("Noto Sans", '"Noto Sans", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'),
}

CORNERS = {"square": ("0", "0", "0"), "standard": ("4px", "2px", "6px"), "rounded": ("8px", "6px", "12px")}

MAX_CUSTOM_CSS = 50_000
MAX_LOGO_BYTES = 200_000
LOGO_TYPES = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff", "image/webp": b"RIFF"}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary: str = "#2C3E5A"  # buttons, active states
    link: str = "#5C7A8C"
    background: str = "#F7F4EF"  # page
    surface: str = "#FFFFFF"  # cards, panels, menus
    text: str = "#2C3E5A"
    border: str = "#D6C9B0"
    heading_font: str = "stacks-display"
    body_font: str = "stacks-serif"
    corners: Literal["square", "standard", "rounded"] = "standard"

    @field_validator("primary", "link", "background", "surface", "text", "border")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not _HEX.match(value):
            raise ValueError("Colors must look like #2C3E5A")
        return value.upper()

    @field_validator("heading_font", "body_font")
    @classmethod
    def _font(cls, value: str) -> str:
        if value not in FONTS:
            raise ValueError(f"Choose one of: {', '.join(FONTS)}")
        return value


class ThemeSettings(BaseModel):
    """organizations.settings['theme'] (the logo is stored separately)."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["stacks", "lms", "custom"] = "stacks"
    lms: Literal["auto", "brightspace", "canvas", "moodle"] = "auto"
    # LMS mode: the institution's main color over the vendor look (LMSs are usually rebranded)
    lms_primary: str | None = None
    tokens: ThemeTokens = Field(default_factory=ThemeTokens)
    custom_css: str = Field(default="", max_length=MAX_CUSTOM_CSS)

    @field_validator("lms_primary")
    @classmethod
    def _lms_primary(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not _HEX.match(value):
            raise ValueError("Colors must look like #2C3E5A")
        return value.upper()

    @field_validator("custom_css")
    @classmethod
    def _contained(cls, value: str) -> str:
        problems = css_problems(value)
        if problems:
            raise ValueError("Custom CSS can't contain " + ", ".join(problems))
        return value


# Anything that could load a resource or run code. CSS can't send data anywhere
# without loading something, so refusing these (plus the page policy) contains it.
_FORBIDDEN = [
    (re.compile(r"@import", re.I), "@import"),
    (re.compile(r"url\s*\(", re.I), "url(…)"),
    (re.compile(r"image-set\s*\(", re.I), "image-set(…)"),
    (re.compile(r"@font-face", re.I), "@font-face"),
    (re.compile(r"expression\s*\(", re.I), "expression(…)"),
    (re.compile(r"javascript\s*:", re.I), "javascript:"),
    (re.compile(r"-moz-binding|behavior\s*:", re.I), "script bindings"),
    (re.compile(r"<\s*/?\s*(style|script)", re.I), "HTML tags"),
    (re.compile(r"\\[0-9a-f]", re.I), "escape sequences"),  # e.g. u\72l( to sneak url( past the checks
]


def css_problems(css: str) -> list[str]:
    return [label for pattern, label in _FORBIDDEN if pattern.search(css or "")]


# ── Colors ───────────────────────────────────────────────────────────────────


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex_of(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def mix(color: str, other: str, weight: float) -> str:
    """`weight` of `other` mixed into `color` (Sass's mix, roughly)."""
    a, b = _rgb(color), _rgb(other)
    return _hex_of(tuple(x * (1 - weight) + y * weight for x, y in zip(a, b, strict=True)))


def luminance(color: str) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def on_color(color: str) -> str:
    """Readable text color on `color`: white or near-black, whichever contrasts more."""
    return "#FFFFFF" if contrast(color, "#FFFFFF") >= contrast(color, "#1C2A3A") else "#1C2A3A"


def contrast_warnings(t: ThemeTokens) -> list[str]:
    """WCAG 2.1 AA (4.5:1 for normal text) problems with a set of tokens."""
    checks = [
        (t.text, t.background, "Text on the page background"),
        (t.text, t.surface, "Text on cards and panels"),
        (t.link, t.background, "Links on the page background"),
        (t.link, t.surface, "Links on cards and panels"),
        (on_color(t.primary), t.primary, "Button text on the primary color"),
    ]
    return [
        f"{what}: contrast {ratio:.1f}:1 (needs 4.5:1)"
        for fg, bg, what in checks
        if (ratio := contrast(fg, bg)) < 4.5
    ]


# ── CSS ──────────────────────────────────────────────────────────────────────


def _vars(name: str, color: str) -> str:
    r, g, b = _rgb(color)
    return f"--bs-{name}: {color}; --bs-{name}-rgb: {r}, {g}, {b};"


def tokens_css(t: ThemeTokens, scope: str = "html") -> str:
    """Bootstrap variable overrides for a set of tokens. `scope` is `html` for the site,
    or a class (".stacks-theme-preview") to preview inside one element."""
    root = "html:root" if scope == "html" else scope
    s = scope  # prefix for component rules
    heading, body = FONTS[t.heading_font][1], FONTS[t.body_font][1]
    radius, radius_sm, radius_lg = CORNERS[t.corners]
    primary_text = on_color(t.primary)
    hover, active = mix(t.primary, "#000000", 0.12), mix(t.primary, "#000000", 0.2)
    focus = _rgb(t.primary)
    return f"""{root} {{
  {_vars("primary", t.primary)}
  {_vars("link-color", t.link)}
  --bs-link-hover-color: {mix(t.link, t.text, 0.5)}; --bs-link-hover-color-rgb: {", ".join(map(str, _rgb(mix(t.link, t.text, 0.5))))};
  {_vars("body-bg", t.background)}
  {_vars("body-color", t.text)}
  --bs-emphasis-color: {t.text};
  --bs-secondary-color: {mix(t.text, t.background, 0.35)};
  --bs-border-color: {t.border};
  --bs-body-font-family: {body};
  --bs-border-radius: {radius}; --bs-border-radius-sm: {radius_sm}; --bs-border-radius-lg: {radius_lg};
  --bs-border-radius-xl: {radius_lg}; --bs-border-radius-pill: {radius_lg if t.corners == "square" else "50rem"};
  --bs-focus-ring-color: rgba({focus[0]}, {focus[1]}, {focus[2]}, 0.25);
  --stacks-heading-font: {heading};
  font-family: {body};
  color: {t.text};
  background-color: {t.background};
}}
{s} h1, {s} h2, {s} h3, {s} h4, {s} h5, {s} h6,
{s} .h1, {s} .h2, {s} .h3, {s} .h4, {s} .h5, {s} .h6, {s} .stacks-wordmark {{ font-family: {heading}; }}
{s} .card, {s} .modal-content, {s} .dropdown-menu, {s} .list-group-item, {s} .navbar.bg-white {{
  --bs-card-bg: {t.surface}; --bs-modal-bg: {t.surface}; --bs-dropdown-bg: {t.surface}; --bs-list-group-bg: {t.surface};
  --bs-card-border-color: {t.border}; --bs-list-group-border-color: {t.border};
}}
{s} .navbar.bg-white {{ background-color: {t.surface} !important; }}
{s} .btn-primary {{
  --bs-btn-color: {primary_text}; --bs-btn-bg: {t.primary}; --bs-btn-border-color: {t.primary};
  --bs-btn-hover-color: {primary_text}; --bs-btn-hover-bg: {hover}; --bs-btn-hover-border-color: {hover};
  --bs-btn-active-color: {primary_text}; --bs-btn-active-bg: {active}; --bs-btn-active-border-color: {active};
  --bs-btn-disabled-color: {primary_text}; --bs-btn-disabled-bg: {t.primary}; --bs-btn-disabled-border-color: {t.primary};
  --bs-btn-focus-shadow-rgb: {focus[0]}, {focus[1]}, {focus[2]};
}}
{s} .btn-outline-primary {{
  --bs-btn-color: {t.primary}; --bs-btn-border-color: {t.primary};
  --bs-btn-hover-color: {primary_text}; --bs-btn-hover-bg: {t.primary}; --bs-btn-hover-border-color: {t.primary};
  --bs-btn-active-color: {primary_text}; --bs-btn-active-bg: {t.primary}; --bs-btn-active-border-color: {t.primary};
  --bs-btn-disabled-color: {t.primary}; --bs-btn-disabled-border-color: {t.primary};
  --bs-btn-focus-shadow-rgb: {focus[0]}, {focus[1]}, {focus[2]};
}}
{s} .form-control:focus, {s} .form-select:focus, {s} .form-check-input:focus {{
  border-color: {mix(t.primary, "#FFFFFF", 0.5)};
  box-shadow: 0 0 0 0.25rem rgba({focus[0]}, {focus[1]}, {focus[2]}, 0.25);
}}
{s} .form-check-input:checked {{ background-color: {t.primary}; border-color: {t.primary}; }}
{s} .nav-tabs .nav-link.active {{ color: {t.text}; background-color: {t.background}; }}
"""


# ── LMS looks ────────────────────────────────────────────────────────────────
#
# Written for Stacks from the vendors' published design values (Brightspace
# Daylight / BrightspaceUI core, Canvas Instructure UI, Moodle Boost); no vendor
# CSS is copied or loaded, and fonts are Stacks' own bundled copies.


def _status(name: str, color: str) -> str:
    return _vars(name, color)


def _brightspace(root: str, s: str, primary: str, hover: str) -> str:
    # Brightspace sets 1rem = 20px; sizes here are converted to Stacks' 16px rem
    return f"""{root} {{
  --bs-body-font-size: 1.1875rem; --bs-body-line-height: 1.47; letter-spacing: 0.01rem;
  --bs-secondary-color: #494C4E;
  {_status("success", "#027A21")} {_status("warning", "#BA4700")} {_status("danger", "#CD2026")} {_status("info", "#006FBF")}
  --bs-border-radius: 6px; --bs-border-radius-sm: 6px; --bs-border-radius-lg: 6px; --bs-border-radius-xl: 6px;
}}
{s} h1, {s} .h1 {{ font-size: 2.5rem; font-weight: 400; line-height: 1.2; }}
{s} h2, {s} .h2 {{ font-size: 1.875rem; font-weight: 400; line-height: 1.2; }}
{s} h3, {s} .h3 {{ font-size: 1.25rem; font-weight: 700; line-height: 1.5; }}
{s} h4, {s} .h4 {{ font-size: 1rem; font-weight: 700; line-height: 1.5; }}
{s} .btn {{ --bs-btn-font-size: 0.875rem; --bs-btn-font-weight: 700; letter-spacing: 0.2px; }}
{s} .btn:not(.btn-sm):not(.btn-link) {{ min-height: 2.625rem; --bs-btn-padding-x: 1.5rem; }}
{s} .btn-primary {{ --bs-btn-hover-bg: {hover}; --bs-btn-hover-border-color: {hover}; --bs-btn-active-bg: {hover}; }}
{s} .btn-secondary, {s} .btn-outline-secondary {{
  --bs-btn-color: #202122; --bs-btn-bg: #E3E9F1; --bs-btn-border-color: #E3E9F1;
  --bs-btn-hover-color: #202122; --bs-btn-hover-bg: #CDD5DC; --bs-btn-hover-border-color: #CDD5DC;
  --bs-btn-active-color: #202122; --bs-btn-active-bg: #CDD5DC; --bs-btn-active-border-color: #CDD5DC;
}}
{s} .btn:focus-visible, {s} .form-control:focus, {s} .form-select:focus, {s} .form-check-input:focus {{
  outline: 2px solid {primary}; outline-offset: 2px; box-shadow: none;
}}
{s} .form-control, {s} .form-select {{ border-color: #6E7477; }}
{s} .form-control:focus, {s} .form-select:focus {{ border-color: {primary}; }}
{s} a:not(.btn) {{ text-decoration: none; }}
{s} a:not(.btn):hover {{ text-decoration: underline; color: {hover}; }}
{s} .table {{ --bs-table-border-color: #CDD5DC; }}
{s} .table thead th {{ background-color: #F1F5FB; }}
{s} .card, {s} .list-group-item {{ box-shadow: none; }}
"""


def _canvas(root: str, s: str, primary: str, hover: str) -> str:
    return f"""{root} {{
  --bs-body-font-size: 1rem; --bs-body-line-height: 1.5;
  --bs-secondary-color: #586874;
  {_status("success", "#027634")} {_status("warning", "#B34000")} {_status("danger", "#C71F23")} {_status("info", "#0E68B3")}
  --bs-border-radius: 0.25rem; --bs-border-radius-sm: 0.125rem; --bs-border-radius-lg: 0.5rem; --bs-border-radius-xl: 0.5rem;
}}
{s} h1, {s} .h1 {{ font-size: 2.375rem; font-weight: 700; line-height: 1.25; }}
{s} h2, {s} .h2 {{ font-size: 1.75rem; font-weight: 400; line-height: 1.25; }}
{s} h3, {s} .h3 {{ font-size: 1.375rem; font-weight: 700; line-height: 1.25; }}
{s} h4, {s} .h4 {{ font-size: 1rem; font-weight: 700; line-height: 1.25; }}
{s} h5, {s} .h5 {{ font-size: 0.875rem; font-weight: 400; }}
{s} .btn {{ --bs-btn-font-weight: 400; }}
{s} .btn:not(.btn-sm):not(.btn-link) {{ min-height: 2.375rem; }}
{s} .btn-primary {{
  --bs-btn-border-color: {hover}; --bs-btn-hover-bg: {hover}; --bs-btn-hover-border-color: {hover};
  --bs-btn-active-bg: {hover}; --bs-btn-active-border-color: {hover};
}}
{s} .btn-secondary, {s} .btn-outline-secondary {{
  --bs-btn-color: #273540; --bs-btn-bg: #F2F4F4; --bs-btn-border-color: #D7DADE;
  --bs-btn-hover-color: #273540; --bs-btn-hover-bg: #E8EAEC; --bs-btn-hover-border-color: #D7DADE;
  --bs-btn-active-color: #273540; --bs-btn-active-bg: #E8EAEC; --bs-btn-active-border-color: #D7DADE;
}}
{s} .btn:focus-visible, {s} .form-control:focus, {s} .form-select:focus, {s} .form-check-input:focus {{
  outline: 2px solid {primary}; outline-offset: 0.25rem; box-shadow: none;
}}
{s} .form-control, {s} .form-select {{ border-color: #8D959F; }}
{s} .form-control:not(textarea), {s} .form-select {{ min-height: 2.375rem; }}
{s} a:not(.btn) {{ text-decoration: none; }}
{s} a:not(.btn):hover {{ text-decoration: underline; }}
{s} .table {{ --bs-table-border-color: #8D959F; }}
"""


def _moodle(root: str, s: str, primary: str, hover: str) -> str:
    r, g, b = _rgb(primary)
    return f"""{root} {{
  --bs-body-font-size: 1rem; --bs-body-line-height: 1.5;
  --bs-secondary-color: rgba(29, 33, 37, 0.75);
  {_status("success", "#357A32")} {_status("warning", "#F0AD4E")} {_status("danger", "#CA3120")} {_status("info", "#008196")}
  --bs-border-radius: 0.5rem; --bs-border-radius-sm: 0.25rem; --bs-border-radius-lg: 0.6rem; --bs-border-radius-xl: 0.6rem;
  --bs-focus-ring-color: rgba({r}, {g}, {b}, 0.75);
}}
{s} h1, {s} .h1 {{ font-size: 2.5rem; }}
{s} h2, {s} .h2 {{ font-size: 2rem; }}
{s} h3, {s} .h3 {{ font-size: 1.75rem; }}
{s} h4, {s} .h4 {{ font-size: 1.5rem; }}
{s} h1, {s} h2, {s} h3, {s} h4, {s} h5, {s} h6, {s} .h1, {s} .h2, {s} .h3, {s} .h4 {{ font-weight: 500; line-height: 1.2; }}
{s} .btn {{ --bs-btn-font-weight: 400; }}
{s} .btn-primary {{ --bs-btn-hover-bg: {hover}; --bs-btn-hover-border-color: {hover}; --bs-btn-active-bg: {hover}; }}
{s} .btn-secondary, {s} .btn-outline-secondary {{
  --bs-btn-color: #000000; --bs-btn-bg: #CED4DA; --bs-btn-border-color: #CED4DA;
  --bs-btn-hover-color: #000000; --bs-btn-hover-bg: #D5DAE0; --bs-btn-hover-border-color: #D5DAE0;
  --bs-btn-active-color: #000000; --bs-btn-active-bg: #D5DAE0; --bs-btn-active-border-color: #D5DAE0;
}}
{s} .form-control, {s} .form-select {{ border-color: #8F959E; }}
{s} .form-control:focus, {s} .form-select:focus, {s} .btn:focus-visible {{ box-shadow: 0 0 0 0.25rem rgba({r}, {g}, {b}, 0.75); }}
{s} .card {{ --bs-card-border-color: #E9ECEF; }}
"""


class Preset(BaseModel):
    label: str
    tokens: ThemeTokens
    hover: str  # the vendor's primary hover color (computed when an institution sets its own)

    model_config = ConfigDict(arbitrary_types_allowed=True)


PRESETS: dict[str, tuple[Preset, object]] = {
    "brightspace": (
        Preset(label="Brightspace", hover="#004489", tokens=ThemeTokens(
            primary="#006FBF", link="#006FBF", text="#202122", background="#FFFFFF", surface="#FFFFFF",
            border="#CDD5DC", heading_font="lato", body_font="lato", corners="standard")),
        _brightspace,
    ),
    "canvas": (
        Preset(label="Canvas", hover="#225F92", tokens=ThemeTokens(
            primary="#2B7ABC", link="#0E68B3", text="#273540", background="#FFFFFF", surface="#FFFFFF",
            border="#D7DADE", heading_font="lato", body_font="lato", corners="standard")),
        _canvas,
    ),
    "moodle": (
        Preset(label="Moodle", hover="#0D5CA2", tokens=ThemeTokens(
            primary="#0F6CBF", link="#0F6CBF", text="#1D2125", background="#F8F9FA", surface="#FFFFFF",
            border="#DEE2E6", heading_font="noto-sans", body_font="noto-sans", corners="rounded")),
        _moodle,
    ),
}


def lms_look(settings: ThemeSettings, detected: str | None) -> str | None:
    """Which LMS look to use: the chosen one, or for 'auto' the LMS people launch from."""
    lms = detected if settings.lms == "auto" else settings.lms
    return lms if lms in PRESETS else None


def effective_tokens(settings: ThemeSettings, detected: str | None = None) -> ThemeTokens | None:
    """The tokens a mode applies; None for the standard Stacks theme."""
    if settings.mode == "custom":
        return settings.tokens
    if settings.mode == "lms":
        look = lms_look(settings, detected)
        base = PRESETS[look][0].tokens if look else ThemeTokens()
        # LMSs are usually rebranded: the institution's color replaces the vendor's
        return base.model_copy(update={"primary": settings.lms_primary}) if settings.lms_primary else (base if look else None)
    return None


def theme_css(settings: ThemeSettings, detected: str | None = None, scope: str = "html") -> str:
    """Token overrides plus, in LMS mode, that LMS's component styles."""
    tokens = effective_tokens(settings, detected)
    if tokens is None:
        return ""
    css = tokens_css(tokens, scope)
    look = lms_look(settings, detected) if settings.mode == "lms" else None
    if look:
        preset, components = PRESETS[look]
        hover = preset.hover if not settings.lms_primary else mix(tokens.primary, "#000000", 0.22)
        root = "html:root" if scope == "html" else scope
        css += components(root, scope, tokens.primary, hover)
    return css


def render_css(settings: ThemeSettings, detected: str | None = None) -> str:
    parts = ["/* Stacks theme: generated, do not edit */"]
    if css := theme_css(settings, detected):
        parts.append(css)
    if settings.mode == "custom" and settings.custom_css.strip():
        parts.append("/* Custom CSS */\n" + settings.custom_css)
    return "\n".join(parts) + "\n"


def version(settings: ThemeSettings, logo: dict | None, detected: str | None = None) -> str:
    """Changes whenever anything visible changes (cache key for the stylesheet and logo)."""
    data = settings.model_dump_json() + json.dumps(logo or {}, sort_keys=True) + (detected or "")
    return hashlib.sha256(data.encode()).hexdigest()[:12]


def validate_logo(content_type: str, data_b64: str) -> bytes:
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except ValueError as exc:
        raise ValueError("The logo isn't valid image data") from exc
    if len(raw) > MAX_LOGO_BYTES:
        raise ValueError(f"The logo is too large (at most {MAX_LOGO_BYTES // 1000} KB)")
    magic = LOGO_TYPES.get(content_type)
    if magic is None:
        raise ValueError("Use a PNG, JPEG or WebP image (SVG isn't accepted: it can contain scripts)")
    if not raw.startswith(magic) or (content_type == "image/webp" and raw[8:12] != b"WEBP"):
        raise ValueError("The file isn't the kind of image it says it is")
    return raw
