#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
控制面板 Flask 应用
整合电阻控制、电源控制、示波器读取功能
"""

import os
from flask import Flask, render_template, request, jsonify

from device_runtime import (
    state,
    ntc_table,
    res_controller,
    power_controller,
    scope_controller,
    ResistanceDevice,
    build_res_device_status,
    format_resistance_display,
)

app = Flask(__name__)


def get_request_data():
    """安全读取 JSON 请求体，避免空 body 导致异常"""
    return request.get_json(silent=True) or {}
# ========== Flask 路由 ==========

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


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
    success, msg = res_controller.connect(port)
    if success:
        state.resistance_connected = True
    return jsonify({"success": success, "message": msg})


@app.route('/api/res/disconnect', methods=['POST'])
def res_disconnect():
    """断开串口"""
    res_controller.disconnect()
    state.resistance_connected = False
    state.resistance_port = None
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
    """批量读取设备当前电阻值（AT+RES.SP?）"""
    if not res_controller.connected:
        return jsonify({"success": False, "message": "串口未连接"}), 400

    result_devices = []
    for device in res_controller.devices_list:
        success, msg, value = res_controller.get_value(device.sn)
        if success:
            device.current_resistance = format_resistance_display(value)

        status = build_res_device_status(device)
        status["read_success"] = success
        if not success:
            status["read_message"] = msg
        result_devices.append(status)

    return jsonify({"success": True, "devices": result_devices})


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
        res_controller.devices[sn].current_resistance = f"{int(float(value))}Ω"
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
        res_controller.devices[sn].current_resistance = f"{resistance}Ω"
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
    success, msg = power_controller.connect(address)
    return jsonify({"success": success, "message": msg})


@app.route('/api/power/disconnect', methods=['POST'])
def power_disconnect():
    """断开电源"""
    power_controller.disconnect()
    state.power_address = None
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

    return jsonify({"results": results})


@app.route('/api/power/measure', methods=['GET'])
def power_measure():
    """测量电源电压电流"""
    result = power_controller.measure()
    if result:
        return jsonify(result)
    return jsonify({"error": "未连接或测量失败"})


# ----- 示波器 API -----
@app.route('/api/scope/connect', methods=['POST'])
def scope_connect():
    """连接示波器"""
    data = get_request_data()
    serial = data.get('serial', '90Y701585')
    success, msg = scope_controller.connect(serial)
    if success:
        state.scope_serial = serial
    return jsonify({"success": success, "message": msg})


@app.route('/api/scope/disconnect', methods=['POST'])
def scope_disconnect():
    """断开示波器"""
    scope_controller.disconnect()
    return jsonify({"success": True})


@app.route('/api/scope/unlock', methods=['POST'])
def scope_unlock():
    """解锁示波器本地控制（保持连接）"""
    try:
        scope_controller.unlock_local()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/api/scope/lock', methods=['POST'])
def scope_lock():
    """锁定示波器为远程控制（保持连接）"""
    try:
        scope_controller.lock_remote()
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
    return jsonify({"success": success, "message": msg})


@app.route('/api/scope/channel_state', methods=['GET'])
def scope_channel_state():
    """获取所有通道的开关状态"""
    if scope_controller.device_id is None:
        return jsonify({"error": "示波器未连接"})

    states = {}
    for ch in range(1, 5):
        state = scope_controller.get_channel_state(ch)
        states[f"ch{ch}"] = state

    return jsonify({"channels": states})


@app.route('/api/scope/get_mean', methods=['GET'])
def scope_get_mean():
    """获取所有通道的平均值"""
    # 返回所有4个通道的数据
    channels = [1, 2, 3, 4]
    results = scope_controller.get_all_means(channels)
    if results:
        return jsonify({"channels": results})
    return jsonify({"error": "读取失败"})


@app.route('/api/scope/copy_screenshot', methods=['POST'])
def scope_copy_screenshot():
    """截图保存到本地并复制到剪贴板"""
    success, msg, filepath = scope_controller.save_screenshot()
    if not success:
        status = 400 if msg == "示波器未连接" else 500
        return jsonify({"success": False, "message": msg}), status

    success, clip_msg = scope_controller.copy_image_to_clipboard(filepath)
    if not success:
        return jsonify({
            "success": False,
            "message": f"截图已保存，但复制失败: {clip_msg}",
            "filepath": filepath
        }), 500

    return jsonify({
        "success": True,
        "message": "截图已保存并复制到剪贴板",
        "filepath": filepath
    })


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
    return jsonify({"success": True, "config": {
        "channels": state.scope_channels,
        "refresh_interval": state.scope_refresh_interval,
        "auto_refresh": state.scope_auto_refresh
    }})


@app.route('/api/scope/state', methods=['GET'])
def scope_state():
    """获取示波器状态"""
    return jsonify({
        "serial": state.scope_serial,
        "channels": state.scope_channels,
        "refresh_interval": state.scope_refresh_interval,
        "mean_value": state.scope_mean_value
    })


# ----- 设备状态 API -----
@app.route('/api/state', methods=['GET'])
def get_state():
    """获取所有设备状态"""
    return jsonify({
        "resistance": {
            "connected": res_controller.connected,
            "port": res_controller.port,
            "value": state.resistance_value
        },
        "power": {
            "connected": power_controller.ps is not None,
            "address": state.power_address,
            "voltage": state.power_voltage,
            "current": state.power_current,
            "output": state.power_output
        },
        "scope": {
            "connected": scope_controller.device_id is not None,
            "serial": state.scope_serial,
            "channels": state.scope_channels,
            "refresh_interval": state.scope_refresh_interval,
            "auto_refresh": state.scope_auto_refresh
        }
    })


if __name__ == '__main__':
    # 创建 templates 目录（如果不存在）
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)

    print("=" * 50)
    print("控制面板启动中...")
    print("请在浏览器打开: http://127.0.0.1:5000")
    print("=" * 50)

    app.run(debug=True, host='0.0.0.0', port=5000)
