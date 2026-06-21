from datetime import date
import os
import structlog
import asyncio
from adjudication.schemas import ClaimBatch
import instructor
from ingestion.parsing.document_parser import DocumentParser
from openai import AsyncOpenAI

log = structlog.get_logger()

CLAIM_EXTRACTION_PROMPT = """
You are a precise medical billing extraction engine. 
Read the provided medical invoice/claim document and extract the billing line items.
Map each line item to the provided Pydantic schema (ClaimBatch -> ClaimEvent).

RULES:
1. For 'benefit_code', you MUST map the described service to standard policy categories 
   (e.g., OUTPATIENT_CONSULTATION, PHYSIOTHERAPY, DIAGNOSTICS_LAB_IMAGING, PRESCRIBED_MEDICATION_PHARMACY).
2. Look for keywords like "in-network" or "out-of-network" to determine 'network_type'. If unknown, default to "any".
3. Extract the exact 'billed_amount' for each line item.
4. 'description' should be a short summary of the service provided.
"""

class ClaimParser:
    def __init__(self, llm_client: AsyncOpenAI, model_name: str = "gpt-4o-mini"):
        self.doc_parser = DocumentParser()
        self.client = instructor.from_openai(llm_client, mode=instructor.Mode.JSON)
        self.model_name = model_name
    
    async def parse_pdf_invoice(
        self,
        file_bytes: bytes,
        batch_id: str,
        policy_id: str,
        member_id: str,
        year_start: str,
        year_end: str
    ) -> ClaimBatch:
        log.info("claim_parser.reading_pdf", batch_id=batch_id)

        parsed_doc = await asyncio.to_thread(self.doc_parser.parse, file_bytes)
        claim_text = "\n".join([sec.raw_markdown for sec in parsed_doc.sections])

        log.info(
            "claim_parser.llm_call.start",
            model=self.model_name,
            system_prompt_chars=len(CLAIM_EXTRACTION_PROMPT),
            user_content_chars=len(claim_text),
        )

        # Debug: log full prompts when LOG_PROMPTS=true in .env
        if os.getenv("LOG_PROMPTS", "").lower() == "true":
            log.debug(
                "claim_parser.llm_call.prompt_in",
                system_prompt=CLAIM_EXTRACTION_PROMPT,
                user_content=f"Extract line items from this invoice:\n\n{claim_text}",
            )

        extracted_data, completion = await self.client.chat.completions.create_with_completion(
            model=self.model_name,
            response_model=ClaimBatch,
            messages=[
                {"role": "system", "content": CLAIM_EXTRACTION_PROMPT},
                {"role": "user", "content": f"Extract line items from this invoice:\n\n{claim_text}"}
            ]
        )

        log.info(
            "claim_parser.llm_call.complete",
            model=self.model_name,
            input_tokens=completion.usage.prompt_tokens,
            output_tokens=completion.usage.completion_tokens,
            total_tokens=completion.usage.total_tokens,
        )

        # Debug: log the raw structured response
        if os.getenv("LOG_PROMPTS", "").lower() == "true":
            log.debug(
                "claim_parser.llm_call.response_out",
                extracted_claims=[c.model_dump() for c in extracted_data.claims],
            )

        extracted_data.batch_id = batch_id
        extracted_data.policy_id = policy_id
        extracted_data.member_id = member_id
        
        extracted_data.policy_year_start = date.fromisoformat(year_start)
        extracted_data.policy_year_end = date.fromisoformat(year_end)

        log.info("claim_parser.success", items_found=len(extracted_data.claims))

        return extracted_data


    
        

