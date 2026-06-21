import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from ingestion.storage.models import Base

DATABASE_URL = "postgresql+asyncpg://admin:admin@localhost:5432/policies"
engine = create_async_engine(DATABASE_URL, echo=True)

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        print("Dropped all tables.")

if __name__ == "__main__":
    asyncio.run(main())
