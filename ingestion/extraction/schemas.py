from __future__ import annotations
from pydantic import BaseModel, Field, field_validator, model_validator
from decimal import Decimal
from typing import Optional, Literal
from datetime import date
import hashlib

# -- Primitives
class MonetaryLimit(BaseModel):
    amount: Decimal
    currency: str = "AED"
    period: Literal["per_claim", "per_year", "per_admission", "lifetime", "per_treatment", "per_day", "per_maternity_confinement"]
    is_unlimited: bool = False

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, v):
        if isinstance(v, str):
            cleaned = v.replace("AED", "").replace(",", "").strip()
            if cleaned.lower() in ("unlimited", "n/a", "-"):
                return Decimal("0")
        return Decimal(str(v))

class Provenance(BaseModel):
    """Audit trail of where the rule came from"""
    source_document: str
    source_section: str
    source_page: int
    verbatim_text: str
    overridden_by: Optional[str] = None # endorsment_id if overridden
    overrides_original: Optional[dict] = None # snapshot of what was there before being overridden

# -- Coverage Rules
class CoverageRule(BaseModel):
    benefit_code: str
    benefit_label: str
    coverage_type: Literal["percentage", "fixed_copay", "schedule", "denied"]

    #Percentage-based (most common)
    insurer_pays_pct: Optional[Decimal] = Field(
        default=None,
        description="The percentage the insurer pays (0.00 to 1.00). If policy says '20% coinsurance', the insurer pays 0.80"
    ) # 0.00 to 1.00

    # Copay based
    member_copay_fixed: Optional[Decimal] = None # e.g., AED 50

    # Limits
    annual_limit: Optional[MonetaryLimit] = None
    per_claim_limit: Optional[MonetaryLimit] = None
    lifetime_limit: Optional[MonetaryLimit] = None
    per_day_limit: Optional[MonetaryLimit] = None
    
    # Conditions
    network_restriction: Literal["in_network", "out_of_network", "any"] = "any"
    requires_preauth: bool = False
    waiting_period_days: int = 0

    # Override tracking
    priority: int = 0 # Higher number = wins in conflict
    provenance: Optional[Provenance] = None

    @model_validator(mode="after")
    def validate_coverage_math(self) -> CoverageRule:
        if self.coverage_type == "percentage":
            assert self.insurer_pays_pct is not None, \
                f"benefit_code {self.benefit_code}: percentage coverage requires insurer_pays+pct"
            assert Decimal("0") <= self.insurer_pays_pct <= Decimal("1"), \
                f"insurer_pays_pct must be between 0 and 1, got {self.insurer_pays_pct}"
        
        return self
    
# Exclusions
class Exclusion(BaseModel):
    exclusion_id: str
    description: str
    keywords: list[str] # for deterministic matching
    icd_codes: list[str] = []  # for exact matching
    applies_to_benefits: list[str] # benefit_codes, [*] for all
    hard_exclude: bool = True # True = deny; False = reduce benefit
    reduction_factor: Optional[Decimal] = None # If hard_exclude = False
    verbatim_text: str
    provenance: Optional[Provenance] = None

# Endorsement BaseModel
class Endorsement(BaseModel):
    endorsement_id: str
    title: str
    overrides_benefit_code: str
    amendment_text: str  # Verbatim "notwithstanding..." clause
    new_rule: CoverageRule # the replacement rule
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    priority: int = 100 # Always beats base policy

# Policy Conditions
class Deductible(BaseModel):
    annual_amount: Decimal
    currency: str = "AED"
    applies_to: list[str]  # benefit codes
    waived_for: list[str] = [] # benefit_codes where deductible is waived
    accumulation_basis: Literal["per_member", "per_family"] = "per_member"

class OutOfPocketMax(BaseModel):
    annual_amount: Decimal
    currency: str = "AED"
    includes: list[str] # What counts toward OOP max
    excludes: list[str] = [] # What does not count

# Final Output

class PolicyRuleSet(BaseModel):
    """The single source of truth produced by the ingestion pipeline.
    All adjudication runs against this object"""

    policy_id: str
    policy_name: str
    insurer_name: str
    effective_date: date
    expiry_date: date

    deductible: Deductible
    out_of_pocket_max: OutOfPocketMax
    coverage_rules: list[CoverageRule]
    exclusions: list[Exclusion]
    endorsements: list[Endorsement]

    # Compilation metadata
    compiled_at: str
    source_document_hash: str
    compilation_warnings: list[str] = []
    schema_version: str = "1.0.0"

    @property
    def version_hash(self) -> str:
        content = self.model_dump_json(exclude={"compiled_at"})
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def get_rule(self, benefit_code: str) -> Optional[CoverageRule]:
        """Lookup with O(1) after dict is built"""
        return {r.benefit_code: r for r in self.coverage_rules}.get(benefit_code)
    
    def get_applicable_exclusions(self, benefit_code: str) -> list[Exclusion]:
        return [
            e for e in self.exclusions
            if "*" in e.applies_to_benefits or benefit_code in e.applies_to_benefits
        ]

# Intermediate Extraction Results (per section) 
class TableOfBenefitsExtraction(BaseModel):
    coverage_rules: list[CoverageRule]
    extraction_warnings: list[str] = []
class ExclusionsExtraction(BaseModel):
    exclusions: list[Exclusion]
    extraction_warnings: list[str] = []
class EndorsementsExtraction(BaseModel):
    endorsements: list[Endorsement]
    extraction_warnings: list[str] = []
class ConditionsExtraction(BaseModel):
    deductible: Deductible
    out_of_pocket_max: OutOfPocketMax
    additional_conditions: list[str] = []
    extraction_warnings: list[str] = []

    



    



