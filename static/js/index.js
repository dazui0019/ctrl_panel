let scopeRefreshTimer = null;
let powerRefreshTimer = null;
let resValueRefreshTimer = null;
let resValueRefreshInProgress = false;
let resValueAutoRefreshEnabled = false;
let scopeConnected = false;
let scopeChannelStates = {1: false, 2: false, 3: false, 4: false};  // 通道开关状态
let powerConnected = false;
let resSerialConnected = false;
let devices = [];  // 设备列表
let selectedDevices = new Set();  // 选中的设备
let contextMenuSN = null;  // 右键点击的设备SN

function showToast(message, type = 'info', duration = 2600) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    requestAnimationFrame(() => {
        toast.classList.add('show');
    });

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 220);
    }, duration);
}

// 初始化
window.onload = async function() {
    // 先获取设备状态，再加载设备列表
    await updateDeviceStates();

    await Promise.all([
        resRefreshPorts(),
        powerRefreshResources()
    ]);

    // 如果串口已连接，确保下拉框显示正确的值
    if (resSerialConnected && state.resistance_port) {
        document.getElementById('res-port').value = state.resistance_port;
    }

    // 如果电源已连接，确保下拉框显示正确的值
    if (powerConnected && state.power_address) {
        document.getElementById('power-address').value = state.power_address;
    }

    // 如果示波器已连接，确保输入框显示正确的值
    if (scopeConnected && state.scope_serial) {
        document.getElementById('scope-serial').value = state.scope_serial;
    }

    // 点击其他地方关闭右键菜单
    document.addEventListener('click', function(e) {
        const contextMenu = document.getElementById('context-menu');
        if (!contextMenu.contains(e.target)) {
            contextMenu.style.display = 'none';
        }
    });
};

// 保存当前连接的设备信息
let state = {
    resistance_port: null,
    power_address: null,
    scope_serial: null
};

// 更新设备连接状态
async function updateDeviceStates() {
    try {
        const res = await fetch('/api/state');
        const data = await res.json();

        // 保存端口号到全局状态
        state.resistance_port = data.resistance.port;

        // 电阻（串口连接）
        if (data.resistance.connected) {
            resSerialConnected = true;
            document.getElementById('res-port').value = data.resistance.port || '';
            document.getElementById('res-port').disabled = true;
            document.getElementById('btn-res-serial-connect').textContent = '断开';
            document.getElementById('res-title-status').textContent = '串口已连接';
            // 加载设备列表
            await resLoadDevices();
            startResValueAutoRefresh();
        }

        // 电源
        if (data.power.connected) {
            powerConnected = true;
            state.power_address = data.power.address;
            document.getElementById('power-address').value = data.power.address || '';
            document.getElementById('power-address').disabled = true;
            document.getElementById('btn-power-connect').textContent = '断开';
            document.getElementById('power-title-status').textContent = '已连接';
            startPowerAutoRefresh();
        }

        // 示波器
        if (data.scope.connected) {
            scopeConnected = true;
            state.scope_serial = data.scope.serial;
            document.getElementById('scope-serial').value = data.scope.serial || '';
            document.getElementById('scope-serial').disabled = true;
            document.getElementById('btn-scope-connect').textContent = '断开';
            document.getElementById('scope-title-status').textContent = '已连接';
            // 显示锁定按钮
            document.getElementById('btn-scope-lock').style.display = 'inline-block';
            document.getElementById('btn-scope-copy').style.display = 'inline-block';
            document.getElementById('btn-scope-copy').disabled = false;
            // 同步通道状态
            scopeSyncChannelState();
        }

        if (data.scope.refresh_interval) {
            document.getElementById('scope-interval').value = data.scope.refresh_interval;
        }
        // 默认开启自动刷新（如果示波器已连接）
        if (scopeConnected) {
            startAutoRefresh();
        }
    } catch (e) {
        console.error('获取设备状态失败', e);
    }
}

// ===== 电阻控制 (多设备RS485) =====
async function resRefreshPorts() {
    try {
        const res = await fetch('/api/res/list_ports');
        const data = await res.json();
        const select = document.getElementById('res-port');
        select.innerHTML = '<option value="">请选择串口...</option>';
        data.ports.forEach(port => {
            select.innerHTML += `<option value="${port}">${port}</option>`;
        });
    } catch (e) {
        console.error('获取串口列表失败', e);
    }
}

