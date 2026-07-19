"""
Quality taxonomy — MAI Sec 2.4.3
Transforms processed source corpora into structured collection of buckets
quality tiers language groups topical categories educational value educational level source type domain-specific subcorpora
Enables controlled ablations across source families quality tiers topics etc.

Implements:
- metadata signals: domain names filenames repo metadata PDF creator
- source-specific heuristics: web text-quality OCR-artifact math-aware filters STEM content path/content-based filters generated code
- learned classifiers: fastText-style language topic educational value educational level quality semantic attributes (stub)
- prompted LLMs: via Ollama qwen3:32b keep/remove only (stub)
- manual exploration labeling: failure modes validated filtering precision audit high-impact source categories training data classifiers LLM judges

Also Bloom taxonomy for mid-training: Essential AI heuristic + Anderson Krathwohl
Solo personal project, no connection to employer
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple
import re

class QualityTier(Enum):
    T1_HIGH = "t1_high"
    T2_MID = "t2_mid"
    T3_LOW = "t3_low"

class EduValue(Enum):
    LOW = 0
    MID = 1
    HIGH = 2

class EduLevel(Enum):
    ELEMENTARY = 1
    HIGH_SCHOOL = 2
    COLLEGE = 3
    GRADUATE = 4

class Topic(Enum):
    CODE = "coding"
    STEM = "stem"
    MATH = "math"
    GENERAL = "general"
    MULTILINGUAL = "multilingual"
    WEB = "web"
    SAFETY = "safety"
    ENCYCLOPEDIA = "encyclopedia"
    TOOL_USE = "tool_use"

@dataclass
class QualityLabels:
    tier: QualityTier
    topic: Topic
    edu_value: EduValue
    edu_level: EduLevel
    language: str
    bloom_level: int  # 1-6
    source_type: str
    domain: str = ""
    keep: bool = True
    reason: str = ""

# --- heuristics ---
STEM_KEYWORDS = {"theorem","proof","equation","molecule","algorithm","experiment","derivative","integral"}
CODE_EXTS = {".py",".js",".ts",".java",".cpp",".rs",".go"}
HIGH_QUALITY_DOMAINS = {"arxiv.org","wikipedia.org","github.com","mathoverflow.net","openai.com"}

def _topic_from_source(source: str, text: str) -> Topic:
    s = source.lower()
    t = text.lower()
    if "code" in s or any(ext in s for ext in CODE_EXTS) or "github" in s:
        return Topic.CODE
    if "math" in s or "proof" in s:
        return Topic.MATH
    if "tool" in s or "react" in s:
        return Topic.TOOL_USE
    if "encyclopedia" in s or "wikipedia" in s:
        return Topic.ENCYCLOPEDIA
    if any(k in t for k in STEM_KEYWORDS):
        return Topic.STEM
    if "safety" in s:
        return Topic.SAFETY
    return Topic.GENERAL

def _edu_value_heuristic(text: str) -> EduValue:
    # simple length + reasoning cues
    if len(text) < 200:
        return EduValue.LOW
    reasoning_cues = ["because","therefore","however","implies","derive","compare","analyze"]
    score = sum(text.lower().count(w) for w in reasoning_cues)
    if score >= 4 and len(text) > 1000:
        return EduValue.HIGH
    if score >= 1:
        return EduValue.MID
    return EduValue.LOW

def _edu_level_heuristic(text: str) -> EduLevel:
    # crude: Flesch-like via avg word length + keywords
    if any(w in text.lower() for w in ["quantum","relativity","cohomology","stochastic"]):
        return EduLevel.GRADUATE
    if any(w in text.lower() for w in ["derivative","molecule","algorithm"]):
        return EduLevel.COLLEGE
    if len(text.split()) > 500:
        return EduLevel.HIGH_SCHOOL
    return EduLevel.ELEMENTARY

def _bloom_score(text: str) -> int:
    cues_high = ["analyze","compare","evaluate","derive","prove","theorem","consequence","because","therefore","implies","hypothesis"]
    low = 0
    high = sum(text.lower().count(w) for w in cues_high)
    if high >= 3:
        return 5
    if high >= 1 and len(text) > 500:
        return 4
    if high == 1:
        return 3
    return 2

def _quality_tier(text: str, edu_value: EduValue, edu_level: EduLevel, domain: str) -> QualityTier:
    if domain in HIGH_QUALITY_DOMAINS or edu_value==EduValue.HIGH and edu_level in (EduLevel.COLLEGE, EduLevel.GRADUATE):
        return QualityTier.T1_HIGH
    if edu_value==EduValue.LOW or len(text)<300:
        return QualityTier.T3_LOW
    return QualityTier.T2_MID

def classify(text: str, source: str = "general", meta: Dict | None = None) -> QualityLabels:
    meta = meta or {}
    domain = meta.get("domain") or ""
    topic = _topic_from_source(source, text)
    edu_value = _edu_value_heuristic(text)
    edu_level = _edu_level_heuristic(text)
    bloom = _bloom_score(text)
    tier = _quality_tier(text, edu_value, edu_level, domain)
    # keep rules: T3 low with low edu value filtered, bloom <3 filtered for high-quality buckets
    keep = True
    reason = ""
    if tier == QualityTier.T3_LOW and edu_value == EduValue.LOW:
        keep = False
        reason = "t3_low_edu_low"
    if topic in (Topic.STEM, Topic.MATH) and bloom < 4:
        # for mid-training STEM filter we want >=Analyze, but for general keep
        pass
    lang = meta.get("language") or "en"
    return QualityLabels(tier=tier, topic=topic, edu_value=edu_value, edu_level=edu_level, language=lang, bloom_level=bloom, source_type=source, domain=domain, keep=keep, reason=reason)

# Bloom Analyze filter for mid-training
def bloom_analyze_keep(text: str, min_level: int = 4) -> bool:
    return _bloom_score(text) >= min_level

# File-level + repo-level formatting complementary flag
def code_format_type(source: str) -> str:
    if "repo" in source.lower():
        return "repo-level"
    return "file-level"

# Memorization-aware epoch capping proxy
def mem_aware_fraction(nll_before: float, nll_after: float, nll_near_zero_frac: float) -> float:
    """
    Proxy fraction validation loss improvement that comes tokens predicted near-certainty NLL<0.01
    Higher fraction indicates significant NLL reduction due memorization highly repeated structure
    => assign stricter epoch caps.
    Returns cap 1..8
    """
    if nll_near_zero_frac > 0.5:
        return 1.0  # strict
    if nll_near_zero_frac > 0.3:
        return 2.0
    if nll_near_zero_frac > 0.15:
        return 4.0
    return 8.0

# Convenience for data flywheel
def bucket_key(labels: QualityLabels) -> str:
    return f"{labels.topic.value}/{labels.tier.value}/{labels.edu_level.name}/{labels.language}"
