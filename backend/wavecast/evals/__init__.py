"""Credential-free Guided Discovery evaluation contracts and benchmark fixtures."""

from .fixtures import GUIDED_DISCOVERY_CASES, PHASE51_EDITORIAL_CASES
from .quality import (
    PHASE51_RUBRIC,
    GuidedDiscoveryCase,
    GuidedDiscoveryReview,
    HardCheckResult,
    HumanReviewDimension,
    Phase51Diagnostics,
    Phase51Evaluation,
    QualityDimension,
    QualityRubric,
    ReviewCandidate,
    build_phase51_evaluation,
    build_review_bundle,
)
from .retrieval import (
    RETRIEVAL_BENCHMARK_CASES,
    SYNTHETIC_RETRIEVAL_FIXTURES,
    RetrievalBenchmarkCase,
    RetrievalFixtureTrack,
)

__all__ = [
    "GUIDED_DISCOVERY_CASES",
    "PHASE51_EDITORIAL_CASES",
    "GuidedDiscoveryCase",
    "GuidedDiscoveryReview",
    "HardCheckResult",
    "HumanReviewDimension",
    "Phase51Diagnostics",
    "Phase51Evaluation",
    "PHASE51_RUBRIC",
    "QualityDimension",
    "QualityRubric",
    "RETRIEVAL_BENCHMARK_CASES",
    "SYNTHETIC_RETRIEVAL_FIXTURES",
    "RetrievalBenchmarkCase",
    "RetrievalFixtureTrack",
    "ReviewCandidate",
    "build_phase51_evaluation",
    "build_review_bundle",
]
