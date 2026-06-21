from datetime import datetime
from sqlalchemy import select
from ..extraction.schemas import PolicyRuleSet
from sqlalchemy.ext.asyncio.session import AsyncSession
from .models import PolicyRuleSetRecord
from typing import Optional


class PolicyStore:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
    
    async def get_by_document_hash(self, document_hash: str) -> Optional[PolicyRuleSet]:
        query = select(PolicyRuleSetRecord).where(PolicyRuleSetRecord.document_hash == document_hash
        )
        result = await self.db.execute(query)
        record = result.scalar_one_or_none()

        if record:
            return PolicyRuleSet.model_validate(record.ruleset_json)
        return None

    async def save(self, ruleset: PolicyRuleSet) -> None:
        existing = await self.db.execute(
            select(PolicyRuleSetRecord).where(PolicyRuleSetRecord.version_hash == ruleset.version_hash)
        )
        if existing.scalar_one_or_none():
            return
        
        record = PolicyRuleSetRecord(
            policy_id=ruleset.policy_id,
            version_hash=ruleset.version_hash,
            document_hash=ruleset.source_document_hash,
            compiled_at=datetime.fromisoformat(ruleset.compiled_at),
            ruleset_json=ruleset.model_dump(mode="json"),
            rule_count=len(ruleset.coverage_rules),
            exclusion_count=len(ruleset.exclusions),
            endorsement_count=len(ruleset.endorsements),
            warning_count=len(ruleset.compilation_warnings),
            compilation_warnings=ruleset.compilation_warnings,
            schema_version=ruleset.schema_version,
        )

        self.db.add(record)
        await self.db.commit()
        return record
    
    async def get_latest(self, policy_id: str) -> Optional[PolicyRuleSet]:
        query = (
            select(PolicyRuleSetRecord)
            .where(PolicyRuleSetRecord.policy_id == policy_id)
            .order_by(PolicyRuleSetRecord.compiled_at.desc())
            .limit(1)
        )
        result = await self.db.execute(query)
        record = result.scalar_one_or_none()
        
        if record:
            return PolicyRuleSet.model_validate(record.ruleset_json)
        return None

        

