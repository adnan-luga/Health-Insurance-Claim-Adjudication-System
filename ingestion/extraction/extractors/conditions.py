from ..prompts import CONDITIONS_SYSTEM_PROMPT
from ingestion.parsing.document_parser import ParsedSection
from ..client import ExtractionClient
from ..schemas import ConditionsExtraction

class ConditionExtractor:
    def __init__(self, client: ExtractionClient):
        self.client = client
    
    async def extract(self, section: ParsedSection) -> ConditionsExtraction:
        result = await self.client.extract(
            schema=ConditionsExtraction,
            system_prompt=CONDITIONS_SYSTEM_PROMPT,
            user_content=f"Extract deductible and out-of-pocket maximum:\n\n{section.raw_markdown}",
            task_label="conditions",
            use_large_model=False,
        )
        self._validate_deductible(result)
        return result
    
    def _validate_deductible(self, result: ConditionsExtraction):
        if (
            result.deductible.applies_to == ["*"]
            and not result.deductible.waived_for
        ):
            result.extraction_warnings.append(
                "Deductible applies_to=["*"] and waived_for=[]. "
                "Verify that no waiver clauses were missed."
            )
        