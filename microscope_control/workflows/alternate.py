from __future__ import annotations

from microscope_control.workflows.light_timelapse import (
    LightTimelapseConfig,
    LightTimelapseResult,
    run_light_timelapse,
)


AlternateConfig = LightTimelapseConfig
AlternateResult = LightTimelapseResult


def run_alternate(system, config: AlternateConfig) -> AlternateResult:
    return run_light_timelapse(system, config)


__all__ = ["AlternateConfig", "AlternateResult", "run_alternate"]