async function resToggleSerial() {
    if (resSerialConnected) {
        await resSerialDisconnect();
    } else {
        await resSerialConnect();
    }
}

async function resSerialConnect() {
    const port = document.getElementById('res-port').value;
    if (!port) {
        return;
    }

    try {
        const res = await fetch('/api/res/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({port: port})
        });
        const data = await res.json();
        if (data.success) {
            resSerialConnected = true;
            state.resistance_port = port;
            document.getElementById('res-title-status').textContent = '串口已连接';
            document.getElementById('btn-res-serial-connect').textContent = '断开';
            document.getElementById('res-port').disabled = true;
            // 加载设备列表
            await resLoadDevices();
            startResValueAutoRefresh();
        } else {
            alert('连接失败: ' + data.message);
        }
    } catch (e) {
        console.error('连接失败', e);
    }
}

async function resSerialDisconnect() {
    try {
        const res = await fetch('/api/res/disconnect', {
            method: 'POST'
        });
        const data = await res.json();
        if (data.success) {
            resSerialConnected = false;
            state.resistance_port = null;
            document.getElementById('res-title-status').textContent = '';
            document.getElementById('btn-res-serial-connect').textContent = '连接';
            document.getElementById('res-port').disabled = false;
            stopResValueAutoRefresh();
            // 清空设备列表
            devices = [];
            renderDevices();
        }
    } catch (e) {
        console.error('断开失败', e);
    }
}

function resPortChanged() {
    const port = document.getElementById('res-port').value;
    document.getElementById('btn-res-serial-connect').disabled = !port || resSerialConnected;
}

// 加载设备列表
async function resLoadDevices() {
    if (!resSerialConnected) {
        document.getElementById('device-loading').textContent = '请先连接串口';
        return;
    }

    try {
        const res = await fetch('/api/res/devices');
        const data = await res.json();
        const newDevices = data.devices || [];

        // 保持当前顺序，只更新数据
        if (devices.length > 0 && newDevices.length > 0) {
            // 按当前顺序重新排列新数据
            const orderedDevices = [];
            for (const sn of devices.map(d => d.sn)) {
                const found = newDevices.find(d => d.sn === sn);
                if (found) orderedDevices.push(found);
            }
            // 添加新设备（可能新增的）
            for (const d of newDevices) {
                if (!orderedDevices.find(x => x.sn === d.sn)) {
                    orderedDevices.push(d);
                }
            }
            devices = orderedDevices;
        } else {
            devices = newDevices;
        }
        renderDevices();
    } catch (e) {
        console.error('加载设备列表失败', e);
    }
}

async function resRefreshDeviceValues() {
    if (!resValueAutoRefreshEnabled || !resSerialConnected) {
        return;
    }
    if (resValueRefreshInProgress) {
        scheduleResValueRefresh(300);
        return;
    }
    if (devices.length === 0) {
        scheduleResValueRefresh(1000);
        return;
    }

    resValueRefreshInProgress = true;
    const beginAt = performance.now();
    let nextDelayMs = 1000;

    try {
        const res = await fetch('/api/res/device_values');
        const data = await res.json();
        if (!res.ok || !data.success || !Array.isArray(data.devices)) {
            nextDelayMs = 1500;
            return;
        }

        const latestBySn = new Map(data.devices.map(d => [d.sn, d]));
        devices = devices.map(d => latestBySn.has(d.sn) ? {...d, ...latestBySn.get(d.sn)} : d);

        for (const device of data.devices) {
            const displayREl = document.getElementById(`res-display-r-${device.sn}`);
            const displayTEl = document.getElementById(`res-display-t-${device.sn}`);
            if (displayREl) {
                displayREl.textContent = device.current_resistance || '--';
            }
            if (displayTEl) {
                displayTEl.textContent = `T: ${device.current_temperature_display || '--'}`;
            }
        }

        const elapsedMs = performance.now() - beginAt;
        const deviceCount = data.devices.length;
        nextDelayMs = calcResValueRefreshDelayMs(deviceCount, elapsedMs);
    } catch (e) {
        console.error('刷新电阻值失败', e);
        nextDelayMs = 2000;
    } finally {
        resValueRefreshInProgress = false;
        scheduleResValueRefresh(nextDelayMs);
    }
}

