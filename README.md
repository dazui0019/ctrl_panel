# 控制面板 (Control Panel)

基于 Flask 的设备控制面板，用于控制电阻、电源和示波器。

## 功能特性

### 电阻控制
- 串口连接/断开
- 连接/断开电阻
- 短路/取消短路
- 设置自定义电阻值 (0-7MΩ)
- 按温度设置电阻 (NTC 热敏电阻表 -40~150°C)

### 电源控制
- VISA 资源连接
- 设置电压 (默认 13.5V)
- 设置电流 (默认 20A)
- 输出开关控制
- 实时电压/电流显示 (每秒自动刷新)

### 示波器控制
- USB 序列号连接
- 远程/本地模式切换
- 通道开关 (控制示波器 CH1-CH4)
- 平均值显示 (mV/mA)
- 自动刷新 (可设置间隔 500-10000ms)

## 环境要求

- Python 3.11+
- Windows 操作系统

## 安装依赖

```bash
pip install flask pyserial pyvisa
```

## 运行

```bash
python app.py
```

然后在浏览器打开: http://127.0.0.1:5000

## 硬件连接

### 电阻控制器
- 通过串口 (COMx) 连接

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
├── templates/
│   └── index.html     # 前端页面
├── scripts/
│   ├── res_ctrl/      # 电阻控制脚本
│   │   └── ntc_res.txt    # NTC 电阻-温度对照表
│   ├── power_ctrl/    # 电源控制脚本
│   └── yokogawa/      # 示波器控制脚本
└── pyproject.toml     # 项目配置
```
