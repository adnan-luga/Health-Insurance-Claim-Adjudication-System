from ..prompts import TABLE_OF_BENEFITS_SYSTEM_PROMPT
from ..schemas import TableOfBenefitsExtraction
from ingestion.parsing.document_parser import ParsedSection
from ..client import ExtractionClient
import json


class TableOfBenefitsExtractor:
    def __init__(self, client: ExtractionClient):
        self.client = client
    
    async def extract(self, section: ParsedSection) -> TableOfBenefitsExtraction:
        """
        Send both the markdown and the structured cell JSON.
        The markdown gives the LLM context, the cell JSON gives it precise values.
        """
        # Universal guard: if this section has no table data AND barely any text,
        # it is a preamble/reference paragraph — not the real benefits section.
        # Return empty rather than sending it to the LLM which will hallucinate.
        table_context = self._build_hybrid_context(section)
        has_table_data = bool(table_context.strip())
        has_sufficient_text = len(section.raw_markdown.strip()) >= 300

        if not has_table_data and not has_sufficient_text:
            return TableOfBenefitsExtraction(
                coverage_rules=[],
                extraction_warnings=[f"Section '{section.section_title}' skipped: no table data and insufficient text content ({len(section.raw_markdown)} chars)."]
            )


        result = await self.client.extract(
            schema=TableOfBenefitsExtraction,
            system_prompt=TABLE_OF_BENEFITS_SYSTEM_PROMPT,
            user_content=f"""Extract all coverage rules from this Table of Benefits.

STRUCTURED TABLE DATA (use these values precisely - do not invent numbers):
{table_context}

SURROUNDING TEXT CONTEXT:
{section.raw_markdown[:2000]}

SCHEMA NOTES:
- "Unlimited" annual limits: set is_unlimited=True and amount=0
""",
            task_label="table_of_benefits",
            use_large_model=True,
        )

        self._deduplicate_and_validate(result)

        return result
    
    def _build_hybrid_context(self, section: ParsedSection) -> str:
        parts = []
        for i, table in enumerate(section.tables):
            parts.append(f"--- Table {i+1} ---")
            parts.append(table["markdown"]) # Human readable
            parts.append("\nCell-level data:")
            for cell in table["cells"]:
                parent = cell.get("__parent_label__", None)
                prefix = f"[under: {parent}] " if parent else ""
                parts.append(f" {prefix}{json.dumps(cell)}") 
        
        return "\n".join(parts)

    def _deduplicate_and_validate(self, result: TableOfBenefitsExtraction):
        """Catch duplicate benefit_codes before they cause silent errors downstream."""
        seen = set()
        unique_rules = []
        
        for rule in result.coverage_rules:
            key = (rule.benefit_code, rule.network_restriction)
            if key in seen:
                result.extraction_warnings.append(
                    f"Duplicate benefit_code+network_restriction: {key}. Keeping first occurrence."
                )
            else:
                seen.add(key)
                unique_rules.append(rule)
        result.coverage_rules = unique_rules
