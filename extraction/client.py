from pydantic import BaseModel
from openai import AsyncOpenAI
import instructor
from typing import Type, TypeVar
import structlog

T = TypeVar("T", bound=BaseModel)
log = structlog.get_logger()

class ExtractionClient:

    def __init__(
        self,
        base_url: str,
        large_model: str,
        small_model: str,
        api_key: str = "not-needed",
        max_retries: int = 3,
    ):
        raw_client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.client = instructor.from_openai(
            raw_client,
            mode=instructor.Mode.JSON,
        )
        self.large_model = large_model
        self.small_model = small_model
        self.max_retries = max_retries

    async def extract(
        self,
        schema: Type[T],
        system_prompt: str,
        user_content: str,
        use_large_model: bool = True,
        task_label: str = "extraction"
    ) -> T:
        """Core extraction method that returns validated Pydantic object.
        Instructor handles schema enforcement and retry loop internally
        """
        model = self.large_model if use_large_model else self.small_model

        log.info("extraction.start", task=task_label, model=model, schema=schema.__name__)
        
        result, completion = await self.client.chat.completions.create_with_completion(
            model=model,
            response_model=schema,
            max_retries=self.max_retries,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            # vLLM specific constrain output format
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=8192,
        )

        log.info(
            "extraction.complete",
            task=task_label,
            model=model,
            input_tokens=completion.usage.prompt_tokens,
            output_tokens=completion.usage.completion_tokens,
            total_tokens=completion.usage.total_tokens,
        )

        return result