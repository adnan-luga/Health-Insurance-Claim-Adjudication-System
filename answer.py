import json
from decimal import Decimal
from datetime import date
from adjudication.schemas import ClaimBatch, ClaimEvent
from ingestion.extraction.schemas import PolicyRuleSet
from adjudication.engine import AdjudicationEngine

# Load the JSON ruleset
with open("formatted_ruleset.json", "r") as f:
    ruleset_json = json.load(f)
ruleset = PolicyRuleSet.model_validate(ruleset_json)

# Create the claim batch
claims = [
    ClaimEvent(claim_id="C1", date=date(2025, 2, 15), benefit_code="OUTPATIENT_CONSULTATION", network_type="in_network", billed_amount=Decimal("300"), pre_auth_obtained=False, description="Acute viral illness (influenza) — unrelated to asthma"),
    ClaimEvent(claim_id="C2", date=date(2025, 3, 10), benefit_code="OUTPATIENT_CONSULTATION", network_type="in_network", billed_amount=Decimal("400"), pre_auth_obtained=False, description="Asthma review (declared chronic condition)"),
    ClaimEvent(claim_id="C3", date=date(2025, 8, 5), benefit_code="OUTPATIENT_CONSULTATION", network_type="in_network", billed_amount=Decimal("400"), pre_auth_obtained=False, description="Asthma review (declared chronic condition)"),
    ClaimEvent(claim_id="C4", date=date(2025, 9, 12), benefit_code="PHYSIOTHERAPY", network_type="in_network", billed_amount=Decimal("3000"), pre_auth_obtained=False, description="Lower-back strain (acute)"),
    ClaimEvent(claim_id="C5", date=date(2025, 10, 3), benefit_code="INPATIENT_SURGERY", network_type="in_network", billed_amount=Decimal("18000"), pre_auth_obtained=False, description="Elective knee arthroscopy (non-emergency)"),
    ClaimEvent(claim_id="C6", date=date(2025, 11, 20), benefit_code="PRESCRIBED_MEDICATION", network_type="out_of_network", billed_amount=Decimal("500"), pre_auth_obtained=False, description="Pharmacy purchase at non-network pharmacy"),
]

batch = ClaimBatch(
    batch_id="BATCH-001",
    policy_id="test_001",
    member_id="Mr. A. Karim",
    policy_year_start=date(2025, 1, 1),
    policy_year_end=date(2025, 12, 31),
    claims=claims
)

engine = AdjudicationEngine()
result = engine.adjudicate_batch(ruleset, batch)

print("--- RESULTS ---")
for r in result.results:
    print(f"{r.claim_id}: {r.decision} | Billed: {r.billed_amount} | Eligible: {r.eligible_amount} | Insurer Pays: {r.insurer_pays} | Member Owes: {r.member_owes}")
    if r.denial_reason:
        print(f"  Denial Reason: {r.denial_reason}")

print(f"\nTOTAL INSURER PAYS: {result.total_insurer_paid}")
print(f"TOTAL MEMBER OWES: {result.total_member_paid}")
import pprint
for r in result.results:
    if r.claim_id == "C5":
        for a in r.audit_trail:
            print(a.step, a.description)
