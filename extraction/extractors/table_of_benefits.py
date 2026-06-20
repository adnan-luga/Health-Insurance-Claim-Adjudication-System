from extraction.prompts import TABLE_OF_BENEFITS_SYSTEM_PROMPT
from extraction.schemas import TableOfBenefitsExtraction
from ingestion.parsing.document_parser import ParsedSection
from extraction.client import ExtractionClient
import json


class TableOfBenefitsExtractor:
    def __init__(self, client: ExtractionClient):
        self.client = client
    
    async def extract(self, section: ParsedSection) -> TableOfBenefitsExtraction:
        """
        Send both the markdown and the structured cell JSON.
        The markdown gives the LLM context, the cell JSON gives it precise values.
        """

        table_context = self._build_hybrid_context(section)

        result = await self.client.extract(
            schema=TableOfBenefitsExtraction,
            system_prompt=TABLE_OF_BENEFITS_SYSTEM_PROMPT,
            user_content=f"""Extract all coverage rules from this Table of Benefits.
            STRUCTURED TABLE DATA (use these values precisely - do not invent numbers):
            {table_context}
            
            SURROUNDING TEXT CONTEXT:
            {section.raw_markdown[:2000]}
            
            IMPORTANT RULES:
            - insurer_pays_pct must be expressed as decimal (0.8 for 80%, 0.50 for 50%, 1.0 for 100%)
            - If a benefit has both in-network and out-of-network rates, create TWO CoverageRule entries with network_restriction="in_network" and "out_of_network" respectively
            - Use the parent label to construct benefit_code: e.g. parent="Inpatient Surgery", child="Cardiac" -> benefit_code="IP_SURGERY_CARDIAC".
            - If a cell contains "(Endorsed)" or similar note, set priority=100 and note it in the provenance verbatim_text
            - "Unlimited" annual limits should have is_unlimited=True and amount=0
            """,
            task_label="table_of_benefits",
            use_large_model=True, # Complex table
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
