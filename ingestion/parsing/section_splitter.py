from __future__ import annotations
from dataclasses import dataclass
import instructor
import yaml
from pydantic import BaseModel
from enum import Enum
from .document_parser import ParsedSection
from openai import OpenAI


class SectionType(str, Enum):
    DEFINITIONS = "definitions"
    TABLE_OF_BENEFITS = "table_of_benefits"
    EXCLUSIONS = "exclusions"
    GENERAL_CONDITIONS = "general_conditions"
    ENDORSEMENTS = "endorsements"
    UNKNOWN = "unknown"

class LLMClassification(BaseModel):
    section_type: SectionType

@dataclass
class ClassifiedSection:
    section_type: SectionType
    parsed_section: ParsedSection
    classification_confidence: float
    routed_via: str  # 'keyword', 'llm', or 'unresolved'
    requires_human_review: bool

class SectionSplitter:

    def __init__(
        self,
        config_path: str = "config/section_patterns.yml",
        vllm_base_url: str = "http://localhost:12434/v1",
        model_name: str = "hf.co/mlx-community/Qwen2.5-7B-Instruct-4bit",
        fallback_threshold: float = 0.4
    ):

        self.fallback_thrashold = fallback_threshold
        self.model_name = model_name

        self._patterns = self._load_patterns(config_path)

        self.client = instructor.from_openai(
            OpenAI(base_url=vllm_base_url, api_key="not-needed"),
            mode=instructor.Mode.JSON
        )

    def _load_patterns(self, path: str) -> dict[SectionType, list[str]]:
        with open(path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
        
        patterns = {}

        for key, words in raw_config.items():
            try:
                enum_key = SectionType(key)
                patterns[enum_key] = words
            except ValueError:
                print(f"Warning: No section in YAML: {key}")
        return patterns
    
    def classify(self, sections: list[ParsedSection]) -> tuple[list[ClassifiedSection], list[str]]:
        """Retunr the classified sections and the warning list"""
        classified = []
        warnings = []

        for section in sections:
            #. LAYER 1
            stype, conf = self._heuristic_match(section)
            routed_via = "keyword"
            requires_human = False

            # LAYER 2: llm
            if conf < self.fallback_thrashold or stype == SectionType.UNKNOWN:
                print(f"[*] Activating LLM...")
                try:
                    llm_type = self._llm_classify(section)

                    if llm_type != SectionType.UNKNOWN:
                        stype = llm_type
                        conf = 0.90
                        routed_via = "llm"
                    else:
                        # LAYER 3 Human review
                        stype = SectionType.UNKNOWN
                        conf = 0.0
                        routed_via = "unresolved"
                        requires_human = True
                        warn_msg = f"Manual review needed: Section '{section.section_title}' not recognized by LLM."
                        warnings.append(warn_msg)

                except Exception as e:
                    print(f"[-] LLM Call Error: {e}")
                    stype = SectionType.UNKNOWN
                    requires_human = True
                    routed_via = "error"
                    warnings.append(f"LLM Error for section '{section.section_title}': {str(e)}")
            
            classified.append(
                ClassifiedSection(
                    section_type=stype,
                    parsed_section=section,
                    classification_confidence=conf,
                    routed_via=routed_via,
                    requires_human_review=requires_human
                )
            )
        
        return classified, warnings
    
    def _heuristic_match(self, section: ParsedSection) -> tuple[SectionType, float]:
        """LAyer 1 logic"""
        title_lower = section.section_title.lower()
        content_lower = section.raw_markdown[:600].lower()

        best_type = SectionType.UNKNOWN
        best_score = 0.0

        for section_type, patterns in self._patterns.items():
            score = 0.0
            for pattern in patterns:
                if pattern in title_lower:
                    score += 1.0
                elif pattern in content_lower:
                    score += 0.4
            
            if section_type == SectionType.TABLE_OF_BENEFITS and section.tables:
                score += 0.5
            
            normalised = min(score, 1.0)

            if normalised > best_score:
                best_score = normalised
                best_type = section_type
        
        return best_type, best_score

    def _llm_classify(self, section: ParsedSection) -> SectionType:
        """Layer 2 logic. Small, cheap call through Instructor"""
        system_prompt = """
            You are an insurance legal document classification assistant.
            Your task is to read the first 800 characters of a section and classify it into EXACTLY ONE of the provided categories.
            If you are not completely sure, return 'unknown'.
        """        

        content_sample = f"Headline: {section.section_title}\n\nText: {section.raw_markdown[:800]}"

        result = self.client.chat.completions.create(
            model=self.model_name,
            response_model=LLMClassification,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content_sample}
            ],
            temperature=0.0
        )

        return result.section_type

    def group_by_type(self, classified: list[ClassifiedSection]) -> dict[SectionType, list[ClassifiedSection]]:
        groups: dict[SectionType, list[ClassifiedSection]] = {}
        for section in classified:
            if not section.requires_human_review:
                groups.setdefault(section.section_type, []).append(section)
        return groups
        