function calcResValueRefreshDelayMs(deviceCount, elapsedMs) {
    const minInterval = 1000;
    const estimatedSerialCost = Math.max(minInterval, deviceCount * 320 + 200);
    const elapsedCost = Math.ceil(elapsedMs) + 120;
    return Math.max(minInterval, estimatedSerialCost, elapsedCost);
}

function scheduleResValueRefresh(delayMs) {
    if (!resValueAutoRefreshEnabled || !resSerialConnected) {
        return;
    }
    if (resValueRefreshTimer) {
        clearTimeout(resValueRefreshTimer);
        resValueRefreshTimer = null;
    }
    resValueRefreshTimer = setTimeout(resRefreshDeviceValues, delayMs);
}

function startResValueAutoRefresh() {
    stopResValueAutoRefresh();
    resValueAutoRefreshEnabled = true;
    scheduleResValueRefresh(80);
}

function stopResValueAutoRefresh() {
    resValueAutoRefreshEnabled = false;
    if (resValueRefreshTimer) {
        clearTimeout(resValueRefreshTimer);
        resValueRefreshTimer = null;
    }
    resValueRefreshInProgress = false;
}

// 渲染设备列表
function renderDevices() {
    const grid = document.getElementById('device-grid');

    if (devices.length === 0) {
        grid.innerHTML = '<div class="loading">暂无设备，请添加设备</div>';
        return;
    }

    grid.innerHTML = '';
    devices.forEach((device, index) => {
        const card = document.createElement('div');
        card.className = 'device-card' + (selectedDevices.has(device.sn) ? ' selected' : '');
        card.dataset.sn = device.sn;
        card.draggable = true;
        card.dataset.index = index;
        card.style.cursor = 'move';

        card.ondragstart = function(e) {
            e.dataTransfer.setData('text/plain', index);
            card.style.opacity = '0.5';
        };

        card.ondragend = function() {
            card.style.opacity = '1';
        };

        card.ondragover = function(e) {
            e.preventDefault();
            const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
            if (fromIndex !== index) {
                card.style.transform = 'scale(1.02)';
                card.style.boxShadow = '0 4px 12px rgba(102, 126, 234, 0.4)';
                card.style.borderColor = '#667eea';
            }
        };

        card.ondragleave = function() {
            card.style.transform = '';
            card.style.boxShadow = '';
            card.style.borderColor = '';
        };

        card.ondrop = function(e) {
            e.preventDefault();
            card.style.transform = '';
            card.style.boxShadow = '';
            card.style.borderColor = '';
            const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
            const toIndex = index;
            if (fromIndex !== toIndex) {
                // 交换位置
                const movedDevice = devices.splice(fromIndex, 1)[0];
                devices.splice(toIndex, 0, movedDevice);
                renderDevices();
                // 保存顺序到后端
                saveDeviceOrder();
            }
        };

        card.onclick = function(e) {
            if (e.target.type !== 'checkbox' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON' && e.target.tagName !== 'SELECT') {
                toggleDeviceSelect(device.sn);
            }
        };
        card.oncontextmenu = function(e) {
            e.preventDefault();
            showContextMenu(e, device.sn);
        };

        card.innerHTML = `
            <div class="device-card-header" style="position:relative;">
                <input type="checkbox" ${selectedDevices.has(device.sn) ? 'checked' : ''}
                       onclick="event.stopPropagation(); toggleDeviceSelect('${device.sn}')">
                <span class="device-card-name">${device.name}</span>
                <div id="res-display-${device.sn}" style="position:absolute;top:0;right:0;text-align:right;line-height:1.2;">
                    <div id="res-display-r-${device.sn}" style="font-size:14px;font-weight:600;color:#667eea;">${device.current_resistance || '--'}</div>
                    <div id="res-display-t-${device.sn}" style="font-size:12px;color:#718096;">T: ${device.current_temperature_display || '--'}</div>
                </div>
            </div>
            <div class="device-card-sn">SN: ${device.sn}</div>
            <div class="device-card-actions" style="flex-direction: column;gap:10px;">
                <div style="display:flex;gap:4px;align-items:center;">
                    <span style="font-size:11px;color:#666;min-width:18px;">R:</span>
                    <input type="number" id="res-input-${device.sn}" placeholder="Ω" style="flex:1;padding:8px 10px;font-size:14px;border:1px solid #ddd;border-radius:4px;outline:none;background:#fafafa;" onclick="event.stopPropagation()" onkeydown="if(event.key==='Enter')resSetDeviceValue('${device.sn}', 'value')">
                </div>
                <div style="display:flex;gap:4px;align-items:center;">
                    <span style="font-size:11px;color:#666;min-width:18px;">T:</span>
                    <input type="number" id="res-temp-${device.sn}" placeholder="°C" style="flex:1;padding:8px 10px;font-size:14px;border:1px solid #ddd;border-radius:4px;outline:none;background:#fafafa;" onclick="event.stopPropagation()" onkeydown="if(event.key==='Enter')resSetDeviceValue('${device.sn}', 'temp')">
                </div>
            </div>
        `;

        grid.appendChild(card);
    });
}

