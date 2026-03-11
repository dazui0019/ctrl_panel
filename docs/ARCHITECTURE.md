# 架构与运行说明

本文档描述当前控制面板的模块划分、运行流程和关键设计点。

## 1. 模块划分

- `app.py`
  - Flask 应用入口
  - 仅负责 HTTP 路由、参数校验与响应组织
  - 默认 `debug` 关闭（可用 `FLASK_DEBUG=1` 开启）
- `device_runtime.py`
  - 全局状态 `DeviceState`
  - 三类控制器：`ResistanceController` / `PowerController` / `ScopeController`
  - 后台监控线程 `DeviceMonitor`
  - NTC 计算与显示格式化
- `templates/base.html`
  - 共享页面骨架与顶部导航
- `templates/workspace.html`
  - 工作页面 DOM，集中展示操作区和数据区
- `templates/device_management.html`
  - 设备管理页面 DOM，集中处理连接和设备清单维护
- `static/css/index.css`
  - 两个页面共享的样式系统与响应式布局
- `static/js/index.js`
  - 前端交互逻辑、Toast、按页面初始化的设备卡片渲染

## 2. 关键状态与持久化

- 运行时状态：`device_runtime.state`
- 后端后台采集缓存：
  - 电源：`power_connected` / `power_voltage` / `power_current`
  - 示波器：`scope_connected` / `scope_channel_states` / `scope_channel_values`
  - 电阻：各设备 `current_resistance` / `connected`
- 电阻设备配置持久化：
  - `scripts/res_ctrl/devices_config.json`
- 示波器截图存储目录：
  - `screenshots/`

## 3. 后端后台监控

`DeviceMonitor` 在服务启动后常驻运行，负责：

- 周期性维护示波器连接健康状态
- 周期性读取示波器已开启通道的平均值
- 周期性刷新电源测量缓存
- 轮转读取电阻设备当前值，避免一次性占满串口或拖慢其他设备

设计目标：

- 真实设备读写由后端统一负责
- 页面切换、刷新只读取后端缓存
- 连接掉线时由后端按既定策略恢复，而不是由前端页面生命周期驱动

## 4. 电阻模块设计

### 4.1 串口并发模型

`ResistanceController` 使用单独 worker 线程串行化串口访问：

- 外部请求通过 `_run_serial_task()` 提交任务
- worker 线程 `_serial_worker_loop()` 顺序执行
- 避免多个 HTTP 请求并发争用串口，降低“无响应/互相打断”风险

### 4.2 当前值读取

- 读取命令：`AT+RES.SP?`（可带 `@SN`）
- 后端接口：`GET /api/res/device_values`
- 当前实现中，该接口返回后台缓存；后台线程会轮转刷新设备值
- 返回值解析策略：
  - 优先匹配 `RES.SP=xxx` 或 `AT+RES.SP=xxx`
  - 其次匹配整行纯数字（可带 `Ω/OHM`）

### 4.3 温度显示规则

- 后端根据 NTC 表反查温度
- 仅显示 `-40℃~150℃`
- 超出范围或无法反查时显示 `--`

## 5. 示波器模块设计

### 5.1 通信互斥

`ScopeController` 内部使用 `io_lock`，保证同一时刻仅有一个示波器 I/O 操作。

### 5.2 连接保活与重连

- 运行时用 `scope_expected_connected` 区分“用户希望保持连接”与“当前 session 仍然可用”。
- 健康检查使用 `*STB?`，失败时作废当前 session 并按需自动重连。
- 通道读取、均值读取、本地/远程切换在单次失败时会执行一次“重连后重试”。
- 连接、健康检查失败、自动重连、断开都会输出 `[scope]` 日志，便于定位 `Invalid session handle` 等问题。

### 5.3 本地/远程控制语义

- 连接成功后，后端会立即调用 `unlock_local()`。
- `unlock_local()` 会发送 `:COMMunicate:REMote OFF`，让前面板按键恢复可用。
- 前端仍然保留远程读取、通道切换、截图与刷新周期设置，不会因为“本地已解锁”而暂停。
- 用户主动点击“锁定”时，后端改发 `:COMMunicate:REMote ON`，切回远程独占模式。

### 5.4 截图复制流程

接口：`POST /api/scope/copy_screenshot`

执行顺序：

1. 停止采集并获取 PNG 数据块
2. 保存到服务端文件
3. 返回截图下载 URL 给前端
4. 前端在浏览器侧复制到“当前访问页面的电脑”剪贴板
5. 浏览器策略不允许时回退为下载到本机
6. 恢复采集和超时设置

## 6. 电源资源扫描隔离

- 设备管理页仍会自动刷新电源 VISA 资源列表。
- 为避免 `pyvisa.ResourceManager().list_resources()` 干扰主进程内已打开的示波器 session，资源扫描改为单独 Python 子进程执行。
- 这样既能保留电源下拉框自动更新，又能尽量避免示波器被动断句柄。

## 7. 前端数据更新策略

### 7.1 电阻卡片

- 单次读取接口：`/api/res/device_values`
- 触发时机：
  - 页面刷新且串口已连接
  - 刚连接串口
  - 创建设备后
- 前端接口读到的是后端缓存；手动设置后仍会用接口返回值立即更新卡片显示

### 7.2 电源与示波器

- 工作页前端仍保留定时请求，但这些请求只读取后端缓存，不直接驱动真实设备采集。
- 因此页面刷新或切页不应再主动触发设备重新连接。

### 7.3 示例日志格式

- 温度设置：`T=10℃ (94630Ω)`
- 直接电阻：`R=94630Ω`

### 7.4 示波器提示

- 复制截图完成后使用 toast 气泡提示
- 自动消失，不需要用户点击关闭

## 8. 启动与调试

启动：

```bash
uv run python app.py
```

开启 debug（默认关闭）：

```bash
# Linux / macOS
FLASK_DEBUG=1 uv run python app.py

# Windows PowerShell
$env:FLASK_DEBUG = "1"
uv run python app.py
```

## 9. 后续可扩展方向

- 为关键 API 增加统一错误码（目前主要依赖 `message` 文本）
- 增加最小化集成测试（mock 串口与示波器）
