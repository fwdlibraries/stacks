import base64

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Organization, OrganizationDomain, ScopeType
from app.services import access, theme
from tests.test_api.test_admin import person, sign_in

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


@pytest.mark.parametrize(
    "css",
    [
        "@import 'https://evil.example/x.css';",
        ".a { background: url(https://evil.example/?v=1) }",
        ".a { background: URL ( 'x' ) }",
        'input[value^="a"] { background-image: image-set("https://x" 1x) }',
        "@font-face { font-family: x; src: local(x) }",
        ".a { width: expression(alert(1)) }",
        ".a { -moz-binding: x }",
        "</style><script>alert(1)</script>",
        ".a { background: u\\72l(https://evil.example) }",  # escapes to sneak url( past the checks
    ],
)
def test_custom_css_that_could_load_or_run_anything_is_refused(css):
    assert theme.css_problems(css)
    with pytest.raises(ValueError):
        theme.ThemeSettings(mode="custom", custom_css=css)


def test_harmless_custom_css_is_kept():
    css = ".card { border-width: 2px; } h1 { letter-spacing: -0.5px; }"
    assert theme.ThemeSettings(mode="custom", custom_css=css).custom_css == css


def test_contrast():
    assert round(theme.contrast("#000000", "#FFFFFF"), 1) == 21.0
    assert theme.on_color("#2C3E5A") == "#FFFFFF" and theme.on_color("#F2C94C") == "#1C2A3A"
    low = theme.ThemeTokens(text="#999999", background="#FFFFFF", surface="#FFFFFF", link="#2C3E5A")
    assert [w.split(":")[0] for w in theme.contrast_warnings(low)] == ["Text on the page background", "Text on cards and panels"]


def test_render_by_mode():
    assert "--bs-primary" not in theme.render_css(theme.ThemeSettings())  # standard: nothing to override
    lms = theme.render_css(theme.ThemeSettings(mode="lms", lms_primary="#006fbf"))
    assert "--bs-primary: #006FBF;" in lms
    custom = theme.ThemeSettings(mode="custom", tokens=theme.ThemeTokens(primary="#7A1F2B", body_font="system-sans",
                                                                         corners="square"), custom_css=".x{color:red}")
    css = theme.render_css(custom)
    assert "html:root {" in css and "--bs-primary: #7A1F2B; --bs-primary-rgb: 122, 31, 43;" in css
    assert "--bs-border-radius: 0;" in css and "system-ui" in css
    assert "html .btn-primary" in css and css.rstrip().endswith(".x{color:red}")
    # Custom CSS only applies in custom mode
    assert ".x{color:red}" not in theme.render_css(custom.model_copy(update={"mode": "stacks"}))


def test_token_validation():
    for bad in ({"primary": "red"}, {"primary": "#12345"}, {"body_font": "Comic Sans"}, {"corners": "blobby"}):
        with pytest.raises(ValueError):
            theme.ThemeTokens(**bad)


@pytest.mark.parametrize(
    ("content_type", "data", "ok"),
    [
        ("image/png", PNG, True),
        ("image/svg+xml", base64.b64encode(b"<svg onload=alert(1)>").decode(), False),
        ("image/png", base64.b64encode(b"\xff\xd8\xff not a png").decode(), False),
        ("image/png", "!!!not base64", False),
        ("image/png", base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 210_000).decode(), False),
    ],
)
def test_logo_validation(content_type, data, ok):
    if ok:
        assert theme.validate_logo(content_type, data)
    else:
        with pytest.raises(ValueError):
            theme.validate_logo(content_type, data)


@pytest.fixture
async def uni(db_session: AsyncSession):
    org = Organization(name="Uni", slug="uni")
    db_session.add(org)
    await db_session.flush()
    db_session.add(OrganizationDomain(organization_id=org.id, hostname="stacks.uni.edu", is_primary=True))
    await db_session.commit()
    return org