// 切换设备选中状态
function toggleDeviceSelect(sn) {
    if (selectedDevices.has(sn)) {
        selectedDevices.delete(sn);
    } else {
        selectedDevices.add(sn);
    }
    renderDevices();
}

// 全选
function resSelectAll() {
    devices.forEach(d => selectedDevices.add(d.sn));
    renderDevices();
}

// 取消全选
function resDeselectAll() {
    selectedDevices.clear();
    renderDevices();
}

// 添加设备
async function resAddDevice() {
    const name = document.getElementById('res-device-name').value.trim() || '未命名';
    const sn = document.getElementById('res-device-sn').value.trim();

    if (!sn) {
        alert('请输入 SN 码');
        return;
    }

    try {
        const res = await fetch('/api/res/devices', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name, sn: sn})
        });
        const data = await res.json();

        if (data.success) {
            document.getElementById('res-device-name').value = '';
            document.getElementById('res-device-sn').value = '';
            await resLoadDevices();
        } else {
            alert(data.message);
        }
    } catch (e) {
        console.error('添加设备失败', e);
    }
}

// 批量设备操作
async function resDeviceAction(action) {
    if (!resSerialConnected) {
        alert('请先连接串口');
        return;
    }

    const sns = Array.from(selectedDevices);
    if (sns.length === 0) {
        alert('请先选择设备');
        return;
    }

    try {
        await fetch('/api/res/device_action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: action, sns: sns})
        });
        // 刷新设备列表
        await resLoadDevices();
    } catch (e) {
        console.error('操作失败', e);
    }
}

// 删除选中的设备
async function resDeleteSelected() {
    const sns = Array.from(selectedDevices);
    if (sns.length === 0) {
        alert('请先选择要删除的设备');
        return;
    }

    if (!confirm(`确定要删除选中的 ${sns.length} 个设备吗？`)) {
        return;
    }

    for (const sn of sns) {
        try {
            await fetch(`/api/res/devices/${sn}`, {method: 'DELETE'});
        } catch (e) {
            console.error(`删除设备 ${sn} 失败`, e);
        }
    }

    selectedDevices.clear();
    await resLoadDevices();
}

// 设置设备电阻值或温度
async function resSetDeviceValue(sn, type) {
    let value;
    let data;

    try {
        if (type === 'value') {
            const input = document.getElementById(`res-input-${sn}`);
            value = input.value;
            if (!value) return;

            const res = await fetch('/api/res/device_value', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({sn: sn, value: value})
            });
            data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.message || '设置电阻值失败');
            }
        } else {
            const input = document.getElementById(`res-temp-${sn}`);
            value = input.value;
            if (!value) return;

            const res = await fetch('/api/res/device_temp', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({sn: sn, temperature: parseFloat(value)})
            });
            data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.message || '按温度设置失败');
            }
        }

        const device = devices.find(d => d.sn === sn);
        const deviceName = device ? device.name : sn;
        const resistanceText = data.current_resistance || '--';
        const temperatureText = data.current_temperature_display || '--';
        const logValueText = type === 'temp'
            ? `T=${temperatureText} (${resistanceText})`
            : `R=${resistanceText}`;

        const logEl = document.getElementById('res-log');
        if (logEl) {
            const time = new Date().toLocaleTimeString();
            const line = document.createElement('div');
            line.textContent = `[${time}] ${deviceName}: ${logValueText}`;
            line.style.marginTop = '3px';
            logEl.appendChild(line);
            logEl.scrollTop = logEl.scrollHeight;
        }
    } catch (e) {
        console.error('设置失败', e);
    }
}

