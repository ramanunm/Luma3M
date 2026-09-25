"""Multi-device microscope workflows."""

from microscope_control.workflows.alternate import AlternateConfig, run_alternate
from microscope_control.workflows.focus import AutofocusConfig, run_autofocus
from microscope_control.workflows.image import capture_light_image

__all__ = ["AlternateConfig", "AutofocusConfig", "capture_light_image", "run_alternate", "run_autofocus"]

