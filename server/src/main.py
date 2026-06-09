from dotenv import load_dotenv

load_dotenv()

import asyncio  # noqa: E402
from pathlib import Path  # noqa: E402
import sys  # noqa: E402
from typing import Literal, Optional  # noqa: E402
import httpx  # noqa: E402
from db.background_jobs import reset_in_progress_jobs_to_pending  # noqa: E402
from db.common import CreateGlobalTemplate  # noqa: E402
from db.links import reset_processing_links_to_pending  # noqa: E402
from logging_config import get_logger, setup_logging  # noqa: E402
import os  # noqa: E402

import uvicorn  # noqa: E402
from litestar import Litestar, asgi, get  # noqa: E402
from litestar.router import Router  # noqa: E402
from litestar.exceptions import ValidationException  # noqa: E402
from litestar.config.cors import CORSConfig  # noqa: E402
from litestar.static_files import StaticFiles  # noqa: E402
from litestar.types import Receive, Scope, Send  # noqa: E402
from litestar.file_system import BaseLocalFileSystem  # noqa: E402
from litestar.response.file import ASGIFileResponse  # noqa: E402
import threading  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from worker import run_worker  # noqa: E402
from controllers.api_request_logs import ApiRequestLogController  # noqa: E402
from controllers.providers import ProviderController  # noqa: E402
from controllers.sse import SSEController  # noqa: E402
from controllers.projects import ProjectController  # noqa: E402
from controllers.sources import SourceController  # noqa: E402
from controllers.links import LinksController  # noqa: E402
from controllers.lorebook_entries import LorebookEntryController  # noqa: E402
from controllers.character_cards import CharacterCardController  # noqa: E402
from controllers.background_jobs import (  # noqa: E402
    BackgroundJobController,
)
from controllers.analytics import AnalyticsController  # noqa: E402
from controllers.global_templates import GlobalTemplateController  # noqa: E402
from controllers.credentials import CredentialsController  # noqa: E402
from controllers.health import HealthController  # noqa: E402
from exceptions import (  # noqa: E402
    generic_exception_handler,
    validation_exception_handler,
    value_error_exception_handler,
)
from db.connection import close_database, get_db_connection, init_database  # noqa: E402
from db.global_templates import create_global_template, get_global_template  # noqa: E402
from db.credentials import (  # noqa: E402
    CreateCredential,
    CredentialValues,
    create_credential,
    list_credentials,
)
import default_templates  # noqa: E402

import providers.openrouter  # noqa: E402, F401
import providers.gemini  # noqa: E402, F401
import providers.openai_compatible  # noqa: E402, F401

logger = get_logger(__name__)

cors_config = CORSConfig(
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"]
)


async def create_default_templates():
    """Create default global templates if they don't exist."""
    templates_to_create = [
        CreateGlobalTemplate(
            id="selector-prompt",
            name="selector_prompt",
            content=default_templates.selector_prompt,
        ),
        CreateGlobalTemplate(
            id="search-params-prompt",
            name="search_params_prompt",
            content=default_templates.search_params_prompt,
        ),
        CreateGlobalTemplate(
            id="entry-creation-prompt",
            name="entry_creation_prompt",
            content=default_templates.entry_creation_prompt,
        ),
        CreateGlobalTemplate(
            id="lorebook-definition",
            name="lorebook_definition",
            content=default_templates.lorebook_definition,
        ),
        CreateGlobalTemplate(
            id="character-card-definition",
            name="character_card_definition",
            content=default_templates.character_card_definition,
        ),
        CreateGlobalTemplate(
            id="character-generation-prompt",
            name="character_generation_prompt",
            content=default_templates.character_generation_prompt,
        ),
        CreateGlobalTemplate(
            id="character-field-regeneration-prompt",
            name="character_field_regeneration_prompt",
            content=default_templates.character_field_regeneration_prompt,
        ),
        CreateGlobalTemplate(
            id="json-formatter-prompt",
            name="JSON Formatter Prompt",
            content=default_templates.json_formatter_prompt,
        ),
    ]
    for template in templates_to_create:
        existing_template = await get_global_template(template.id)
        if not existing_template:
            await create_global_template(template)
            logger.info(f"Created default template: {template.name}")


async def create_credentials_from_env():
    """Create default credentials from environment variables if they don't exist."""
    logger.info("Checking for environment variables to create default credentials...")
    existing_credentials = await list_credentials()
    existing_provider_types = {c.provider_type for c in existing_credentials}

    # --- OpenRouter ---
    if "openrouter" not in existing_provider_types:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if api_key:
            await create_credential(
                CreateCredential(
                    name="Default OpenRouter (from env)",
                    provider_type="openrouter",
                    values=CredentialValues(api_key=api_key),
                )
            )
            logger.info(
                "Created default credential for OpenRouter from OPENROUTER_API_KEY."
            )

    # --- Gemini ---
    if "gemini" not in existing_provider_types:
        api_key = os.getenv("GOOGLE_GEMINI_KEY")
        if api_key:
            await create_credential(
                CreateCredential(
                    name="Default Gemini (from env)",
                    provider_type="gemini",
                    values=CredentialValues(api_key=api_key),
                )
            )
            logger.info("Created default credential for Gemini from GOOGLE_GEMINI_KEY.")

    # --- OpenAI Compatible ---
    if "openai_compatible" not in existing_provider_types:
        base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
        if base_url:
            api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY")
            await create_credential(
                CreateCredential(
                    name="Default OpenAI Compatible (from env)",
                    provider_type="openai_compatible",
                    values=CredentialValues(base_url=base_url, api_key=api_key),
                )
            )
            logger.info(
                "Created default credential for OpenAI Compatible from environment variables."
            )


