# 工作电脑部署与日常使用

本文件只描述实验工作电脑。源码开发位置仍在 CodexWorkspace，工作电脑运行副本建议放在：

```text
D:\opticalplatformcontrol\microscope-control-v2
```

旧版 `D:\opticalplatformcontrol\microscope-control` 先保留，作为可回退版本。

## 首次部署

1. 将整个 `microscope-control` 交付目录复制到上述 `microscope-control-v2`。
2. 打开 PowerShell：

```powershell
cd D:\opticalplatformcontrol\microscope-control-v2
.\setup_work_computer.ps1
.\run.ps1 doctor
```

安装脚本使用工作电脑既定的 Python 3.11，并尝试从旧项目复制 ASEQ DLL 和波长标定文件。它不会删除或修改旧项目。

如果工作电脑暂时不能联网且尚未建立新版 `.venv`，`run.ps1` 会自动借用旧项目已经可运行的 Python 环境，同时强制加载新版源码；这样可以先完成硬件验收，之后再单独建立新版环境。

如果 PowerShell 阻止本地脚本，可仅对当前窗口执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## 工作电脑配置

所有默认值集中在 `config\work_computer.toml`：

- 数据保存根目录：`D:\captures\microscope`
- MLJ050：序列号 `49871116`
- Kinesis：`C:\Program Files\Thorlabs\Kinesis`
- Arduino：默认 `COM3`
- ASEQ DLL：`drivers\aseq\spectrlib_shared_64bits.dll`
- ASEQ 标定：`drivers\aseq\aseq_wavelengths_latest.txt`

旧项目记录显示 Arduino 曾使用 `COM3` 或 `COM5`。运行 `doctor` 后，以报告中的 detected ports 为准修改 TOML，不要在每条命令中重复填写端口。

## 每日启动

运行前关闭 ASIStudio、Kinesis 图形界面和 Arduino Serial Monitor，避免占用硬件。

```powershell
cd D:\opticalplatformcontrol\microscope-control-v2
.\run.ps1 doctor
```

环境检查通过后，常用命令为：

```powershell
.\run.ps1 image --light-image led
.\run.ps1 focus --focus-light led
.\run.ps1 alternate
```

`alternate` 已从工作电脑配置读取 LED/laser 相机参数、光谱标定、采集时序、自动对焦间隔和 `D:` 盘输出路径。需要临时改变参数时再追加命令行选项。

## 首次短测试

```powershell
.\run.ps1 stage --move-mode up --move-range-mm 0.001
.\run.ps1 stage --move-mode down --move-range-mm 0.001
.\run.ps1 light --led-on-s 1
.\run.ps1 light --laser-on-s 1
.\run.ps1 image --light-image led
.\run.ps1 focus --focus-light led --scan-mode up --scan-range-mm 0.02 --step-mm 0.005
.\run.ps1 alternate --duration-m 0.2 --focus off
```

完成短测试并检查 `D:\captures\microscope` 中的图像、光谱和 CSV 后，再启动正式 60 分钟采集。

## 正式采集

配置文件正确时，正式流程可简化为：

```powershell
.\run.ps1 alternate
```

显式等价示例：

```powershell
.\run.ps1 alternate `
  --lights both --duration-m 60 --cycle-interval-s 10 `
  --focus on --focus-interval 100 --spectrum on `
  --light-led-on-s 3 --light-led-off-s 2 `
  --light-laser-on-s 3 --light-laser-off-s 2
```
