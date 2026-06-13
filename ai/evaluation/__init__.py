"""Shared evaluation tools for leakage-safe Lotto ML workflows."""

from .baselines import expected_random_hits, hypergeometric_match_distribution, random_number_probability
from .metrics import brier_score, calibration_error, lift, log_loss, mean_hit, match_count_distribution
from .probability import (
    apply_isotonic_calibrator,
    calibrate_scores,
    capped_simplex_projection,
    fit_isotonic_calibrator,
    project_probability_map,
    scores_to_probabilities,
)

__all__ = [
    "apply_isotonic_calibrator",
    "brier_score",
    "calibration_error",
    "capped_simplex_projection",
    "calibrate_scores",
    "expected_random_hits",
    "fit_isotonic_calibrator",
    "hypergeometric_match_distribution",
    "lift",
    "log_loss",
    "mean_hit",
    "match_count_distribution",
    "project_probability_map",
    "random_number_probability",
    "scores_to_probabilities",
]
