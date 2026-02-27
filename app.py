#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
控制面板 Flask 应用
整合电阻控制、电源控制、示波器读取功能
"""

import sys
import os
import json
import threading
import time
from flask import Flask, render_template, request, jsonify

# 添加 scripts 目录到路径
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts')
sys.path.insert(0, SCRIPT_DIR)

app = Flask(__name__)

# ========== 全局状态 ==========
class DeviceState:
    """设备状态管理"""
    def __init__(self):
        self.resistance_connected = False
        self.resistance_port = None
        self.resistance_value = None

        self.power_address = None
        self.power_voltage = None
        self.power_current = None
        self.power_output = False

        self.scope_serial = "90Y701585"
        self.scope_channels = []  # 用户选择的通道列表
        self.scope_refresh_interval = 1000  # ms
        self.scope_auto_refresh = False  # 自动刷新开关
        self.scope_mean_value = None

state = DeviceState()

# ========== 电阻控制模块 ==========
class ResistanceDevice:
    """单个电阻设备"""
    def __init__(self, sn, name="未命名"):
        self.sn = sn
        self.name = name
        self.current_resistance = None
        self.connected = False


class ResistanceController:
    """电阻控制器 - 支持多设备 RS485"""
    def __init__(self):
        self.tester = None
        self.port = None
        self.baudrate = 9600
        self.connected = False
        self.devices = {}  # {sn: ResistanceDevice}
        self.config_file = os.path.join(SCRIPT_DIR, 'res_ctrl', 'devices_config.json')

        # 加载保存的设备
        self.load_devices()

    def load_devices(self):
        """从 JSON 文件加载设备配置"""
        if not os.path.exists(self.config_file):
            return

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                saved_devices = json.load(f)
            for sn, info in saved_devices.items():
                device = ResistanceDevice(sn, info.get('name', '未命名'))
                self.devices[sn] = device
        except Exception as e:
            print(f"加载设备配置失败: {e}")

    def save_devices(self):
        """保存设备配置到 JSON 文件"""
        try:
            devices_data = {}
            for sn, device in self.devices.items():
                devices_data[sn] = {'name': device.name}
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(devices_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存设备配置失败: {e}")

    def list_ports(self):
        """列出可用串口"""
        from serial.tools import list_ports
        ports = list_ports.comports()
        return [p.device for p in ports]

    def connect(self, port, baudrate=9600):
        """连接串口"""
        try:
            import serial
            self.tester = serial.Serial(port, baudrate, timeout=1)
            self.port = port
            self.baudrate = baudrate
            self.connected = True
            state.resistance_port = port
            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    def disconnect(self):
        """断开串口"""
        if self.tester and self.tester.is_open:
            self.tester.close()
        self.connected = False
        # 重置所有设备状态
        for device in self.devices.values():
            device.connected = False

    def _format_command(self, cmd, sn=None):
        """格式化指令，支持 RS485 SN 码"""
        if sn:
            if cmd.startswith("AT+"):
                base = cmd.replace("\r\n", "").replace("\n", "")
                return f"AT+{base[3:]}@{sn}\r\n"
        return cmd

    def send_command(self, cmd, sn=None):
        """发送 AT 指令，可选指定 SN 码"""
        if not self.tester or not self.tester.is_open:
            return False, "串口未连接"

        try:
            formatted_cmd = self._format_command(cmd, sn)
            self.tester.write(formatted_cmd.encode())
            time.sleep(0.3)
            response = self.tester.read_all().decode(errors='ignore')
            return True, response.strip()
        except Exception as e:
            return False, str(e)

    def set_connect(self, sn=None):
        """连接电阻"""
        return self.send_command("AT+RES.CONNECT", sn)

    def set_disconnect(self, sn=None):
        """断开电阻"""
        return self.send_command("AT+RES.DISCONNECT", sn)

    def set_short(self, sn=None):
        """短路电阻"""
        return self.send_command("AT+RES.SHORT", sn)

    def set_unshort(self, sn=None):
        """取消短路"""
        return self.send_command("AT+RES.UNSHORTEN", sn)

    def set_value(self, value, sn=None):
        """设置自定义电阻值"""
        if not self.tester or not self.tester.is_open:
            return False, "串口未连接"

        try:
            value = float(value)
            if value < 0 or value > 7000000:
                return False, "电阻值超出范围 (0-7MΩ)"

            # 先连接
            self.send_command("AT+RES.CONNECT", sn)
            time.sleep(0.2)
            # 设置值
            result, msg = self.send_command(f"AT+RES.SP={value}", sn)
            if result:
                state.resistance_value = value
                # 更新设备状态
                if sn and sn in self.devices:
                    self.devices[sn].current_resistance = f"{int(value)}Ω"
                    self.devices[sn].connected = True
            return result, msg
        except ValueError:
            return False, "无效的电阻值"

    def set_by_temperature(self, temperature, sn=None):
        """通过温度设置电阻值"""
        # 根据温度查找电阻值
        resistance = ntc_table.get_resistance(temperature)
        if resistance is None:
            return False, "无法根据温度查找电阻值"

        # 设置电阻值
        return self.set_value(resistance, sn)


res_controller = ResistanceController()


# ========== NTC 电阻表 ==========
class NTCTable:
    """NTC 电阻表"""
    def __init__(self):
        self.table = {}  # temperature -> resistance
        self.loaded = False

    def load(self, filepath=None):
        """加载 NTC 电阻表"""
        if filepath is None:
            filepath = os.path.join(SCRIPT_DIR, 'res_ctrl', 'ntc_res.txt')

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(';'):
                        continue

                    # 解析格式: 电阻值 ;温度
                    parts = line.split(';')
                    if len(parts) == 2:
                        try:
                            resistance = int(parts[0].strip())
                            temp_str = parts[1].strip()
                            # 解析温度，如 -40C, 0C, 25C
                            temp = int(temp_str.replace('C', '').replace('c', ''))
                            self.table[temp] = resistance
                        except ValueError:
                            continue
            self.loaded = True
            return True, f"加载成功，共 {len(self.table)} 条记录"
        except Exception as e:
            return False, str(e)

    def get_resistance(self, temperature):
        """根据温度获取电阻值"""
        if not self.loaded:
            self.load()

        # 精确匹配
        if temperature in self.table:
            return self.table[temperature]

        # 线性插值
        temps = sorted(self.table.keys())
        if not temps:
            return None

        if temperature < temps[0]:
            return self.table[temps[0]]
        if temperature > temps[-1]:
            return self.table[temps[-1]]

        # 找到相邻温度进行插值
        for i in range(len(temps) - 1):
            if temps[i] <= temperature <= temps[i + 1]:
                t1, t2 = temps[i], temps[i + 1]
                r1, r2 = self.table[t1], self.table[t2]
                # 线性插值
                ratio = (temperature - t1) / (t2 - t1)
                return int(r1 + (r2 - r1) * ratio)

        return None


ntc_table = NTCTable()


# ========== 电源控制模块 ==========
class PowerController:
    """电源控制器"""
    def __init__(self):
        self.ps = None
        self.address = None

    def list_resources(self):
        """列出可用 VISA 资源"""
        try:
            import pyvisa
            rm = pyvisa.ResourceManager()
            resources = rm.list_resources()
            return resources
        except Exception as e:
            return []

    def connect(self, address):
        """连接电源"""
        try:
            from power_ctrl.power_supply_control import PowerSupplyController

            self.ps = PowerSupplyController(address, verbose=False)
            self.ps.connect()
            self.address = address
            state.power_address = address
            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    def disconnect(self):
        """断开电源"""
        if self.ps:
            try:
                self.ps.close()
            except:
                pass
            self.ps = None

    def set_voltage(self, voltage):
        """设置电压"""
        if not self.ps:
            return False, "电源未连接"
        try:
            self.ps.set_voltage(float(voltage))
            state.power_voltage = float(voltage)
            return True, "设置成功"
        except Exception as e:
            return False, str(e)

    def set_current(self, current):
        """设置电流"""
        if not self.ps:
            return False, "电源未连接"
        try:
            self.ps.set_current(float(current))
            state.power_current = float(current)
            return True, "设置成功"
        except Exception as e:
            return False, str(e)

    def set_output(self, on):
        """设置输出开关"""
        if not self.ps:
            return False, "电源未连接"
        try:
            self.ps.set_output(bool(on))
            state.power_output = bool(on)
            return True, "设置成功"
        except Exception as e:
            return False, str(e)

    def measure(self):
        """测量电压电流"""
        if not self.ps:
            return None
        try:
            v = self.ps.measure_voltage()
            c = self.ps.measure_current()
            return {"voltage": v, "current": c}
        except:
            return None


power_controller = PowerController()


# ========== 示波器控制模块 ==========
class ScopeController:
    """示波器控制器"""
    def __init__(self):
        self.tmctl = None
        self.device_id = None

    def connect(self, serial_num="90Y701585"):
        """连接示波器"""
        try:
            # 添加 yokogawa 目录到路径（需要 DLL 文件在同一目录）
            yokogawa_dir = os.path.join(SCRIPT_DIR, 'yokogawa')
            if yokogawa_dir not in sys.path:
                sys.path.insert(0, yokogawa_dir)

            from tmctl_lib import tmctlLib

            self.tmctl = tmctlLib.TMCTL()

            # 编码序列号
            ret, encode = self.tmctl.EncodeSerialNumber(128, serial_num)
            if ret != 0:
                return False, "序列号编码失败"

            ret, self.device_id = self.tmctl.Initialize(tmctlLib.TM_CTL_USBTMC3, encode)
            if ret != 0:
                return False, f"连接失败 (Error Code: {ret})"

            # 基础设置
            self.tmctl.SetTerm(self.device_id, 2, 1)
            self.tmctl.SetRen(self.device_id, 1)
            self.tmctl.SetTimeout(self.device_id, 30)
            self.tmctl.DeviceClear(self.device_id)

            # 测量初始化（只需要在连接时设置一次）
            self.tmctl.Send(self.device_id, ":COMMunicate:HEADer OFF")
            for ch in range(1, 5):  # 4个通道都开启平均值测量
                self.tmctl.Send(self.device_id, f":MEASure:CHANnel{ch}:AVERage:STATe ON")
            self.tmctl.Send(self.device_id, ":MEASure:MODE ON")

            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    def disconnect(self):
        """断开示波器"""
        if self.device_id is not None and self.device_id >= 0:
            try:
                self.tmctl.SetRen(self.device_id, 0)
                self.tmctl.Finish(self.device_id)
            except:
                pass
            self.device_id = None

    def unlock_local(self):
        """解锁示波器本地控制（保持连接）"""
        if self.device_id is not None and self.device_id >= 0:
            self.tmctl.SetRen(self.device_id, 0)

    def lock_remote(self):
        """锁定示波器为远程控制（保持连接）"""
        if self.device_id is not None and self.device_id >= 0:
            self.tmctl.SetRen(self.device_id, 1)

    def set_channel(self, channel, enable):
        """设置通道开关"""
        if self.device_id is None:
            return False, "示波器未连接"

        try:
            cmd = f":CHANnel{channel}:DISPlay {'ON' if enable else 'OFF'}"
            self.tmctl.Send(self.device_id, cmd)
            return True, "设置成功"
        except Exception as e:
            return False, str(e)

    def get_channel_state(self, channel):
        """获取通道开关状态"""
        if self.device_id is None:
            return None

        try:
            cmd = f":CHANnel{channel}:DISPlay?"
            self.tmctl.Send(self.device_id, cmd)
            ret, buf, length = self.tmctl.Receive(self.device_id, 1000)
            buf_str = buf.strip().upper()
            return buf_str in ['1', 'ON']
        except Exception as e:
            return None

    def get_mean(self, channel=1):
        """获取通道平均值（不暂停示波器）"""
        if self.device_id is None:
            return None

        try:
            # 查询
            cmd = f":MEASure:CHANnel{channel}:AVERage:VALue?"
            self.tmctl.Send(self.device_id, cmd)
            ret, buf, length = self.tmctl.Receive(self.device_id, 1000)

            try:
                # 清理响应字符串（去除换行符、空格等）
                buf_str = buf.strip()
                # 检查是否是 NAN
                if buf_str.upper() == 'NAN':
                    return None
                val = float(buf_str) * 1000.0  # 转换为毫伏/毫安
                return val
            except ValueError:
                return None
        except Exception as e:
            print(f"示波器读取错误: {e}")
            return None

    def get_all_means(self, channels=[1, 2, 3, 4]):
        """获取指定通道的平均值，每个通道独立处理错误"""
        results = {}
        for ch in channels:
            try:
                val = self.get_mean(ch)
                results[f"ch{ch}"] = val
            except Exception as e:
                # 每个通道独立处理错误，不影响其他通道
                print(f"读取 CH{ch} 失败: {e}")
                results[f"ch{ch}"] = None
        return results


scope_controller = ScopeController()


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
    data = request.json
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
    data = request.json
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
    data = request.json
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
    data = request.json
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
    for sn, device in res_controller.devices.items():
        devices.append({
            "sn": sn,
            "name": device.name,
            "current_resistance": device.current_resistance,
            "connected": device.connected
        })
    return jsonify({"devices": devices})


@app.route('/api/res/devices', methods=['POST'])
def res_add_device():
    """添加设备"""
    data = request.json
    name = data.get('name', '未命名')
    sn = data.get('sn')

    if not sn:
        return jsonify({"success": False, "message": "请提供 SN 码"})

    if sn in res_controller.devices:
        return jsonify({"success": False, "message": f"设备 {sn} 已存在"})

    # 创建设备
    device = ResistanceDevice(sn, name)
    res_controller.devices[sn] = device
    res_controller.save_devices()

    return jsonify({"success": True, "sn": sn, "name": name})


@app.route('/api/res/devices/<sn>', methods=['DELETE'])
def res_delete_device(sn):
    """删除设备"""
    if sn not in res_controller.devices:
        return jsonify({"success": False, "message": f"设备 {sn} 不存在"})

    name = res_controller.devices[sn].name
    del res_controller.devices[sn]
    res_controller.save_devices()

    return jsonify({"success": True, "message": f"已删除设备 {name} ({sn})"})


@app.route('/api/res/devices/<sn>', methods=['PUT'])
def res_rename_device(sn):
    """重命名设备"""
    data = request.json
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
    data = request.json
    sn = data.get('sn')
    value = data.get('value')

    if not sn:
        return jsonify({"success": False, "message": "请提供 SN 码"})

    if sn not in res_controller.devices:
        return jsonify({"success": False, "message": f"设备 {sn} 不存在"})

    success, msg = res_controller.set_value(value, sn)

    if success and sn in res_controller.devices:
        res_controller.devices[sn].current_resistance = f"{int(float(value))}Ω"

    return jsonify({"success": success, "message": msg})


@app.route('/api/res/device_temp', methods=['POST'])
def res_set_device_temp():
    """通过温度设置指定设备的电阻值"""
    data = request.json
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
    data = request.json
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
    data = request.json
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
    data = request.json
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
    data = request.json
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


@app.route('/api/scope/config', methods=['POST'])
def scope_config():
    """配置示波器参数"""
    data = request.json
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
