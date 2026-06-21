from fastapi import FastAPI
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from ingestion.storage.models import Base
from ingestion.storage.policy_store import PolicyStore
from adjudication.api.routes import router, get_store, get_engine, get_invoice_parser
from adjudication.claim_parser import ClaimParser
from adjudication.engine import AdjudicationEngine

load_dotenv()

app = FastAPI(title="Adjudication Engine API")

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

OPENAI_API_KEY = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY"))
LLM_BASE_URL = os.getenv("LLM_API_URL") or None
SMALL_MODEL = os.getenv("LLM_SMALL_MODEL", "gpt-4o-mini")

openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=LLM_BASE_URL
)

async def provide_store():
    async with AsyncSessionLocal() as session:
        yield PolicyStore(session)

def provide_engine():
    return AdjudicationEngine()

async def provide_invoice_parser():
    return ClaimParser(
        llm_client=openai_client,
        model_name=SMALL_MODEL
    )
app.dependency_overrides[get_store] = provide_store
app.dependency_overrides[get_engine] = provide_engine
app.dependency_overrides[get_invoice_parser] = provide_invoice_parser

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("adjudication.main:app", host="0.0.0.0", port=8081, reload=True)
