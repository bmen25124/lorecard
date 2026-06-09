import asyncio
import json
from typing import List, Optional
from uuid import UUID
from litestar import Controller, get, post
from litestar.exceptions import HTTPException, NotFoundException
from pydantic import BaseModel, Field
from logging_config import get_logger
from providers.index import (
    ChatCompletionErrorResponse,
    ChatCompletionRequest,
    ChatMessage,
    ModelInfo,
    JsonMode,
    ProviderInfo,
    provider_classes,
    get_provider_for_listing,
    get_provider_instance,
)
from db.credentials import (
    CredentialValues,
    get_credential_with_values,
    list_credentials,
)
from providers.index import (
    ResponseSchema,
)

logger = get_logger(__name__)


class TestCredentialPayload(BaseModel):
    provider_type: str
    values: CredentialValues
    model_name: Optional[str] = None
    credential_id: Optional[UUID] = None
    json_mode: JsonMode = JsonMode.api_native


class TestCredentialResult(BaseModel):
    success: bool
    message: str
    native_json_supported: bool = Field(default=False)


class TestSchemaPayload(BaseModel):
    greeting: str
    status: bool


class ProviderController(Controller):
    path = "/providers"

    @get(path="/")
    async def get_providers(self, include_models: bool = True) -> List[ProviderInfo]:
        logger.debug("Listing all available providers and their models")

        all_credentials = await list_credentials()
        provider_info_tasks = []

        for provider_id in provider_classes.keys():

            async def get_info(pid):
                instance = None
                is_configured = False

                # --- Prioritize credentials from the database ---
                first_credential_for_provider = next(
                    (c for c in all_credentials if c.provider_type == pid), None
                )

                if first_credential_for_provider:
                    try:
                        full_credential = await get_credential_with_values(
                            first_credential_for_provider.id
                        )
                        if full_credential and full_credential.get("values"):
                            instance = get_provider_instance(
                                pid, full_credential["values"].model_dump()
                            )
                        logger.info(
                            f"Using credential '{first_credential_for_provider.name}' to list models for {pid}."
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to instantiate provider '{pid}' with credential '{first_credential_for_provider.name}': {e}"
                        )

                # --- Fallback to environment variables if no instance yet ---
                if not instance:
                    try:
                        instance = get_provider_for_listing(pid)
                        logger.info(
                            f"Using environment variables to list models for {pid}."
                        )
                    except Exception:
                        # This provider is not configured via credential or env var.
                        pass

                if instance:
                    if not include_models:
                        return ProviderInfo(
                            id=pid,
                            name=pid.capitalize(),
                            models=[],
                            configured=True,
                        )

                    # --- If we have an instance, get models ---
                    try:
                        models = await instance.get_models()
                        is_configured = True
                        return ProviderInfo(
                            id=pid,
                            name=pid.capitalize(),
                            models=models,
                            configured=is_configured,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Provider '{pid}' is configured, but failed to fetch models: {e}"
                        )
                        # Fallthrough to return as unconfigured

                # --- Return as unconfigured if any step failed ---
                return ProviderInfo(
                    id=pid,
                    name=pid.capitalize(),
                    models=[],
                    configured=False,
                )

            provider_info_tasks.append(get_info(provider_id))

        results = await asyncio.gather(*provider_info_tasks)
        return results

    @post(path="/models")
    async def get_provider_models(self, data: TestCredentialPayload) -> List[ModelInfo]:
        """Dynamically fetches models using provided, unsaved credential values."""
        logger.info(f"Fetching models for provider: {data.provider_type}")
        try:
            provider = get_provider_instance(
                data.provider_type, data.values.model_dump()
            )
            return await provider.get_models()
        except Exception as e:
            logger.error(
                f"Failed to fetch models for {data.provider_type}: {e}", exc_info=True
            )
            raise HTTPException(
                status_code=400, detail=f"Failed to connect to provider: {e}"
            )

    @post(path="/test")
    async def test_credential(
        self, data: TestCredentialPayload
    ) -> TestCredentialResult:
        logger.info(
            f"Testing credential for provider: {data.provider_type}, model: {data.model_name}, mode: {data.json_mode}"
        )
        if not data.model_name:
            raise HTTPException(
                status_code=400, detail="A model name is required for testing."
            )

        values_to_test = data.values.model_dump()

        if data.credential_id:
            existing_credential = await get_credential_with_values(data.credential_id)
            if not existing_credential:
                raise NotFoundException(f"Credential {data.credential_id} not found.")

            merged_values = existing_credential["values"].model_dump()
            if data.values.api_key:
                merged_values["api_key"] = data.values.api_key
            if data.values.base_url:
                merged_values["base_url"] = data.values.base_url
            values_to_test = merged_values

        provider = get_provider_instance(data.provider_type, values_to_test)

        json_test_request = ChatCompletionRequest(
            model=data.model_name,
            messages=[
                ChatMessage(
                    role="user",
                    content="Respond with a simple greeting and status.",
                )
            ],
            temperature=1,
            response_format=ResponseSchema(
                name="test_schema", schema_value=TestSchemaPayload.model_json_schema()
            ),
            json_mode=data.json_mode,
        )

        response = await provider.generate(json_test_request)

        if isinstance(response, ChatCompletionErrorResponse):
            if (
                data.json_mode == JsonMode.api_native
                and response.raw_response
                and 400 <= response.status_code < 500
            ):
                response_text = (
                    json.dumps(response.raw_response)
                    if isinstance(response.raw_response, dict)
                    else str(response.raw_response)
                )
                if any(
                    term in response_text
                    for term in [
                        "response_format",
                        "json_schema",
                        "unrecognized",
                        "tool_choice",
                    ]
                ):
                    return TestCredentialResult(
                        success=False,
                        message="Native JSON mode is not supported by this model or endpoint. Try 'Prompt Engineering' mode.",
                        native_json_supported=False,
                    )
            return TestCredentialResult(
                success=False,
                message=f"API Error ({response.status_code}): {response.raw_response or 'Unknown error'}",
                native_json_supported=False,
            )

        if not isinstance(response.content, dict):
            return TestCredentialResult(
                success=False,
                message="Test failed. The model did not return a valid JSON object.",
                native_json_supported=False,
            )

        try:
            TestSchemaPayload.model_validate(response.content)
        except Exception as e:
            return TestCredentialResult(
                success=False,
                message=f"Test failed. Returned JSON did not match the schema. Error: {e}",
                native_json_supported=False,
            )

        if data.json_mode == JsonMode.api_native:
            return TestCredentialResult(
                success=True,
                message="Connection successful. Native JSON mode is supported.",
                native_json_supported=True,
            )
        else:  # prompt_engineering
            return TestCredentialResult(
                success=True,
                message="Connection successful. Prompt Engineering JSON mode is working correctly.",
                native_json_supported=False,
            )
