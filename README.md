# Microscope Control 2.0

这是显微镜平台控制程序的正式精简版。它保留旧项目中已经验证的设备通信、自动对焦、相机重试、光谱采集、缓冲等待和异常安全关灯逻辑，同时把对外入口收敛为少量一致命令。

## 1. 项目结构

```text
microscope_control/
├─ devices/       # 硬件驱动：只处理 SDK、DLL 和串口通信
├─ functions/     # 单设备功能：相机、平台、光源、光谱仪
├─ workflows/     # 多设备流程：image、focus、alternate
├─ config.py      # 公共相机及基础配置
├─ system.py      # 设备连接、断开及异常清理
└─ cli.py         # 唯一命令行入口
```

旧版 `commands.py` 已取消。推荐统一使用：

```powershell
python -m microscope_control <command> [options]
```

安装后也可以直接使用 `microscopy` 命令。

## 2. 工作电脑部署

旧项目已经确认工作电脑使用 64 位 Python 3.11.9，运行目录为 `D:\opticalplatformcontrol`。新版建议与旧版并存：

```powershell
cd D:\opticalplatformcontrol\microscope-control-v2
.\setup_work_computer.ps1
.\run.ps1 doctor
```

详细步骤见 [WORK_COMPUTER_zh.md](WORK_COMPUTER_zh.md)。日常运行统一使用 `run.ps1`，不需要每次激活虚拟环境：

```powershell
.\run.ps1 image --light-image led
.\run.ps1 focus --focus-light led
.\run.ps1 alternate
```

工作电脑运行前还需要：

- 安装 ZWO ASI SDK/驱动并保证 `pyzwoasi` 能找到 SDK DLL；
- 安装 Thorlabs Kinesis；默认从 `C:\Program Files\Thorlabs\Kinesis` 查找；
- 接好 Arduino Uno，默认串口为 `COM3`；
- 使用光谱仪时提供 ASEQ 的 `spectrlib_shared_64bits.dll`。

所有工作电脑默认值集中在 `config\work_computer.toml`。当前配置继承旧项目记录：MLJ050 序列号 `49871116`、Kinesis 标准安装路径、Arduino 默认 `COM3`、数据输出到 `D:\captures\microscope`。由于旧记录中也出现过 `COM5`，应以 `doctor` 检测结果为准修改一次配置文件。

## 3. 相机通用参数

所有需要相机的命令都使用同一套参数：

| 参数 | 含义 |
|---|---|
| `--exposure-us 100` | 曝光 100 µs |
| `--exposure-ms 100` | 曝光 100 ms；不能与 `--exposure-us` 同时使用 |
| `--exposure-us auto` | SDK 自动曝光 |
| `--gain 300` / `--gain auto` | 固定或自动增益 |
| `--wb-r 66 --wb-b 95` | 红、蓝白平衡 |
| `--image-type raw16` | 图像数据格式 |
| `--roi-width 1440 --roi-height 1080` | ROI；宽度须为 8 的倍数，高度须为 2 的倍数 |
| `--software-binning 2` | 软件 binning |
| `--high-speed on` | 高速模式 |
| `--bandwidth 40` | USB 带宽控制 |
| `--cooler on --target-temperature-c -10` | 支持制冷的型号使用 |
| `--camera-control Contrast=10` | 设置当前型号支持的其他控制项 |

ZWO SDK 支持的图像类型只有以下四种：

- `raw8`：8 位原始 Bayer/单色数据；
- `raw16`：16 位容器中的高位深原始数据，推荐用于定量分析；
- `rgb24`：8 位三通道彩色图；
- `y8`：8 位灰度/亮度图；驱动内部也接受 `mono8`、`gray8`，CLI 统一显示为 `y8`。

不同相机型号支持的对比度、伽马、翻转、USB 带宽、制冷等控制项并不相同。连接实际相机后运行：

```powershell
.\run.ps1 camera-info
```

该命令会从 SDK 读取本机相机的完整控制项、范围、默认值和是否支持 auto。不要假设某个型号必然具有 `Contrast`。

