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
| GET | `/api/res/device_values` | 批量读取设备电阻（`AT+RES.SP?`） |
| POST | `/api/res/device_value` | 按电阻值设置指定设备 |
| POST | `/api/res/device_temp` | 按温度设置指定设备 |

说明：

- `/api/res/device_values` 内部逐个 SN 查询并回填 `current_resistance`。
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
      "connected": true,
      "read_success": true
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
| POST | `/api/scope/copy_screenshot` | 保存截图并复制到剪贴板 |
| POST | `/api/scope/config` | 更新前端配置状态（刷新间隔等） |
| GET | `/api/scope/state` | 获取示波器状态 |

`/api/scope/copy_screenshot` 关键行为：

1. 从示波器拉取 PNG 二进制数据。
2. 保存到本地 `screenshots/`。
3. 调用 `powershell -STA` 将图片放入 Windows 剪贴板。

成功返回示例：

```json
{
  "success": true,
  "message": "截图已保存并复制到剪贴板",
  "filepath": "D:/.../screenshots/DLM_20260304_123456.png"
}
```

## 全局状态 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/state` | 一次返回电阻/电源/示波器连接状态 |

## 前端相关约定

- 电阻卡片显示值由 `/api/res/device_values` 轮询结果驱动。
- 手动设置电阻后不会立即改卡片，等待下一次读取更新。
- 设置日志格式：
  - 温度设置：`T=10℃ (94630Ω)`
  - 直接电阻：`R=94630Ω`
