

from ..extraction.schemas import Provenance
from dataclasses import dataclass
from ..extraction.schemas import Endorsement
from ..extraction.schemas import CoverageRule


@dataclass
class OverrideConflict:
    benefit_code: str
    conflict_description: str
    resolution: str

class OverrideResolver:
    """Applies endoresments to base coverage rules and produces a final list of CoverageRules with provenance.

    Priority resolution:
    Endorsment(>=100) > Rider (50-99) > Base Policy (0-49)

    Warning capture:
    - Detects overridden rules where provenance.overrides_original is missing.
    - Detects riders/endorsements that override '*' (all benefits) and raises awareness.
    """
    def resolve(
        self,
        base_rules: list[CoverageRule],
        endorsments: list[Endorsement],
    ) -> tuple[list[CoverageRule], list[OverrideConflict]]:
        
        # O(1) indexing — normalize keys to UPPERCASE to be LLM-casing agnostic
        conflicts: list[OverrideConflict] = []
        rule_index: dict[tuple, CoverageRule] = {}
        for r in base_rules:
            # Normalize the rule itself in-place
            r.benefit_code = r.benefit_code.upper().strip()
            r.network_restriction = r.network_restriction.lower().strip()
            key = (r.benefit_code, r.network_restriction)
            if key in rule_index:
                conflicts.append(OverrideConflict(
                    benefit_code=key[0],
                    conflict_description=f"Duplicate benefit_code+network_restriction: {key}. Keeping first occurrence.",
                    resolution="First occurrence wins.",
                ))
            else:
                rule_index[key] = r


        applied_endorsements: dict[tuple, Endorsement] = {}

        # Sort endorsements by priority
        for endorsment in sorted(endorsments, key=lambda e: e.priority):
            # Normalize keys — never trust LLM casing
            norm_benefit_code = endorsment.overrides_benefit_code.upper().strip()
            norm_network = endorsment.new_rule.network_restriction.lower().strip()
            key = (norm_benefit_code, norm_network)
            
            if key in applied_endorsements:
                prev_end = applied_endorsements[key]
                if prev_end.priority == endorsment.priority:
                    conflicts.append(
                        OverrideConflict(
                            benefit_code=key[0],
                            conflict_description=(
                                f"Conflicting endorsements at same priority level ({endorsment.priority})."
                                f"'{endorsment.endorsement_id}' conflicting with '{prev_end.endorsement_id}'."
                            ),
                            resolution=f"'{endorsment.endorsement_id}' takes precedence due to stable sort."
                        )
                    )
            
            if key not in rule_index:
                new_rule = endorsment.new_rule.model_copy(deep=True)
                new_rule.priority = endorsment.priority
                new_rule.provenance = Provenance(
                    source_document="endorsement",
                    source_section=endorsment.endorsement_id,
                    source_page=0,
                    verbatim_text=endorsment.amendment_text,
                    overridden_by=None,
                    overrides_original=None,
                )
                rule_index[key] = new_rule
                applied_endorsements[key] = endorsment
                continue
            
            original = rule_index[key]
            new_rule = endorsment.new_rule.model_copy(deep=True)
            new_rule.priority = endorsment.priority

            ## Old rule snapshot
            original_dump = original.model_dump()
            if original_dump.get("provenance"):
                original_dump["provenance"]["overridden_by"] = endorsment.endorsement_id
            else:
                original_dump["provenance"] = {"overridden_by" : endorsment.endorsement_id}
            
            new_rule.provenance = Provenance(
                source_document="endorsement",
                source_section=endorsment.endorsement_id,
                source_page=0,
                verbatim_text=endorsment.amendment_text,
                overridden_by=None,           # New rule is active
                overrides_original=original_dump,
            )
            
            rule_index[key] = new_rule
            applied_endorsements[key] = endorsment
        
        return list(rule_index.values()), conflicts

            