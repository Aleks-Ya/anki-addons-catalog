import argparse
import logging
import sys
from typing import Any

import uvicorn

from anki_addons_catalog import __version__
from anki_addons_catalog.bootstrap import create_app
from anki_addons_catalog.config import Settings


def _parse_args(argv: list[str] | None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(prog="anki-addons-catalog", description="Anki Addons Catalog web app")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--mcp-url", dest="mcp_url")
    parser.add_argument("--log-level", dest="log_level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return {k: v for k, v in vars(parser.parse_args(argv)).items() if v is not None}


def main(argv: list[str] | None = None) -> None:
    settings = Settings(**_parse_args(argv))
    logging.basicConfig(stream=sys.stderr, level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if settings.log_level != "DEBUG":
        for noisy in ("httpx", "httpx2", "mcp", "huggingface_hub"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level=settings.log_level.lower(),
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
