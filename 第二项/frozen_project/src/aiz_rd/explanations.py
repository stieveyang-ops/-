"""Deterministic, non-generative explanations for frozen difficulty scores."""
from __future__ import annotations


def reaction_explanation(row: dict) -> tuple[str, str]:
    code = "reaction_difficulty_v1"
    text = (
        f"Reaction difficulty is {float(row['reaction_difficulty']):.6f}/100 "
        f"from feasibility difficulty {float(row['d_feas']):.6f}, "
        f"precedent difficulty {float(row['d_prec']):.6f}, and normalized delta-SC "
        f"difficulty {float(row['d_sc']):.6f}; confidence is {str(row['confidence'])}."
    )
    return code, text


def route_explanation(route: dict) -> str:
    if not route.get("difficulty_applicable"):
        return "No reaction steps were present; route difficulty is not applicable."
    return (
        f"Route difficulty is governed by the hardest reaction step "
        f"({route.get('hardest_step_id')}); bottleneck={float(route['difficulty_bottleneck']):.6f}, "
        f"mean={float(route['difficulty_mean']):.6f}, confidence={route.get('route_confidence')}."
    )