async def test_theme_admin_and_site_stylesheet(client: AsyncClient, db_session, uni):
    await sign_in(client, await person(db_session, uni, "admin", access.ADMINISTRATOR, (ScopeType.organization, uni.id)))
    host = {"Host": "stacks.uni.edu"}

    state = (await client.get("/api/v1/admin/theme")).json()
    assert (state["mode"], state["has_logo"], state["lms_presets_ready"]) == ("stacks", False, False)
    assert {f["key"] for f in state["fonts"]} >= {"stacks-serif", "system-sans"}

    standard = await client.get("/api/v1/tenant/theme.css", headers=host)
    assert standard.headers["content-type"].startswith("text/css") and "--bs-primary" not in standard.text

    saved = (await client.put("/api/v1/admin/theme", json={
        "mode": "custom", "tokens": {"primary": "#7a1f2b", "text": "#999999"}, "custom_css": ".card{border-width:2px}"})).json()
    assert saved["tokens"]["primary"] == "#7A1F2B"
    assert any(w.startswith("Text on the page background") for w in saved["warnings"])

    site = await client.get("/api/v1/tenant/theme.css", headers=host)
    assert "--bs-primary: #7A1F2B;" in site.text and ".card{border-width:2px}" in site.text
    etag = site.headers["etag"]
    assert (await client.get("/api/v1/tenant/theme.css", headers={**host, "If-None-Match": etag})).status_code == 304
    info = (await client.get("/api/v1/tenant", headers=host)).json()
    assert info["theme"]["mode"] == "custom" and info["theme"]["version"] in etag

    bad = await client.put("/api/v1/admin/theme", json={"mode": "custom", "custom_css": "a{background:url(x)}"})
    assert bad.status_code == 422 and "url(…)" in bad.json()["detail"]

    # Saving other organization settings keeps the theme
    await client.patch("/api/v1/admin/organization", json={"contact_email": "lib@uni.edu"})
    assert (await client.get("/api/v1/admin/theme")).json()["mode"] == "custom"


async def test_preview_is_scoped_and_not_saved(client, db_session, uni):
    await sign_in(client, await person(db_session, uni, "admin", access.ADMINISTRATOR, (ScopeType.organization, uni.id)))
    body = (await client.post("/api/v1/admin/theme/preview", json={"mode": "custom", "tokens": {"primary": "#7A1F2B"}})).json()
    assert body["css"].startswith(".stacks-theme-preview {") and "html" not in body["css"]
    assert (await client.get("/api/v1/admin/theme")).json()["mode"] == "stacks"


async def test_logo(client, db_session, uni):
    await sign_in(client, await person(db_session, uni, "admin", access.ADMINISTRATOR, (ScopeType.organization, uni.id)))
    host = {"Host": "stacks.uni.edu"}
    assert (await client.get("/api/v1/tenant/logo", headers=host)).status_code == 404
    assert (await client.put("/api/v1/admin/theme/logo", json={"content_type": "image/png", "data": PNG})).json()["has_logo"]
    logo = await client.get("/api/v1/tenant/logo", headers=host)
    assert (logo.status_code, logo.headers["content-type"], logo.headers["x-content-type-options"]) == (200, "image/png", "nosniff")
    assert logo.content.startswith(b"\x89PNG")
    svg = await client.put("/api/v1/admin/theme/logo", json={"content_type": "image/svg+xml", "data": PNG})
    assert svg.status_code == 422
    assert (await client.delete("/api/v1/admin/theme/logo")).json()["has_logo"] is False


async def test_theme_needs_organization_wide_settings(client, db_session, uni):
    await sign_in(client, await person(db_session, uni, "lib", access.LIBRARIAN, (ScopeType.organization, uni.id)))
    assert (await client.get("/api/v1/admin/theme")).status_code == 403
    assert (await client.put("/api/v1/admin/theme", json={"mode": "custom"})).status_code == 403


async def test_pages_get_a_policy_that_contains_custom_css(client, uni):
    resp = await client.get("/api/v1/tenant/frame-policy", headers={"Host": "stacks.uni.edu"})
    policy = resp.headers["content-security-policy"]
    for part in ("default-src 'self'", "img-src 'self' data:", "font-src 'self' data:", "connect-src 'self'", "object-src 'none'"):
        assert part in policy
