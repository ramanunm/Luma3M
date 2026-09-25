from __future__ import annotations

import time


def set_light(light, name: str, enabled: bool) -> str:
    if not enabled:
        return light.off()
    if name == "led":
        return light.select_led()
    if name == "laser":
        return light.select_laser()
    raise ValueError("name must be 'led' or 'laser'.")


def timed_light(light, name: str, on_seconds: float, off_seconds: float = 0.0) -> None:
    if on_seconds < 0 or off_seconds < 0:
        raise ValueError("Light timing values cannot be negative.")
    set_light(light, name, True)
    try:
        time.sleep(on_seconds)
    finally:
        light.off()
    if off_seconds:
        time.sleep(off_seconds)


def run_light_sequence(
    light,
    *,
    led_on_seconds: float,
    led_off_seconds: float,
    laser_on_seconds: float,
    laser_off_seconds: float,
) -> None:
    try:
        timed_light(light, "led", led_on_seconds, led_off_seconds)
        timed_light(light, "laser", laser_on_seconds, laser_off_seconds)
    finally:
        light.off()

