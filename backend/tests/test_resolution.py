import asyncio
import uuid

import httpx
import pytest

from app.models.models import Citation, ResourceType
from app.services import links, resolution
from tests.test_ingest.fake_http import FakeSources

ALMA = "https://abc.alma.exlibrisgroup.com/view/uresolver/01ABC_INST/openurl"
OPENALEX = "https://api.openalex.org/works/doi:10.1/x"
LIBKEY = "https://public-api.thirdiron.com/public/v1/libraries/99/articles/doi/10.1%2Fx"


def cto(*services: dict) -> str:
    """An Alma resolver CTO response with the given services (shape as seen live)."""
    body = ""
    for s in services:
        keys = "".join(f'<key id="{k}">{v}</key>' for k, v in s.get("keys", {}).items())
        url = f"<resolution_url>{s['url']}</resolution_url>" if s.get("url") else ""
        body += (
            f'<context_service service_type="{s.get("type", "getFullTxt")}" context_service_id="1">'
            f"<keys>{keys}</keys>{url}</context_service>"
        )
    return (
        '<uresolver_content xmlns="http://com/exlibris/urm/uresolver/xmlbeans/u">'
        f"<context_services>{body}</context_services></uresolver_content>"
    )


def make(**fields) -> Citation:
    fields.setdefault("resource_type", ResourceType.journal_article)
    fields.setdefault("title", "An article")
    fields.setdefault("metadata_", {})
    return Citation(id=uuid.uuid4(), **fields)


def context(stack=("libkey", "alma", "open_access"), libkey=True, alma=True, timeout=2.5) -> resolution.ResolutionContext:
    return resolution.ResolutionContext(
        config=resolution.ResolutionConfig(stack=list(stack), step_timeout_seconds=timeout),
        link_settings=links.LinkSettings("https://abc.primo.exlibrisgroup.com", "01ABC_INST:NDE", "01ABC_INST"),
        alma=resolution.AlmaResolver("https://abc.alma.exlibrisgroup.com", "01ABC_INST") if alma else None,
        libkey=resolution.LibKey(99, "token") if libkey else None,
    )


class Router(FakeSources):
    """FakeSources that also answers XML (the Alma resolver)."""

    def __init__(self):
        super().__init__()
        self.xml: dict[str, str] = {}
        self.slow: set[str] = set()

    async def async_handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host in self.slow:
            await asyncio.sleep(5)
        url = f"{request.url.scheme}://{request.url.host}{request.url.raw_path.decode().split('?')[0]}"
        if url in self.xml:
            self.requests.append(request)
            return httpx.Response(200, text=self.xml[url], headers={"content-type": "text/xml"})
        return self.handler(request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.async_handler))


async def run(router: Router, citation: Citation, ctx: resolution.ResolutionContext):
    trace = resolution.Trace()
    async with router.client() as http:
        found = await resolution.resolve(citation, ctx, http, trace)
    return found, [(s.step, s.outcome) for s in trace.steps]


def test_first_usable_full_text_service():
    xml = cto(
        {"type": "getHolding", "url": "https://x/holding"},
        {"keys": {"Filtered": "true", "package_public_name": "No access"}, "url": "https://x/filtered"},
        {"keys": {"is_related_service": "true"}, "url": "https://x/related"},
        {"keys": {"package_public_name": "ScienceDirect"}, "url": "https://x/sd"},
        {"keys": {"package_public_name": "Later"}, "url": "https://x/later"},
    )
    assert resolution.first_full_text_service(xml) == ("https://x/sd", "ScienceDirect")
    assert resolution.first_full_text_service(cto()) is None


async def test_libkey_wins_when_it_finds_the_article():
    router = Router()
    router.add(LIBKEY, {"data": {"fullTextFile": "https://libkey.io/pdf", "contentLocation": "https://libkey.io/page"}})
    found, steps = await run(router, make(doi="10.1/x"), context())
    assert (found.url, found.step, found.detail) == ("https://libkey.io/pdf", "libkey", "PDF")
    assert steps == [("libkey", "found")]
    assert router.requests[0].url.params["access_token"] == "token"


