from decimal import Decimal
from typing import List, Optional

from ingestion.extraction.schemas import CoverageRule, PolicyRuleSet
from adjudication.schemas import AuditLine, ClaimEvent, AdjudicationResult, ClaimBatch, ClaimBatchResult
from adjudication.tracker import PolicyTracker


class AdjudicationEngine:
    """Core deterministic engine for processing claims"""

    def adjudicate_batch(self, ruleset: PolicyRuleSet, batch: ClaimBatch) -> ClaimBatchResult:
        tracker = PolicyTracker(ruleset)
        results: List[AdjudicationResult] = []

        sorted_claims = sorted(batch.claims, key=lambda c: c.date)

        for claim in sorted_claims:
            result = self._process_claim(claim, ruleset, tracker)
            results.append(result)

        return ClaimBatchResult(
            batch_id=batch.batch_id,
            policy_id=batch.policy_id,
            member_id=batch.member_id,
            results=results,
            total_insurer_paid=sum(r.insurer_pays for r in results),
            total_member_paid=sum(r.member_owes for r in results)
        )
    
    def _process_claim(self, claim: ClaimEvent, ruleset: PolicyRuleSet, tracker: PolicyTracker) -> AdjudicationResult:
        audit_trail: List[AuditLine] = []
        billed = claim.billed_amount
        eligible_amount = billed

        def _deny(reason: str) -> AdjudicationResult:
            return AdjudicationResult(
                claim_id=claim.claim_id,
                decision="DENIED",
                denial_reason=reason,
                billed_amount=billed,
                eligible_amount=eligible_amount,
                deductible_applied=Decimal("0.00"),
                insurer_pays=Decimal("0.00"),
                member_owes=billed,
                audit_trail=audit_trail
            )
    
        # Step 1: Exclusion Check
        for exclusion in ruleset.exclusions:
            keywords = exclusion.keywords or []
            if any(kw.lower() in claim.description.lower() for kw in keywords):
                applies = exclusion.applies_to_benefits or []
                if "*" in applies or claim.benefit_code in applies:
                    audit_trail.append(AuditLine(
                        step="exclusion_check",
                        description=f"Claim DENIED. Matched exclusion: {exclusion.description}",
                        value_applied=None,
                        running_eligible_amount=Decimal("0.00")
                    ))
                    eligible_amount = Decimal("0.00")
                    return _deny(f"Matched exclusion: {exclusion.description}")
        
        audit_trail.append(AuditLine(
            step="exclusion_check", 
            description="Checked exclusions. No matching keywords found.", 
            value_applied=None,
            running_eligible_amount=eligible_amount
        ))

        # Step 2: Benefit Lookup
        rule: Optional[CoverageRule] = None
        
        claim_code = claim.benefit_code.upper().strip()
        claim_net = claim.network_type.replace("-", "_").lower().strip()
        
        for r in ruleset.coverage_rules:
            rule_code = r.benefit_code.upper().strip()
            rule_net = r.network_restriction.replace("-", "_").lower().strip()
            
            if rule_code in claim_code or claim_code in rule_code:
                if rule_net in [claim_net, "any"]:
                    rule = r
                    break
                    
        if not rule:
            audit_trail.append(AuditLine(
                step="benefit_lookup", 
                description=f"No matching coverage rule found for benefit code {claim.benefit_code} at {claim.network_type}.", 
                value_applied=Decimal("0.0"),
                running_eligible_amount=Decimal("0.00")
            ))
            eligible_amount = Decimal("0.00")
            return _deny("Benefit not covered under this network tier.")

        audit_trail.append(AuditLine(
            step="benefit_lookup", 
            description=f"Applied rule: {rule.benefit_label}", 
            value_applied=billed,
            running_eligible_amount=eligible_amount
        ))        
        insurer_pct = Decimal(rule.insurer_pays_pct) if rule.insurer_pays_pct else Decimal("1.0")
        member_coinsurance_pct = (Decimal("1.0") - insurer_pct) * Decimal("100")

        audit_trail.append(AuditLine(
            step="benefit_lookup", 
            description=f"Found coverage rule for {rule.benefit_code} ({rule.network_restriction}). Base insurer pays: {insurer_pct*100}% (Member coinsurance: {member_coinsurance_pct}%).", 
            value_applied=insurer_pct,
            running_eligible_amount=eligible_amount
        ))

        # Step 3: Zero-Coverage Check
        if rule.coverage_type == "denied" or insurer_pct == Decimal("0.0"):
            audit_trail.append(AuditLine(
                step="zero_coverage_check", 
                description="Coverage type is explicitly denied or insurer pays 0% under this tier.", 
                value_applied=Decimal("0.0"),
                running_eligible_amount=Decimal("0.00")
            ))
            eligible_amount = Decimal("0.00")
            return _deny("Benefit is explicitly not covered")

        # Step 4: Annual Sub-limit Check
        limit_amt = None
        limit_desc = "Unlimited"
        if rule.annual_limit and not rule.annual_limit.is_unlimited:
            limit_amt = Decimal(rule.annual_limit.amount)
            limit_desc = f"AED {limit_amt}"
            
        remaining_sublimit = tracker.get_remaining_sublimit(claim.benefit_code, limit_amt)
        prior_ytd = tracker.ytd_by_benefit.get(claim.benefit_code, Decimal("0.00"))
        
        eligible_amount = min(eligible_amount, remaining_sublimit)
        
        audit_trail.append(AuditLine(
            step="annual_sublimit", 
            description=f"Checked Annual Sub-limit. Policy limit for {claim.benefit_code} is {limit_desc}. Prior YTD spend: AED {prior_ytd}. Remaining limit: AED {remaining_sublimit}. Billed: AED {billed}. Eligible amount capped at AED {eligible_amount}.", 
            value_applied=limit_amt,
            running_eligible_amount=eligible_amount
        ))
        
        if eligible_amount == Decimal("0.0"):
            return _deny(f"Annual sub-limit for {claim.benefit_code} exhausted")
        
        # Step 5: Aggregate Limit Check
        remaining_aggregate = tracker.get_remaining_aggregate()
        agg_limit = tracker.aggregate_limit
        agg_desc = f"AED {agg_limit}" if agg_limit else "Unlimited"

        eligible_amount = min(eligible_amount, remaining_aggregate)
        
        audit_trail.append(AuditLine(
            step="aggregate_limit", 
            description=f"Checked Annual Aggregate Limit. Policy aggregate limit is {agg_desc}. Prior YTD total spend: AED {tracker.ytd_aggregate}. Remaining aggregate: AED {remaining_aggregate}. Eligible amount remains AED {eligible_amount}.", 
            value_applied=agg_limit,
            running_eligible_amount=eligible_amount
        ))
        
        if eligible_amount == Decimal("0.0"):
            return _deny("Annual aggregate limit exhausted")
        
        # Step 6: Deductible Application
        deductible_applied = Decimal("0.0")
        if rule.member_copay_fixed:
            fixed_copay = Decimal(rule.member_copay_fixed)
            deductible_applied = min(eligible_amount, fixed_copay)
            after_deductible = eligible_amount - deductible_applied
            audit_trail.append(AuditLine(
                step="deductible_copay", 
                description=f"Checked Deductible. Policy specifies AED {fixed_copay} fixed copay/deductible applies to this benefit. Deductible applied: AED {deductible_applied}.", 
                value_applied=fixed_copay,
                running_eligible_amount=after_deductible
            ))
        else:
            after_deductible = eligible_amount
            audit_trail.append(AuditLine(
                step="deductible_copay", 
                description=f"Checked Deductible. No fixed copay/deductible specified for this benefit. Deductible applied: AED 0.", 
                value_applied=Decimal("0.0"),
                running_eligible_amount=after_deductible
            ))

        # Step 7: Coinsurance Calculation
        insurer_pays = after_deductible * insurer_pct
        member_coinsurance = after_deductible - insurer_pays
        
        audit_trail.append(AuditLine(
            step="coinsurance", 
            description=f"Calculated Coinsurance. Policy specifies member coinsurance is {member_coinsurance_pct}%. Insurer pays {insurer_pct*100}% of AED {after_deductible} = AED {insurer_pays}. Member owes coinsurance: AED {member_coinsurance}.", 
            value_applied=insurer_pct,
            running_eligible_amount=after_deductible
        ))

        # Step 8: Pre-authorisation Check
        penalty = Decimal("0.0")
        if rule.requires_preauth:
            if claim.pre_auth_obtained:
                audit_trail.append(AuditLine(
                    step="pre_auth_check",
                    description=f"Pre-authorisation check passed. Policy requires pre-auth for {claim.benefit_code} and claim confirms pre-auth was obtained. No penalty applied.",
                    value_applied=Decimal("0.0"),
                    running_eligible_amount=after_deductible
                ))
            else:
                # No pre-auth obtained. Apply a 20% reduction to the insurer's share regardless of coverage tier.
                penalty = insurer_pays * Decimal("0.20")
                insurer_pays -= penalty
                member_coinsurance += penalty  # member absorbs the penalty
                audit_trail.append(AuditLine(
                    step="pre_auth_check",
                    description=(
                        f"Pre-authorisation MISSING. Policy requires pre-auth for {claim.benefit_code} (see General Conditions). "
                        f"Claim does not have pre-auth. Applying 20% penalty to insurer share: "
                        f"penalty = AED {penalty}. Insurer pays reduced to AED {insurer_pays}. "
                        f"Member absorbs penalty: member owes coinsurance + penalty = AED {member_coinsurance}."
                    ),
                    value_applied=Decimal("0.20"),
                    running_eligible_amount=after_deductible
                ))
        else:
            audit_trail.append(AuditLine(
                step="pre_auth_check",
                description=f"Pre-authorisation not required for {claim.benefit_code}. No check needed.",
                value_applied=None,
                running_eligible_amount=after_deductible
            ))

        # Step 9: Total Calculation
        above_limit_portion = billed - eligible_amount
        member_owes = above_limit_portion + deductible_applied + member_coinsurance + penalty
        
        audit_trail.append(AuditLine(
            step="final_calculation", 
            description=f"Final Calculation. Member owes: AED {above_limit_portion} (over limit) + AED {deductible_applied} (deductible) + AED {member_coinsurance} (coinsurance) + AED {penalty} (penalty) = AED {member_owes}. Insurer pays: AED {insurer_pays}.", 
            value_applied=member_owes,
            running_eligible_amount=after_deductible
        ))

        # Step 10: Record to Ledger
        tracker.record_payment(claim.benefit_code, insurer_pays)

        decision = "APPROVED" if member_owes == 0 else "PARTIALLY_APPROVED"
        
        return AdjudicationResult(
            claim_id=claim.claim_id,
            decision=decision,
            denial_reason=None,
            billed_amount=billed,
            eligible_amount=eligible_amount,
            deductible_applied=deductible_applied,
            insurer_pays=insurer_pays,
            member_owes=member_owes,
            audit_trail=audit_trail
        )
