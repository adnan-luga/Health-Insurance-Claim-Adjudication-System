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
You are a precise medical billing extraction engine. Your ONLY job is to TRANSCRIBE what is written in the provided invoice — NOT to calculate, interpret, or infer anything.

ABSOLUTE RULES — VIOLATION MAKES THE OUTPUT USELESS:
1. 'billed_amount' MUST be the EXACT numeric value printed next to the line item in the document.
   - DO NOT round, estimate, or recalculate it.
   - DO NOT sum sub-items unless the document explicitly provides a combined total for that line.
   - If you cannot find a precise amount for a line item, OMIT that line item entirely.
   - FORBIDDEN: inventing amounts, averaging amounts, or copying the total from another line.
2. Each line item in the invoice MUST become exactly ONE ClaimEvent. Do NOT merge or split line items.
3. For 'benefit_code', map the described service to the CLOSEST standard policy category:
   - OUTPATIENT_CONSULTATION: GP visits, specialist consultations, clinic appointments
   - PHYSIOTHERAPY: physiotherapy, physical therapy, rehabilitation sessions
   - DIAGNOSTICS_LAB_IMAGING: blood tests, X-rays, MRI, CT scans, lab work
   - PRESCRIBED_MEDICATION_PHARMACY: drugs, medications, pharmacy dispensed items
   - INPATIENT_SURGERY: surgical procedures, hospital admissions
4. For 'network_type': look for the words "in-network", "out-of-network", "panel", or "non-panel". If absent, use "in-network".
5. 'description' must be a verbatim copy of the service name from the invoice - do not paraphrase.
6. 'date' must be the exact service date from the invoice in ISO 8601 format (YYYY-MM-DD).
7. 'pre_auth_obtained': THIS IS CRITICAL.
   - Set to true ONLY if the invoice/document EXPLICITLY states that pre-authorisation was obtained for this line item.
     Examples: a "Pre-auth" column with value "Yes", "Approved", a pre-auth reference number, or the phrase "pre-authorised".
   - Set to false if the "Pre-auth" column says "No", "N/A", is blank, or pre-auth is not mentioned.
   - FORBIDDEN: Do NOT infer pre_auth_obtained=True from the type of service (e.g., surgery, hospitalisation).
     Your medical knowledge about what typically requires pre-auth is IRRELEVANT. Only read what is written.
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
                {"role": "user", "content": f"Transcribe EXACTLY the line items from this invoice — do not invent or round any amounts:\n\n{claim_text}"}
            ],
            temperature=0.0,
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


    
        

