
from decimal import Decimal
from datetime import date
from pydantic import BaseModel
from typing import List, Optional

# Input data
class ClaimEvent(BaseModel):
    claim_id: str
    date: date
    benefit_code: str
    network_type: str
    billed_amount: Decimal
    pre_auth_obtained: bool = False
    description: str

class ClaimBatch(BaseModel):
    batch_id: str
    policy_id: str
    member_id: str
    policy_year_start: date
    policy_year_end: date
    claims: List[ClaimEvent]

# ouptut data

class AuditLine(BaseModel):
    step: str
    description: str
    value_applied: Optional[Decimal] = None
    running_eligible_amount: Decimal

class AdjudicationResult(BaseModel):
    claim_id: str
    decision: str
    denial_reason: Optional[str] = None
    billed_amount: Decimal
    eligible_amount: Decimal  
    deductible_applied: Decimal 
    insurer_pays: Decimal
    member_owes: Decimal
    audit_trail: List[AuditLine]

class ClaimBatchResult(BaseModel):
    batch_id: str
    policy_id: str
    member_id: str
    results: List[AdjudicationResult]
    total_insurer_paid: Decimal
    total_member_paid: Decimal

