"""An httpx transport that answers from a table of canned responses."""
import httpx


class FakeSources:
    """Route requests by (host, path) to canned JSON; records every request made."""

    def __init__(self):
        self.routes: dict[tuple[str, str], tuple[int, object]] = {}
        self.requests: list[httpx.Request] = []
        self.down: set[str] = set()

    def add(self, url: str, body: object, status: int = 200) -> None:
        parsed = httpx.URL(url)
        self.routes[(parsed.host, parsed.path)] = (status, body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host in self.down:
            raise httpx.ConnectError("unreachable", request=request)
        status, body = self.routes.get((request.url.host, request.url.path), (404, {"error": "not found"}))
        return httpx.Response(status, json=body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]
