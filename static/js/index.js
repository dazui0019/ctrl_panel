let scopeRefreshTimer = null;
let powerRefreshTimer = null;

const RES_QUICK_TEMP_STORAGE_KEY = 'res_quick_temps_v1';
const RES_QUICK_TEMP_DEFAULTS = [-40, 25, 85];

const appState = {
    page: 'workspace',
    resSerialConnected: false,
    powerConnected: false,
    scopeConnected: false,
    scopeLocked: false,
    scopeChannelStates: {1: false, 2: false, 3: false, 4: false},
    devices: [],
    selectedDevices: new Set(),
    contextMenuSN: null,
    resQuickTemps: [...RES_QUICK_TEMP_DEFAULTS],
    connection: {
        resistancePort: null,
        powerAddress: null,
        scopeSerial: null,
    },
};

document.addEventListener('DOMContentLoaded', () => {
    initApp().catch((error) => {
        console.error('页面初始化失败', error);
        showToast('页面初始化失败，请刷新后重试。', 'error', 4200);
    });
});

window.addEventListener('beforeunload', () => {
    stopAutoRefresh();
    stopPowerAutoRefresh();
});

function $id(id) {
    return document.getElementById(id);
}

function setText(id, text) {
    const el = $id(id);
    if (el) {
        el.textContent = text;
    }
}

function setValue(id, value) {
    const el = $id(id);
    if (el) {
        el.value = value ?? '';
    }
}

function setDisabled(id, disabled) {
    const el = $id(id);
    if (el) {
        el.disabled = disabled;
    }
}

function toggleHidden(id, hidden) {
    const el = $id(id);
    if (el) {
        el.classList.toggle('is-hidden', hidden);
    }
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[char]));
}

