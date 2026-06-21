# main.py
import asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from ingestion.api.routes import router, get_pipeline, get_store

from ingestion.pipeline import PolicyIngestionPipeline
from ingestion.storage.policy_store import PolicyStore
from ingestion.compilation.snapshot import PolicySnapshot
from ingestion.extraction.client import ExtractionClient
from ingestion.storage.models import Base
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Test Policy Ingestion API")

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

llm_client = ExtractionClient(
    base_url=os.getenv("LLM_API_URL"),
    large_model=os.getenv("LLM_LARGE_MODEL"),
    small_model=os.getenv("LLM_SMALL_MODEL"),
    api_key=os.getenv("LLM_API_KEY"),
)
snapshot_tool = PolicySnapshot(output_dir="snapshots")


async def provide_real_store():
    """Ova funkcija daje pravu bazu."""
    async with AsyncSessionLocal() as session:
        yield PolicyStore(session)

async def provide_real_pipeline():
    """Ova funkcija sklapa pravi pipeline i daje ga ruteru."""
    async with AsyncSessionLocal() as session:
        store = PolicyStore(session)
        pipeline = PolicyIngestionPipeline(
            extraction_client=llm_client,
            policy_store=store,
            snapshot=snapshot_tool
        )
        yield pipeline

app.dependency_overrides[get_pipeline] = provide_real_pipeline
app.dependency_overrides[get_store] = provide_real_store

app.include_router(router)

@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ingestion.tests.main:app", host="127.0.0.1", port=8080, reload=True)
