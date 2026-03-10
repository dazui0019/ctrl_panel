# 控制面板 (Control Panel)

基于 Flask 的设备控制面板，用于控制电阻、电源和示波器。

## 功能特性

### 电阻控制 (支持 RS485 多设备)
- 串口连接/断开
- 多设备管理：添加、删除、重命名设备
- 批量控制：连接、开路、短路、取消短路
- 设备拖拽排序
- 设置电阻值 (0-7MΩ)
- 按温度设置电阻 (NTC 热敏电阻表 -40~150°C)
- 设置日志记录

### 电源控制
- VISA 资源连接
- 设置电压 (默认 13.5V)
- 设置电流 (默认 20A)
- 输出开关控制
- 实时电压/电流显示 (每秒自动刷新)

### 示波器控制
- USB 序列号连接
- 自动锁定远程模式
- 通道开关：点击通道卡片切换 CH1-CH4
- 平均值显示 (mV/mA)
- 自动刷新 (可设置间隔 500-10000ms)
- 所有通道关闭时停止自动刷新

## 环境要求

- Python 3.11+
- Windows 或 Linux 操作系统
- Linux 下示波器控制需确保已安装 `pyvisa-py`/`pyusb`，并按 `scripts/yokogawa/README_Linux.md` 配置 udev 权限

## 运行

```bash
uv run python app.py
```

然后在浏览器打开: http://127.0.0.1:5000

### 后台启动/停止脚本

```bash
# 后台启动（日志写入 .ctrl_panel.log，PID 写入 .ctrl_panel.pid）
./start.sh

# 停止
./stop.sh
```

说明：
- `start.sh` 会在端口已被本项目进程占用时直接复用，并自动修复 PID 文件。
- `stop.sh` 在 PID 文件缺失时也会按端口自动查找并停止本项目进程。

### HTTPS（用于浏览器剪贴板）

开发环境可直接启用临时证书：

```bash
FLASK_SSL_MODE=adhoc uv run python app.py
```

生产/局域网建议使用证书文件：

```bash
FLASK_SSL_MODE=files FLASK_SSL_CERT=/path/to/fullchain.pem FLASK_SSL_KEY=/path/to/privkey.pem uv run python app.py
```

## 技术文档

- [API 文档](docs/API.md)
- [架构与运行说明](docs/ARCHITECTURE.md)

## 硬件连接

### 电阻控制器
- 通过串口连接（Windows 常见 COMx，Linux 常见 /dev/ttyUSBx）
- 支持 RS485 总线多设备，通过 SN 码区分

### 电源
- 通过 VISA (USB/GPIB) 连接
- 支持 ITECH IT6722 等可编程电源

### 示波器
- 通过 USB 连接
- 默认序列号: 90Y701585

## 项目结构

```
ctrl_panel/
├── app.py              # Flask 主应用
├── device_runtime.py   # 设备控制器与运行时状态
├── templates/
│   └── index.html     # 前端页面
├── static/
│   ├── css/
│   │   └── index.css  # 前端样式
│   └── js/
│       └── index.js   # 前端脚本逻辑
├── scripts/
│   ├── res_ctrl/      # 电阻控制脚本
│   │   └── ntc_res.txt    # NTC 电阻-温度对照表
│   ├── power_ctrl/    # 电源控制脚本
│   └── yokogawa/      # 示波器控制脚本
└── pyproject.toml     # 项目配置
```