function deviceDomId(sn) {
    return String(sn ?? '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

function ensureOption(select, value, label = value) {
    if (!select || !value) {
        return;
    }

    const exists = Array.from(select.options).some((option) => option.value === value);
    if (!exists) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
    }
}

function jsonOptions(method, payload) {
    return {
        method: method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
    };
}

async function apiJson(url, options = {}) {
    const response = await fetch(url, options);
    let data = {};

    try {
        data = await response.json();
    } catch (error) {
        data = {};
    }

    if (!response.ok) {
        const message = data.message || data.error || `请求失败 (${response.status})`;
        const err = new Error(message);
        err.status = response.status;
        err.data = data;
        throw err;
    }

    return data;
}

function showToast(message, type = 'info', duration = 2600) {
    let container = $id('toast-container');
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

async function initApp() {
    appState.page = document.body.dataset.page || 'workspace';

    initGlobalListeners();
    prepareStaticUi();
    initResQuickTemps();

    if (appState.page === 'device-management') {
        await Promise.all([resRefreshPorts(), powerRefreshResources()]);
    }

    await syncDeviceStates();
}

function initGlobalListeners() {
    document.addEventListener('click', (event) => {
        const menu = $id('context-menu');
        if (menu && menu.style.display === 'block' && !menu.contains(event.target)) {
            closeContextMenu();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeContextMenu();
            closeRenameModal();
        }

        if (event.key === 'Enter') {
            const overlay = $id('rename-modal');
            const renameInput = $id('rename-input');
            if (
                overlay &&
                renameInput &&
                overlay.style.display === 'flex' &&
                document.activeElement === renameInput
            ) {
                saveRename();
            }
        }
    });

    const renameOverlay = $id('rename-modal');
    if (renameOverlay) {
        renameOverlay.addEventListener('click', (event) => {
            if (event.target === renameOverlay) {
                closeRenameModal();
            }
        });
    }
}

function prepareStaticUi() {
    updateStatusBadge('res-title-status', false, '串口已连接', '未连接');
    updateStatusBadge('power-title-status', false);
    updateStatusBadge('scope-title-status', false);
    updateSelectToggleButton();
    renderQuickTempButtons();
    togglePowerWorkspaceControls(false);
    toggleScopeWorkspaceControls(false);
    resetScopeChannelDisplays();
    clearResLog();
    resPortChanged();
    powerAddressChanged();
    scopeSerialChanged();
}

async function syncDeviceStates() {
    try {
        const data = await apiJson('/api/state');

        applyResistanceState(data.resistance || {});
        applyPowerState(data.power || {});
        applyScopeState(data.scope || {});

        if ($id('device-grid')) {
            if (appState.resSerialConnected) {
                await resLoadDevices();
                await resRefreshDeviceValuesOnce(true);
            } else {
                appState.devices = [];
                appState.selectedDevices.clear();
                renderDevices();
            }
        }

        if (appState.scopeConnected && appState.page === 'workspace') {
            await scopeSyncChannelState(true);
        }
    } catch (error) {
        console.error('获取设备状态失败', error);
        showToast(`获取设备状态失败: ${error.message || '未知错误'}`, 'error', 3800);
    }
}

function updateStatusBadge(id, connected, connectedText = '已连接', disconnectedText = '未连接') {
    const badge = $id(id);
    if (!badge) {
        return;
    }

    badge.textContent = connected ? connectedText : disconnectedText;
    badge.classList.toggle('is-active', connected);
    badge.classList.toggle('is-inactive', !connected);
}

function applyResistanceState(data) {
    appState.resSerialConnected = Boolean(data.connected);
    appState.connection.resistancePort = data.port || null;

    updateStatusBadge('res-title-status', appState.resSerialConnected, '串口已连接', '未连接');

    const portSelect = $id('res-port');
    if (portSelect) {
        ensureOption(portSelect, data.port);
        if (data.port) {
            portSelect.value = data.port;
        }
        portSelect.disabled = appState.resSerialConnected;
    }

    const connectButton = $id('btn-res-serial-connect');
    if (connectButton) {
        connectButton.textContent = appState.resSerialConnected ? '断开' : '连接';
    }

    if (!appState.resSerialConnected) {
        appState.selectedDevices.clear();
    }

    resPortChanged();
    updateResistanceHint();
}

function applyPowerState(data) {
    appState.powerConnected = Boolean(data.connected);
    appState.connection.powerAddress = data.address || null;

    updateStatusBadge('power-title-status', appState.powerConnected);

    const addressSelect = $id('power-address');
    if (addressSelect) {
        ensureOption(addressSelect, data.address);
        if (data.address) {
            addressSelect.value = data.address;
        }
        addressSelect.disabled = appState.powerConnected;
    }

    const connectButton = $id('btn-power-connect');
    if (connectButton) {
        connectButton.textContent = appState.powerConnected ? '断开' : '连接';
    }

    if (typeof data.voltage === 'number' && $id('power-voltage')) {
        setValue('power-voltage', data.voltage);
    }
    if (typeof data.current === 'number' && $id('power-current')) {
        setValue('power-current', data.current);
    }

    setText('power-resource-label', data.address || '--');
    if (!appState.powerConnected) {
        setText('power-measure', '-- V, -- A');
    }

    powerAddressChanged();
    togglePowerWorkspaceControls(appState.powerConnected);
    updatePowerHint();

    if (appState.powerConnected && appState.page === 'workspace') {
        startPowerAutoRefresh();
    } else {
        stopPowerAutoRefresh();
    }
}

function applyScopeState(data) {
    appState.scopeConnected = Boolean(data.connected);
    appState.connection.scopeSerial = data.serial || null;
    if (appState.scopeConnected) {
        appState.scopeLocked = typeof data.locked === 'boolean' ? data.locked : false;
    } else {
        appState.scopeLocked = false;
    }

    updateStatusBadge('scope-title-status', appState.scopeConnected);

    if (typeof data.refresh_interval === 'number') {
        setValue('scope-interval', data.refresh_interval);
    }

    const serialInput = $id('scope-serial');
    if (serialInput) {
        if (data.serial) {
            serialInput.value = data.serial;
        }
        serialInput.disabled = appState.scopeConnected;
    }

    setText('scope-serial-display', data.serial || '--');

    const connectButton = $id('btn-scope-connect');
    if (connectButton) {
        connectButton.textContent = appState.scopeConnected ? '断开' : '连接';
    }

    scopeSerialChanged();
    toggleScopeWorkspaceControls(appState.scopeConnected);
    updateScopeHint();

    if (!appState.scopeConnected) {
        appState.scopeChannelStates = {1: false, 2: false, 3: false, 4: false};
        stopAutoRefresh();
        resetScopeChannelDisplays();
    }
}

function updateResistanceHint() {
    const hint = $id('res-work-hint');
    if (!hint) {
        return;
    }

    if (!appState.resSerialConnected) {
        hint.textContent = '先在设备管理页连接电阻串口，并维护好设备列表。';
        toggleHidden('res-work-hint', false);
        return;
    }

    if (appState.devices.length === 0) {
        hint.textContent = '串口已连接，但设备列表为空。请先到设备管理页添加设备。';
        toggleHidden('res-work-hint', false);
        return;
    }

    toggleHidden('res-work-hint', true);
}

function updatePowerHint() {
    if (!$id('power-work-hint')) {
        return;
    }
    toggleHidden('power-work-hint', appState.powerConnected);
}

function updateScopeHint() {
    if (!$id('scope-work-hint')) {
        return;
    }

    if (!appState.scopeConnected) {
        setText('scope-work-hint', '请先到设备管理页连接示波器，然后这里会自动显示通道数据。');
        toggleHidden('scope-work-hint', false);
        return;
    }

    toggleHidden('scope-work-hint', true);
}

function togglePowerWorkspaceControls(connected) {
    const controls = document.querySelectorAll('.power-work-control');
    controls.forEach((control) => {
        control.disabled = !connected;
    });
}

function toggleScopeWorkspaceControls(connected) {
    const intervalInput = $id('scope-interval');
    if (intervalInput) {
        intervalInput.disabled = !connected;
    }

    const lockButton = $id('btn-scope-lock');
    if (lockButton) {
        lockButton.style.display = connected ? 'inline-flex' : 'none';
        lockButton.disabled = !connected;
        lockButton.textContent = appState.scopeLocked ? '解锁' : '锁定';
    }

    const copyButton = $id('btn-scope-copy');
    if (copyButton) {
        copyButton.style.display = connected ? 'inline-flex' : 'none';
        copyButton.disabled = !connected;
    }

    for (let channel = 1; channel <= 4; channel += 1) {
        const card = $id(`scope-ch${channel}`);
        if (card) {
            card.classList.toggle('disconnected', !connected);
        }
    }
}

function resetScopeChannelDisplays() {
    for (let channel = 1; channel <= 4; channel += 1) {
        const card = $id(`scope-ch${channel}`);
        if (!card) {
            continue;
        }

        card.classList.add('disabled');
        card.classList.add('disconnected');

        const valueEl = card.querySelector('.ch-value');
        if (valueEl) {
            valueEl.textContent = '--';
        }

        const labelEl = card.querySelector('.ch-label');
        if (labelEl) {
            labelEl.style.color = '';
        }
    }
}

async function resRefreshPorts() {
    const select = $id('res-port');
    if (!select) {
        return;
    }

    try {
        const data = await apiJson('/api/res/list_ports');
        const current = appState.connection.resistancePort || select.value;

        select.innerHTML = '<option value="">请选择串口...</option>';
        (data.ports || []).forEach((port) => {
            const option = document.createElement('option');
            option.value = port;
            option.textContent = port;
            select.appendChild(option);
        });

        ensureOption(select, current);
        if (current) {
            select.value = current;
        }
    } catch (error) {
        console.error('获取串口列表失败', error);
        showToast(`获取串口列表失败: ${error.message || '未知错误'}`, 'error', 3600);
    } finally {
        resPortChanged();
    }
}

function resPortChanged() {
    const select = $id('res-port');
    const button = $id('btn-res-serial-connect');
    if (!select || !button) {
        return;
    }

    button.disabled = !appState.resSerialConnected && !select.value;
}

async function resToggleSerial() {
    if (appState.resSerialConnected) {
        await resSerialDisconnect();
    } else {
        await resSerialConnect();
    }
}

async function resSerialConnect() {
    const select = $id('res-port');
    if (!select || !select.value) {
        return;
    }

    try {
        const data = await apiJson('/api/res/connect', jsonOptions('POST', {port: select.value}));
        if (!data.success) {
            throw new Error(data.message || '连接失败');
        }

        applyResistanceState({connected: true, port: select.value});
        await resLoadDevices();
        await resRefreshDeviceValuesOnce(true);
        showToast(`电阻串口已连接: ${select.value}`, 'success', 2800);
    } catch (error) {
        console.error('连接电阻串口失败', error);
        showToast(`连接电阻串口失败: ${error.message || '未知错误'}`, 'error', 3800);
    }
}

async function resSerialDisconnect() {
    try {
        const data = await apiJson('/api/res/disconnect', {method: 'POST'});
        if (!data.success) {
            throw new Error(data.message || '断开失败');
        }

        appState.devices = [];
        appState.selectedDevices.clear();
        applyResistanceState({connected: false, port: null});
        renderDevices();
        showToast('电阻串口已断开', 'info', 2400);
    } catch (error) {
        console.error('断开电阻串口失败', error);
        showToast(`断开电阻串口失败: ${error.message || '未知错误'}`, 'error', 3800);
    }
}

async function resLoadDevices() {
    const grid = $id('device-grid');
    if (!grid) {
        return;
    }

    if (!appState.resSerialConnected) {
        appState.devices = [];
        renderDevices();
        return;
    }

    try {
        const data = await apiJson('/api/res/devices');
        const latestDevices = Array.isArray(data.devices) ? data.devices : [];

        if (appState.devices.length > 0 && latestDevices.length > 0) {
            const orderedDevices = [];
            for (const sn of appState.devices.map((device) => device.sn)) {
                const match = latestDevices.find((device) => device.sn === sn);
                if (match) {
                    orderedDevices.push(match);
                }
            }
            for (const device of latestDevices) {
                if (!orderedDevices.find((item) => item.sn === device.sn)) {
                    orderedDevices.push(device);
                }
            }
            appState.devices = orderedDevices;
        } else {
            appState.devices = latestDevices;
        }
    } catch (error) {
        console.error('加载设备列表失败', error);
        showToast(`加载设备列表失败: ${error.message || '未知错误'}`, 'error', 3600);
    }

    renderDevices();
}

async function resRefreshDeviceValuesOnce(silent = false) {
    if (!appState.resSerialConnected || appState.devices.length === 0) {
        return;
    }

    try {
        const data = await apiJson('/api/res/device_values');
        if (!data.success || !Array.isArray(data.devices)) {
            throw new Error(data.message || '刷新失败');
        }

        const latestBySn = new Map(data.devices.map((device) => [device.sn, device]));
        appState.devices = appState.devices.map((device) => (
            latestBySn.has(device.sn) ? {...device, ...latestBySn.get(device.sn)} : device
        ));

        data.devices.forEach((device) => {
            const key = deviceDomId(device.sn);
            setText(`res-display-r-${key}`, device.current_resistance || '--');

            const tempEl = $id(`res-display-t-${key}`);
            if (tempEl) {
                tempEl.textContent = appState.page === 'workspace'
                    ? `T: ${device.current_temperature_display || '--'}`
                    : (device.current_temperature_display || '--');
            }

        });

        if (!silent) {
            showToast('设备当前值已刷新', 'info', 1800);
        }
    } catch (error) {
        console.error('刷新设备当前值失败', error);
        if (!silent) {
            showToast(`刷新当前值失败: ${error.message || '未知错误'}`, 'error', 3600);
        }
    }
}

function renderDevices() {
    const grid = $id('device-grid');
    if (!grid) {
        return;
    }

    appState.selectedDevices = new Set(
        Array.from(appState.selectedDevices).filter((sn) => appState.devices.some((device) => device.sn === sn))
    );

    if (!appState.resSerialConnected) {
        grid.innerHTML = appState.page === 'workspace'
            ? '<div class="loading">电阻串口未连接，请先到 <a href="/devices">设备管理</a> 页面完成连接。</div>'
            : '<div class="loading">请先连接串口，再管理设备清单。</div>';
        updateSelectToggleButton();
        updateResistanceHint();
        return;
    }

    if (appState.devices.length === 0) {
        grid.innerHTML = appState.page === 'workspace'
            ? '<div class="loading">当前没有设备，请前往 <a href="/devices">设备管理</a> 页面添加。</div>'
            : '<div class="loading">暂无设备，请添加设备后再进行管理。</div>';
        updateSelectToggleButton();
        updateResistanceHint();
        return;
    }

    grid.innerHTML = '';
    appState.devices.forEach((device, index) => {
        const card = appState.page === 'device-management'
            ? renderManagementDeviceCard(device, index)
            : renderWorkspaceDeviceCard(device);
        grid.appendChild(card);
    });

    updateSelectToggleButton();
    updateResistanceHint();
}

function renderManagementDeviceCard(device, index) {
    const selected = appState.selectedDevices.has(device.sn);
    const key = deviceDomId(device.sn);
    const card = document.createElement('article');

    card.className = `device-card management-card${selected ? ' selected' : ''}`;
    card.dataset.index = String(index);
    card.dataset.sn = device.sn;
    card.draggable = true;

    card.innerHTML = `
        <div class="device-card-head">
            <div class="device-head-main">
                <input type="checkbox" class="device-checkbox" ${selected ? 'checked' : ''}>
                <div class="device-title-wrap">
                    <div class="device-card-name">${escapeHtml(device.name)}</div>
                    <div class="device-card-sn">SN: ${escapeHtml(device.sn)}</div>
                </div>
            </div>
        </div>
        <div class="device-metrics">
            <div class="metric">
                <span>电阻</span>
                <strong id="res-display-r-${key}">${escapeHtml(device.current_resistance || '--')}</strong>
            </div>
            <div class="metric">
                <span>温度</span>
                <strong id="res-display-t-${key}">${escapeHtml(device.current_temperature_display || '--')}</strong>
            </div>
        </div>
        <div class="device-card-hint">拖拽排序，右键编辑</div>
    `;

    const checkbox = card.querySelector('.device-checkbox');
    if (checkbox) {
        checkbox.addEventListener('click', (event) => {
            event.stopPropagation();
            toggleDeviceSelect(device.sn, {card, checkbox});
        });
    }

    bindCardTapAnimation(card);

    card.addEventListener('contextmenu', (event) => {
        event.preventDefault();
        showContextMenu(event, device.sn);
    });

    card.addEventListener('dragstart', (event) => {
        if (event.dataTransfer) {
            event.dataTransfer.setData('text/plain', String(index));
            event.dataTransfer.effectAllowed = 'move';
        }
        card.classList.add('dragging');
    });

    card.addEventListener('dragend', () => {
        card.classList.remove('dragging');
    });

    card.addEventListener('dragover', (event) => {
        event.preventDefault();
        card.classList.add('drag-over');
    });

    card.addEventListener('dragleave', () => {
        card.classList.remove('drag-over');
    });

    card.addEventListener('drop', (event) => {
        event.preventDefault();
        card.classList.remove('drag-over');

        const rawIndex = event.dataTransfer ? event.dataTransfer.getData('text/plain') : '';
        const fromIndex = Number.parseInt(rawIndex, 10);
        const toIndex = index;

        if (Number.isNaN(fromIndex) || fromIndex === toIndex) {
            return;
        }

        const movedDevice = appState.devices.splice(fromIndex, 1)[0];
        appState.devices.splice(toIndex, 0, movedDevice);
        renderDevices();
        saveDeviceOrder();
    });

    return card;
}

function renderWorkspaceDeviceCard(device) {
    const selected = appState.selectedDevices.has(device.sn);
    const key = deviceDomId(device.sn);
    const card = document.createElement('article');

    card.className = `device-card workspace-card${selected ? ' selected' : ''}`;
    card.dataset.sn = device.sn;

    card.innerHTML = `
        <div class="device-card-head">
            <div class="device-head-main">
                <input type="checkbox" class="device-checkbox" ${selected ? 'checked' : ''}>
                <div class="device-title-wrap">
                    <div class="device-card-name">${escapeHtml(device.name)}</div>
                    <div class="device-card-sn">SN: ${escapeHtml(device.sn)}</div>
                </div>
            </div>
        </div>
        <div class="workspace-reading">
            <strong id="res-display-r-${key}">${escapeHtml(device.current_resistance || '--')}</strong>
            <span id="res-display-t-${key}">T: ${escapeHtml(device.current_temperature_display || '--')}</span>
        </div>
        <div class="workspace-controls">
            <label class="mini-field">
                <span>电阻</span>
                <div class="mini-input-group">
                    <input type="number" id="res-input-${key}" placeholder="Ω">
                    <button class="btn btn-primary btn-small">设置</button>
                </div>
            </label>
            <label class="mini-field">
                <span>温度</span>
                <div class="mini-input-group">
                    <input type="number" id="res-temp-${key}" placeholder="℃">
                    <button class="btn btn-secondary btn-small">换算</button>
                </div>
            </label>
        </div>
    `;

    const checkbox = card.querySelector('.device-checkbox');
    const buttons = card.querySelectorAll('button');
    const valueInput = $id(`res-input-${key}`);
    const tempInput = $id(`res-temp-${key}`);

    if (checkbox) {
        checkbox.addEventListener('click', (event) => {
            event.stopPropagation();
            toggleDeviceSelect(device.sn, {card, checkbox});
        });
    }

    bindCardTapAnimation(card);

    if (buttons[0]) {
        buttons[0].addEventListener('click', (event) => {
            event.stopPropagation();
            resSetDeviceValue(device.sn, 'value');
        });
    }

    if (buttons[1]) {
        buttons[1].addEventListener('click', (event) => {
            event.stopPropagation();
            resSetDeviceValue(device.sn, 'temp');
        });
    }

    if (valueInput) {
        valueInput.addEventListener('click', (event) => event.stopPropagation());
        valueInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                resSetDeviceValue(device.sn, 'value');
            }
        });
    }

    if (tempInput) {
        tempInput.addEventListener('click', (event) => event.stopPropagation());
        tempInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                resSetDeviceValue(device.sn, 'temp');
            }
        });
    }

    return card;
}

