from adjudication.claim_parser import ClaimParser
from fastapi import Depends
from ingestion.storage.policy_store import PolicyStore
from adjudication.schemas import ClaimBatchResult
from fastapi import UploadFile, File, Form, APIRouter
from adjudication.engine import AdjudicationEngine

router = APIRouter(prefix="/api/v1/policies", tags=["Policy Ingestion"])


async def get_store() -> PolicyStore:
    raise NotImplementedError("Wired up in main.py")

def get_engine() -> AdjudicationEngine:
    return AdjudicationEngine()

# --- OVO DODAJEŠ ---
async def get_invoice_parser() -> ClaimParser:
    raise NotImplementedError("Wired up in main.py")

@router.post("/process-pdf", response_model=ClaimBatchResult)
async def process_pdf_invoice(
    policy_id: str = Form(...),
    member_id: str = Form(...),
    file: UploadFile = File(...),
    store: PolicyStore = Depends(get_store),
    engine: AdjudicationEngine = Depends(get_engine),
    invoice_parser: ClaimParser = Depends(get_invoice_parser) 
):
    file_bytes = await file.read()
    
    batch = await invoice_parser.parse_pdf_invoice(
        file_bytes=file_bytes,
        batch_id=f"BATCH-{file.filename}",
        policy_id=policy_id,
        member_id=member_id,
        year_start="2026-01-01",
        year_end="2026-12-31"
    )
    
    ruleset = await store.get_latest(batch.policy_id)
    
    return engine.adjudicate_batch(ruleset=ruleset, batch=batch)
