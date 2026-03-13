#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
控制面板 Flask 应用
整合电阻控制、电源控制、示波器读取功能
"""

import os
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for

from device_runtime import (
    state,
    ntc_table,
    res_controller,
    power_controller,
    scope_controller,
    device_monitor,
    ResistanceDevice,
    build_res_device_status,
    empty_scope_channel_states,
    empty_scope_channel_values,
    empty_scope_channel_aliases,
)

app = Flask(__name__)


def get_request_data():
    """安全读取 JSON 请求体，避免空 body 导致异常"""
    return request.get_json(silent=True) or {}


def normalize_scope_channel_aliases(raw_aliases):
    """校验并规范化示波器通道别名"""
    if not isinstance(raw_aliases, dict):
        raise ValueError("通道别名格式无效")

    aliases = dict(getattr(state, "scope_channel_aliases", empty_scope_channel_aliases()))
    valid_keys = set(aliases.keys())
    invalid_keys = [str(key) for key in raw_aliases.keys() if key not in valid_keys]
    if invalid_keys:
        raise ValueError(f"无效的通道标识: {', '.join(invalid_keys)}")

    for channel in range(1, 5):
        key = f"ch{channel}"
        if key not in raw_aliases:
            continue

        value = raw_aliases.get(key)
        if value is None:
            normalized = ""
        elif isinstance(value, (str, int, float)):
            normalized = str(value).strip()
        else:
            raise ValueError(f"CH{channel} 别名格式无效")

        if len(normalized) > 24:
            raise ValueError(f"CH{channel} 别名最多 24 个字符")

        aliases[key] = normalized

    return aliases


@app.after_request
def disable_api_cache(response):
    """禁用 API 响应缓存，避免工作页轮询拿到浏览器旧数据"""
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


# ========== Flask 路由 ==========

@app.route('/')
def index():
    """默认进入工作页面"""
    return redirect(url_for('workspace'))


@app.route('/workspace')
def workspace():
    """工作页面"""
    return render_template('workspace.html', page='workspace', page_title='工作页面')


@app.route('/devices')
def device_management():
    """设备管理页面"""
    return render_template('device_management.html', page='device-management', page_title='设备管理')


# ----- 电阻 API -----
@app.route('/api/res/list_ports', methods=['GET'])
def res_list_ports():
    """获取可用串口列表"""
    ports = res_controller.list_ports()
    return jsonify({"ports": ports})


@app.route('/api/res/connect', methods=['POST'])
def res_connect():
    """连接串口"""
    data = get_request_data()
    port = data.get('port')
    if res_controller.connected and port and state.resistance_port == port:
        return jsonify({"success": True, "message": "串口已连接"})

    success, msg = res_controller.connect(port)
    if success:
        state.resistance_connected = True
        state.resistance_port = port
        device_monitor.refresh_resistance_now(full=True)
    return jsonify({"success": success, "message": msg})


@app.route('/api/res/disconnect', methods=['POST'])
def res_disconnect():
    """断开串口"""
    res_controller.disconnect()
    state.resistance_connected = False
    state.resistance_port = None
    state.resistance_value = None
    device_monitor.request_refresh()
    return jsonify({"success": True})


@app.route('/api/res/action', methods=['POST'])
def res_action():
    """执行电阻操作"""
    data = get_request_data()
    action = data.get('action')
    value = data.get('value')
    sn = data.get('sn')  # SN 码参数，支持多设备

    if action == 'connect':
        success, msg = res_controller.set_connect(sn)
    elif action == 'disconnect':
        success, msg = res_controller.set_disconnect(sn)
    elif action == 'short':
        success, msg = res_controller.set_short(sn)
    elif action == 'unshort':
        success, msg = res_controller.set_unshort(sn)
    elif action == 'set_value' and value:
        success, msg = res_controller.set_value(value, sn)
    else:
        success, msg = False, "未知操作"

    if success:
        device_monitor.request_refresh()
    return jsonify({"success": success, "message": msg})


@app.route('/api/res/device_action', methods=['POST'])
def res_device_action():
    """对多个设备执行操作"""
    data = get_request_data()
    action = data.get('action')
    sns = data.get('sns', [])  # 设备 SN 列表

    results = []
    for sn in sns:
        if action == 'connect':
            success, msg = res_controller.set_connect(sn)
        elif action == 'disconnect':
            success, msg = res_controller.set_disconnect(sn)
        elif action == 'short':
            success, msg = res_controller.set_short(sn)
        elif action == 'unshort':
            success, msg = res_controller.set_unshort(sn)
        else:
            success, msg = False, "未知操作"
        results.append({"sn": sn, "success": success, "message": msg})

    if any(item["success"] for item in results):
        device_monitor.request_refresh()
    return jsonify({"results": results})


@app.route('/api/res/set_by_temperature', methods=['POST'])
def res_set_by_temperature():
    """通过温度设置电阻"""
    data = get_request_data()
    temperature = data.get('temperature')
    sn = data.get('sn')  # SN 码参数

    if temperature is None:
        return jsonify({"success": False, "message": "请提供温度值"})

    try:
        temperature = float(temperature)
    except ValueError:
        return jsonify({"success": False, "message": "无效的温度值"})

    if temperature < -40 or temperature > 150:
        return jsonify({"success": False, "message": "温度超出范围 (-40~150°C)"})

    # 获取对应的电阻值
    resistance = ntc_table.get_resistance(temperature)
    if resistance is None:
        return jsonify({"success": False, "message": "无法查找对应电阻值"})

    # 设置电阻
    success, msg = res_controller.set_by_temperature(temperature, sn)

    return jsonify({
        "success": success,
        "message": msg,
        "temperature": temperature,
        "resistance": resistance
    })


# ----- 设备管理 API -----
@app.route('/api/res/devices', methods=['GET'])
def res_get_devices():
    """获取设备列表"""
    devices = []
    for device in res_controller.devices_list:
        devices.append(build_res_device_status(device))
    return jsonify({"devices": devices})


@app.route('/api/res/device_values', methods=['GET'])
def res_get_device_values():
    """获取后台缓存的设备当前电阻值"""
    if not res_controller.connected:
        return jsonify({"success": False, "message": "串口未连接"}), 400

    return jsonify({
        "success": True,
        "devices": [build_res_device_status(device) for device in res_controller.devices_list]
    })


@app.route('/api/res/devices', methods=['POST'])
def res_add_device():
    """添加设备"""
    data = get_request_data()
    name = data.get('name', '未命名')
    sn = data.get('sn')

    if not sn:
        return jsonify({"success": False, "message": "请提供 SN 码"})

    if sn in res_controller.devices:
        return jsonify({"success": False, "message": f"设备 {sn} 已存在"})

    # 创建设备
    device = ResistanceDevice(sn, name)
    res_controller.devices[sn] = device
    res_controller.devices_list.append(device)
    res_controller.save_devices()

    return jsonify({"success": True, "sn": sn, "name": name})


@app.route('/api/res/devices/<sn>', methods=['DELETE'])
def res_delete_device(sn):
    """删除设备"""
    if sn not in res_controller.devices:
        return jsonify({"success": False, "message": f"设备 {sn} 不存在"})

    name = res_controller.devices[sn].name
    del res_controller.devices[sn]
    # 从列表中移除
    res_controller.devices_list = [d for d in res_controller.devices_list if d.sn != sn]
    res_controller.save_devices()

    return jsonify({"success": True, "message": f"已删除设备 {name} ({sn})"})


@app.route('/api/res/devices/order', methods=['POST'])
def res_update_device_order():
    """更新设备顺序"""
    data = get_request_data()
    order = data.get('order', [])

    # 按新顺序重新排列
    new_list = []
    for sn in order:
        if sn in res_controller.devices:
            new_list.append(res_controller.devices[sn])

    # 添加不在列表中的设备
    for device in res_controller.devices_list:
        if device not in new_list:
            new_list.append(device)

    res_controller.devices_list = new_list
    res_controller.save_devices()

    return jsonify({"success": True})


@app.route('/api/res/devices/<sn>', methods=['PUT'])
def res_rename_device(sn):
    """重命名设备"""
    data = get_request_data()
    new_name = data.get('name')

    if sn not in res_controller.devices:
        return jsonify({"success": False, "message": f"设备 {sn} 不存在"})

    if not new_name:
        return jsonify({"success": False, "message": "请提供新名称"})

    res_controller.devices[sn].name = new_name
    res_controller.save_devices()

    return jsonify({"success": True, "sn": sn, "name": new_name})


@app.route('/api/res/device_value', methods=['POST'])
def res_set_device_value():
    """设置指定设备的电阻值"""
    data = get_request_data()
    sn = data.get('sn')
    value = data.get('value')

    if not sn:
        return jsonify({"success": False, "message": "请提供 SN 码"})

    if sn not in res_controller.devices:
        return jsonify({"success": False, "message": f"设备 {sn} 不存在"})

    success, msg = res_controller.set_value(value, sn)

    if success and sn in res_controller.devices:
        device_monitor.request_refresh()
        status = build_res_device_status(res_controller.devices[sn])
        return jsonify({"success": True, "message": msg, **status})

    return jsonify({"success": success, "message": msg})


@app.route('/api/res/device_temp', methods=['POST'])
def res_set_device_temp():
    """通过温度设置指定设备的电阻值"""
    data = get_request_data()
    sn = data.get('sn')
    temperature = data.get('temperature')

    if not sn:
        return jsonify({"success": False, "message": "请提供 SN 码"})

    if sn not in res_controller.devices:
        return jsonify({"success": False, "message": f"设备 {sn} 不存在"})

    if temperature is None:
        return jsonify({"success": False, "message": "请提供温度值"})

    try:
        temperature = float(temperature)
    except ValueError:
        return jsonify({"success": False, "message": "无效的温度值"})

    # 获取对应的电阻值
    resistance = ntc_table.get_resistance(temperature)
    if resistance is None:
        return jsonify({"success": False, "message": "无法查找对应电阻值"})

    success, msg = res_controller.set_value(resistance, sn)

    if success and sn in res_controller.devices:
        device_monitor.request_refresh()
        status = build_res_device_status(res_controller.devices[sn])
        return jsonify({
            "success": True,
            "message": msg,
            "temperature": temperature,
            "resistance": resistance,
            **status
        })

    return jsonify({
        "success": success,
        "message": msg,
        "temperature": temperature,
        "resistance": resistance
    })


# ----- 电源 API -----
@app.route('/api/power/list_resources', methods=['GET'])
def power_list_resources():
    """获取可用 VISA 资源"""
    resources = power_controller.list_resources()
    return jsonify({"resources": resources})


@app.route('/api/power/connect', methods=['POST'])
def power_connect():
    """连接电源"""
    data = get_request_data()
    address = data.get('address')
    if state.power_connected and address and state.power_address == address:
        return jsonify({"success": True, "message": "电源已连接"})

    success, msg = power_controller.connect(address)
    if success:
        device_monitor.refresh_power_now()
    return jsonify({"success": success, "message": msg})


@app.route('/api/power/disconnect', methods=['POST'])
def power_disconnect():
    """断开电源"""
    power_controller.disconnect()
    state.power_connected = False
    state.power_address = None
    state.power_voltage = None
    state.power_current = None
    state.power_output = False
    device_monitor.request_refresh()
    return jsonify({"success": True})


@app.route('/api/power/set', methods=['POST'])
def power_set():
    """设置电源参数"""
    data = get_request_data()
    voltage = data.get('voltage')
    current = data.get('current')
    output = data.get('output')

    results = []

    if voltage is not None:
        success, msg = power_controller.set_voltage(voltage)
        results.append({"action": "voltage", "success": success, "message": msg})

    if current is not None:
        success, msg = power_controller.set_current(current)
        results.append({"action": "current", "success": success, "message": msg})

    if output is not None:
        success, msg = power_controller.set_output(output)
        results.append({"action": "output", "success": success, "message": msg})

    if any(item["success"] for item in results):
        device_monitor.request_refresh()
    return jsonify({"results": results})


@app.route('/api/power/measure', methods=['GET'])
def power_measure():
    """获取后台缓存的电源电压电流"""
    if state.power_connected and isinstance(state.power_voltage, (int, float)) and isinstance(state.power_current, (int, float)):
        return jsonify({
            "voltage": state.power_voltage,
            "current": state.power_current
        })
    return jsonify({"error": "未连接或测量失败"})


# ----- 示波器 API -----
@app.route('/api/scope/connect', methods=['POST'])
def scope_connect():
    """连接示波器"""
    data = get_request_data()
    serial = str(data.get('serial', state.scope_serial or '90Y701585')).strip()
    scope_controller._log("收到前端连接请求", serial_num=serial)

    if state.scope_expected_connected and state.scope_serial == serial:
        if scope_controller.ensure_connected(validate=True):
            scope_controller._log("前端连接请求命中已连接会话，跳过重连", serial_num=serial)
            device_monitor.refresh_scope_now()
            return jsonify({
                "success": True,
                "message": "示波器已连接",
                "locked": state.scope_remote_locked,
                "already_connected": True,
            })

    success, msg = scope_controller.connect(serial)
    if success:
        state.scope_serial = serial
        state.scope_expected_connected = True
        locked = False
        try:
            scope_controller.unlock_local()
        except Exception as e:
            locked = True
            msg = f"{msg}; 本地控制解锁失败: {e}"
        state.scope_remote_locked = locked
        device_monitor.refresh_scope_now()
        return jsonify({"success": True, "message": msg, "locked": locked})
    state.scope_connected = False
    state.scope_remote_locked = False
    return jsonify({"success": success, "message": msg, "locked": False})


@app.route('/api/scope/disconnect', methods=['POST'])
def scope_disconnect():
    """断开示波器"""
    scope_controller._log("收到前端断开请求")
    scope_controller.disconnect()
    state.scope_connected = False
    state.scope_expected_connected = False
    state.scope_remote_locked = False
    state.scope_channel_states = empty_scope_channel_states()
    state.scope_channel_values = empty_scope_channel_values()
    state.scope_mean_value = state.scope_channel_values
    state.scope_channels = []
    return jsonify({"success": True})


@app.route('/api/scope/unlock', methods=['POST'])
def scope_unlock():
    """解锁示波器本地控制（保持连接）"""
    try:
        if not scope_controller.ensure_connected(validate=True):
            return jsonify({"success": False, "message": "示波器未连接"})
        scope_controller.unlock_local()
        state.scope_remote_locked = False
        device_monitor.request_refresh()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/api/scope/lock', methods=['POST'])
def scope_lock():
    """锁定示波器为远程控制（保持连接）"""
    try:
        if not scope_controller.ensure_connected(validate=True):
            return jsonify({"success": False, "message": "示波器未连接"})
        scope_controller.lock_remote()
        state.scope_remote_locked = True
        device_monitor.request_refresh()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/api/scope/channel', methods=['POST'])
def scope_channel():
    """设置通道开关"""
    data = get_request_data()
    channel = data.get('channel')
    enable = data.get('enable')

    if channel is None or enable is None:
        return jsonify({"success": False, "message": "缺少参数"})

    try:
        channel = int(channel)
        if channel < 1 or channel > 4:
            return jsonify({"success": False, "message": "通道号无效"})
    except ValueError:
        return jsonify({"success": False, "message": "无效的通道号"})

    success, msg = scope_controller.set_channel(channel, enable)
    if success:
        state.scope_channel_states[f"ch{channel}"] = bool(enable)
        if not enable:
            state.scope_channel_values[f"ch{channel}"] = None
        state.scope_channels = [
            index for index in range(1, 5)
            if state.scope_channel_states.get(f"ch{index}")
        ]
        state.scope_mean_value = state.scope_channel_values
        device_monitor.request_refresh()
    return jsonify({"success": success, "message": msg})


@app.route('/api/scope/channel_state', methods=['GET'])
def scope_channel_state():
    """获取后台缓存的所有通道开关状态"""
    if not state.scope_connected:
        return jsonify({"error": "示波器未连接"})

    return jsonify({"channels": dict(state.scope_channel_states)})


@app.route('/api/scope/get_mean', methods=['GET'])
def scope_get_mean():
    """获取后台缓存的所有通道平均值"""
    if not state.scope_connected:
        return jsonify({"error": "示波器未连接"})

    return jsonify({"channels": dict(state.scope_channel_values)})


@app.route('/api/scope/copy_screenshot', methods=['POST'])
def scope_copy_screenshot():
    """截图保存到服务端，并返回给前端用于客户端复制"""
    success, msg, filepath = scope_controller.save_screenshot()
    if not success:
        status = 400 if msg == "示波器未连接" else 500
        return jsonify({"success": False, "message": msg}), status

    filename = os.path.basename(filepath)

    return jsonify({
        "success": True,
        "message": "截图已保存，正在复制到当前浏览器所在电脑的剪贴板",
        "filepath": filepath,
        "filename": filename,
        "download_url": f"/api/scope/screenshot/{filename}",
    })


@app.route('/api/scope/screenshot/<path:filename>', methods=['GET'])
def scope_screenshot_file(filename):
    """读取服务端保存的截图文件"""
    if not filename.lower().endswith(".png"):
        return jsonify({"success": False, "message": "仅支持 PNG 文件"}), 400

    screenshot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
    return send_from_directory(screenshot_dir, filename, mimetype="image/png", as_attachment=False)


@app.route('/api/scope/config', methods=['POST'])
def scope_config():
    """配置示波器参数"""
    data = get_request_data()
    if 'channels' in data:
        state.scope_channels = [int(ch) for ch in data['channels']]
    if 'refresh_interval' in data:
        state.scope_refresh_interval = int(data['refresh_interval'])
    if 'auto_refresh' in data:
        state.scope_auto_refresh = bool(data['auto_refresh'])
    if 'channel_aliases' in data:
        try:
            state.scope_channel_aliases = normalize_scope_channel_aliases(data['channel_aliases'])
        except ValueError as error:
            return jsonify({"success": False, "message": str(error)}), 400
    return jsonify({"success": True, "config": {
        "channels": state.scope_channels,
        "refresh_interval": state.scope_refresh_interval,
        "auto_refresh": state.scope_auto_refresh,
        "channel_aliases": state.scope_channel_aliases,
    }})


@app.route('/api/scope/state', methods=['GET'])
def scope_state():
    """获取示波器状态"""
    return jsonify({
        "serial": state.scope_serial,
        "channels": state.scope_channels,
        "refresh_interval": state.scope_refresh_interval,
        "mean_value": state.scope_mean_value,
        "channel_aliases": state.scope_channel_aliases,
    })


# ----- 设备状态 API -----
@app.route('/api/state', methods=['GET'])
def get_state():
    """获取所有设备状态"""
    return jsonify({
        "resistance": {
            "connected": state.resistance_connected,
            "port": state.resistance_port or res_controller.port,
            "value": state.resistance_value
        },
        "power": {
            "connected": state.power_connected,
            "address": state.power_address,
            "voltage": state.power_voltage,
            "current": state.power_current,
            "output": state.power_output
        },
        "scope": {
            "connected": state.scope_connected,
            "serial": state.scope_serial,
            "locked": state.scope_remote_locked,
            "channels": state.scope_channels,
            "channel_states": state.scope_channel_states,
            "channel_values": state.scope_channel_values,
            "channel_aliases": state.scope_channel_aliases,
            "refresh_interval": state.scope_refresh_interval,
            "auto_refresh": state.scope_auto_refresh
        }
    })


if __name__ == '__main__':
    # 创建 templates 目录（如果不存在）
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)

    debug_mode = os.getenv("FLASK_DEBUG", "0").strip().lower() in ("1", "true", "yes", "on")
    port = int(os.getenv("FLASK_PORT", "5000"))

    ssl_mode = os.getenv("FLASK_SSL_MODE", "off").strip().lower()
    ssl_cert = os.getenv("FLASK_SSL_CERT", "").strip()
    ssl_key = os.getenv("FLASK_SSL_KEY", "").strip()
    ssl_context = None

    if ssl_mode in ("1", "true", "yes", "on", "adhoc"):
        ssl_context = "adhoc"
    elif ssl_mode in ("files", "cert", "certificate"):
        if ssl_cert and ssl_key and os.path.exists(ssl_cert) and os.path.exists(ssl_key):
            ssl_context = (ssl_cert, ssl_key)
        else:
            print("[警告] FLASK_SSL_MODE=files 但证书或私钥无效，已回退 HTTP")

    print("=" * 50)
    print("控制面板启动中...")
    scheme = "https" if ssl_context else "http"
    print(f"请在浏览器打开: {scheme}://127.0.0.1:{port}")
    print("=" * 50)

    app.run(debug=debug_mode, host='0.0.0.0', port=port, ssl_context=ssl_context)
