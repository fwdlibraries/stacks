"""Primo VE / NDE search API (the same API serves both interfaces).

Used here to find the library's own record for an ISBN; the "Add from library"
search dialog will build on `search()`.
"""
from app.ingest.resolvers.base import ResolveContext, get_json
from app.ingest.sources import PrimoConfig


def available(ctx: ResolveContext) -> bool:
    return "primo" in ctx.sources


async def search(ctx: ResolveContext, query: str, *, limit: int = 10, local_only: bool = False) -> list[dict]:
    """Primo search; returns PNX documents. `query` uses Primo syntax, e.g. "isbn,exact,978…"."""
    source = ctx.sources["primo"]
    config: PrimoConfig = source.config  # type: ignore[assignment]
    params = {
        "vid": config.vid,
        "tab": config.tab,
        "scope": config.scope,
        "q": query,
        "limit": limit,
        "offset": 0,
    }
    data = await get_json(
        ctx,
        "Primo",
        f"{config.api_base}/primo/v1/search",
        params=params,
        headers={"Authorization": f"apikey {source.api_key}", "Accept": "application/json"},
    )
    docs = (data or {}).get("docs") or []
    return [d for d in docs if d.get("context") == "L"] if local_only else docs


def mms_id(doc: dict) -> str | None:
    """The Alma MMS ID behind a local Primo record, if it is one."""
    control = (doc.get("pnx") or {}).get("control") or {}
    for value in control.get("sourcerecordid") or []:
        if value.isdigit():
            return value
    for value in control.get("recordid") or []:
        if value.startswith("alma") and value[4:].isdigit():
            return value[4:]
    return None
