"""Per-organization connections to library systems, and their settings."""
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import LibrarySource
from app.services import credentials

# Ex Libris API gateways (developers.exlibrisgroup.com: "API gateway by region")
EXLIBRIS_GATEWAYS = {
    "na": "https://api-na.hosted.exlibrisgroup.com",
    "eu": "https://api-eu.hosted.exlibrisgroup.com",
    "ap": "https://api-ap.hosted.exlibrisgroup.com",
    "aps": "https://api-aps.hosted.exlibrisgroup.com",
    "ca": "https://api-ca.hosted.exlibrisgroup.com",
    "cn": "https://api-cn.hosted.exlibrisgroup.com.cn",
}

Region = Literal["na", "eu", "ap", "aps", "ca", "cn"]


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: Region

    @property
    def api_base(self) -> str:
        return EXLIBRIS_GATEWAYS[self.region]


class AlmaConfig(_Config):
    """Alma: authoritative record fetches and sync (Bibs API)."""


class PrimoConfig(_Config):
    """Primo VE / NDE: search, and the discovery URL that student links point at."""

    vid: str = Field(description="View ID, e.g. 01ABC_INST:MAIN")
    tab: str = "Everything"
    scope: str = "MyInst_and_CI"
    discovery_url: str = Field(description="e.g. https://abc.primo.exlibrisgroup.com")
    interface: Literal["nde", "ve"] = "nde"

    @field_validator("vid")
    @classmethod
    def _vid(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_]+:[A-Za-z0-9_]+", value):
            raise ValueError("vid should look like 01ABC_INST:MAIN")
        return value

    @field_validator("discovery_url")
    @classmethod
    def _discovery_url(cls, value: str) -> str:
        if not re.fullmatch(r"https://[A-Za-z0-9.-]+", value.rstrip("/")):
            raise ValueError("discovery_url should be an https origin, e.g. https://abc.primo.exlibrisgroup.com")
        return value.rstrip("/")

    @property
    def institution(self) -> str:
        return self.vid.split(":", 1)[0]


SOURCE_CONFIGS: dict[str, type[_Config]] = {"alma": AlmaConfig, "primo": PrimoConfig}


@dataclass(frozen=True)
class Source:
    """A configured, active source with its decrypted key, ready for API calls."""

    kind: str
    config: _Config
    api_key: str


async def load_sources(db: AsyncSession, organization_id: uuid.UUID) -> dict[str, Source]:
    """Active, usable sources for an organization, keyed by kind."""
    rows = await db.scalars(
        select(LibrarySource).where(
            LibrarySource.organization_id == organization_id, LibrarySource.is_active.is_(True)
        )
    )
    sources: dict[str, Source] = {}
    for row in rows:
        config_cls = SOURCE_CONFIGS.get(row.kind)
        if config_cls is None or not row.api_key_encrypted:
            continue
        sources[row.kind] = Source(
            kind=row.kind,
            config=config_cls.model_validate(row.config),
            api_key=credentials.decrypt(row.api_key_encrypted),
        )
    return sources
