from extraction.prompts import EXCLUSIONS_SYSTEM_PROMPT
from extraction.schemas import ExclusionsExtraction
from ingestion.parsing.document_parser import ParsedSection
from extraction.client import ExtractionClient



class ExclusionExtractor:
    def __init__(self, client: ExtractionClient):
        self.client = client
    
async def extract(self, section: ParsedSection) -> ExclusionsExtraction:
    result = await self.client.extract(
        schema=ExclusionsExtraction,
        system_prompt=EXCLUSIONS_SYSTEM_PROMPT,
        user_content=f"Extract all exclusions from the following policy section:\n\n{section.raw_markdown}",
        task_label="exclusions",
        use_large_model=False,
    )
    self._assign_ids_if_missing(result)
    return result

    def _assign_ids_if_missing(self, result: ExclusionsExtraction):
        """Assign deterministic IDs if LLM didn't provide them"""
        for i, exc in enumerate(result.exclusions):
            if not exc.exclusion_id or exc.exclusion_id.strip() == "":
                exc.exclusion_id = f"EX-{i+1:03d}"