async def test_libkey_without_a_direct_link_moves_on():
    # Seen live: LibKey answers 200 with empty link fields (e.g. JSTOR) rather than 404
    router = Router()
    router.add(LIBKEY, {"data": {"fullTextFile": "", "contentLocation": "", "retractionNoticeUrl": None,
                                 "linkResolverOpenUrl": "https://primo/openurl"}})
    router.xml[ALMA] = cto({"keys": {"package_public_name": "JSTOR"}, "url": "https://alma/jstor"})
    found, steps = await run(router, make(doi="10.1/x"), context())
    assert (found.step, found.detail) == ("alma", "JSTOR")
    assert steps == [("libkey", "not_found"), ("alma", "found")]


async def test_libkey_sends_retracted_articles_to_the_notice():
    router = Router()
    router.add(LIBKEY, {"data": {"retractionNoticeUrl": "https://notice", "fullTextFile": "https://pdf"}})
    found, _ = await run(router, make(doi="10.1/x"), context())
    assert (found.url, found.retracted) == ("https://notice", True)


async def test_no_find_and_failure_both_move_down_the_stack():
    router = Router()
    router.add(LIBKEY, {"errors": "boom"}, status=500)  # failure
    router.xml[ALMA] = cto()  # no full text
    router.add(OPENALEX, {"open_access": {"is_oa": True}, "best_oa_location": {"pdf_url": "https://oa/pdf", "source": {"display_name": "PMC"}}})
    found, steps = await run(router, make(doi="10.1/x"), context())
    assert (found.url, found.step, found.detail) == ("https://oa/pdf", "open_access", "PMC")
    assert steps == [("libkey", "error"), ("alma", "not_found"), ("open_access", "found")]


async def test_slow_step_is_abandoned():
    router = Router()
    router.slow.add("public-api.thirdiron.com")
    router.xml[ALMA] = cto({"keys": {"package_public_name": "JSTOR"}, "url": "https://alma/jstor"})
    found, steps = await run(router, make(doi="10.1/x"), context(timeout=0.5))
    assert found.step == "alma"
    assert steps[0] == ("libkey", "error")


async def test_alma_finds_library_records_by_mms_id():
    router = Router()
    router.xml[ALMA] = cto({"keys": {"package_public_name": "Ebook Central"}, "url": "https://alma/ebc"})
    citation = make(resource_type=ResourceType.ebook, source_system="alma", source_identifier="991234567890123")
    found, steps = await run(router, citation, context(libkey=False))
    assert (found.step, found.detail) == ("alma", "Ebook Central")
    assert steps == [("libkey", "skipped"), ("alma", "found")]
    params = router.requests[0].url.params
    assert (params["rft.mms_id"], params["svc_dat"]) == ("991234567890123", "CTO")


async def test_print_book_falls_back_to_the_catalogue_record():
    router = Router()
    router.xml[ALMA] = cto({"type": "getHolding", "url": "https://x/holding"})
    citation = make(resource_type=ResourceType.book, source_system="alma", source_identifier="991234567890123")
    found, steps = await run(router, citation, context(libkey=False))
    assert (found.step, found.detail) == ("fallback", "library_record")
    assert "/discovery/fulldisplay?docid=alma991234567890123" in found.url
    # No DOI: open access is asked nothing
    assert steps == [("libkey", "skipped"), ("alma", "not_found"), ("open_access", "not_found"), ("fallback", "found")]


async def test_empty_stack_means_plain_links():
    router = Router()
    found, steps = await run(router, make(doi="10.1/x", issn="1234-5678"), context(stack=()))
    assert (found.step, found.detail) == ("fallback", "full_text")
    assert router.requests == []
    assert steps == [("fallback", "found")]


async def test_nothing_at_all():
    found, _ = await run(Router(), make(resource_type=ResourceType.other), context(stack=()))
    assert found is None


@pytest.mark.parametrize("stack", [["alma"], []])
def test_config_defaults_and_validation(stack):
    assert resolution.ResolutionConfig().stack == ["libkey", "alma", "open_access"]
    assert resolution.ResolutionConfig(stack=stack).stack == stack
    with pytest.raises(ValueError):
        resolution.ResolutionConfig(stack=["made_up"])