async def recover_stale_datas():
    """Resets any datas that were 'in_progress' back to 'pending'."""
    logger.info("Checking for stale jobs to recover...")
    async with (await get_db_connection()).transaction() as tx:
        await reset_in_progress_jobs_to_pending(tx=tx)
        await reset_processing_links_to_pending(tx=tx)


CLIENT_BUILD_DIR = (
    Path(os.path.abspath(__file__)).parent.parent.parent / "client" / "dist"
)
assets_app = StaticFiles(
    is_html_mode=False,
    directories=[CLIENT_BUILD_DIR / "assets"],
    file_system=BaseLocalFileSystem(),
)


@asgi(path="/assets", is_static=True)
async def serve_assets(scope: Scope, receive: Receive, send: Send) -> None:
    """Handles serving static assets from the /assets directory."""
    await assets_app(scope, receive, send)


@get(path=["/", "/{path:path}"], sync_to_thread=False)
async def spa_fallback(path: str | None = None) -> ASGIFileResponse:
    """
    Serves the index.html file for all non-API and non-asset routes.
    This is the catch-all for the Single-Page Application.
    """
    return ASGIFileResponse(
        file_path=CLIENT_BUILD_DIR / "index.html",
        media_type="text/html",
        filename="index.html",
        content_disposition_type="inline",
    )


class AppInfo(BaseModel):
    current_version: str
    latest_version: Optional[str] = None
    runtime_env: Literal["docker", "source"]
    update_available: bool


async def get_latest_github_version() -> Optional[str]:
    """Fetches the latest tag name from the GitHub repository."""
    # Use the /tags endpoint since the repo uses tags, not formal releases
    repo_url = "https://api.github.com/repos/bmen25124/lorecard/tags"
    headers = {"Accept": "application/vnd.github.v3+json"}
    try:
        async with httpx.AsyncClient() as client:
            # Get the list of tags; the API returns them in reverse chronological order
            response = await client.get(repo_url, headers=headers, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            # The latest tag is the first one in the list
            if data and isinstance(data, list) and len(data) > 0:
                return data[0].get("name")
            else:
                logger.warning("No tags found in the GitHub repository.")
                return None
    except httpx.RequestError as e:
        logger.warning(f"Could not fetch latest version from GitHub: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching GitHub version: {e}")
        return None


@get(path="/info", sync_to_thread=False)
async def get_app_info() -> AppInfo:
    """Returns basic application information, including whether an update is available."""
    current_version = os.getenv("APP_VERSION", "development").split("-")[0]
    latest_version = await get_latest_github_version()
    runtime_env = os.getenv("RUNTIME_ENV", "source")

    update_available = False
    if (
        current_version != "development"
        and latest_version
        and current_version != latest_version
    ):
        update_available = True

    return AppInfo(
        current_version=current_version,
        latest_version=latest_version,
        runtime_env=runtime_env,  # pyright: ignore[reportArgumentType]
        update_available=update_available,
    )


def create_app(close_db_on_shutdown: bool = True):
    api_router = Router(
        path="/api",
        exception_handlers={
            Exception: generic_exception_handler,
            ValidationException: validation_exception_handler,
            ValueError: value_error_exception_handler,
        },
        route_handlers=[
            get_app_info,
            HealthController,
            CredentialsController,
            ApiRequestLogController,
            ProviderController,
            SSEController,
            ProjectController,
            SourceController,
            LinksController,
            LorebookEntryController,
            CharacterCardController,
            BackgroundJobController,
            AnalyticsController,
            GlobalTemplateController,
        ],
    )

    return Litestar(
        cors_config=cors_config,
        exception_handlers={
            Exception: generic_exception_handler,
            ValidationException: validation_exception_handler,
            ValueError: value_error_exception_handler,
        },
        route_handlers=[
            api_router,
            serve_assets,
            spa_fallback,
        ],
        on_startup=[
            create_default_templates,
            recover_stale_datas,
            create_credentials_from_env,
        ],
        on_shutdown=[close_database] if close_db_on_shutdown else [],
        static_files_config=None,
    )


app = create_app()


async def main():
    """Main function to orchestrate application startup."""
    setup_logging()

    logger.info("Initializing database...")
    await init_database()
    logger.info("Database initialization complete.")

    logger.info("Starting worker thread...")
    worker_thread = threading.Thread(
        target=lambda: asyncio.run(run_worker()), daemon=True
    )
    worker_thread.start()

    port = int(os.getenv("PORT", 3000))
    config = uvicorn.Config(
        app, host="0.0.0.0", port=port, log_config=None, forwarded_allow_ips="*"
    )
    server = uvicorn.Server(config)

    logger.info(f"Starting API server on http://0.0.0.0:{port}")
    await server.serve()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
