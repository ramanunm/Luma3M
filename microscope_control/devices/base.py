from __future__ import annotations


class DeviceNotConnectedError(RuntimeError):
    """当设备还没有连接却被使用时抛出这个错误。"""


class Device:
    """所有硬件设备的最小接口。

    以后相机、位移台、光源、滤镜轮都可以长成类似样子：
    connect() 负责连接硬件，disconnect() 负责释放硬件。
    """

    def connect(self):
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

