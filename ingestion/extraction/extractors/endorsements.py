

from ingestion.parsing.document_parser import ParsedSection
from ..client import ExtractionClient
from ..schemas import EndorsementsExtraction
from ..prompts import ENDORSEMENTS_SYSTEM_PROMPT

class EndorsementsExtractor:
    def __init__(self, client: ExtractionClient):
        self.client = client
    
    async def extract(self, section: ParsedSection) -> EndorsementsExtraction:
        result = await self.client.extract(
            schema=EndorsementsExtraction,
            system_prompt=ENDORSEMENTS_SYSTEM_PROMPT,
            user_content=f"Extract all endorsements:\n\n{section.raw_markdown}",
            task_label="endorsements",
            use_large_model=True,
        )
        self._validate_priorities(result)
        return result
    
    def _validate_priorities(self, result: EndorsementsExtraction):
        """Guarantee all endorsements beat base policy rules."""
        for end in result.endorsements:
            if end.priority < 100:
                result.extraction_warnings.append(
                    f"Endorsement {end.endorsement_id} had priority {end.priority} < 100. "
                    f"Corrected to 100"
                )
                end.priority = 100
        