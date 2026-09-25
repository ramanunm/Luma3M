from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


CameraAutoSetting: TypeAlias = int | Literal["auto"]


@dataclass(slots=True)
class CameraConfig:
    """相机启动参数。

    这个类只负责“保存参数”，不负责真正控制相机。
    以后你想改默认曝光、增益、ROI，优先改这里或在脚本里创建新的 CameraConfig。
    """

    # 第几台 ZWO 相机。只有一台相机时通常是 0。
    camera_index: int = 0

    # 曝光时间，单位是微秒：
    # 1_000 = 1 ms，10_000 = 10 ms，1_000_000 = 1 s。
    exposure_us: CameraAutoSetting = 10_000

    # 增益。None 表示使用 pyzwoasi 初始化后的默认/最小值。
    gain: CameraAutoSetting | None = None

    # 彩色白平衡。主要影响 rgb24 彩色图像；raw16 通常仍建议保留原始数据。
    white_balance_r: int | None = None
    white_balance_b: int | None = None

    # 图像格式。显微定量分析通常优先 raw16。
    # 可选值：raw8, raw16, rgb24, y8。
    image_type: str = "raw16"

    # ROI 是只读取传感器的一块区域，用于提速。
    # None 表示使用当前默认全幅大小。
    roi_width: int | None = None
    roi_height: int | None = None

    # 软件 binning。None 表示不主动修改。
    software_binning: int | None = None

    # 是否打开高速模式。None 表示不主动修改。
    high_speed_mode: bool | None = None

    # USB 带宽参数。不同型号范围不同，None 表示不主动修改。
    bandwidth: int | None = None

    # 制冷相机才有这些参数。普通相机保持 None 即可。
    cooler: bool | None = None
    target_temperature_c: int | None = None