function toggleDeviceSelect(sn, options = {}) {
    const nextSelected = !appState.selectedDevices.has(sn);
    if (nextSelected) {
        appState.selectedDevices.add(sn);
    } else {
        appState.selectedDevices.delete(sn);
    }

    const card = options.card || null;
    const checkbox = options.checkbox || null;
    if (card) {
        card.classList.toggle('selected', nextSelected);
    }
    if (checkbox) {
        checkbox.checked = nextSelected;
    }

    updateSelectToggleButton();
}

function bindCardTapAnimation(card) {
    const releaseCard = () => {
        card.classList.remove('pressed');
    };

    card.addEventListener('pointerdown', (event) => {
        if (!(event.target instanceof HTMLElement)) {
            return;
        }

        if (event.target.closest('button, select, textarea, a, .workspace-controls')) {
            return;
        }

        const input = event.target.closest('input');
        if (input instanceof HTMLInputElement && input.type !== 'checkbox') {
            return;
        }

        card.classList.add('pressed');
    });

    card.addEventListener('pointerup', releaseCard);
    card.addEventListener('pointerleave', releaseCard);
    card.addEventListener('pointercancel', releaseCard);
}

function resToggleSelectAll() {
    if (!appState.resSerialConnected || appState.devices.length === 0) {
        return;
    }

    const allSelected = appState.devices.every((device) => appState.selectedDevices.has(device.sn));
    if (allSelected) {
        appState.selectedDevices.clear();
    } else {
        appState.devices.forEach((device) => appState.selectedDevices.add(device.sn));
    }

    renderDevices();
}

