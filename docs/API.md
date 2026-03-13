# API 文档

本文档对应当前 `main` 分支实现（`app.py` + `device_runtime.py`）。

## 通用约定

- 后端框架：Flask
- 请求体：JSON（后端使用 `get_request_data()`，空 body 不会抛异常）
- 返回格式：以 JSON 为主，通常包含 `success` 和 `message`
- 默认服务地址：`http://127.0.0.1:5000`

## 电阻相关 API

### 1. 串口与基础控制

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/res/list_ports` | 获取可用串口列表 |
| POST | `/api/res/connect` | 连接电阻串口 |
| POST | `/api/res/disconnect` | 断开电阻串口 |
| POST | `/api/res/action` | 对单个设备执行动作（可带 SN） |
| POST | `/api/res/device_action` | 对多个设备批量执行动作 |
| POST | `/api/res/set_by_temperature` | 按温度设置电阻（支持 SN） |

`/api/res/action` `action` 可选值：

- `connect`
- `disconnect`
- `short`
- `unshort`
- `set_value`（需要 `value`）

请求示例：

```json
POST /api/res/connect
{ "port": "COM5" }
```

```json
POST /api/res/action
{ "action": "set_value", "value": 94630, "sn": "1001" }
```

### 2. 设备管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/res/devices` | 获取设备列表 |
| POST | `/api/res/devices` | 添加设备 |
| PUT | `/api/res/devices/<sn>` | 重命名设备 |
| DELETE | `/api/res/devices/<sn>` | 删除设备 |
| POST | `/api/res/devices/order` | 保存设备顺序 |

请求示例：

```json
POST /api/res/devices
{ "name": "左前", "sn": "1001" }
```

```json
POST /api/res/devices/order
{ "order": ["1001", "1002", "1003"] }
```

### 3. 设备值读取与设置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/res/device_values` | 获取设备电阻缓存 |
| POST | `/api/res/device_value` | 按电阻值设置指定设备 |
| POST | `/api/res/device_temp` | 按温度设置指定设备 |

说明：

- `/api/res/device_values` 当前返回后端后台缓存，不在请求内逐个现查设备。
- `/api/res/device_value` 与 `/api/res/device_temp` 会优先使用设备设置指令返回的电阻值更新 `current_resistance`。
- 设备温度显示由后端通过 NTC 反查得到，超出 `-40℃~150℃` 显示 `--`。
- 返回字段中包含 `current_temperature_display`（如 `10℃` 或 `--`）。

典型返回（节选）：

```json
{
  "success": true,
  "devices": [
    {
      "sn": "1001",
      "name": "左前",
      "current_resistance": "94630Ω",
      "current_temperature_display": "10℃",
      "connected": true
    }
  ]
}
```

## 电源相关 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/power/list_resources` | 列出 VISA 资源 |
| POST | `/api/power/connect` | 连接电源 |
| POST | `/api/power/disconnect` | 断开电源 |
| POST | `/api/power/set` | 设置电压/电流/输出 |
| GET | `/api/power/measure` | 读取电压电流 |

说明：

- `/api/power/list_resources` 当前通过独立子进程扫描 VISA 资源，避免干扰主进程内已打开的示波器 session。
- `/api/power/connect` 对同一地址是幂等的；已连接时再次请求会直接返回“电源已连接”。
- `/api/power/measure` 当前返回后端后台缓存，而不是在请求内直接访问电源。

`/api/power/list_resources` 返回示例：

```json
{
  "resources": [
    {
      "address": "USB0::0x2EC7::0x6700::DP8A123456::INSTR",
      "label": "ITECH (SN=DP8A123456, VID=0x2EC7, PID=0x6700)"
    }
  ]
}
```

`/api/power/set` 请求示例：

```json
{
  "voltage": 13.5,
  "current": 20,
  "output": true
}
```

## 示波器相关 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/scope/connect` | 按序列号连接示波器 |
| POST | `/api/scope/disconnect` | 断开示波器 |
| POST | `/api/scope/unlock` | 解锁本地控制 |
| POST | `/api/scope/lock` | 锁定远程控制 |
| POST | `/api/scope/channel` | 设置通道开关 |
| GET | `/api/scope/channel_state` | 获取 4 通道开关状态 |
| GET | `/api/scope/get_mean` | 获取 4 通道平均值 |
| POST | `/api/scope/copy_screenshot` | 生成并保存截图，返回客户端复制所需信息 |
| GET | `/api/scope/screenshot/<filename>` | 读取服务端保存的 PNG 截图 |
| POST | `/api/scope/config` | 更新前端配置状态（刷新间隔、通道别名等） |
| GET | `/api/scope/state` | 获取示波器状态 |

`/api/scope/connect` 当前行为：

- 连接成功后，服务端会立即尝试执行本地解锁。
- 成功时返回 `locked: false`，表示前面板已可操作。
- 若解锁失败，会返回 `locked: true`，同时 `message` 中附带失败原因。
- 对同一序列号的重复连接请求是幂等的；若会话仍健康，会直接返回 `already_connected: true`，不会重新连接。

返回示例：

```json
{
  "success": true,
  "message": "连接成功",
  "locked": false
}
```

`/api/scope/channel_state` / `/api/scope/get_mean` 当前返回后端后台缓存，不在请求内直接现查示波器。

`/api/scope/unlock` / `/api/scope/lock` 仅切换仪器本地/远程模式，不会中断当前连接。

`/api/scope/config` 补充约定：

- `channel_aliases` 为可选对象，键固定为 `ch1` 到 `ch4`。
- 别名为空字符串时，前端回退显示 `CH1` 到 `CH4`。
- 单个别名最长 24 个字符。

服务端日志说明：

- 示波器连接、健康检查失败、自动重连、断开会打印 `[scope]` 前缀日志。
- 如果遇到 `Invalid session handle. The resource might be closed.`，优先排查该时刻是否发生了 VISA 资源扫描或 USB 会话异常。

`/api/scope/copy_screenshot` 关键行为：

1. 从示波器拉取 PNG 二进制数据。
2. 保存到服务端 `screenshots/`。
3. 返回 `download_url`，前端再拉取 PNG 并尝试写入“当前访问页面的电脑”的剪贴板。
4. 若浏览器不支持或策略不允许（如非 HTTPS），前端会回退为下载到本机。

成功返回示例：

```json
{
  "success": true,
  "message": "截图已保存，正在复制到当前浏览器所在电脑的剪贴板",
  "filepath": "/.../screenshots/DLM_20260304_123456.png",
  "filename": "DLM_20260304_123456.png",
  "download_url": "/api/scope/screenshot/DLM_20260304_123456.png"
}
```

## 全局状态 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/state` | 一次返回电阻/电源/示波器连接状态 |

说明：

- `/api/state` 当前返回后端统一维护的运行时缓存。
- `scope` 对象额外包含 `channel_states`、`channel_values` 与 `channel_aliases`。

`/api/state` 中 `scope.locked` 含义：

- `true`：当前处于远程锁定模式，示波器前面板按键受限
- `false`：当前已解锁本地控制，前面板和网页都可继续使用

## 前端相关约定

- 前端页面刷新或切页只读取后端缓存，不应主动触发设备重连。
- 电阻卡片值在这些时机请求缓存：页面刷新且串口已连接、刚连接串口、创建设备后。
- 手动设置电阻/温度后，前端直接使用接口返回值立即更新卡片显示。
- 设置日志格式：
  - 温度设置：`T=10℃ (94630Ω)`
  - 直接电阻：`R=94630Ω`
