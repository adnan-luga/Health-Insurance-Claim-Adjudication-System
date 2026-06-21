from .storage.policy_store import PolicyStore
from .compilation.compiler import PolicyCompiler
from .extraction.schemas import OutOfPocketMax
from decimal import Decimal
from .extraction.schemas import Deductible
from .extraction.schemas import ConditionsExtraction
from .extraction.schemas import EndorsementsExtraction
from .extraction.schemas import ExclusionsExtraction
from .extraction.schemas import TableOfBenefitsExtraction
from typing import Dict
from .extraction.extractors.conditions import ConditionExtractor
from .extraction.extractors.endorsements import EndorsementsExtractor
from .extraction.extractors.exclusions import ExclusionExtractor
from .extraction.extractors.table_of_benefits import TableOfBenefitsExtractor
from .parsing.section_splitter import SectionSplitter, SectionType
from .parsing.document_parser import DocumentParser
from .extraction.client import ExtractionClient
import structlog
from typing import Any
import asyncio

log = structlog.get_logger()

class PolicyIngestionPipeline:
    """
        End to end pipeline: PDF -> compiled POlicyRuleSet stored in DB
    """

    def __init__(
        self,
        extraction_client: ExtractionClient,
        policy_store: PolicyStore,
        snapshot: Any,
    ):
        self.parser = DocumentParser()
        self.splitter = SectionSplitter()
        self.store = policy_store
        self.snapshot = snapshot
        self.compiler = PolicyCompiler()
        
        #Extractors
        self.benefits_extractor = TableOfBenefitsExtractor(extraction_client)
        self.exclusion_extractor = ExclusionExtractor(extraction_client)
        self.endorsements_extractor = EndorsementsExtractor(extraction_client)
        self.conditions_extractor = ConditionExtractor(extraction_client)
    
    async def run(self, policy_id: str, source: str | bytes, metadata: Dict[str, Any] = None) -> Any:
        log.info("pipeline.start", policy_id=policy_id)
        metadata = metadata or {}

        # Stage 1: parse & idempotency check
        parsed_doc = await asyncio.to_thread(self.parser.parse, source)

        # if we have DB, check hash
        if self.store:
            existing = await self.store.get_by_document_hash(parsed_doc.document_hash)
            if existing:
                log.info("pipeline.cache_hit", policy_id=policy_id)
                return existing
        
        log.info("pipeline.parsing", policy_id=policy_id, pages=parsed_doc.total_pages)

        # Stage 2: section split
        classified_sections, routing_warnings = self.splitter.classify(parsed_doc.sections)
        section_groups = self.splitter.group_by_type(classified_sections)

        log.info("pipeline.section_classified", policy_id=policy_id, section_types={k.value: len(v) for k, v in section_groups.items()})

        # Stage 3: parallel extraction
        log.info("pipeline.extraction_start", policy_id=policy_id)

        benefits_sections = section_groups.get(SectionType.TABLE_OF_BENEFITS, [])
        exclusions_sections = section_groups.get(SectionType.EXCLUSIONS, [])
        endorsement_sections = section_groups.get(SectionType.ENDORSEMENTS, [])
        conditions_sections = section_groups.get(SectionType.GENERAL_CONDITIONS, [])

        (
            benefits_result,
            exclusions_result,
            endorsements_result,
            conditions_result,
        ) = await asyncio.gather(
            self._extract_benefits(benefits_sections),
            self._extract_exclusions(exclusions_sections),
            self._extract_endorsements(endorsement_sections),
            self._extract_conditions(conditions_sections),
            return_exceptions=True,
        )
    
        # Handle exceptions if any extraction task failed
        if isinstance(benefits_result, Exception):
            benefits_result = TableOfBenefitsExtraction(coverage_rules=[], extraction_warnings=[f"Benefits extraction failed: {str(benefits_result)}"])
        if isinstance(exclusions_result, Exception):
            exclusions_result = ExclusionsExtraction(exclusions=[], extraction_warnings=[f"Exclusions extraction failed: {str(exclusions_result)}"])
        if isinstance(endorsements_result, Exception):
            endorsements_result = EndorsementsExtraction(endorsements=[], extraction_warnings=[f"Endorsements extraction failed: {str(endorsements_result)}"])
        if isinstance(conditions_result, Exception):
            conditions_result = ConditionsExtraction(
                deductible=Deductible(annual_amount=Decimal("0"), applies_to=[]),
                out_of_pocket_max=OutOfPocketMax(annual_amount=Decimal("0"), includes=[]),
                extraction_warnings=[f"Conditions extraction failed: {str(conditions_result)}"]
            )

        # Stage 4: compile
        log.info("pipeline.compiling", policy_id=policy_id)

        if routing_warnings:
            benefits_result.extraction_warnings.extend(routing_warnings)
        
        ruleset = self.compiler.compile(
            policy_id=policy_id,
            document_hash=parsed_doc.document_hash,
            metadata=metadata,
            benefits=benefits_result,
            exclusions=exclusions_result,
            endorsements=endorsements_result,
            conditions=conditions_result,
        )

        # Stage 5: persist
        if self.store:
            await self.store.save(ruleset)
        if self.snapshot:
            await self.snapshot.save_yaml(ruleset)
        
        log.info(
            "pipeline.complete",
            policy_id=policy_id,
            version_hash=ruleset.version_hash,
            rules=len(ruleset.coverage_rules),
            exclusions=len(ruleset.exclusions),
            endorsements=len(ruleset.endorsements),
            warnings=len(ruleset.compilation_warnings),
        )

        return ruleset

    # merging helpers

    async def _extract_benefits(self, sections):
        if not sections:
            return TableOfBenefitsExtraction(coverage_rules=[], extraction_warnings=["No Table of benefits section found"])

        results = await asyncio.gather(*[
            self.benefits_extractor.extract(s.parsed_section) for s in sections
        ])
        return TableOfBenefitsExtraction(
            coverage_rules=[rule for r in results for rule in r.coverage_rules],
            extraction_warnings=[w for r in results for w in r.extraction_warnings],
        )
    
    async def _extract_exclusions(self, sections):
        if not sections:
            return ExclusionsExtraction(exclusions=[], extraction_warnings=["No Exclusions section found"])
            
        results = await asyncio.gather(*[
            self.exclusion_extractor.extract(s.parsed_section) for s in sections
        ])
        return ExclusionsExtraction(
            exclusions=[exc for r in results for exc in r.exclusions],
            extraction_warnings=[w for r in results for w in r.extraction_warnings]
        )
    
    async def _extract_endorsements(self, sections):
        if not sections:
            return EndorsementsExtraction(endorsements=[], extraction_warnings=[])
            
        results = await asyncio.gather(*[
            self.endorsements_extractor.extract(s.parsed_section) for s in sections
        ])
        return EndorsementsExtraction(
            endorsements=[end for r in results for end in r.endorsements],
            extraction_warnings=[w for r in results for w in r.extraction_warnings]
        )
    
    async def _extract_conditions(self, sections):
        
        if not sections:
            return ConditionsExtraction(
                deductible=Deductible(annual_amount=Decimal("0"), applies_to=[]),
                out_of_pocket_max=OutOfPocketMax(annual_amount=Decimal("0"), includes=[]),
                extraction_warnings=["No General Conditions found. Defaulting limits to 0."]
            )
            
        results = await asyncio.gather(*[
            self.conditions_extractor.extract(s.parsed_section) for s in sections
        ])
        
        return ConditionsExtraction(
            deductible=results[0].deductible,
            out_of_pocket_max=results[0].out_of_pocket_max,
            additional_conditions=[c for r in results for c in r.additional_conditions] if hasattr(results[0], 'additional_conditions') else [],
            extraction_warnings=[w for r in results for w in r.extraction_warnings]
        )



        