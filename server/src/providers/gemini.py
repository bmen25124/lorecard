import json
import time
from typing import Dict, List, Literal, Optional, Union
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, ConfigDict
from db.global_templates import get_global_template
from logging_config import get_logger

from providers.index import (
    ChatCompletionUsage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionErrorResponse,
    BaseProvider,
    JsonMode,
    register_provider,
    ModelInfo,
    normalize_response_content,
)
from providers.utils import extract_json_from_code_block, generate_example_from_schema
from services.templates import create_messages_from_template

logger = get_logger(__name__)

API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# --- Structured Pricing Data ---
# Prices are per 1 million tokens.
# Tiers are sorted by threshold (ascending). The first tier where prompt_tokens <= threshold is used.
GEMINI_PRICING_DATA = {
    "gemini-2.5-pro": [
        {"threshold": 200000, "input_cost": 1.25, "output_cost": 10.00},
        {"threshold": float("inf"), "input_cost": 2.50, "output_cost": 15.00},
    ],
    "gemini-2.5-flash-lite": [
        {"threshold": float("inf"), "input_cost": 0.10, "output_cost": 0.40},
    ],
    "gemini-2.5-flash": [
        {"threshold": float("inf"), "input_cost": 0.30, "output_cost": 2.50},
    ],
    "gemini-2.0-flash-lite": [
        {"threshold": float("inf"), "input_cost": 0.075, "output_cost": 0.30},
    ],
    "gemini-2.0-flash": [
        {"threshold": float("inf"), "input_cost": 0.10, "output_cost": 0.40},
    ],
    "gemini-1.5-pro": [
        {"threshold": 128000, "input_cost": 1.25, "output_cost": 5.00},
        {"threshold": float("inf"), "input_cost": 2.50, "output_cost": 10.00},
    ],
    "gemini-1.5-flash-8b": [
        {"threshold": 128000, "input_cost": 0.0375, "output_cost": 0.15},
        {"threshold": float("inf"), "input_cost": 0.075, "output_cost": 0.30},
    ],
    "gemini-1.5-flash": [
        {"threshold": 128000, "input_cost": 0.075, "output_cost": 0.30},
        {"threshold": float("inf"), "input_cost": 0.15, "output_cost": 0.60},
    ],
    "gemma": [
        {"threshold": float("inf"), "input_cost": 0.0, "output_cost": 0.0},
    ],
}


