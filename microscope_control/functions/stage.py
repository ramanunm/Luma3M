from __future__ import annotations


def move_stage(stage, mode: str, distance_mm: float) -> float:
    """Move the stage up (positive) or down (negative) by a positive distance."""

    if distance_mm <= 0:
        raise ValueError("distance_mm must be positive.")
    if mode not in {"up", "down"}:
        raise ValueError("mode must be 'up' or 'down'.")
    signed_distance = distance_mm if mode == "up" else -distance_mm
    return float(stage.move_relative_mm(signed_distance))


def home_stage(stage) -> float:
    stage.home()
    return float(stage.get_position_mm())

