# ingestion/api/routes.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
import httpx
import structlog

# Importujemo klase koje smo ranije napravili
from ingestion.pipeline import PolicyIngestionPipeline
from ..storage.policy_store import PolicyStore

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/policies", tags=["Policy Ingestion"])

class IngestResponse(BaseModel):
    policy_id: str
    version_hash: str
    rule_count: int
    exclusion_count: int
    endorsement_count: int
    compilation_warnings: list[str]
    status: str  # "compiled" | "cached" | "failed"



async def get_pipeline() -> PolicyIngestionPipeline:
    raise NotImplementedError("Dependency injection not wired up yet")

async def get_store() -> PolicyStore:
    raise NotImplementedError("Dependency injection not wired up yet")


@router.post("/ingest", response_model=IngestResponse)
async def ingest_policy(
    policy_id: str = Form(..., description="Unique ID for this policy"),
    document_url: str | None = Form(None, description="URL to download PDF"),
    file: UploadFile | None = File(None, description="Direct PDF upload"),
    pipeline: PolicyIngestionPipeline = Depends(get_pipeline)
):
    """
    Ingest a policy document and compile it to a PolicyRuleSet.
    
    - Upload PDF directly via multipart/form-data (file=), OR
    - Provide a document_url as a form field.
    """
    
    if file:
        source = await file.read()
    elif document_url:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(document_url)
                resp.raise_for_status()
                source = resp.content
            except httpx.HTTPError as e:
                log.error("api.download_failed", url=document_url, error=str(e))
                raise HTTPException(status_code=400, detail=f"Failed to download PDF: {e}")
    else:
        raise HTTPException(status_code=400, detail="Provide either a file upload or document_url")
    
    try:
        # Proslijeđujemo metadata (policy_id) u pipeline kako smo maloprije dogovorili
        ruleset = await pipeline.run(
            policy_id=policy_id,
            source=source,
            metadata={"policy_id": policy_id} 
        )
    except Exception as e:
        log.error("api.ingestion_failed", policy_id=policy_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Ingestion pipeline failed: {str(e)}")
    
    return IngestResponse(
        policy_id=ruleset.policy_id,
        version_hash=ruleset.version_hash,
        rule_count=len(ruleset.coverage_rules),
        exclusion_count=len(ruleset.exclusions),
        endorsement_count=len(ruleset.endorsements),
        compilation_warnings=ruleset.compilation_warnings,
        status="compiled" # Ili dodaj logiku za detekciju "cached"
    )

@router.get("/{policy_id}/rules")
async def get_compiled_rules(
    policy_id: str,
    store: PolicyStore = Depends(get_store)
):
    """Inspect the compiled ruleset — for human review and debugging."""
    ruleset = await store.get_latest(policy_id)
    if not ruleset:
        raise HTTPException(status_code=404, detail=f"No compiled ruleset found for policy_id={policy_id}")
    
    # Vraćamo puni JSON reprezentaciju Pydantic modela
    return ruleset.model_dump(mode="json")