// 保存设备顺序到后端
async function saveDeviceOrder() {
    const order = devices.map(d => d.sn);
    try {
        await fetch('/api/res/devices/order', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({order: order})
        });
    } catch (e) {
        console.error('保存设备顺序失败', e);
    }
}

// 清除日志
function clearResLog() {
    const logEl = document.getElementById('res-log');
    if (logEl) {
        logEl.innerHTML = '<div style="color: #718096;">日志记录...</div>';
    }
}

// 显示右键菜单
function showContextMenu(e, sn) {
    e.preventDefault();
    contextMenuSN = sn;
    const menu = document.getElementById('context-menu');
    menu.style.display = 'block';
    menu.style.left = e.clientX + 'px';
    menu.style.top = e.clientY + 'px';
}

// 从菜单重命名设备
function resRenameDeviceFromMenu() {
    if (!contextMenuSN) return;

    const device = devices.find(d => d.sn === contextMenuSN);
    if (!device) return;

    document.getElementById('rename-input').value = device.name;
    document.getElementById('rename-modal').style.display = 'flex';
    document.getElementById('rename-input').focus();

    document.getElementById('context-menu').style.display = 'none';
}

// 从菜单删除设备
async function resDeleteDeviceFromMenu() {
    if (!contextMenuSN) return;

    if (!confirm('确定要删除这个设备吗？')) {
        document.getElementById('context-menu').style.display = 'none';
        return;
    }

    try {
        await fetch(`/api/res/devices/${contextMenuSN}`, {method: 'DELETE'});
        selectedDevices.delete(contextMenuSN);
        await resLoadDevices();
    } catch (e) {
        console.error('删除设备失败', e);
    }

    document.getElementById('context-menu').style.display = 'none';
}

// 关闭重命名模态框
function closeRenameModal() {
    document.getElementById('rename-modal').style.display = 'none';
    contextMenuSN = null;
}

