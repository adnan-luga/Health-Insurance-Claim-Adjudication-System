from datetime import date, datetime, timezone
from typing import Dict, Any
from ..extraction.schemas import (
    PolicyRuleSet, TableOfBenefitsExtraction,
    ExclusionsExtraction, EndorsementsExtraction, ConditionsExtraction
)
from .override_resolver import OverrideResolver

class PolicyCompiler:
    def __init__(self, resolver: OverrideResolver = None):
        # Dependency Injection 
        self.resolver = resolver or OverrideResolver()
    
    def compile(
        self,
        policy_id: str,
        document_hash: str,
        metadata: Dict[str, Any],
        benefits: TableOfBenefitsExtraction,
        exclusions: ExclusionsExtraction,
        endorsements: EndorsementsExtraction,
        conditions: ConditionsExtraction,
    ) -> PolicyRuleSet:
        
        # 1. Resolution of conflicts (Endorsements vs Base Rules)
        resolved_rules, conflicts = self.resolver.resolve(
            base_rules=benefits.coverage_rules,
            endorsments=endorsements.endorsements,
        )
        
        # 2. Collecting all warnings in one place
        all_warnings = (
            benefits.extraction_warnings
            + exclusions.extraction_warnings
            + endorsements.extraction_warnings
            + conditions.extraction_warnings
            + [c.conflict_description for c in conflicts]
        )
        
        # 3. Parsing dates from metadata with fallback
        today = datetime.now(timezone.utc).date()
        effective_date = metadata.get("effective_date", today)
        expiry_date = metadata.get("expiry_date", today)
        
        # 4. Final construction of immutable PolicyRuleSet
        return PolicyRuleSet(
            policy_id=policy_id,
            policy_name=metadata.get("policy_name", "Unknown Policy"),
            insurer_name=metadata.get("insurer_name", "Unknown Insurer"),
            effective_date=effective_date,
            expiry_date=expiry_date,
            deductible=conditions.deductible,
            out_of_pocket_max=conditions.out_of_pocket_max,
            coverage_rules=resolved_rules,
            exclusions=exclusions.exclusions,
            endorsements=endorsements.endorsements,
            compiled_at=datetime.now(timezone.utc).isoformat(),
            source_document_hash=document_hash,
            compilation_warnings=all_warnings,
        )