function updateSelectToggleButton() {
    const button = $id('btn-res-select-toggle');
    if (!button) {
        return;
    }

    if (!appState.resSerialConnected || appState.devices.length === 0) {
        button.textContent = '全选';
        button.disabled = true;
        return;
    }

    const allSelected = appState.devices.every((device) => appState.selectedDevices.has(device.sn));
    button.textContent = allSelected ? '取消全选' : '全选';
    button.disabled = false;
}

function initResQuickTemps() {
    try {
        const raw = localStorage.getItem(RES_QUICK_TEMP_STORAGE_KEY);
        if (!raw) {
            renderQuickTempButtons();
            return;
        }

        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) {
            renderQuickTempButtons();
            return;
        }

        const values = parsed
            .map((item) => Number(item))
            .filter((item) => !Number.isNaN(item))
            .slice(0, 3);

        if (values.length === 3) {
            appState.resQuickTemps = values;
        }
    } catch (error) {
        console.error('加载常用温度配置失败', error);
    }

    renderQuickTempButtons();
}

function renderQuickTempButtons() {
    for (let index = 0; index < 3; index += 1) {
        const button = $id(`btn-res-quick-temp-${index}`);
        if (!button) {
            continue;
        }

        const value = appState.resQuickTemps[index];
        button.textContent = `${value}℃`;
        button.title = `为选中设备设置 ${value}℃`;
    }
}