// 保存重命名
async function saveRename() {
    const newName = document.getElementById('rename-input').value.trim();
    if (!newName || !contextMenuSN) {
        closeRenameModal();
        return;
    }

    try {
        await fetch(`/api/res/devices/${contextMenuSN}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: newName})
        });
        await resLoadDevices();
    } catch (e) {
        console.error('重命名失败', e);
    }

    closeRenameModal();
}

// ===== 电源控制 =====
async function powerRefreshResources() {
    try {
        const res = await fetch('/api/power/list_resources');
        const data = await res.json();
        const select = document.getElementById('power-address');
        select.innerHTML = '<option value="">请选择电源...</option>';
        data.resources.forEach(r => {
            select.innerHTML += `<option value="${r}">${r}</option>`;
        });
    } catch (e) {
        console.error('获取资源列表失败', e);
    }
}

async function powerConnect() {
    const address = document.getElementById('power-address').value;
    if (!address) {
        return;
    }

    try {
        const res = await fetch('/api/power/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({address: address})
        });
        const data = await res.json();
        if (data.success) {
            powerConnected = true;
            state.power_address = address;
            document.getElementById('power-title-status').textContent = '已连接';
            togglePowerButtons(true);
            startPowerAutoRefresh();
        }
    } catch (e) {
        console.error('连接失败', e);
    }
}

async function powerDisconnect() {
    try {
        const res = await fetch('/api/power/disconnect', {
            method: 'POST'
        });
        const data = await res.json();
        if (data.success) {
            powerConnected = false;
            state.power_address = null;
            document.getElementById('power-title-status').textContent = '';
            togglePowerButtons(false);
            stopPowerAutoRefresh();
        }
    } catch (e) {
        console.error('断开失败', e);
    }
}

function powerAddressChanged() {
    const address = document.getElementById('power-address').value;
    document.getElementById('btn-power-connect').disabled = !address || powerConnected;
}

async function powerToggleConnect() {
    if (powerConnected) {
        await powerDisconnect();
    } else {
        await powerConnect();
    }
}

function togglePowerButtons(connected) {
    document.getElementById('btn-power-connect').textContent = connected ? '断开' : '连接';
    document.getElementById('power-address').disabled = connected;
}

async function powerSetParams() {
    if (!powerConnected) {
        return;
    }

    const voltage = document.getElementById('power-voltage').value;
    const current = document.getElementById('power-current').value;

    try {
        const body = {};
        if (voltage) body.voltage = parseFloat(voltage);
        if (current) body.current = parseFloat(current);

        await fetch('/api/power/set', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
    } catch (e) {
        console.error('设置参数失败', e);
    }
}

async function powerSetOutput(on) {
    if (!powerConnected) {
        return;
    }

    try {
        await fetch('/api/power/set', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({output: on})
        });
    } catch (e) {
        console.error('设置输出失败', e);
    }
}

async function powerMeasure() {
    if (!powerConnected) {
        return;
    }

    try {
        const res = await fetch('/api/power/measure');
        const data = await res.json();
        if (!data.error) {
            document.getElementById('power-measure').textContent =
                `${data.voltage.toFixed(4)} V, ${data.current.toFixed(4)} A`;
        }
    } catch (e) {
        console.error('测量失败', e);
    }
}

function startPowerAutoRefresh() {
    stopPowerAutoRefresh();
    powerRefreshTimer = setInterval(powerMeasure, 1000);
}

function stopPowerAutoRefresh() {
    if (powerRefreshTimer) {
        clearInterval(powerRefreshTimer);
        powerRefreshTimer = null;
    }
}

// ===== 示波器控制 =====
async function scopeConnect() {
    const serial = document.getElementById('scope-serial').value;
    if (!serial) {
        return;
    }

    try {
        const res = await fetch('/api/scope/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({serial: serial})
        });
        const data = await res.json();
        if (data.success) {
            scopeConnected = true;
            state.scope_serial = serial;
            document.getElementById('scope-title-status').textContent = '已连接';
            toggleScopeButtons(true);

            // 锁定示波器
            await fetch('/api/scope/lock', { method: 'POST' });
            scopeLocked = true;
            document.getElementById('btn-scope-lock').textContent = '解锁';

            // 获取通道状态并同步
            scopeSyncChannelState();
            // 启动自动刷新
            startAutoRefresh();
        }
    } catch (e) {
        console.error('连接失败', e);
    }
}

async function scopeDisconnect() {
    try {
        const res = await fetch('/api/scope/disconnect', {
            method: 'POST'
        });
        const data = await res.json();
        if (data.success) {
            scopeConnected = false;
            state.scope_serial = null;
            document.getElementById('scope-title-status').textContent = '';
            stopAutoRefresh();
            toggleScopeButtons(false);
        }
    } catch (e) {
        console.error('断开失败', e);
    }
}

function scopeSerialChanged() {
    const serial = document.getElementById('scope-serial').value;
    document.getElementById('btn-scope-connect').disabled = !serial || scopeConnected;
}

async function scopeToggleConnect() {
    if (scopeConnected) {
        await scopeDisconnect();
    } else {
        await scopeConnect();
    }
}

function toggleScopeButtons(connected) {
    document.getElementById('btn-scope-connect').textContent = connected ? '断开' : '连接';
    document.getElementById('scope-serial').disabled = connected;
    document.getElementById('btn-scope-lock').style.display = connected ? 'inline-block' : 'none';
    document.getElementById('btn-scope-copy').style.display = connected ? 'inline-block' : 'none';
    document.getElementById('btn-scope-copy').disabled = !connected;
    // 更新通道卡片颜色
    for (let i = 1; i <= 4; i++) {
        const ch = document.getElementById(`scope-ch${i}`);
        if (ch) {
            if (connected) {
                ch.classList.remove('disconnected');
            } else {
                ch.classList.add('disconnected');
            }
        }
    }
}

let scopeLocked = true;  // 远程模式为锁定

async function scopeToggleLock() {
    try {
        const url = scopeLocked ? '/api/scope/unlock' : '/api/scope/lock';
        const res = await fetch(url, {
            method: 'POST'
        });
        const data = await res.json();
        if (data.success) {
            scopeLocked = !scopeLocked;
            document.getElementById('btn-scope-lock').textContent = scopeLocked ? '解锁' : '锁定';
        }
    } catch (e) {
        console.error('操作失败', e);
    }
}

async function scopeCopyScreenshot() {
    if (!scopeConnected) {
        return;
    }

    const btn = document.getElementById('btn-scope-copy');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '复制中...';
    stopAutoRefresh();

    try {
        const res = await fetch('/api/scope/copy_screenshot', {
            method: 'POST'
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.message || '复制示波器截图失败');
        }

        showToast(`示波器截图已复制到剪贴板\n保存路径: ${data.filepath}`, 'success', 3600);
    } catch (e) {
        console.error('复制示波器截图失败', e);
        showToast('复制示波器截图失败: ' + (e.message || '未知错误'), 'error', 4200);
    } finally {
        btn.textContent = originalText;
        btn.disabled = !scopeConnected;
        if (scopeConnected) {
            checkAllChannelsClosed();
        }
    }
}

function scopeUpdateInterval() {
    // 重新设置刷新定时器
    startAutoRefresh();
}

async function scopeSyncChannelState() {
    if (!scopeConnected) {
        return;
    }

    try {
        const res = await fetch('/api/scope/channel_state');
        const data = await res.json();
        if (data.channels) {
            for (let i = 1; i <= 4; i++) {
                const enabled = data.channels[`ch${i}`];
                scopeChannelStates[i] = enabled || false;
                updateChannelStyle(i, scopeChannelStates[i]);
            }
        }
        // 检查是否需要启动自动刷新
        checkAllChannelsClosed();
    } catch (e) {
        console.error('获取通道状态失败', e);
    }
}

// 更新通道样式
function updateChannelStyle(channel, enabled) {
    const el = document.getElementById(`scope-ch${channel}`);
    const labelEl = el.querySelector('.ch-label');
    if (enabled) {
        el.classList.remove('disabled');
        if (labelEl) {
            labelEl.style.color = '#333';
        }
    } else {
        el.classList.add('disabled');
        // 关闭通道时清除数值显示
        const valueEl = el.querySelector('.ch-value');
        if (valueEl) {
            valueEl.textContent = '--';
        }
        // 变灰通道号
        if (labelEl) {
            labelEl.style.color = '#999';
        }
    }
}

// 点击通道切换开关
async function scopeToggleChannel(channel) {
    if (!scopeConnected) {
        return;
    }

    // 切换状态
    const newState = !scopeChannelStates[channel];
    scopeChannelStates[channel] = newState;
    updateChannelStyle(channel, newState);

    try {
        await fetch('/api/scope/channel', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({channel: channel, enable: newState})
        });

        // 检查是否所有通道都关闭
        checkAllChannelsClosed();
    } catch (e) {
        console.error('设置通道开关失败', e);
    }
}

// 检查是否所有通道都关闭
function checkAllChannelsClosed() {
    const allClosed = !Object.values(scopeChannelStates).some(v => v);
    if (allClosed) {
        stopAutoRefresh();
    } else {
        startAutoRefresh();
    }
}

async function scopeGetMean() {
    if (!scopeConnected) {
        return;
    }

    try {
        const res = await fetch('/api/scope/get_mean');
        const data = await res.json();
        if (!data.error && data.channels) {
            const channels = data.channels;
            for (let i = 1; i <= 4; i++) {
                const chKey = 'ch' + i;
                const val = channels[chKey];
                const el = document.querySelector(`#scope-ch${i} .ch-value`);
                // 只更新有效值，null、undefined 或 NaN 时显示 --
                if (el && val !== undefined && val !== null && !isNaN(val)) {
                    el.textContent = `${val.toFixed(3)}`;
                } else if (el) {
                    el.textContent = '--';
                }
            }
        }
    } catch (e) {
        // 读取失败时不显示错误，数值保持不变
    }
}

function startAutoRefresh() {
    stopAutoRefresh();
    const interval = parseInt(document.getElementById('scope-interval').value) || 1000;
    scopeRefreshTimer = setInterval(scopeGetMean, interval);
}

function stopAutoRefresh() {
    if (scopeRefreshTimer) {
        clearInterval(scopeRefreshTimer);
        scopeRefreshTimer = null;
    }
}