def _calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Calculates the cost of a Gemini API call based on a structured pricing table.
    - Matches model ID by prefix.
    - Handles tiered pricing based on input token count.
    - Returns -1.0 for unknown models to signify that pricing is not available.
    """
    pricing_info = None
    # Find the most specific matching prefix for the model
    for prefix in sorted(GEMINI_PRICING_DATA.keys(), key=len, reverse=True):
        if model.startswith(prefix):
            pricing_info = GEMINI_PRICING_DATA[prefix]
            break

    if not pricing_info:
        logger.warning(
            f"Pricing not found for model '{model}'. Returning -1.0 to indicate unknown cost."
        )
        return -1.0

    input_cost_per_million = 0.0
    output_cost_per_million = 0.0

    # Find the correct pricing tier based on the number of prompt tokens
    for tier in pricing_info:
        if prompt_tokens <= tier["threshold"]:
            input_cost_per_million = tier["input_cost"]
            output_cost_per_million = tier["output_cost"]
            break

    cost = (prompt_tokens / 1_000_000 * input_cost_per_million) + (
        completion_tokens / 1_000_000 * output_cost_per_million
    )

    return cost


# --- Gemini Specific Pydantic Models ---


class GeminiGenerationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stop_sequences: Optional[List[str]] = Field(
        None, serialization_alias="stopSequences"
    )
    max_output_tokens: Optional[int] = Field(
        None, serialization_alias="maxOutputTokens"
    )
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, serialization_alias="topP")
    top_k: Optional[int] = Field(None, serialization_alias="topK")
    response_mime_type: Optional[str] = Field(
        None, serialization_alias="responseMimeType"
    )


class GeminiPart(BaseModel):
    text: str


class GeminiContent(BaseModel):
    role: Literal["user", "model"]
    parts: List[GeminiPart]


class GeminiSystemInstruction(BaseModel):
    role: Literal["user"] = "user"  # System instructions are user role in Gemini
    parts: List[GeminiPart]


class GeminiRequestBody(BaseModel):
    contents: List[GeminiContent]
    system_instruction: Optional[GeminiSystemInstruction] = Field(
        None, serialization_alias="systemInstruction"
    )
    generation_config: GeminiGenerationConfig = Field(
        ..., serialization_alias="generationConfig"
    )


# --- Gemini Response Models ---


class GeminiResponsePart(BaseModel):
    text: Optional[str] = None


class GeminiResponseContent(BaseModel):
    parts: List[GeminiResponsePart] = Field(default_factory=list)
    role: Optional[str] = None


class GeminiResponseCandidate(BaseModel):
    content: GeminiResponseContent


class GeminiUsageMetadata(BaseModel):
    prompt_token_count: int = Field(..., alias="promptTokenCount")
    candidates_token_count: int = Field(..., alias="candidatesTokenCount")
    total_token_count: int = Field(..., alias="totalTokenCount")


class GeminiAPIResponse(BaseModel):
    candidates: List[GeminiResponseCandidate] = Field(default_factory=list)
    usage_metadata: Optional[GeminiUsageMetadata] = Field(None, alias="usageMetadata")


class GeminiClient(BaseProvider):
    def __init__(self, api_key: Optional[str] = None, **kwargs):
        self.api_key = api_key
        if not self.api_key:
            raise ValueError(
                "Google Gemini API key not found. Please provide it in your credential or set the GOOGLE_GEMINI_KEY environment variable."
            )

    async def get_models(self) -> List[ModelInfo]:
        logger.debug("Fetching models from Google Gemini")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{API_BASE_URL}/models", params={"key": self.api_key}, timeout=30
                )
                response.raise_for_status()

            data = response.json().get("models", [])
            text_models: list[ModelInfo] = []
            for model in data:
                capabilities = model.get("supportedGenerationMethods", [])
                if "generateContent" in capabilities:
                    model_id = model.get("name", "").replace("models/", "")
                    text_models.append(
                        ModelInfo(id=model_id, name=model.get("displayName", model_id))
                    )

            text_models.sort(key=lambda x: x.name)
            logger.info(
                f"Fetched and filtered {len(text_models)} models from Google Gemini."
            )
            return text_models
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP Error fetching models from Google Gemini: {e.response.status_code}"
            )
            return []
        except Exception as e:
            logger.error(
                f"Error fetching models from Google Gemini: {e}", exc_info=True
            )
            return []

    async def generate(
        self, request: ChatCompletionRequest
    ) -> Union[ChatCompletionResponse, ChatCompletionErrorResponse]:
        use_prompt_engineering = (
            request.json_mode == JsonMode.prompt_engineering and request.response_format
        )

        if not use_prompt_engineering:
            return await self._generate_native(request)

        return await self._generate_with_prompt_engineering(request)

    async def _generate_native(
        self, request: ChatCompletionRequest
    ) -> Union[ChatCompletionResponse, ChatCompletionErrorResponse]:
        system_instruction = None
        contents = []

        system_prompt_parts = []

        for msg in request.messages:
            if msg.role == "system":
                system_prompt_parts.append(msg.content)
            else:
                role = "model" if msg.role == "assistant" else "user"
                contents.append(
                    GeminiContent(role=role, parts=[GeminiPart(text=msg.content)])
                )

        generation_config_data = {
            "temperature": request.temperature,
            "max_output_tokens": request.reasoning.max_tokens
            if request.reasoning
            else None,
        }

        if request.response_format:
            generation_config_data["response_mime_type"] = "application/json"
            schema_prompt = f"You must respond with a valid JSON object that strictly adheres to the following JSON schema. Do not include any other text or explanations before or after the JSON. JSON Schema: {json.dumps(request.response_format.schema_value)}"
            system_prompt_parts.insert(0, schema_prompt)

        if system_prompt_parts:
            system_instruction = GeminiSystemInstruction(
                parts=[GeminiPart(text="\n\n".join(system_prompt_parts))]
            )

        generation_config = GeminiGenerationConfig(
            **{k: v for k, v in generation_config_data.items() if v is not None}
        )

        # Ensure alternating user/model roles, merge consecutive messages of the same role
        merged_contents = []
        if contents:
            current_content = contents[0]
            for i in range(1, len(contents)):
                if contents[i].role == current_content.role:
                    current_content.parts.extend(contents[i].parts)
                else:
                    merged_contents.append(current_content)
                    current_content = contents[i]
            merged_contents.append(current_content)

        if not merged_contents or merged_contents[0].role != "user":
            # Gemini API requires the conversation to start with a user message.
            merged_contents.insert(
                0,
                GeminiContent(
                    role="user", parts=[GeminiPart(text="Start of conversation.")]
                ),
            )

        gemini_request = GeminiRequestBody(
            contents=merged_contents,
            system_instruction=system_instruction,
            generation_config=generation_config,
        )

        payload = gemini_request.model_dump(exclude_none=True, by_alias=True)

        logger.debug("--- Sending Gemini Payload ---")
        logger.debug(json.dumps(payload, indent=2))
        logger.debug("------------------------------")

        start_time = time.time()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{API_BASE_URL}/models/{request.model}:generateContent",
                    params={"key": self.api_key},
                    json=payload,
                    timeout=60,
                )
                response.raise_for_status()

            raw_response = response.json()
            api_response = GeminiAPIResponse.model_validate(raw_response)

            content_text = ""
            if api_response.candidates:
                candidate = api_response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text:
                            content_text += part.text

            final_content: Union[str, Dict] = content_text
            if request.response_format:
                try:
                    final_content = normalize_response_content(
                        json.loads(content_text)
                    )
                except json.JSONDecodeError:
                    logger.warning(
                        f"Gemini response was not valid JSON despite being asked. Raw: {content_text}"
                    )

            usage = ChatCompletionUsage(
                prompt_tokens=0, completion_tokens=0, total_tokens=0, cost=0.0
            )
            if api_response.usage_metadata:
                usage = ChatCompletionUsage(
                    prompt_tokens=api_response.usage_metadata.prompt_token_count,
                    completion_tokens=api_response.usage_metadata.candidates_token_count,
                    total_tokens=api_response.usage_metadata.total_token_count,
                    cost=_calculate_cost(
                        request.model,
                        api_response.usage_metadata.prompt_token_count,
                        api_response.usage_metadata.candidates_token_count,
                    ),
                )

            return ChatCompletionResponse(
                id=str(uuid4()),  # Gemini response doesn't have a top-level ID
                content=final_content,
                reasoning=None,
                usage=usage,
                raw_response=raw_response,
                raw_request=payload,
                latency_ms=int((time.time() - start_time) * 1000),
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Error: {e.response.status_code}")
            logger.error(f"Response Body: {e.response.text}")
            return ChatCompletionErrorResponse(
                raw_request=payload,
                raw_response=e.response.json() if e.response.text else None,
                status_code=e.response.status_code,
                latency_ms=int((time.time() - start_time) * 1000),
            )
        except httpx.RequestError as e:
            logger.error(f"Request Error: {e}", exc_info=True)
            return ChatCompletionErrorResponse(
                raw_request=payload,
                raw_response={"error": str(e)},
                status_code=500,
                latency_ms=int((time.time() - start_time) * 1000),
            )

    async def _generate_with_prompt_engineering(
        self, request: ChatCompletionRequest
    ) -> Union[ChatCompletionResponse, ChatCompletionErrorResponse]:
        formatter_template = await get_global_template("json-formatter-prompt")
        if not formatter_template or not request.response_format:
            raise Exception(
                "JSON formatter template not found or response_format not requested."
            )

        schema_str = json.dumps(request.response_format.schema_value, indent=2)
        example_response_str = generate_example_from_schema(
            request.response_format.schema_value
        )

        final_messages = request.messages + create_messages_from_template(
            formatter_template.content,
            {"schema": schema_str, "example_response": example_response_str},
        )

        # Re-run the message processing logic with the new messages
        system_instruction = None
        contents = []
        system_prompt_parts = []

        for msg in final_messages:
            if msg.role == "system":
                system_prompt_parts.append(msg.content)
            else:
                role = "model" if msg.role == "assistant" else "user"
                contents.append(
                    GeminiContent(role=role, parts=[GeminiPart(text=msg.content)])
                )

        if system_prompt_parts:
            system_instruction = GeminiSystemInstruction(
                parts=[GeminiPart(text="\n\n".join(system_prompt_parts))]
            )

        generation_config = GeminiGenerationConfig(temperature=request.temperature)  # pyright: ignore[reportCallIssue]

        merged_contents = []
        if contents:
            current_content = contents[0]
            for i in range(1, len(contents)):
                if contents[i].role == current_content.role:
                    current_content.parts.extend(contents[i].parts)
                else:
                    merged_contents.append(current_content)
                    current_content = contents[i]
            merged_contents.append(current_content)

        if not merged_contents or merged_contents[0].role != "user":
            merged_contents.insert(
                0, GeminiContent(role="user", parts=[GeminiPart(text="")])
            )

        gemini_request = GeminiRequestBody(
            contents=merged_contents,
            system_instruction=system_instruction,
            generation_config=generation_config,
        )

        payload = gemini_request.model_dump(exclude_none=True, by_alias=True)

        content_text = ""
        raw_response = {}
        parsed_content = None
        start_time = time.time()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{API_BASE_URL}/models/{request.model}:generateContent",
                    params={"key": self.api_key},
                    json=payload,
                    timeout=60,
                )
            response.raise_for_status()

            raw_response = response.json()
            api_response = GeminiAPIResponse.model_validate(raw_response)
            if api_response.candidates:
                candidate = api_response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text:
                            content_text += part.text

            json_str = extract_json_from_code_block(content_text)
            if not json_str:
                raise ValueError("No JSON code block found in the response.")

            parsed_content = normalize_response_content(json.loads(json_str))

            usage = ChatCompletionUsage(
                prompt_tokens=0, completion_tokens=0, total_tokens=0, cost=0.0
            )
            if api_response.usage_metadata:
                usage = ChatCompletionUsage(
                    prompt_tokens=api_response.usage_metadata.prompt_token_count,
                    completion_tokens=api_response.usage_metadata.candidates_token_count,
                    total_tokens=api_response.usage_metadata.total_token_count,
                    cost=_calculate_cost(
                        request.model,
                        api_response.usage_metadata.prompt_token_count,
                        api_response.usage_metadata.candidates_token_count,
                    ),
                )

            return ChatCompletionResponse(
                id=str(uuid4()),
                content=parsed_content,
                reasoning=None,
                usage=usage,
                raw_response=raw_response,
                raw_request=payload,
                latency_ms=int((time.time() - start_time) * 1000),
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Error: {e.response.status_code}")
            logger.error(f"Response Body: {e.response.text}")
            return ChatCompletionErrorResponse(
                raw_request=payload,
                raw_response=e.response.json() if e.response else None,
                status_code=e.response.status_code,
                latency_ms=int((time.time() - start_time) * 1000),
            )
        except httpx.RequestError as e:
            logger.error(f"Request Error: {e}", exc_info=True)
            return ChatCompletionErrorResponse(
                raw_request=payload,
                raw_response={"error": str(e)},
                status_code=500,
                latency_ms=int((time.time() - start_time) * 1000),
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to get valid JSON: {e}", exc_info=True)
            return ChatCompletionErrorResponse(
                raw_request=payload,
                raw_response={
                    "error": "Failed to get valid JSON.",
                    "final_response_text": content_text,
                },
                status_code=422,
                latency_ms=int((time.time() - start_time) * 1000),
            )


register_provider("gemini", GeminiClient)