function resConfigQuickTemps() {
    const input = window.prompt(
        '请输入 3 个常用温度，使用英文逗号分隔，例如：-40,25,85',
        appState.resQuickTemps.join(',')
    );

    if (input === null) {
        return;
    }

    const values = input
        .split(',')
        .map((item) => Number(item.trim()))
        .filter((item) => !Number.isNaN(item));

    if (values.length !== 3) {
        showToast('请准确输入 3 个温度值。', 'error', 3200);
        return;
    }

    appState.resQuickTemps = values;
    renderQuickTempButtons();

    try {
        localStorage.setItem(RES_QUICK_TEMP_STORAGE_KEY, JSON.stringify(values));
    } catch (error) {
        console.error('保存常用温度配置失败', error);
    }
}

function resBatchSetTemperatureByIndex(index) {
    const temperature = appState.resQuickTemps[index];
    if (typeof temperature === 'undefined') {
        return;
    }
    resBatchSetTemperature(temperature);
}

async function resAddDevice() {
    if (!appState.resSerialConnected) {
        showToast('请先连接电阻串口。', 'info', 2400);
        return;
    }

    const nameInput = $id('res-device-name');
    const snInput = $id('res-device-sn');
    if (!snInput) {
        return;
    }

    const name = nameInput && nameInput.value.trim() ? nameInput.value.trim() : '未命名';
    const sn = snInput.value.trim();

    if (!sn) {
        showToast('请输入设备 SN。', 'error', 2600);
        return;
    }

    try {
        const data = await apiJson('/api/res/devices', jsonOptions('POST', {name, sn}));
        if (!data.success) {
            throw new Error(data.message || '添加设备失败');
        }

        if (nameInput) {
            nameInput.value = '';
        }
        snInput.value = '';

        await resLoadDevices();
        await resRefreshDeviceValuesOnce(true);
        showToast(`设备 ${sn} 已添加`, 'success', 2400);
    } catch (error) {
        console.error('添加设备失败', error);
        showToast(`添加设备失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

async function resDeviceAction(action) {
    if (!appState.resSerialConnected) {
        showToast('请先连接电阻串口。', 'info', 2400);
        return;
    }

    const sns = Array.from(appState.selectedDevices);
    if (sns.length === 0) {
        showToast('请先选择设备。', 'info', 2200);
        return;
    }

    try {
        const data = await apiJson('/api/res/device_action', jsonOptions('POST', {action, sns}));
        const results = Array.isArray(data.results) ? data.results : [];
        const successCount = results.filter((item) => item.success).length;
        const failCount = results.length - successCount;

        await resLoadDevices();
        await resRefreshDeviceValuesOnce(true);

        if (failCount === 0) {
            showToast(`批量操作完成: ${successCount} 台设备成功`, 'success', 2600);
        } else {
            showToast(`批量操作完成: 成功 ${successCount} 台，失败 ${failCount} 台`, 'info', 3400);
        }
    } catch (error) {
        console.error('批量设备操作失败', error);
        showToast(`批量设备操作失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

async function resBatchSetTemperature(temperature) {
    if (!appState.resSerialConnected) {
        showToast('请先连接电阻串口。', 'info', 2400);
        return;
    }

    const sns = Array.from(appState.selectedDevices);
    if (sns.length === 0) {
        showToast('请先选择设备。', 'info', 2200);
        return;
    }

    const tempValue = Number(temperature);
    if (Number.isNaN(tempValue)) {
        return;
    }

    let successCount = 0;
    let failCount = 0;

    for (const sn of sns) {
        try {
            const data = await apiJson('/api/res/device_temp', jsonOptions('POST', {sn, temperature: tempValue}));
            if (!data.success) {
                throw new Error(data.message || '按温度设置失败');
            }

            const {resistanceText, temperatureText} = applyResDeviceStatus(sn, data);
            appendResLog(sn, 'temp', resistanceText, temperatureText);
            successCount += 1;
        } catch (error) {
            failCount += 1;
            console.error(`设备 ${sn} 按温度设置失败`, error);
        }
    }

    if (failCount === 0) {
        showToast(`已为 ${successCount} 台设备设置 ${tempValue}℃`, 'success', 3000);
    } else {
        showToast(`温度设置完成: 成功 ${successCount} 台，失败 ${failCount} 台`, 'info', 3600);
    }
}

async function resDeleteSelected() {
    const sns = Array.from(appState.selectedDevices);
    if (sns.length === 0) {
        showToast('请先选择要删除的设备。', 'info', 2200);
        return;
    }

    if (!window.confirm(`确定要删除选中的 ${sns.length} 个设备吗？`)) {
        return;
    }

    let successCount = 0;
    for (const sn of sns) {
        try {
            const data = await apiJson(`/api/res/devices/${encodeURIComponent(sn)}`, {method: 'DELETE'});
            if (data.success) {
                successCount += 1;
            }
        } catch (error) {
            console.error(`删除设备 ${sn} 失败`, error);
        }
    }

    appState.selectedDevices.clear();
    await resLoadDevices();
    showToast(`已删除 ${successCount} 台设备`, 'success', 2400);
}

async function resSetDeviceValue(sn, type) {
    if (!appState.resSerialConnected) {
        showToast('请先连接电阻串口。', 'info', 2400);
        return;
    }

    const key = deviceDomId(sn);
    const input = $id(type === 'value' ? `res-input-${key}` : `res-temp-${key}`);
    if (!input || !input.value) {
        return;
    }

    try {
        const payload = type === 'value'
            ? {sn, value: input.value}
            : {sn, temperature: Number.parseFloat(input.value)};
        const endpoint = type === 'value' ? '/api/res/device_value' : '/api/res/device_temp';
        const data = await apiJson(endpoint, jsonOptions('POST', payload));

        if (!data.success) {
            throw new Error(data.message || '设置失败');
        }

        const {resistanceText, temperatureText} = applyResDeviceStatus(sn, data);
        appendResLog(sn, type, resistanceText, temperatureText);
        input.value = '';
    } catch (error) {
        console.error('设置设备值失败', error);
        showToast(`设置失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

function applyResDeviceStatus(sn, data) {
    const resistanceText = data.current_resistance || '--';
    const temperatureText = data.current_temperature_display || '--';

    const target = appState.devices.find((device) => device.sn === sn);
    if (target) {
        target.current_resistance = resistanceText;
        target.current_temperature_display = temperatureText;
        if (typeof data.current_temperature !== 'undefined') {
            target.current_temperature = data.current_temperature;
        }
        if (typeof data.connected !== 'undefined') {
            target.connected = data.connected;
        } else {
            target.connected = true;
        }
    }

    const key = deviceDomId(sn);
    setText(`res-display-r-${key}`, resistanceText);

    const tempEl = $id(`res-display-t-${key}`);
    if (tempEl) {
        tempEl.textContent = appState.page === 'workspace'
            ? `T: ${temperatureText}`
            : temperatureText;
    }

    return {resistanceText, temperatureText};
}

function appendResLog(sn, type, resistanceText, temperatureText) {
    const logEl = $id('res-log');
    if (!logEl) {
        return;
    }

    const device = appState.devices.find((item) => item.sn === sn);
    const deviceName = device ? device.name : sn;
    const valueText = type === 'temp'
        ? `T=${temperatureText} (${resistanceText})`
        : `R=${resistanceText}`;

    const line = document.createElement('div');
    line.className = 'log-line';
    line.textContent = `[${new Date().toLocaleTimeString()}] ${deviceName}: ${valueText}`;
    logEl.appendChild(line);
    logEl.scrollTop = logEl.scrollHeight;
}

async function saveDeviceOrder() {
    try {
        await apiJson('/api/res/devices/order', jsonOptions('POST', {
            order: appState.devices.map((device) => device.sn),
        }));
    } catch (error) {
        console.error('保存设备顺序失败', error);
        showToast(`保存设备顺序失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

function clearResLog() {
    const logEl = $id('res-log');
    if (logEl) {
        logEl.innerHTML = '<div class="placeholder">日志记录...</div>';
    }
}

function showContextMenu(event, sn) {
    const menu = $id('context-menu');
    if (!menu) {
        return;
    }

    appState.contextMenuSN = sn;
    menu.style.display = 'block';

    const gap = 12;
    const menuWidth = menu.offsetWidth || 140;
    const menuHeight = menu.offsetHeight || 92;
    const left = Math.min(event.clientX, window.innerWidth - menuWidth - gap);
    const top = Math.min(event.clientY, window.innerHeight - menuHeight - gap);

    menu.style.left = `${Math.max(gap, left)}px`;
    menu.style.top = `${Math.max(gap, top)}px`;
}

function closeContextMenu() {
    const menu = $id('context-menu');
    if (menu) {
        menu.style.display = 'none';
    }
}

function resRenameDeviceFromMenu() {
    if (!appState.contextMenuSN) {
        return;
    }

    const device = appState.devices.find((item) => item.sn === appState.contextMenuSN);
    if (!device) {
        closeContextMenu();
        return;
    }

    setValue('rename-input', device.name);
    const modal = $id('rename-modal');
    if (modal) {
        modal.style.display = 'flex';
    }

    closeContextMenu();

    const input = $id('rename-input');
    if (input) {
        input.focus();
        input.select();
    }
}

async function resDeleteDeviceFromMenu() {
    if (!appState.contextMenuSN) {
        return;
    }

    if (!window.confirm('确定要删除这个设备吗？')) {
        closeContextMenu();
        return;
    }

    try {
        const data = await apiJson(`/api/res/devices/${encodeURIComponent(appState.contextMenuSN)}`, {method: 'DELETE'});
        if (!data.success) {
            throw new Error(data.message || '删除失败');
        }

        appState.selectedDevices.delete(appState.contextMenuSN);
        await resLoadDevices();
        showToast('设备已删除', 'success', 2200);
    } catch (error) {
        console.error('删除设备失败', error);
        showToast(`删除设备失败: ${error.message || '未知错误'}`, 'error', 3600);
    }

    closeContextMenu();
}

function closeRenameModal() {
    const modal = $id('rename-modal');
    if (modal) {
        modal.style.display = 'none';
    }
    appState.contextMenuSN = null;
}

async function saveRename() {
    const input = $id('rename-input');
    if (!input || !appState.contextMenuSN) {
        closeRenameModal();
        return;
    }

    const newName = input.value.trim();
    if (!newName) {
        closeRenameModal();
        return;
    }

    try {
        const data = await apiJson(
            `/api/res/devices/${encodeURIComponent(appState.contextMenuSN)}`,
            jsonOptions('PUT', {name: newName})
        );
        if (!data.success) {
            throw new Error(data.message || '重命名失败');
        }

        await resLoadDevices();
        showToast('设备名称已更新', 'success', 2200);
    } catch (error) {
        console.error('重命名设备失败', error);
        showToast(`重命名失败: ${error.message || '未知错误'}`, 'error', 3600);
    }

    closeRenameModal();
}

async function powerRefreshResources() {
    const select = $id('power-address');
    if (!select) {
        return;
    }

    try {
        const data = await apiJson('/api/power/list_resources');
        const current = appState.connection.powerAddress || select.value;

        select.innerHTML = '<option value="">请选择电源...</option>';
        (data.resources || []).forEach((item) => {
            const address = typeof item === 'string' ? item : (item.address || '');
            const label = typeof item === 'string' ? item : (item.label || address);
            if (!address) {
                return;
            }

            const option = document.createElement('option');
            option.value = address;
            option.textContent = label;
            select.appendChild(option);
        });

        ensureOption(select, current);
        if (current) {
            select.value = current;
        }
    } catch (error) {
        console.error('获取电源资源失败', error);
        showToast(`获取电源资源失败: ${error.message || '未知错误'}`, 'error', 3600);
    } finally {
        powerAddressChanged();
    }
}

function powerAddressChanged() {
    const select = $id('power-address');
    const button = $id('btn-power-connect');
    if (!select || !button) {
        return;
    }

    button.disabled = !appState.powerConnected && !select.value;
}

async function powerToggleConnect() {
    if (appState.powerConnected) {
        await powerDisconnect();
    } else {
        await powerConnect();
    }
}

async function powerConnect() {
    const select = $id('power-address');
    if (!select || !select.value) {
        return;
    }

    try {
        const data = await apiJson('/api/power/connect', jsonOptions('POST', {address: select.value}));
        if (!data.success) {
            throw new Error(data.message || '连接失败');
        }

        applyPowerState({connected: true, address: select.value});
        showToast('电源已连接', 'success', 2400);
    } catch (error) {
        console.error('连接电源失败', error);
        showToast(`连接电源失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

async function powerDisconnect() {
    try {
        const data = await apiJson('/api/power/disconnect', {method: 'POST'});
        if (!data.success) {
            throw new Error(data.message || '断开失败');
        }

        applyPowerState({connected: false, address: null});
        showToast('电源已断开', 'info', 2200);
    } catch (error) {
        console.error('断开电源失败', error);
        showToast(`断开电源失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

async function powerSetParams() {
    if (!appState.powerConnected) {
        showToast('请先在设备管理页连接电源。', 'info', 2400);
        return;
    }

    const voltageValue = $id('power-voltage') ? $id('power-voltage').value : '';
    const currentValue = $id('power-current') ? $id('power-current').value : '';
    const payload = {};

    if (voltageValue !== '') {
        payload.voltage = Number.parseFloat(voltageValue);
    }
    if (currentValue !== '') {
        payload.current = Number.parseFloat(currentValue);
    }

    try {
        await apiJson('/api/power/set', jsonOptions('POST', payload));
    } catch (error) {
        console.error('设置电源参数失败', error);
        showToast(`设置电源参数失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

async function powerSetOutput(on) {
    if (!appState.powerConnected) {
        showToast('请先在设备管理页连接电源。', 'info', 2400);
        return;
    }

    try {
        await apiJson('/api/power/set', jsonOptions('POST', {output: on}));
    } catch (error) {
        console.error('设置电源输出失败', error);
        showToast(`设置电源输出失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

async function powerMeasure() {
    if (!appState.powerConnected) {
        return;
    }

    try {
        const data = await apiJson('/api/power/measure');
        if (!data.error && typeof data.voltage === 'number' && typeof data.current === 'number') {
            setText('power-measure', `${data.voltage.toFixed(4)} V, ${data.current.toFixed(4)} A`);
        }
    } catch (error) {
        console.error('测量电源失败', error);
    }
}

function startPowerAutoRefresh() {
    stopPowerAutoRefresh();

    if (appState.page !== 'workspace' || !appState.powerConnected) {
        return;
    }

    powerMeasure();
    powerRefreshTimer = setInterval(powerMeasure, 1000);
}

function stopPowerAutoRefresh() {
    if (powerRefreshTimer) {
        clearInterval(powerRefreshTimer);
        powerRefreshTimer = null;
    }
}

function scopeSerialChanged() {
    const input = $id('scope-serial');
    const button = $id('btn-scope-connect');
    if (!input || !button) {
        return;
    }

    button.disabled = !appState.scopeConnected && !input.value.trim();
}

async function scopeToggleConnect() {
    if (appState.scopeConnected) {
        await scopeDisconnect();
    } else {
        await scopeConnect();
    }
}

async function scopeConnect() {
    const input = $id('scope-serial');
    if (!input || !input.value.trim()) {
        return;
    }

    const serial = input.value.trim();

    try {
        const data = await apiJson('/api/scope/connect', jsonOptions('POST', {serial}));
        if (!data.success) {
            throw new Error(data.message || '连接失败');
        }

        applyScopeState({
            connected: true,
            serial,
            locked: typeof data.locked === 'boolean' ? data.locked : false,
        });

        if (appState.page === 'workspace') {
            await scopeSyncChannelState(true);
        }

        showToast(
            appState.scopeLocked ? '示波器已连接，当前为远程锁定状态' : '示波器已连接，本地控制已解锁',
            'success',
            2400
        );
    } catch (error) {
        console.error('连接示波器失败', error);
        showToast(`连接示波器失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

async function scopeDisconnect() {
    try {
        const data = await apiJson('/api/scope/disconnect', {method: 'POST'});
        if (!data.success) {
            throw new Error(data.message || '断开失败');
        }

        applyScopeState({connected: false, serial: null});
        showToast('示波器已断开', 'info', 2200);
    } catch (error) {
        console.error('断开示波器失败', error);
        showToast(`断开示波器失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

async function scopeToggleLock() {
    if (!appState.scopeConnected) {
        showToast('请先在设备管理页连接示波器。', 'info', 2400);
        return;
    }

    try {
        const endpoint = appState.scopeLocked ? '/api/scope/unlock' : '/api/scope/lock';
        const data = await apiJson(endpoint, {method: 'POST'});
        if (!data.success) {
            throw new Error(data.message || '操作失败');
        }

        appState.scopeLocked = !appState.scopeLocked;
        toggleScopeWorkspaceControls(appState.scopeConnected);
        updateScopeHint();
        await scopeSyncChannelState(true);
        checkAllChannelsClosed();

        showToast(
            appState.scopeLocked ? '示波器已锁定为远程控制' : '示波器已解锁，本地面板可直接操作',
            'info',
            2600
        );
    } catch (error) {
        console.error('切换示波器锁定失败', error);
        showToast(`切换示波器锁定失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

async function scopeCopyScreenshot() {
    if (!appState.scopeConnected) {
        showToast('请先在设备管理页连接示波器。', 'info', 2400);
        return;
    }

    const button = $id('btn-scope-copy');
    if (!button) {
        return;
    }

    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = '复制中...';
    stopAutoRefresh();

    try {
        const data = await apiJson('/api/scope/copy_screenshot', {method: 'POST'});
        if (!data.success) {
            throw new Error(data.message || '截图失败');
        }

        const imageResponse = await fetch(data.download_url, {method: 'GET', cache: 'no-store'});
        if (!imageResponse.ok) {
            throw new Error('获取截图文件失败');
        }

        const imageBlob = await imageResponse.blob();
        let copied = false;
        let copyFailReason = '';

        if (window.isSecureContext && navigator.clipboard && window.ClipboardItem) {
            try {
                const mimeType = imageBlob.type || 'image/png';
                const item = new ClipboardItem({[mimeType]: imageBlob});
                await navigator.clipboard.write([item]);
                copied = true;
            } catch (error) {
                copyFailReason = error && error.message ? error.message : '浏览器未授权图片剪贴板';
            }
        } else if (!window.isSecureContext) {
            copyFailReason = '当前页面不是 HTTPS/localhost，浏览器禁止直接写入系统剪贴板';
        } else {
            copyFailReason = '当前浏览器不支持图片剪贴板 API';
        }

        if (copied) {
            showToast(`示波器截图已复制到当前电脑剪贴板\n保存路径: ${data.filepath}`, 'success', 3800);
            return;
        }

        const filename = data.filename || 'scope_screenshot.png';
        const localUrl = URL.createObjectURL(imageBlob);
        const link = document.createElement('a');
        link.href = localUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(localUrl), 1000);

        showToast(
            `截图已下载到当前电脑（未写入剪贴板）\n原因: ${copyFailReason || '未知原因'}\n服务端保存路径: ${data.filepath}`,
            'info',
            5200
        );
    } catch (error) {
        console.error('复制示波器截图失败', error);
        showToast(`复制示波器截图失败: ${error.message || '未知错误'}`, 'error', 4200);
    } finally {
        button.textContent = originalText;
        button.disabled = !appState.scopeConnected;
        if (appState.scopeConnected) {
            checkAllChannelsClosed();
        }
    }
}

async function scopeUpdateInterval() {
    const intervalInput = $id('scope-interval');
    if (!intervalInput) {
        return;
    }

    const interval = Number.parseInt(intervalInput.value, 10) || 1000;

    try {
        await apiJson('/api/scope/config', jsonOptions('POST', {refresh_interval: interval}));
    } catch (error) {
        console.error('更新示波器刷新周期失败', error);
    }

    if (appState.scopeConnected) {
        checkAllChannelsClosed();
    }
}

async function scopeSyncChannelState() {
    if (!appState.scopeConnected) {
        return;
    }

    try {
        const data = await apiJson('/api/scope/channel_state');
        const channels = data.channels || {};

        for (let channel = 1; channel <= 4; channel += 1) {
            const enabled = Boolean(channels[`ch${channel}`]);
            appState.scopeChannelStates[channel] = enabled;
            updateChannelStyle(channel, enabled);
        }

        checkAllChannelsClosed();
    } catch (error) {
        console.error('获取示波器通道状态失败', error);
    }
}

function updateChannelStyle(channel, enabled) {
    const card = $id(`scope-ch${channel}`);
    if (!card) {
        return;
    }

    card.classList.toggle('disabled', !enabled);
    card.classList.toggle('disconnected', !appState.scopeConnected);

    const labelEl = card.querySelector('.ch-label');
    if (labelEl) {
        labelEl.style.color = enabled && appState.scopeConnected ? '#11211f' : '#87908d';
    }

    const valueEl = card.querySelector('.ch-value');
    if (valueEl && !enabled) {
        valueEl.textContent = '--';
    }
}

async function scopeToggleChannel(channel) {
    if (!appState.scopeConnected) {
        return;
    }

    const previousState = Boolean(appState.scopeChannelStates[channel]);
    const nextState = !previousState;
    appState.scopeChannelStates[channel] = nextState;
    updateChannelStyle(channel, nextState);

    try {
        const data = await apiJson('/api/scope/channel', jsonOptions('POST', {channel, enable: nextState}));
        if (!data.success) {
            throw new Error(data.message || '设置失败');
        }

        await syncScopeConfigChannels();
        checkAllChannelsClosed();
    } catch (error) {
        console.error('设置示波器通道开关失败', error);
        appState.scopeChannelStates[channel] = previousState;
        updateChannelStyle(channel, previousState);
        showToast(`设置通道 CH${channel} 失败: ${error.message || '未知错误'}`, 'error', 3600);
    }
}

async function syncScopeConfigChannels() {
    try {
        await apiJson('/api/scope/config', jsonOptions('POST', {
            channels: Object.keys(appState.scopeChannelStates)
                .filter((channel) => appState.scopeChannelStates[channel])
                .map((channel) => Number(channel)),
        }));
    } catch (error) {
        console.error('同步示波器通道配置失败', error);
    }
}

function checkAllChannelsClosed() {
    if (appState.page !== 'workspace' || !appState.scopeConnected) {
        stopAutoRefresh();
        return;
    }

    const anyOpen = Object.values(appState.scopeChannelStates).some(Boolean);
    if (anyOpen) {
        startAutoRefresh();
    } else {
        stopAutoRefresh();
    }
}

async function scopeGetMean() {
    if (!appState.scopeConnected) {
        return;
    }

    try {
        const data = await apiJson('/api/scope/get_mean');
        if (!data.channels) {
            return;
        }

        for (let channel = 1; channel <= 4; channel += 1) {
            const valueEl = document.querySelector(`#scope-ch${channel} .ch-value`);
            if (!valueEl) {
                continue;
            }

            if (!appState.scopeChannelStates[channel]) {
                valueEl.textContent = '--';
                continue;
            }

            const rawValue = data.channels[`ch${channel}`];
            if (rawValue === null || rawValue === undefined || Number.isNaN(rawValue)) {
                valueEl.textContent = '--';
            } else {
                valueEl.textContent = Number(rawValue).toFixed(3);
            }
        }
    } catch (error) {
        console.error('获取示波器平均值失败', error);
    }
}

function startAutoRefresh() {
    stopAutoRefresh();

    if (appState.page !== 'workspace' || !appState.scopeConnected) {
        return;
    }

    const intervalInput = $id('scope-interval');
    const interval = intervalInput ? (Number.parseInt(intervalInput.value, 10) || 1000) : 1000;

    scopeGetMean();
    scopeRefreshTimer = setInterval(scopeGetMean, interval);
}

function stopAutoRefresh() {
    if (scopeRefreshTimer) {
        clearInterval(scopeRefreshTimer);
        scopeRefreshTimer = null;
    }
}
