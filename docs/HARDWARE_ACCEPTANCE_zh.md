# 硬件验收清单

本清单用于把离线通过的软件交付，安全地推进到显微镜平台正式运行。

## 1. 连接检查

1. 在工作电脑运行 `.\run.ps1 doctor`，确认 Python 3.11.9/64 位、Kinesis、ASEQ DLL、标定文件、COM 端口及 ZWO 相机状态。
2. 如果 Arduino 显示为 `COM5` 而不是默认 `COM3`，修改 `config\work_computer.toml`。
3. 运行 `.\run.ps1 camera-info`，保存实际相机控制项输出。
4. 分别连接 MLJ050、Arduino 和 ASEQ，确认序列号、COM 端口与设备索引。

## 2. 单设备检查

1. 平台先执行 `--move-range-mm 0.001`，确认 up/down 的物理方向。
2. 分别短时开启 LED 和 laser，确认 Arduino 指令映射正确。
3. 分别保存一张 `raw16` 和 `rgb24`，检查尺寸、位深和颜色。
4. 采集一条光谱并确认像素数、积分时间和标定文件。

## 3. 工作流检查

1. 用 reference axes 图确定 focus ROI。
2. 在小扫描范围内分别运行 Tenengrad 和 Laplacian，对比最佳焦点是否合理。
3. 运行 0.2 分钟的 alternate 短测试，检查 LED/laser 图片、光谱及 CSV 报告。
4. 人工中断一次运行，确认光源关闭、串口释放且平台状态可恢复。
5. 模拟相机采集失败，确认重试次数、报告信息和最终关灯行为。

## 4. 正式运行前记录

- 相机型号及 SDK 控制项：
- MLJ050 正向对应的物理方向：
- 有效平台最小/最大位置：
- Arduino 端口：
- ASEQ DLL 与设备索引：
- LED 相机参数：
- laser 相机参数：
- 自动对焦 ROI、指标、范围和步长：
