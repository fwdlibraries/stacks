import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.config import Settings, settings


async def test_responses_carry_frame_ancestors_policy(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "frame_ancestors", "https://lms.example.edu https://*.instructure.com")
    for path in ("/api/v1/health/live", "/lti/jwks", "/lti/login"):
        resp = await client.get(path)
        # API responses carry frame-ancestors; app-rendered pages (the LTI error page) the
        # full page policy, which ends with it
        assert resp.headers["content-security-policy"].endswith(
            "frame-ancestors 'self' https://lms.example.edu https://*.instructure.com"
        ), path


async def test_default_allows_same_origin_only(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "frame_ancestors", "")
    resp = await client.get("/api/v1/health/live")
    assert resp.headers["content-security-policy"] == "frame-ancestors 'self'"


def test_valid_frame_ancestors_are_normalised():
    s = Settings(secret_key="x" * 40, frame_ancestors="  https://a.edu\n  https://*.b.com:8443 ")
    assert s.frame_ancestors == "https://a.edu https://*.b.com:8443"


@pytest.mark.parametrize(
    "value",
    [
        "lms.example.edu",  # no scheme
        "https://lms.example.edu/path",  # not an origin
        "https://lms.example.edu; script-src *",  # header injection attempt
        "*",
        "javascript:alert(1)",
    ],
)
def test_invalid_frame_ancestors_are_rejected(value):
    with pytest.raises(ValidationError):
        Settings(secret_key="x" * 40, frame_ancestors=value)
