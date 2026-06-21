
from decimal import Decimal
from typing import Dict, Optional
from ingestion.extraction.schemas import PolicyRuleSet
class PolicyTracker:
    """
        Tracks year-to-date payments by the insurer across all claims to enforce sub-limits and aggregate limits
    """
    def __init__(self, ruleset: PolicyRuleSet):
        self.ruleset = ruleset
        self.ytd_by_benefit: Dict[str, Decimal] = {}
        self.ytd_aggregate: Decimal = Decimal("0.00")

        self.aggregate_limit = self._extract_aggregate_limit()
    
    def _extract_aggregate_limit(self) -> Optional[Decimal]:
        for rule in self.ruleset.coverage_rules:
            if rule.benefit_code == "ANNUAL_LIMIT" and rule.annual_limit:
                if not rule.annual_limit.is_unlimited:
                    return rule.annual_limit.amount
        return None
    
    def get_remaining_sublimit(self, benefit_code: str, annual_limit_amount: Optional[Decimal]) -> Decimal:
        if annual_limit_amount is None:
            return Decimal("999999999.0")
        
        used_so_far = self.ytd_by_benefit.get(benefit_code, Decimal("0.00"))
        remaining = annual_limit_amount - used_so_far
        return max(Decimal("0.00"), remaining)
    
    def get_remaining_aggregate(self) -> Decimal:
        if self.aggregate_limit is None:
            return Decimal("999999999.0")
        
        remaining = self.aggregate_limit - self.ytd_aggregate
        return max(Decimal("0.00"), remaining)
    
    def record_payment(self, benefit_code: str, insurer_paid_amount: Decimal) -> None:
        if insurer_paid_amount <= 0:
            return
        
        current_benefit_used = self.ytd_by_benefit.get(benefit_code, Decimal("0.00"))
        self.ytd_by_benefit[benefit_code] = current_benefit_used + insurer_paid_amount

        self.ytd_aggregate += insurer_paid_amount