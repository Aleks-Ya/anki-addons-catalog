# Developer Guide

## Set up
The project is managed by [uv](https://docs.astral.sh/uv/) and needs Python 3.13+.

```bash
uv sync
cp .env.example .env    # put your ANTHROPIC_API_KEY there
```

## Run from sources

```bash
uv run anki-addons-catalog                 # http://127.0.0.1:8000, uses the deployed MCP Space
uv run anki-addons-catalog --help
```

Against a local MCP server (see the anki-addons-mcp [Developer Guide](https://github.com/Aleks-Ya/anki-addons-mcp/blob/main/README-DEV.md)):

```bash
cd ../anki-addons-mcp && uv run anki-addons-mcp --transport http --port 8000
cd ../anki-addons-catalog && uv run anki-addons-catalog --port 8080 --mcp-url http://localhost:8000/mcp
```

Without `ANTHROPIC_API_KEY` the plain pages work, and AI search shows an error. Turnstile is disabled while
`ANKI_CATALOG_TURNSTILE_SECRET` is unset. Every AI question costs real money; the daily budget
(`ANKI_CATALOG_DAILY_BUDGET_USD`) applies locally too.

## Run in Docker

```bash
docker build -t anki-addons-catalog .
docker run -p 7860:7860 -e ANTHROPIC_API_KEY anki-addons-catalog
curl http://localhost:7860/healthz
```

## Test and lint

```bash
uv run pytest
uv run ruff check src tests
uv run mypy
```

Tests need no network and no API key: they run the real MCP server code in-process (`anki-addons-mcp` is a dev
dependency) over a small fixture dataset, replace Claude with a scripted fake, and test the Claude adapter against
a mocked HTTP transport.

## Architecture

Ports and adapters, the same layout as the MCP server:

```
interface/web    FastAPI routes, Jinja2 templates, static JS/CSS, SSE endpoint, Turnstile + signed cookie
application      AskService (Claude tool loop), CatalogService (plain pages), TTL cache, rate limit, daily budget
domain           AddonCard, LlmTurn, AnswerEvent; ports CatalogPort (MCP) and LlmPort (Claude)
adapters/mcp     CatalogPort over one long-lived MCP client session (reconnects on failure)
adapters/claude  LlmPort over the Anthropic Messages API (streaming, prompt caching, refusal fallback)
bootstrap        settings -> adapters -> services -> FastAPI app
```

**AI search** (`/search?q=…` page + `GET /api/ask?q=…` Server-Sent Events):
1. Checks the question length, the Turnstile pass cookie, the per-IP rate limit and the daily budget.
2. Serves a cached answer for the same question and dataset snapshot, if any.
3. Runs the tool loop: Claude gets the system prompt and the allowed MCP tools (sorted, with cache breakpoints, so
   the static prefix is prompt-cached), calls tools in parallel, and the app runs them over MCP. At most
   `MAX_TOOL_ROUNDS` rounds; the last round asks Claude to answer with what it has.
4. Streams `status` (tool progress), `text` (raw deltas), `answer` (markdown rendered server-side with raw HTML
   disabled), `addons` (cards of the addons the answer links to), `done` or `error` events. If the visitor leaves,
   the loop is cancelled.

The keyword results (`search_addons`) are rendered server-side under the AI answer, so the page is useful even
when the AI is unavailable or over budget.

## Deploy to a HuggingFace Space

Space: https://huggingface.co/spaces/Ya-Alex/anki-addons-catalog

1. Create a Space with the **Docker** SDK. The YAML header of `README.md` configures it (`sdk: docker`,
   `app_port: 7860`).
2. In the Space settings, add the secrets `ANTHROPIC_API_KEY`, `ANKI_CATALOG_TURNSTILE_SECRET`,
   `ANKI_CATALOG_SESSION_SECRET` (e.g. `openssl rand -hex 32`) and the variable `ANKI_CATALOG_TURNSTILE_SITE_KEY`.
   Optionally adjust `ANKI_CATALOG_DAILY_BUDGET_USD` and `ANKI_CATALOG_RATE_LIMIT_PER_HOUR`.
3. Push the repository:
   ```bash
   git remote add space https://huggingface.co/spaces/Ya-Alex/anki-addons-catalog
   git push space main
   ```
   Or let CI do it: `.github/workflows/deploy-space.yml` pushes `main` after a green Unit-tests run. It needs a
   GitHub environment `huggingface` with the secret `HF_TOKEN` (a HuggingFace token with write access to the Space).

Run one replica: the rate limiter, the daily budget and the caches live in memory and reset on restart.

### Custom domain (anki-addons-catalog.com)

1. In the Space settings (HF Pro), open **Custom domain** and enter `anki-addons-catalog.com`.
2. In the Cloudflare dashboard → **DNS**, add the record that HuggingFace shows (a `CNAME` to `hf.space`) with the
   proxy status **DNS only** (grey cloud), so HuggingFace can issue the TLS certificate. Cloudflare flattens a
   `CNAME` at the apex automatically. If HuggingFace cannot verify the apex, use `www.anki-addons-catalog.com` as
   the Space domain instead and redirect the apex to it (next step, reversed).
3. Add `www` → apex: a proxied `CNAME www → anki-addons-catalog.com` plus a **Redirect Rule** (Rules →
   Redirect Rules, "Redirect from WWW to root" template, 301).
4. Check `https://anki-addons-catalog.com/healthz`.

### Cloudflare Turnstile

Cloudflare dashboard → **Turnstile** → **Add widget**: hostname `anki-addons-catalog.com` (add `localhost` for
local testing), mode **Managed**. Put the site key into `ANKI_CATALOG_TURNSTILE_SITE_KEY` and the secret key into
`ANKI_CATALOG_TURNSTILE_SECRET`.

### MCP Space

The catalog pings the MCP Space's `/healthz` every `ANKI_CATALOG_MCP_KEEPALIVE_SECONDS` so that it does not go to
sleep. With HF Pro you can also set a longer sleep time for that Space in its settings.

## Release a new version

The version lives in `src/anki_addons_catalog/__init__.py` (`__version__`) and is bumped with
[bump-my-version](https://github.com/callowayproject/bump-my-version) (`.bumpversion.toml`), as in the MCP server:

1. `uv run bump-my-version bump release --tag` (`0.1.0.dev0` -> `0.1.0`, tag `v0.1.0`)
2. `uv run bump-my-version bump minor` (`0.1.0` -> `0.2.0.dev0`)
3. `git push origin HEAD --tags`

## Continuous integration
`.github/workflows/unit-tests.yml` runs on every push and pull request to `main`: TruffleHog secret scan,
`uv sync --locked`, ruff, mypy, pytest with coverage and a SonarCloud scan (`sonar-project.properties`; import the
repository into the `aleks-ya` SonarCloud organization and add the `SONAR_TOKEN` repository secret).
