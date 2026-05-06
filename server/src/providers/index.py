from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union, Type
from pydantic import BaseModel, Field, field_validator

from logging_config import get_logger

logger = get_logger(__name__)


class ModelInfo(BaseModel):
    """Information about a specific model."""

    id: str
    name: str


class ProviderInfo(BaseModel):
    """Information about a provider and its models."""

    id: str
    name: str
    models: List[ModelInfo]
    configured: bool


class ChatMessage(BaseModel):
    """A simple message object for the request, only supporting text."""

    role: Literal["system", "user", "assistant"]
    content: str


class Reasoning(BaseModel):
    """Defines the reasoning parameters for the request."""

    max_tokens: Optional[int] = Field(None, description="Reasoning budget in tokens.")
    effort: Optional[Literal["low", "medium", "high"]] = Field(
        None, description="Reasoning effort level."
    )


class ResponseSchema(BaseModel):
    name: str
    schema_value: Dict[str, Any] = Field(
        description="The JSON schema for the response.",
    )

    @field_validator("schema_value")
    def flatten_schema_validator(cls, schema_value: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten a JSON schema by inlining all definitions and set additionalProperties to false and required to all property keys if not set."""
        definitions = schema_value.pop("$defs", {})

        def replace_refs(obj: Any) -> Any:
            if isinstance(obj, dict):
                if "$ref" in obj:
                    ref = obj["$ref"]
                    if ref.startswith("#/$defs/"):
                        def_name = ref.split("/")[-1]
                        return replace_refs(
                            definitions[def_name]
                        )  # Set defaults for objects with properties
                if "properties" in obj:
                    # Set additionalProperties to false if not set or if set to true
                    if (
                        "additionalProperties" not in obj
                        or obj.get("additionalProperties") is True
                    ):
                        obj["additionalProperties"] = False

                return {k: replace_refs(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_refs(item) for item in obj]
            return obj

        flattened_schema = replace_refs(
            schema_value
        )  # Also handle the root level schema
        if "properties" in flattened_schema:
            # Set additionalProperties to false if not set or if set to true
            if (
                "additionalProperties" not in flattened_schema
                or flattened_schema.get("additionalProperties") is True
            ):
                flattened_schema["additionalProperties"] = False

        return flattened_schema


class ChatCompletionUsage(BaseModel):
    """Usage statistics for the API call."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float


class ChatCompletionResponse(BaseModel):
    """The response object for a chat completion."""

    id: str
    content: Union[str, Dict]
    reasoning: Optional[str]
    usage: ChatCompletionUsage
    raw_response: Dict[str, Any]
    raw_request: Dict[str, Any]
    latency_ms: int


class ChatCompletionErrorResponse(BaseModel):
    """The error response object for a chat completion."""

    raw_request: Dict[str, Any]
    raw_response: Optional[Dict[str, Any]] = None
    status_code: int
    latency_ms: int


def normalize_response_content(content: Any) -> Any:
    """Accept providers that wrap one structured JSON object in a list."""
    if (
        isinstance(content, list)
        and len(content) == 1
        and isinstance(content[0], dict)
    ):
        return content[0]
    return content


class JsonMode(str, Enum):
    api_native = "api_native"
    prompt_engineering = "prompt_engineering"


class ChatCompletionRequest(BaseModel):
    """The main request body sent to the provider API."""

    model: str
    messages: list[ChatMessage]
    temperature: Optional[float] = Field(None, ge=0, le=2)
    reasoning: Optional[Reasoning] = None
    response_format: Optional[ResponseSchema] = None
    json_mode: JsonMode = JsonMode.api_native


class BaseProvider(ABC):
    @abstractmethod
    async def generate(
        self, request: ChatCompletionRequest
    ) -> Union[ChatCompletionResponse, ChatCompletionErrorResponse]:
        raise NotImplementedError

    @abstractmethod
    async def get_models(self) -> List[ModelInfo]:
        """Fetch and return a list of available models for the provider."""
        raise NotImplementedError

    @abstractmethod
    async def _generate_native(
        self, request: ChatCompletionRequest
    ) -> Union[ChatCompletionResponse, ChatCompletionErrorResponse]:
        raise NotImplementedError

    @abstractmethod
    async def _generate_with_prompt_engineering(
        self, request: ChatCompletionRequest
    ) -> Union[ChatCompletionResponse, ChatCompletionErrorResponse]:
        raise NotImplementedError


provider_classes: Dict[str, Type[BaseProvider]] = {}


def register_provider(name: str, provider_class: Type[BaseProvider]):
    """Registers a provider class, to be instantiated later."""
    provider_classes[name] = provider_class


def get_provider_for_listing(name: str) -> BaseProvider:
    if name not in provider_classes:
        raise ValueError(f"Provider '{name}' is not registered.")
    try:
        return provider_classes[name]()
    except Exception as e:
        logger.warning(
            f"Could not initialize provider '{name}' for listing. It may be missing configuration. Error: {e}"
        )
        raise


def get_provider_instance(name: str, credential_values: Dict[str, Any]) -> BaseProvider:
    """
    Instantiates and returns a provider with specific credentials for a job.
    """
    if name not in provider_classes:
        raise ValueError(f"Provider '{name}' is not registered.")
    logger.info(f"Instantiating provider '{name}' for a job.")
    return provider_classes[name](**credential_values)
