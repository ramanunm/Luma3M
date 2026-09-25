from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from microscope_control.config import CameraAutoSetting, CameraConfig
from microscope_control.devices.base import Device, DeviceNotConnectedError


class CameraDependencyError(RuntimeError):
    """缺少 pyzwoasi、tifffile、OpenCV 等依赖时抛出这个错误。"""


def _load_pyzwoasi():
    """延迟导入 pyzwoasi。

    这样做的好处是：没有安装 pyzwoasi 的电脑也可以打开、阅读、检查本项目代码。
    只有真正连接相机时，才会要求安装 pyzwoasi。
    """

    try:
        import pyzwoasi
        from pyzwoasi.pyzwoasi import ASIExposureStatus, ASIImageType
    except ImportError as exc:
        raise CameraDependencyError(
            "没有安装 pyzwoasi。请在工作电脑的虚拟环境中运行："
            "python -m pip install pyzwoasi numpy tifffile"
        ) from exc

    return pyzwoasi, ASIImageType, ASIExposureStatus


def _decode_c_string(value: bytes) -> str:
    """ZWO SDK 返回的是 C 风格字符串，这里转成普通 Python 字符串。"""

    return value.decode("utf-8", errors="replace").strip("\x00")


class ZwoCamera(Device):
    """ZWO ASI 相机控制器。

    这个类是“相机设备层”。
    你的主流程不直接调用 pyzwoasi，而是调用这个类。

    注意：
    这里故意不使用 pyzwoasi.ZWOCamera 这个高层类。
    原因是 ZWO SDK 区分“相机序号 camera_index”和“相机 ID camera_id”。
    某些电脑上 pyzwoasi.ZWOCamera 会把二者混用，导致：
    ASI_ERROR_INVALID_ID。

    所以本类直接调用 pyzwoasi 的底层函数：
    1. 用 camera_index 读取 CameraInfo
    2. 从 CameraInfo 里拿到真正的 CameraID
    3. 用 CameraID 打开、初始化和控制相机
    """

    def __init__(self, config: CameraConfig | None = None):
        self.config = config or CameraConfig()
        self._pyzwoasi: Any | None = None
        self._image_type_enum: Any | None = None
        self._exposure_status_enum: Any | None = None
        self._camera_info: Any | None = None
        self._camera_id: int | None = None
        self._connected = False
        self._controls_by_name: dict[str, Any] = {}

    @staticmethod
    def connected_count() -> int:
        """返回当前连接的 ZWO ASI 相机数量。"""

        pyzwoasi, _, _ = _load_pyzwoasi()
        return pyzwoasi.getNumOfConnectedCameras()

    @staticmethod
    def available_cameras() -> list[dict[str, Any]]:
        """读取所有已连接相机的基本信息。

        这个函数不需要打开相机，适合做第一步检测。
        """

        pyzwoasi, _, _ = _load_pyzwoasi()
        cameras: list[dict[str, Any]] = []

        for camera_index in range(pyzwoasi.getNumOfConnectedCameras()):
            info = pyzwoasi.getCameraProperty(camera_index)
            cameras.append(
                {
                    "index": camera_index,
                    "name": _decode_c_string(info.Name),
                    "camera_id": info.CameraID,
                    "max_width": info.MaxWidth,
                    "max_height": info.MaxHeight,
                    "is_color": bool(info.IsColorCam),
                    "pixel_size_um": info.PixelSize,
                    "bit_depth": info.BitDepth,
                    "is_usb3_camera": bool(info.IsUSB3Camera),
                    "is_cooler_camera": bool(info.IsCoolerCam),
                    "is_trigger_camera": bool(info.IsTriggerCam),
                }
            )

        return cameras

    def connect(self) -> "ZwoCamera":
        """打开并初始化相机，然后应用 CameraConfig 中的参数。"""

        if self._connected:
            return self

        pyzwoasi, image_type_enum, exposure_status_enum = _load_pyzwoasi()
        self._pyzwoasi = pyzwoasi
        self._image_type_enum = image_type_enum
        self._exposure_status_enum = exposure_status_enum

        camera_count = pyzwoasi.getNumOfConnectedCameras()
        if camera_count == 0:
            raise RuntimeError("没有检测到 ZWO ASI 相机。请检查 USB、驱动，并关闭 ASIStudio。")
        if self.config.camera_index < 0 or self.config.camera_index >= camera_count:
            raise RuntimeError(
                f"相机序号 {self.config.camera_index} 不存在。当前只检测到 {camera_count} 台相机。"
            )

        # 关键点：getCameraProperty 用 camera_index，openCamera 用 CameraID。
        self._camera_info = pyzwoasi.getCameraProperty(self.config.camera_index)
        self._camera_id = int(self._camera_info.CameraID)

        try:
            pyzwoasi.openCamera(self._camera_id)
            pyzwoasi.initCamera(self._camera_id)
            self._connected = True
            self._load_controls()
            self.apply_config(self.config)
        except Exception:
            # 如果初始化中途失败，尽量关闭相机，避免相机被占用。
            try:
                pyzwoasi.closeCamera(self._camera_id)
            finally:
                self._connected = False
                self._camera_id = None
            raise

        return self

    def disconnect(self) -> None:
        """关闭相机，释放相机资源。"""

        if self._connected and self._camera_id is not None:
            self._pyzwoasi.closeCamera(self._camera_id)
        self._connected = False
        self._camera_id = None
        self._controls_by_name = {}

    def __enter__(self) -> "ZwoCamera":
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.disconnect()

    @property
    def camera_id(self) -> int:
        """返回 ZWO SDK 真正用于控制相机的 CameraID。"""

        if not self._connected or self._camera_id is None:
            raise DeviceNotConnectedError("相机还没有连接。请先调用 connect()，或使用 with ZwoCamera(...)。")
        return self._camera_id

    @property
    def name(self) -> str:
        if self._camera_info is None:
            raise DeviceNotConnectedError("相机还没有连接。")
        return _decode_c_string(self._camera_info.Name)

    @property
    def roi(self):
        """返回当前 ROI: (宽, 高, binning, 图像格式)。"""

        return self._pyzwoasi.getROIFormat(self.camera_id)

    @property
    def exposure_limits(self) -> tuple[int | None, int | None]:
        """返回曝光时间范围，单位仍然是微秒。"""

        caps = self._controls_by_name.get("Exposure")
        if caps is None:
            return None, None
        return caps.MinValue, caps.MaxValue

    @property
    def gain_limits(self) -> tuple[int | None, int | None]:
        """返回增益范围。"""

        caps = self._controls_by_name.get("Gain")
        if caps is None:
            return None, None
        return caps.MinValue, caps.MaxValue

    @property
    def temperature_c(self) -> float | None:
        """读取传感器温度。不是所有相机都支持。"""

        if "Temperature" not in self._controls_by_name:
            return None
        value, _ = self.get_control("Temperature")
        return value * 0.1

    def apply_config(self, config: CameraConfig) -> None:
        """把 CameraConfig 中的参数应用到相机。

        顺序有意这样安排：
        先设置图像格式和 ROI，再设置曝光、增益等普通参数。
        """

        self.set_image_type(config.image_type)

        if config.software_binning is not None:
            self.set_software_binning(config.software_binning)

        if config.roi_width is not None or config.roi_height is not None:
            current_width, current_height, _, _ = self.roi
            self.set_roi(config.roi_width or current_width, config.roi_height or current_height)

        if _is_auto_setting(config.exposure_us):
            self.set_exposure_auto()
        else:
            self.set_exposure_us(config.exposure_us)

        if config.gain is not None:
            if _is_auto_setting(config.gain):
                self.set_gain_auto()
            else:
                self.set_gain(config.gain)
        if config.white_balance_r is not None:
            self.set_white_balance_r(config.white_balance_r)
        if config.white_balance_b is not None:
            self.set_white_balance_b(config.white_balance_b)
        if config.high_speed_mode is not None:
            self.set_high_speed_mode(config.high_speed_mode)
        if config.bandwidth is not None:
            self.set_bandwidth(config.bandwidth)
        if config.cooler is not None:
            self.set_cooler(config.cooler)
        if config.target_temperature_c is not None:
            self.set_target_temperature_c(config.target_temperature_c)

    def set_exposure_us(self, exposure_us: int) -> None:
        """设置曝光时间，单位是微秒。"""

        self.set_control("Exposure", int(exposure_us))

    def set_exposure_auto(self) -> None:
        """Enable the camera/SDK auto-exposure mode when supported."""

        self.set_control_auto("Exposure")

    def set_gain(self, gain: int) -> None:
        """设置增益。具体可用范围请看 gain_limits 或 list_controls()。"""

        self.set_control("Gain", int(gain))

    def set_gain_auto(self) -> None:
        """Enable the camera/SDK auto-gain mode when supported."""

        self.set_control_auto("Gain")

    def set_white_balance_r(self, value: int) -> None:
        """Set red white balance. This mainly affects rgb24 color images."""

        self.set_control("WB_R", int(value))

    def set_white_balance_b(self, value: int) -> None:
        """Set blue white balance. This mainly affects rgb24 color images."""

        self.set_control("WB_B", int(value))

    def set_white_balance(self, red: int | None = None, blue: int | None = None) -> None:
        """Set red and/or blue white balance controls."""

        if red is not None:
            self.set_white_balance_r(red)
        if blue is not None:
            self.set_white_balance_b(blue)

    def set_image_type(self, image_type: str | int) -> None:
        """设置图像格式：raw8, raw16, rgb24, y8。"""

        width, height, binning, _ = self.roi
        self._pyzwoasi.setROIFormat(self.camera_id, width, height, binning, int(self._coerce_image_type(image_type)))

    def set_roi(self, width: int, height: int) -> None:
        """设置 ROI。

        ZWO SDK 要求：
        width 必须是 8 的倍数，height 必须是 2 的倍数。
        """

        if width % 8 != 0:
            raise ValueError("ROI 宽度必须是 8 的倍数。")
        if height % 2 != 0:
            raise ValueError("ROI 高度必须是 2 的倍数。")

        _, _, binning, image_type = self.roi
        self._pyzwoasi.setROIFormat(self.camera_id, int(width), int(height), binning, int(image_type))

    def set_software_binning(self, binning: int) -> None:
        """设置软件 binning。

        这里保持当前视野比例，把 ROI 宽高按 binning 缩小。
        """

        width, height, _, image_type = self.roi
        self._pyzwoasi.setROIFormat(
            self.camera_id,
            int(width / binning),
            int(height / binning),
            int(binning),
            int(image_type),
        )

    def set_hardware_binning(self, binning: int) -> None:
        self.set_control("HardwareBin", int(binning))

    def set_high_speed_mode(self, enabled: bool) -> None:
        self.set_control("HighSpeedMode", int(bool(enabled)))

    def set_bandwidth(self, bandwidth: int) -> None:
        self.set_control("BandWidth", int(bandwidth))

    def set_cooler(self, enabled: bool) -> None:
        self.set_control("CoolerOn", int(bool(enabled)))

    def set_target_temperature_c(self, temperature_c: int) -> None:
        self.set_control("TargetTemp", int(temperature_c))

    def list_controls(self) -> list[dict[str, Any]]:
        """列出当前相机支持的所有控制项。

        不同 ZWO 型号支持的参数不同。
        如果你不知道某个参数叫什么、范围是多少，先运行这个函数。
        """

        controls: list[dict[str, Any]] = []

        for name in sorted(self._controls_by_name):
            caps = self._controls_by_name[name]
            value, is_auto = self.get_control(name)
            controls.append(
                {
                    "name": name,
                    "description": _decode_c_string(caps.Description),
                    "value": value,
                    "min": caps.MinValue,
                    "max": caps.MaxValue,
                    "default": caps.DefaultValue,
                    "is_auto": is_auto,
                    "auto_supported": bool(caps.IsAutoSupported),
                    "writable": bool(caps.IsWritable),
                }
            )

        return controls

    def get_control(self, name: str) -> tuple[int, bool]:
        """按 ZWO 控制项名称读取参数。

        返回值是 (当前数值, 是否自动模式)。
        例如：get_control("Exposure")。
        """

        caps = self._control_caps(name)
        return self._pyzwoasi.getControlValue(self.camera_id, caps.ControlType)

    def set_control(self, name: str, value: int | bool, auto: bool = False) -> None:
        """按 ZWO 控制项名称设置参数。

        常见 name 有 Exposure、Gain、BandWidth 等。
        具体名字以 list_controls() 打印结果为准。
        """

        caps = self._control_caps(name)
        if not bool(caps.IsWritable):
            raise RuntimeError(f"控制项 {name!r} 是只读的，不能设置。")

        if auto and not bool(caps.IsAutoSupported):
            raise RuntimeError(f"Camera control {name!r} does not support auto mode on this camera.")

        numeric_value = int(value)
        if numeric_value < caps.MinValue or numeric_value > caps.MaxValue:
            raise ValueError(f"{name}={numeric_value} 超出范围 [{caps.MinValue}, {caps.MaxValue}]。")

        self._pyzwoasi.setControlValue(self.camera_id, caps.ControlType, numeric_value, bool(auto))

    def set_control_auto(self, name: str) -> None:
        """Enable auto mode for one ZWO control while keeping its current value."""

        current_value, _ = self.get_control(name)
        self.set_control(name, current_value, auto=True)

    def capture(
        self,
        exposure_us: CameraAutoSetting | None = None,
        gain: CameraAutoSetting | None = None,
        image_type: str | int | None = None,
        white_balance_r: int | None = None,
        white_balance_b: int | None = None,
        is_dark: bool = False,
    ):
        """拍摄一张图，返回 numpy.ndarray。

        如果传入 exposure_us、gain、image_type 或白平衡，会先临时修改相机参数，再拍摄。
        is_dark=False 表示普通亮场/荧光图像；只有拍暗场校正时才改成 True。
        """

        import numpy as np

        if _is_auto_setting(exposure_us):
            self.set_exposure_auto()
        elif exposure_us is not None:
            self.set_exposure_us(exposure_us)
        if _is_auto_setting(gain):
            self.set_gain_auto()
        elif gain is not None:
            self.set_gain(gain)
        if white_balance_r is not None:
            self.set_white_balance_r(white_balance_r)
        if white_balance_b is not None:
            self.set_white_balance_b(white_balance_b)
        if image_type is not None:
            self.set_image_type(image_type)

        exposure_value, _ = self.get_control("Exposure")
        self._pyzwoasi.startExposure(self.camera_id, bool(is_dark))

        deadline = time.monotonic() + max(exposure_value / 1_000_000 * 3, 1.0) + 5.0
        while True:
            status = self._pyzwoasi.getExpStatus(self.camera_id)
            if status == self._exposure_status_enum.ASI_EXP_SUCCESS:
                break
            if status == self._exposure_status_enum.ASI_EXP_FAILED:
                try:
                    self._pyzwoasi.stopExposure(self.camera_id)
                except Exception:
                    pass
                exposure_seconds = exposure_value / 1_000_000
                raise RuntimeError(
                    f"相机曝光失败。当前曝光 {exposure_value} us，约 {exposure_seconds:.3f} s。"
                    "如果频繁出现，请降低曝光时间、检查 USB 连接，或增加自动对焦的相机重试等待。"
                )
            if time.monotonic() > deadline:
                self._pyzwoasi.stopExposure(self.camera_id)
                raise TimeoutError("等待相机曝光完成超时。")
            time.sleep(0.01)

        width, height, _, current_image_type = self.roi
        bytes_per_pixel = self._bytes_per_pixel(current_image_type)
        buffer_size = width * height * bytes_per_pixel
        image_data = self._pyzwoasi.getDataAfterExp(self.camera_id, buffer_size)

        if int(current_image_type) == int(self._image_type_enum.ASI_IMG_RAW16):
            frame = np.frombuffer(image_data, dtype=np.uint16).reshape(height, width)
        elif int(current_image_type) == int(self._image_type_enum.ASI_IMG_RGB24):
            frame = np.frombuffer(image_data, dtype=np.uint8).reshape(height, width, 3)
        else:
            frame = np.frombuffer(image_data, dtype=np.uint8).reshape(height, width)

        return frame

    def capture_to_file(
        self,
        output_path: str | Path,
        exposure_us: CameraAutoSetting | None = None,
        gain: CameraAutoSetting | None = None,
        image_type: str | int | None = None,
        white_balance_r: int | None = None,
        white_balance_b: int | None = None,
    ) -> Path:
        """拍摄一张图并保存到文件。"""

        frame = self.capture(
            exposure_us=exposure_us,
            gain=gain,
            image_type=image_type,
            white_balance_r=white_balance_r,
            white_balance_b=white_balance_b,
        )
        return save_frame(frame, output_path)

    def _load_controls(self) -> None:
        """从相机读取所有控制项，并按名称缓存起来。"""

        self._controls_by_name = {}
        control_count = self._pyzwoasi.getNumOfControls(self.camera_id)

        for control_index in range(control_count):
            caps = self._pyzwoasi.getControlCaps(self.camera_id, control_index)
            name = _decode_c_string(caps.Name)
            self._controls_by_name[name] = caps

    def _control_caps(self, name: str):
        try:
            return self._controls_by_name[name]
        except KeyError as exc:
            supported = ", ".join(sorted(self._controls_by_name))
            raise KeyError(f"相机不支持控制项 {name!r}。支持的控制项有：{supported}") from exc

    def _coerce_image_type(self, image_type: str | int):
        """把用户容易理解的 raw16 转成 pyzwoasi 需要的枚举值。"""

        if isinstance(image_type, int):
            return image_type

        normalized = image_type.strip().lower().replace("-", "").replace("_", "")
        aliases = {
            "raw8": "ASI_IMG_RAW8",
            "rgb24": "ASI_IMG_RGB24",
            "raw16": "ASI_IMG_RAW16",
            "y8": "ASI_IMG_Y8",
            "mono8": "ASI_IMG_Y8",
            "gray8": "ASI_IMG_Y8",
        }

        try:
            return getattr(self._image_type_enum, aliases[normalized])
        except KeyError as exc:
            raise ValueError("image_type 只能是 raw8, raw16, rgb24, y8 之一。") from exc

    def _bytes_per_pixel(self, image_type) -> int:
        if int(image_type) in {
            int(self._image_type_enum.ASI_IMG_RAW8),
            int(self._image_type_enum.ASI_IMG_Y8),
        }:
            return 1
        if int(image_type) == int(self._image_type_enum.ASI_IMG_RAW16):
            return 2
        if int(image_type) == int(self._image_type_enum.ASI_IMG_RGB24):
            return 3
        raise ValueError(f"不支持的图像格式：{image_type}")


def save_frame(frame, output_path: str | Path) -> Path:
    """保存图像数组。

    推荐显微图像保存为 .tiff 或 .npy：
    - .tiff 方便其他图像软件打开
    - .npy 完整保留 numpy 数组，方便 Python 后续分析
    """

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()

    if suffix == ".npy":
        import numpy as np

        np.save(output, frame)
        return output

    if suffix in {".tif", ".tiff"}:
        try:
            import tifffile
        except ImportError as exc:
            raise CameraDependencyError("保存 TIFF 需要安装 tifffile：python -m pip install tifffile") from exc

        tifffile.imwrite(output, frame)
        return output

    try:
        import cv2
    except ImportError as exc:
        raise CameraDependencyError("保存 PNG/JPG/BMP 需要安装 OpenCV：python -m pip install opencv-python") from exc

    ok = cv2.imwrite(str(output), frame)
    if not ok:
        raise RuntimeError(f"OpenCV 保存图像失败：{output}")

    return output


def _is_auto_setting(value: CameraAutoSetting | None) -> bool:
    return isinstance(value, str) and value.strip().lower() == "auto"