## 4. 单设备功能

### 平台移动

`up` 在程序中严格定义为正向位移，`down` 定义为负向位移：

```powershell
.\run.ps1 stage --move-mode up --move-range-mm 0.2
.\run.ps1 stage --move-mode down --move-range-mm 0.2
.\run.ps1 stage --home
```

首次在实际光路中使用前，请用很小的位移确认“正向”是否对应你实验装置中的物理向上方向。

### 光源控制

```powershell
.\run.ps1 light --led on
.\run.ps1 light --laser on
.\run.ps1 light --led-on-s 10
.\run.ps1 light --led-on-s 10 --led-off-s 5 --laser-on-s 10 --laser-off-s 5
```

无时长的 `on` 会等待 Enter，然后安全关灯。程序正常结束、异常或 Ctrl+C 时均执行关灯。

### 单次光谱

```powershell
.\run.ps1 spectrum --spectrum-exposure-us 10000 --spectrum-averages 3
```

## 5. 工作流

### image：指定光路成像

```powershell
.\run.ps1 image --light-image led --exposure-ms 100 --gain 300 --image-type rgb24
.\run.ps1 image --light-image laser --reference-axes --output D:\captures\focus_roi.tiff
```

`--reference-axes` 保存 0–1 归一化坐标轴图，用来确定后续 `--focus-roi X Y W H`。

### focus：自动对焦

```powershell
.\run.ps1 focus `
  --focus-light led `
  --focus-metric tenengrad `
  --scan-mode plus-minus `
  --scan-range-mm 0.05 `
  --step-mm 0.005 `
  --focus-roi 0.25 0.25 0.50 0.50 `
  --save-frames clear `
  --light-settle-s 1
```

焦点评分支持 `tenengrad` 和 `laplacian`。`--save-frames all` 保存所有扫描点；`clear` 只保存最清晰点；`--no-save-frames` 不保存扫描图。自动对焦在失败时尝试返回起始位置，并记录 CSV 报告。

### alternate：正式交替采集

```powershell
.\run.ps1 alternate `
  --lights both `
  --duration-m 60 `
  --cycle-interval-s 10 `
  --focus on --focus-interval 100 `
  --spectrum on `
  --light-led-on-s 3 --light-led-off-s 2 `
  --light-laser-on-s 3 --light-laser-off-s 2 `
  --led-exposure-ms 100 --led-gain 300 --led-wb-r 63 --led-wb-b 75 --led-image-type rgb24 `
  --laser-exposure-ms 100 --laser-gain 300 --laser-wb-r 63 --laser-wb-b 75 --laser-image-type rgb24
```

流程顺序为 LED 开启 → 缓冲 → 拍照 → 保持 → 关闭 → 等待 → laser 开启 → 缓冲 → 拍照/光谱 → 保持 → 关闭 → 等待。`--cycle-interval-s` 是完整循环完成后的额外等待。

LED 与 laser 可分别设置曝光、增益、白平衡、图像类型，以及当前相机特有控制项，例如：

```powershell
--led-control Contrast=10 --laser-control Contrast=20
```

`--focus-interval 100` 表示每完成 100 个采集循环执行一次自动对焦。详细对焦参数在 alternate 中使用 `--af-` 前缀，例如 `--af-focus-metric laplacian`。

## 6. 安全与上线建议

- 首次正式运行先用 `--duration-m 0.2`、较长循环间隔和低光强做短测试；
- 确认平台正负方向、软件限位和对焦扫描范围后再无人值守运行；
- `raw16` 更适合定量数据，`rgb24` 更适合直接观察；
- 图像、光谱和 CSV 报告会保存在每次运行的时间戳目录中；
- 如果 `drivers\aseq\aseq_wavelengths_latest.txt` 存在，单次光谱和正式采集会自动输出 `wavelength_nm`；
- 本项目的自动测试不连接硬件，不能代替设备端验收。

## 7. 离线验证

```powershell
.\.venv\Scripts\python.exe -m compileall -q microscope_control
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
