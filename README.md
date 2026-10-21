---
title: Anki Addons Catalog
emoji: 🔎
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: AI-powered search over every Anki addon
---

# Anki Addons Catalog

A web catalog of [Anki](https://apps.ankiweb.net) addons with AI-powered search: https://www.anki-addons-catalog.com

Ask in plain words ("image occlusion that works on Anki 25.02"). Claude searches the catalog through the
[Anki Addons MCP server](https://huggingface.co/spaces/Ya-Alex/anki-addons-mcp), checks compatibility and maintenance,
and recommends the best fits. Plain catalog pages (addon details, top lists, author pages, statistics, monthly
changes) work without AI.

## Links
- Website: https://www.anki-addons-catalog.com
- [HuggingFace Space](https://huggingface.co/spaces/Ya-Alex/anki-addons-catalog) that hosts the website
- [Anki Addons MCP server](https://huggingface.co/spaces/Ya-Alex/anki-addons-mcp)
  ([sources](https://github.com/Aleks-Ya/anki-addons-mcp)), the data access layer
- [Anki Addons dataset](https://huggingface.co/datasets/Ya-Alex/anki-addons)
  ([sources](https://github.com/Aleks-Ya/anki-addons-dataset)), the data
- [Developer Guide](README-DEV.md): running from sources, tests, architecture, deployment

## Architecture

```
Browser ──> www.anki-addons-catalog.com (Cloudflare DNS → HuggingFace custom domain)
              │
              HF Space "Ya-Alex/anki-addons-catalog" (Docker, FastAPI)
              ├── HTML pages (Jinja2)          ── MCP tools ──┐
              └── /api/ask (Server-Sent Events)                │
                    └── Claude tool-use loop ── MCP tools ─────┤
                          │                                    ▼
                          ▼                     anki-addons-mcp server, in-process
                    Anthropic API                              │
                                                               ▼
                                                 HF dataset "Ya-Alex/anki-addons"
```

## Configuration

Environment variables (prefix `ANKI_CATALOG_`, also read from `.env`). `ANTHROPIC_API_KEY` is read by the
Anthropic SDK directly.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | | Claude API key (a Space secret) |
| `ANKI_CATALOG_HOST` / `ANKI_CATALOG_PORT` | `127.0.0.1` / `8000` | HTTP binding (`0.0.0.0` / `7860` in Docker) |
| `ANKI_CATALOG_PUBLIC_URL` | `https://www.anki-addons-catalog.com` | Base URL for the sitemap and canonical links |
| `ANKI_CATALOG_MCP_URL` | | A remote MCP server endpoint (e.g. `http://localhost:8000/mcp`); unset runs the MCP server in-process |
| `ANKI_MCP_*` | | Settings of the in-process MCP server, e.g. `ANKI_MCP_REFRESH_INTERVAL_SECONDS` (see the [MCP server](https://github.com/Aleks-Ya/anki-addons-mcp)) |
| `HF_TOKEN` | | HuggingFace token (a Space secret) for downloading the dataset; also sent to a remote MCP server |
| `ANKI_CATALOG_MCP_TIMEOUT_SECONDS` | `120` | MCP read timeout (covers a Space waking up) |
| `ANKI_CATALOG_MCP_KEEPALIVE_SECONDS` | `600` | Ping a remote MCP server this often to keep its Space awake; `0` disables |
| `ANKI_CATALOG_MCP_CACHE_TTL_SECONDS` | `3600` | Cache of MCP results for the plain pages |
| `ANKI_CATALOG_AI_TOOLS` | all except `query_sql` | JSON list of MCP tools Claude may call |
| `ANKI_CATALOG_MODEL` | `sonnet` | `sonnet` (Claude Sonnet 5.5), `haiku` (Claude Haiku 5.5) or a full model ID; prices and the refusal fallback follow the model |
| `ANKI_CATALOG_EFFORT` | `low` | Claude effort |
| `ANKI_CATALOG_MAX_TOKENS` / `ANKI_CATALOG_MAX_TOOL_ROUNDS` | `8000` / `6` | Per-answer limits |
| `ANKI_CATALOG_FALLBACKS_ENABLED` | `true` | Server-side refusal fallback (`fallbacks: "default"`), for models that have it (not Haiku 5.5) |
| `ANKI_CATALOG_PRICE_*_PER_MTOK` | the model's prices | Override the prices used to count the spend; required for a model the app doesn't know |
| `ANKI_CATALOG_DAILY_BUDGET_USD` | `5` | Global AI spend cap per UTC day; then only keyword search works |
| `ANKI_CATALOG_RATE_LIMIT_PER_HOUR` | `20` | AI questions per visitor IP per hour; `0` disables |
| `ANKI_CATALOG_ANSWER_CACHE_TTL_SECONDS` | `86400` | Cache of AI answers per question and snapshot |
| `ANKI_CATALOG_MAX_QUERY_CHARS` | `500` | Maximum question length |
| `ANKI_CATALOG_TURNSTILE_SITE_KEY` / `_TURNSTILE_SECRET` | | Cloudflare Turnstile bot check for AI search; disabled when unset |
| `ANKI_CATALOG_SESSION_SECRET` | random | Key that signs the "human verified" cookie; set it so the cookie survives restarts |
| `ANKI_CATALOG_PASS_TTL_SECONDS` | `3600` | How long a passed bot check lasts |
| `ANKI_CATALOG_ADMIN_TOKEN` | | Password of the usage page `/admin/usage` (any user name); the page is off when unset |
| `ANKI_CATALOG_USAGE_DB` | in memory | SQLite file with the usage counters; when unset and `/data` is writable, the in-memory counters are saved to `/data/usage.sqlite3` |
| `ANKI_CATALOG_USAGE_SAVE_SECONDS` | `300` | How often the counters are saved to `/data` (also on shutdown) |
| `ANKI_CATALOG_QUESTION_DAYS` | `90` | How long the AI question log (`/admin/questions`) keeps questions |
| `ANKI_CATALOG_LOG_LEVEL` | `INFO` | Logs go to stderr |
