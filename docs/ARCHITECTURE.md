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
  - NTC 计算与显示格式化
- `templates/index.html`
  - 页面结构（DOM）
- `static/css/index.css`
  - 页面样式
- `static/js/index.js`
  - 前端交互逻辑、轮询、Toast、设备卡片渲染

## 2. 关键状态与持久化

- 运行时状态：`device_runtime.state`
- 电阻设备配置持久化：
  - `scripts/res_ctrl/devices_config.json`
- 示波器截图存储目录：
  - `screenshots/`

## 3. 电阻模块设计

### 3.1 串口并发模型

`ResistanceController` 使用单独 worker 线程串行化串口访问：

- 外部请求通过 `_run_serial_task()` 提交任务
- worker 线程 `_serial_worker_loop()` 顺序执行
- 避免多个 HTTP 请求并发争用串口，降低“无响应/互相打断”风险

### 3.2 当前值读取

- 读取命令：`AT+RES.SP?`（可带 `@SN`）
- 后端接口：`GET /api/res/device_values`
- 返回值解析策略：
  - 优先匹配 `RES.SP=xxx` 或 `AT+RES.SP=xxx`
  - 其次匹配整行纯数字（可带 `Ω/OHM`）

### 3.3 温度显示规则

- 后端根据 NTC 表反查温度
- 仅显示 `-40℃~150℃`
- 超出范围或无法反查时显示 `--`

## 4. 示波器模块设计

### 4.1 通信互斥

`ScopeController` 内部使用 `io_lock`，保证同一时刻仅有一个示波器 I/O 操作。

### 4.2 截图复制流程

接口：`POST /api/scope/copy_screenshot`

执行顺序：

1. 停止采集并获取 PNG 数据块
2. 保存到服务端文件
3. 返回截图下载 URL 给前端
4. 前端在浏览器侧复制到“当前访问页面的电脑”剪贴板
5. 浏览器策略不允许时回退为下载到本机
6. 恢复采集和超时设置

## 5. 前端数据更新策略

### 5.1 电阻卡片

- 轮询接口：`/api/res/device_values`
- 使用自适应调度（`setTimeout`），不是固定 `setInterval`
- 手动设置后仅写日志，不立即覆盖卡片显示，等待下一次读取结果

### 5.2 示例日志格式

- 温度设置：`T=10℃ (94630Ω)`
- 直接电阻：`R=94630Ω`

### 5.3 示波器提示

- 复制截图完成后使用 toast 气泡提示
- 自动消失，不需要用户点击关闭

## 6. 启动与调试

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

## 7. 后续可扩展方向

- 为关键 API 增加统一错误码（目前主要依赖 `message` 文本）
- 为设备 I/O 加入结构化日志（便于定位串口/示波器问题）
- 增加最小化集成测试（mock 串口与示波器）
