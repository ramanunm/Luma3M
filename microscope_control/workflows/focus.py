from __future__ import annotations

import time

from microscope_control.workflows.autofocus import AutofocusConfig, AutofocusResult, run_laplacian_autofocus


def run_autofocus(system, config: AutofocusConfig, *, light: str, light_settle_seconds: float = 1.0) -> AutofocusResult:
    """Run autofocus under the selected illumination and guarantee light shutdown."""

    if system.light is None or system.stage is None:
        raise RuntimeError("Autofocus requires both stage and light controller.")
    if light == "led":
        system.light.select_led()
    elif light == "laser":
        system.light.select_laser()
    else:
        raise ValueError("light must be 'led' or 'laser'.")
    try:
        time.sleep(light_settle_seconds)
        return run_laplacian_autofocus(system, config)
    finally:
        system.light.off()


__all__ = ["AutofocusConfig", "AutofocusResult", "run_autofocus"]

