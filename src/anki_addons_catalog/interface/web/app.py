import asyncio
import hashlib
import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from xml.sax.saxutils import escape

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from anki_addons_catalog import __version__
from anki_addons_catalog.application import usage as u
from anki_addons_catalog.application.ask import AskService, BudgetExhausted
from anki_addons_catalog.application.catalog import TOP_METRICS, CatalogService
from anki_addons_catalog.application.limits import RateLimiter
from anki_addons_catalog.application.usage import UsageStats
from anki_addons_catalog.domain.errors import CatalogUnavailable, ToolFailed
from anki_addons_catalog.domain.models import AnswerEvent
from anki_addons_catalog.domain.ports import CatalogPort
from anki_addons_catalog.interface.web.rendering import compact_number, render_markdown, render_readme
from anki_addons_catalog.interface.web.security import PASS_COOKIE, HumanCheck, client_ip

log = logging.getLogger(__name__)

HERE = Path(__file__).parent
EXAMPLES = [
    "Image occlusion that works on Anki 25.02",
    "Best addons for learning Japanese kanji",
    "Show heatmap of my review history",
    "Is the AnkiConnect addon still maintained?",
    "Text-to-speech for language decks",
    "Which addons were updated recently and are popular?",
]


@dataclass
class WebContext:
    catalog_port: CatalogPort
    catalog: CatalogService
    ask: AskService
    human: HumanCheck
    limiter: RateLimiter
    public_url: str
    max_query_chars: int
    keepalive_seconds: int
    usage: UsageStats
    admin_token: str | None = None
    daily_budget_usd: float = 0.0


def _static_hashes() -> dict[str, str]:
    """Content hashes of the static files: a changed file gets a new URL, so browsers do not use a stale copy."""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:12] for p in (HERE / "static").iterdir() if p.is_file()}


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _usage_row(c: dict[str, float]) -> dict[str, float]:
    """One row of the usage table from the raw counters."""
    return {
        "keyword": c.get(u.KEYWORD_SEARCH, 0), "asked": c.get(u.AI_ASKED, 0), "answered": c.get(u.AI_ANSWERED, 0),
        "cached": c.get(u.AI_CACHED, 0), "failed": c.get(u.AI_FAILED, 0) + c.get(u.AI_REFUSED, 0),
        "blocked": c.get(u.AI_RATE_LIMITED, 0) + c.get(u.AI_VERIFY, 0) + c.get(u.AI_BUDGET_EXHAUSTED, 0),
        "cost": c.get(u.AI_COST_USD, 0), "views": sum(v for k, v in c.items() if k.startswith(u.VIEW_PREFIX)),
    }


