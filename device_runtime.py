#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
设备运行时对象与控制器定义
"""

import sys
import os
import json
import queue
import re
import threading
import time
import subprocess

# 添加 scripts 目录到路径
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts')
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

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
        self.devices_list = []  # 按顺序保存设备
        self.config_file = os.path.join(SCRIPT_DIR, 'res_ctrl', 'devices_config.json')

        # 串口操作统一进入单独 worker 线程，避免并发请求直接争用串口
        self._serial_task_queue = queue.Queue()
        self._serial_worker = threading.Thread(
            target=self._serial_worker_loop,
            name="res-serial-worker",
            daemon=True
        )
        self._serial_worker.start()

        # 加载保存的设备
        self.load_devices()

    def load_devices(self):
        """从 JSON 文件加载设备配置"""
        if not os.path.exists(self.config_file):
            return

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                saved_devices = json.load(f)
            # 按顺序加载
            for item in saved_devices:
                sn = item.get('sn')
                name = item.get('name', '未命名')
                device = ResistanceDevice(sn, name)
                self.devices[sn] = device
                self.devices_list.append(device)
        except Exception as e:
            print(f"加载设备配置失败: {e}")

    def save_devices(self):
        """保存设备配置到 JSON 文件"""
        try:
            # 按顺序保存为列表
            devices_data = []
            for device in self.devices_list:
                devices_data.append({'sn': device.sn, 'name': device.name})
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

            def _do_connect():
                if self.tester and self.tester.is_open:
                    self.tester.close()
                self.tester = serial.Serial(port, baudrate, timeout=1)
                self.port = port
                self.baudrate = baudrate
                self.connected = True
                state.resistance_port = port
                return True, "连接成功"

            return self._run_serial_task(_do_connect, timeout=5.0)
        except TimeoutError:
            return False, "连接串口超时"
        except Exception as e:
            return False, str(e)

    def disconnect(self):
        """断开串口"""
        def _do_disconnect():
            if self.tester and self.tester.is_open:
                self.tester.close()
            self.tester = None
            self.connected = False
            # 重置所有设备状态
            for device in self.devices.values():
                device.connected = False
            return True

        try:
            self._run_serial_task(_do_disconnect, timeout=3.0)
        except Exception:
            pass

    def _format_command(self, cmd, sn=None):
        """格式化指令，支持 RS485 SN 码"""
        if sn:
            if cmd.startswith("AT+"):
                base = cmd.replace("\r\n", "").replace("\n", "")
                return f"AT+{base[3:]}@{sn}\r\n"
        return cmd

    def _serial_worker_loop(self):
        """串口 worker 线程主循环"""
        while True:
            task = self._serial_task_queue.get()
            if task is None:
                self._serial_task_queue.task_done()
                break

            try:
                task["result"] = task["func"]()
            except Exception as e:
                task["error"] = e
            finally:
                task["done"].set()
                self._serial_task_queue.task_done()

    def _run_serial_task(self, func, timeout=5.0):
        """提交串口任务并等待结果"""
        if threading.current_thread() is self._serial_worker:
            return func()

        task = {
            "func": func,
            "done": threading.Event(),
            "result": None,
            "error": None
        }
        self._serial_task_queue.put(task)
        if not task["done"].wait(timeout):
            raise TimeoutError("串口操作超时")

        if task["error"] is not None:
            raise task["error"]

        return task["result"]

    def _send_command_raw(self, cmd, sn=None, wait_secs=0.3):
        """在串口 worker 线程内执行真实发送"""
        if not self.tester or not self.tester.is_open:
            return False, "串口未连接"

        formatted_cmd = self._format_command(cmd, sn)
        self.tester.write(formatted_cmd.encode())
        time.sleep(wait_secs)
        response = self.tester.read_all().decode(errors='ignore')
        return True, response.strip()

    def send_command(self, cmd, sn=None, wait_secs=0.3):
        """发送 AT 指令，可选指定 SN 码"""
        try:
            timeout = max(2.0, wait_secs + 2.0)
            return self._run_serial_task(
                lambda: self._send_command_raw(cmd, sn, wait_secs=wait_secs),
                timeout=timeout
            )
        except TimeoutError:
            return False, "串口操作超时"
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
        try:
            value = float(value)
            if value < 0 or value > 7000000:
                return False, "电阻值超出范围 (0-7MΩ)"

            def _do_set_value():
                # 同一个 worker 任务内完成，防止被其他命令插队
                ok, msg = self._send_command_raw("AT+RES.CONNECT", sn, wait_secs=0.2)
                if not ok:
                    return False, msg
                return self._send_command_raw(f"AT+RES.SP={value}", sn, wait_secs=0.3)

            result, msg = self._run_serial_task(_do_set_value, timeout=4.5)
            if result:
                state.resistance_value = value
                # 更新设备状态
                if sn and sn in self.devices:
                    self.devices[sn].current_resistance = f"{int(value)}Ω"
                    self.devices[sn].connected = True
                    # 更新列表中的设备
                    for d in self.devices_list:
                        if d.sn == sn:
                            d.current_resistance = f"{int(value)}Ω"
                            d.connected = True
                            break
            return result, msg
        except TimeoutError:
            return False, "设置电阻超时"
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

    def _parse_resistance_from_response(self, response):
        """从 AT+RES.SP? 响应中解析电阻值"""
        if not response:
            return None

        text = str(response).replace("\r", "\n")
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        # 优先匹配明确字段（如 RES.SP=1234）
        explicit_patterns = [
            r"RES\.SP\??\s*[:=]\s*([+-]?\d+(?:\.\d+)?)",
            r"AT\+RES\.SP\??\s*[:=]\s*([+-]?\d+(?:\.\d+)?)",
        ]
        for line in lines:
            upper_line = line.upper()
            for pattern in explicit_patterns:
                match = re.search(pattern, upper_line, flags=re.IGNORECASE)
                if match:
                    try:
                        value = float(match.group(1))
                        if 0 <= value <= 7000000:
                            return value
                    except ValueError:
                        continue

        # 其次匹配整行纯数值（可带单位）
        for line in lines:
            match = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*(?:Ω|OHM)?$", line, flags=re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1))
                    if 0 <= value <= 7000000:
                        return value
                except ValueError:
                    continue

        return None

    def get_value(self, sn=None):
        """查询电阻当前设定值（AT+RES.SP?）"""
        success, response = self.send_command("AT+RES.SP?", sn, wait_secs=0.3)
        if not success:
            return False, response, None

        value = self._parse_resistance_from_response(response)
        if value is None:
            return False, f"无法解析返回值: {response}", None

        return True, "查询成功", value


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

    def get_temperature(self, resistance):
        """根据电阻值反查温度（线性插值）"""
        if not self.loaded:
            self.load()

        try:
            resistance = float(resistance)
        except (TypeError, ValueError):
            return None

        temps = sorted(self.table.keys())
        if not temps:
            return None

        points = [(t, float(self.table[t])) for t in temps]
        resistances = [r for _, r in points]
        min_r = min(resistances)
        max_r = max(resistances)

        # 超出 NTC 表的电阻范围，直接视为无效
        if resistance < min_r or resistance > max_r:
            return None

        # 精确匹配
        for t, r in points:
            if resistance == r:
                if -40 <= t <= 150:
                    return float(t)
                return None

        # 线性插值（兼容电阻随温度递减的区间）
        temp = None
        for i in range(len(points) - 1):
            t1, r1 = points[i]
            t2, r2 = points[i + 1]
            low = min(r1, r2)
            high = max(r1, r2)
            if low <= resistance <= high and r1 != r2:
                ratio = (resistance - r1) / (r2 - r1)
                temp = t1 + (t2 - t1) * ratio
                break

        if temp is None:
            return None

        if temp < -40 or temp > 150:
            return None

        return round(temp, 1)


ntc_table = NTCTable()


def parse_resistance_ohm(value):
    """将 '1000Ω' / 数值 解析为欧姆浮点数"""
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if not isinstance(value, str):
        return None

    text = value.strip().upper().replace("OHM", "").replace("Ω", "").strip()
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def format_resistance_display(value):
    """格式化电阻显示文本"""
    ohm = parse_resistance_ohm(value)
    if ohm is None:
        return "--"

    if float(ohm).is_integer():
        return f"{int(ohm)}Ω"

    return f"{ohm:.3f}".rstrip("0").rstrip(".") + "Ω"


def format_temperature_display(temp):
    """格式化温度显示文本"""
    if temp is None:
        return "--"

    temp = float(temp)
    if temp.is_integer():
        return f"{int(temp)}℃"
    return f"{temp:.1f}℃"


def build_res_device_status(device):
    """构建设备展示数据（含温度反查）"""
    resistance_ohm = parse_resistance_ohm(device.current_resistance)
    temperature = None
    if resistance_ohm is not None:
        temperature = ntc_table.get_temperature(resistance_ohm)

    return {
        "sn": device.sn,
        "name": device.name,
        "current_resistance": device.current_resistance,
        "current_temperature": temperature,
        "current_temperature_display": format_temperature_display(temperature),
        "connected": device.connected
    }


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
        self.io_lock = threading.Lock()

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
            with self.io_lock:
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
            with self.io_lock:
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
            with self.io_lock:
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

    def get_screenshot(self):
        """获取示波器 PNG 截图数据"""
        if self.device_id is None:
            return False, "示波器未连接", None

        with self.io_lock:
            try:
                # 截图传输较慢，临时延长超时
                self.tmctl.SetTimeout(self.device_id, 300)
                self.tmctl.Send(self.device_id, "*CLS")

                # 暂停采集并等待完成
                self.tmctl.Send(self.device_id, ":STOP")
                self.tmctl.Send(self.device_id, "*OPC?")
                self.tmctl.Receive(self.device_id, 1000)

                # 触发 PNG 截图输出
                self.tmctl.Send(self.device_id, ":IMAGe:FORMat PNG")
                self.tmctl.Send(self.device_id, "*OPC?")
                self.tmctl.Receive(self.device_id, 1000)
                self.tmctl.Send(self.device_id, ":IMAGe:SEND?")

                # 读取块头和二进制图像
                ret, total_len = self.tmctl.ReceiveBlockHeader(self.device_id)
                if ret != 0:
                    return False, f"获取截图头失败 (Ret={ret})", None
                if total_len <= 0:
                    return False, "截图数据长度为 0", None

                block_size = 4096
                loop_count = int(total_len / block_size)
                remainder = total_len % block_size
                image_data = bytearray()

                buf = bytearray(block_size)
                for i in range(loop_count):
                    ret, rlen, end = self.tmctl.ReceiveBlockData(self.device_id, buf, block_size)
                    if ret != 0:
                        return False, f"接收截图数据块失败 (块={i}, Ret={ret})", None
                    if rlen > 0:
                        image_data.extend(buf[:rlen])

                if remainder > 0:
                    req_size = remainder + 16
                    buf_rem = bytearray(req_size)
                    ret, rlen, end = self.tmctl.ReceiveBlockData(self.device_id, buf_rem, req_size)
                    if ret != 0:
                        return False, f"接收截图剩余数据失败 (Ret={ret})", None

                    bytes_to_write = min(rlen, total_len - len(image_data))
                    if bytes_to_write > 0:
                        image_data.extend(buf_rem[:bytes_to_write])

                if len(image_data) < total_len:
                    return False, f"截图数据不完整 ({len(image_data)}/{total_len})", None

                return True, "截图成功", bytes(image_data[:total_len])
            except Exception as e:
                return False, str(e), None
            finally:
                # 无论成功失败都尽量恢复采集和常规超时
                try:
                    self.tmctl.Send(self.device_id, ":STARt")
                except Exception:
                    pass
                try:
                    self.tmctl.SetTimeout(self.device_id, 30)
                except Exception:
                    pass

    def save_screenshot(self):
        """截图并保存到本地文件"""
        success, msg, image_data = self.get_screenshot()
        if not success:
            return False, msg, None

        try:
            screenshot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
            os.makedirs(screenshot_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(screenshot_dir, f"DLM_{timestamp}.png")
            with open(filepath, 'wb') as f:
                f.write(image_data)
            return True, "截图保存成功", filepath
        except Exception as e:
            return False, f"截图保存失败: {e}", None

    def copy_image_to_clipboard(self, filepath):
        """将本地图片复制到 Windows 剪贴板"""
        if not filepath or not os.path.exists(filepath):
            return False, "截图文件不存在"

        path_ps = os.path.abspath(filepath).replace("'", "''")
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            f"$img = [System.Drawing.Image]::FromFile('{path_ps}'); "
            "try { [System.Windows.Forms.Clipboard]::SetImage($img) } "
            "finally { $img.Dispose() }"
        )

        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=20
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                return False, err or f"复制失败 (返回码 {result.returncode})"
            return True, "已复制到剪贴板"
        except Exception as e:
            return False, str(e)


scope_controller = ScopeController()