def create_web_app(ctx: WebContext, close: Any = None) -> FastAPI:
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["markdown"] = render_markdown
    templates.env.filters["readme"] = render_readme
    templates.env.filters["compact"] = compact_number
    templates.env.globals.update(version=__version__, turnstile_site_key=ctx.human.site_key,
                                 public_url=ctx.public_url, top_metrics=TOP_METRICS,
                                 static_hash=_static_hashes())

    async def keepalive() -> None:
        while ctx.keepalive_seconds > 0:
            await ctx.catalog_port.ping()
            await asyncio.sleep(ctx.keepalive_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(keepalive())
        try:
            yield
        finally:
            task.cancel()
            if close is not None:
                await close()

    app = FastAPI(title="Anki Addons Catalog", version=__version__, lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def page(request: Request, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    def view(name: str) -> None:
        ctx.usage.add(u.VIEW_PREFIX + name)

    basic_auth = HTTPBasic(auto_error=False, realm="Anki Addons Catalog admin")

    def require_admin(credentials: Annotated[HTTPBasicCredentials | None, Depends(basic_auth)]) -> None:
        if not ctx.admin_token:
            raise HTTPException(404)
        if credentials is None or not secrets.compare_digest(credentials.password.encode(), ctx.admin_token.encode()):
            raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="Anki Addons Catalog admin"'})

    @app.exception_handler(CatalogUnavailable)
    async def catalog_unavailable(request: Request, exc: CatalogUnavailable) -> HTMLResponse:
        log.warning("Catalog unavailable: %s", exc)
        return page(request, "error.html", 503, title="Catalog is waking up",
                    message="The addon catalog is starting up. Please reload the page in a minute.")

    @app.exception_handler(ToolFailed)
    async def tool_failed(request: Request, exc: ToolFailed) -> HTMLResponse:
        not_found = "not found" in exc.message.lower()
        return page(request, "error.html", 404 if not_found else 502,
                    title="Not found" if not_found else "Catalog error", message=exc.message)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        view("home")
        top, recent = await asyncio.gather(ctx.catalog.top("rating", 8), ctx.catalog.top("recently_updated", 8))
        return page(request, "index.html", examples=EXAMPLES, top=top["items"], recent=recent["items"])

    @app.get("/search", response_class=HTMLResponse)
    async def search(request: Request, q: str = "", offset: int = 0) -> HTMLResponse:
        q = q.strip()[:ctx.max_query_chars]
        view("search")
        if q:
            ctx.usage.add(u.KEYWORD_SEARCH)
        results = await ctx.catalog.search(q, limit=30, offset=max(offset, 0)) if q else None
        return page(request, "search.html", q=q, results=results, offset=offset)

    @app.post("/api/verify")
    async def verify(request: Request, token: str = Form("")) -> Response:
        if not await ctx.human.verify(token, client_ip(request)):
            return JSONResponse({"ok": False}, status_code=403)
        response = JSONResponse({"ok": True})
        response.set_cookie(PASS_COOKIE, ctx.human.issue_pass(), max_age=ctx.human.ttl_seconds, httponly=True,
                            secure=request.url.scheme == "https", samesite="strict")
        return response

    @app.get("/api/ask")
    async def ask(request: Request, q: str = "") -> StreamingResponse:
        query = q.strip()

        async def single(event: str, data: Any) -> AsyncIterator[str]:
            yield _sse(event, data)

        def stream(body: AsyncIterator[str]) -> StreamingResponse:
            return StreamingResponse(body, media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        if not query:
            return stream(single("error", "Please type a question."))
        if len(query) > ctx.max_query_chars:
            return stream(single("error", f"Please keep the question under {ctx.max_query_chars} characters."))
        if not ctx.human.has_pass(request):
            ctx.usage.add(u.AI_VERIFY)
            return stream(single("verify", None))
        if not ctx.limiter.allow(client_ip(request)):
            ctx.usage.add(u.AI_RATE_LIMITED)
            return stream(single("error", "You have asked many questions in a short time. Please wait a bit, "
                                          "or use the keyword results below."))

        async def events() -> AsyncIterator[str]:
            try:
                async for event in ctx.ask.ask(query):
                    yield _sse(event.type, _event_data(event))
            except BudgetExhausted:
                yield _sse("error", "The AI search has reached its daily budget. The keyword results below "
                                    "still work; AI search is back tomorrow.")
            except CatalogUnavailable:
                yield _sse("error", "The addon catalog is waking up. Please try again in a minute.")

        def _event_data(event: AnswerEvent) -> Any:
            if event.type == "answer":
                return {"html": render_markdown(event.data)}
            if event.type == "addons":
                html = templates.get_template("_cards.html").render(cards=event.data)
                return {"html": html, "count": len(event.data)}
            return event.data

        return stream(events())

    @app.get("/addon/{addon_id}", response_class=HTMLResponse)
    async def addon(request: Request, addon_id: int, anki: str = "") -> HTMLResponse:
        view("addon")
        details = await ctx.catalog.addon(addon_id)
        maintenance, similar, readme, description = await asyncio.gather(
            ctx.catalog.maintenance(addon_id), ctx.catalog.similar(addon_id), ctx.catalog.readme(addon_id),
            ctx.catalog.description(addon_id), return_exceptions=True)
        anki = anki.strip()[:20]
        compatibility = await ctx.catalog.compatibility(addon_id, anki) if anki else None
        return page(request, "addon.html", a=details,
                    maintenance=None if isinstance(maintenance, BaseException) else maintenance,
                    similar=[] if isinstance(similar, BaseException) else similar,
                    readme=None if isinstance(readme, BaseException) else readme,
                    description=None if isinstance(description, BaseException) else description,
                    anki=anki, compatibility=compatibility)

    @app.get("/addon/{addon_id}/history")
    async def addon_history(addon_id: int) -> JSONResponse:
        return JSONResponse(await ctx.catalog.history(addon_id))

    @app.get("/author/{github_user}", response_class=HTMLResponse)
    async def author(request: Request, github_user: str) -> HTMLResponse:
        view("author")
        result = await ctx.catalog.by_author(github_user)
        return page(request, "list.html", title=f"Addons by {github_user}",
                    subtitle=f"Addons whose GitHub repository belongs to {github_user}.", cards=result["items"])

    @app.get("/top/{metric}", response_class=HTMLResponse)
    async def top(request: Request, metric: str) -> HTMLResponse:
        if metric not in TOP_METRICS:
            return page(request, "error.html", 404, title="Not found", message=f"Unknown list: {metric}")
        view("top")
        result = await ctx.catalog.top(metric, 50)
        return page(request, "list.html", title=TOP_METRICS[metric], subtitle="Top 50 addons.",
                    cards=result["items"], metric=metric)

    @app.get("/stats", response_class=HTMLResponse)
    async def stats(request: Request) -> HTMLResponse:
        view("stats")
        return page(request, "stats.html", stats=await ctx.catalog.statistics())

    @app.get("/changes", response_class=HTMLResponse)
    async def changes(request: Request) -> HTMLResponse:
        view("changes")
        return page(request, "changes.html", diff=await ctx.catalog.changes())

    @app.get("/about", response_class=HTMLResponse)
    async def about(request: Request) -> HTMLResponse:
        view("about")
        try:
            snapshot = await ctx.catalog.latest_snapshot_info()
        except (CatalogUnavailable, ToolFailed):
            snapshot = None
        return page(request, "about.html", snapshot=snapshot)

    @app.get("/admin/usage", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    async def admin_usage(request: Request) -> HTMLResponse:
        days = [(day, _usage_row(counters)) for day, counters in ctx.usage.daily(30)]
        totals = ctx.usage.totals()
        views = sorted(((k.removeprefix(u.VIEW_PREFIX), v) for k, v in totals.items() if k.startswith(u.VIEW_PREFIX)),
                       key=lambda kv: -kv[1])
        return page(request, "admin_usage.html", days=days, total=_usage_row(totals), views=views,
                    since=ctx.usage.first_day(), persistent=ctx.usage.persistent,
                    spent_today=ctx.usage.today(u.AI_COST_USD), daily_budget=ctx.daily_budget_usd)

    @app.get("/robots.txt", response_class=PlainTextResponse)
    async def robots() -> str:
        return f"User-agent: *\nDisallow: /api/\nDisallow: /admin/\nDisallow: /search\nSitemap: {ctx.public_url}/sitemap.xml\n"

    @app.get("/sitemap.xml")
    async def sitemap() -> Response:
        paths = ["/", "/stats", "/changes", "/about", *(f"/top/{m}" for m in TOP_METRICS)]
        paths += [f"/addon/{i}" for i in await ctx.catalog.all_addon_ids()]
        urls = "".join(f"<url><loc>{escape(ctx.public_url + p)}</loc></url>" for p in paths)
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
        return Response(xml, media_type="application/xml")

    return app
