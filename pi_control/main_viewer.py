#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raspberry Pi Web 監控檢視器 (Viewer Mode)
基於 main_new.py 修改，移除所有控制功能，僅保留監控檢視
"""

from flask import Flask, render_template_string, jsonify, request, send_file, make_response
import paramiko
import json
import time
import threading
from typing import List, Dict, Optional
from datetime import datetime
import subprocess
import platform
from io import BytesIO, StringIO
import os

from concurrent.futures import ThreadPoolExecutor 

# 導入時數追蹤模組
from time_tracker import TimeTracker
# 導入數據匯出模組
from data_exporter import DataExporter

app = Flask(__name__)

class RPiController:
    """Raspberry Pi 控制器（整合時數追蹤）"""
    
    def __init__(self, config_file: str = "hosts.json"):
        self.config_file = config_file
        self.devices = self.load_config()
        
        # 整合時數追蹤器
        self.time_tracker = TimeTracker()
        
        # 初始化數據匯出器
        self.exporter = DataExporter()
        
        # 啟動自動保存線程
        self.start_auto_save()
        
    def load_config(self) -> List[Dict]:
        """載入設備配置"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    
    def reload_config(self) -> Dict:
        """重新載入配置並返回結果"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.devices = json.load(f)
            return {'success': True, 'message': f'已重新載入 {len(self.devices)} 台設備'}
        except Exception as e:
            return {'success': False, 'message': f'設定檔錯誤: {str(e)}'}

    def start_auto_save(self):
        """啟動自動保存線程（每5分鐘）"""
        def auto_save():
            while True:
                time.sleep(300)  # 5分鐘
                self.time_tracker.save_data()
                print(f"💾 自動保存 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        thread = threading.Thread(target=auto_save, daemon=True)
        thread.start()
    
    def connect_ssh(self, device: Dict, timeout: int = 10) -> Optional[paramiko.SSHClient]:
        """建立 SSH 連接"""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=device['ip'],
                username=device['user'],
                password=device['password'],
                timeout=timeout,
                banner_timeout=30
            )
            return client
        except:
            return None
    
    def check_online(self, device: Dict) -> bool:
        """檢查設備是否在線"""
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', param, '1', '-W', '1', device['ip']]
        try:
            result = subprocess.run(command, capture_output=True, timeout=2)
            return result.returncode == 0
        except:
            return False
    
    def check_process_running(self, device: Dict) -> bool:
        """檢查應用程式是否運行"""
        client = self.connect_ssh(device, timeout=5)
        if not client:
            return False
        try:
            keyword = device.get('process_keyword', 'pdf_viewer')
            command = f"pgrep -f '{keyword}'"
            stdin, stdout, stderr = client.exec_command(command)
            output = stdout.read().decode('utf-8').strip()
            return bool(output)
        except:
            return False
        finally:
            client.close()
    
    def get_device_status(self, device: Dict) -> Dict:
        """獲取設備狀態（整合時數追蹤）"""
        online = self.check_online(device)
        running = self.check_process_running(device) if online else False
        
        # 確定狀態
        if running:
            status = 'running'
        elif online:
            status = 'online'
        else:
            status = 'offline'
        
        # 更新時數追蹤
        self.time_tracker.update_status(device['name'], status)
        
        # 獲取時數統計
        stats = self.time_tracker.get_device_stats(device['name'])
        
        return {
            'name': device['name'],
            'ip': device['ip'],
            'online': online,
            'app_running': running,
            'status': status,
            'script': device.get('script_path', '').split('/')[-1],
            'stats': stats  # 添加時數統計
        }

# 全局控制器實例
controller = RPiController("hosts.json")

# HTML 模板（Viewer 版本：移除控制按鈕）
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Raspberry Pi 監控檢視器</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 10px;
        }
        
        .container { max-width: 95%; margin: 0 auto; }
        
        .header {
            background: white;
            border-radius: 12px;
            padding: 8px 10px;
            margin-bottom: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        
        h1 { color: #667eea; font-size: 1.2em; margin-bottom: 4px; }
        
        .uptime {
            color: #6b7280;
            font-size: 0.8em;
            margin: 2px 0;
        }
        
        .uptime strong { color: #667eea; }
        
        .stats {
            display: flex;
            gap: 8px;
            margin-top: 5px;
            flex-wrap: wrap;
        }
        
        .stat-box {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 5px 10px;
            border-radius: 8px;
            flex: 1;
            min-width: 100px;
            text-align: center;
        }
        
        .stat-number { font-size: 1.2em; font-weight: bold; }
        .stat-label { font-size: 0.85em; opacity: 0.9; margin-top: 3px; }
        
        .controls {
            background: white;
            border-radius: 12px;
            padding: 6px 8px;
            margin-bottom: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        
        .control-layout {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }

        .left-panel {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .view-toggle { display: flex; gap: 4px; margin-bottom: 0; }
        
        .toggle-btn {
            padding: 4px 8px;
            border: 2px solid #667eea;
            background: white;
            color: #667eea;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            font-size: 11px;
            transition: all 0.3s;
        }
        
        .toggle-btn.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .devices-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 5px;
        }
        
        .device-card {
            background: white;
            border-radius: 8px;
            padding: 6px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.2);
            transition: all 0.3s;
        }
        
        .device-card:hover { transform: translateY(-2px); box-shadow: 0 12px 32px rgba(0,0,0,0.3); }
        
        .device-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        
        .device-name { font-size: 0.9em; font-weight: bold; color: #1f2937; }
        
        .status-badge {
            padding: 3px 8px;
            border-radius: 16px;
            font-size: 0.65em;
            font-weight: 600;
        }
        
        .status-running { background: #d1fae5; color: #065f46; }
        .status-online { background: #fef3c7; color: #92400e; }
        .status-offline { background: #fee2e2; color: #991b1b; }
        
        .device-info {
            color: #6b7280;
            font-size: 0.7em;
            margin: 6px 0;
            line-height: 1.3;
        }
        
        .device-stats {
            background: #f9fafb;
            border-radius: 4px;
            padding: 5px;
            margin: 6px 0;
            font-size: 0.65em;
            line-height: 1.5;
        }
        
        .stats-row {
            display: flex;
            justify-content: space-between;
            margin: 2px 0;
        }
        
        .stats-label { color: #6b7280; font-weight: 600; }
        .stats-value { color: #1f2937; font-weight: 500; font-family: 'Courier New', monospace; }
        
        .stats-running { color: #065f46; }
        .stats-online { color: #92400e; }
        .stats-offline { color: #991b1b; }
        
        .toast {
            position: fixed;
            top: 20px;
            right: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            z-index: 1000;
            animation: slideIn 0.3s ease-out;
        }
        
        @keyframes slideIn {
            from { transform: translateX(400px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        
        @media (max-width: 1800px) { .devices-grid { grid-template-columns: repeat(4, 1fr); } }
        @media (max-width: 1600px) { .devices-grid { grid-template-columns: repeat(3, 1fr); } }
        @media (max-width: 1200px) { .devices-grid { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 600px) { .devices-grid { grid-template-columns: 1fr; } }
        
        /* List View Styles */
        .devices-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 5px; }
        .list-header {
            display: none;
        }
        .device-list-item {
            background: white;
            border-radius: 8px;
            padding: 4px 10px;
            display: grid;
            grid-template-columns: 200px 120px 1fr 200px;
            align-items: center;
            gap: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }

        @media (max-width: 1200px) {
            .devices-list { grid-template-columns: 1fr; }
        }
        @media (max-width: 800px) {
            .device-list-item { grid-template-columns: 1fr; gap: 8px; padding: 15px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🖥️ Raspberry Pi 監控檢視器</h1>
            <div class="uptime">
                📊 監控運行: <strong id="uptime">00:00:00</strong> | 
                啟動時間: <strong id="start-time">載入中...</strong>
            </div>
            <div class="stats">
                <div class="stat-box">
                    <div class="stat-number" id="total-devices">{{ total }}</div>
                    <div class="stat-label">總設備數</div>
                </div>
                <div class="stat-box">
                    <div class="stat-number" id="online-devices">0</div>
                    <div class="stat-label">在線設備</div>
                </div>
                <div class="stat-box">
                    <div class="stat-number" id="running-apps">0</div>
                    <div class="stat-label">運行中</div>
                </div>
            </div>
        </div>
        
        <div class="controls">
            <div class="control-layout">
            	<div class="left-panel">
                    <div class="view-toggle">
                        <button class="toggle-btn active" id="btn-grid-view" onclick="switchView('grid')">
                            📊 卡片檢視
                        </button>
                        <button class="toggle-btn" id="btn-list-view" onclick="switchView('list')">
                            📋 清單檢視
                        </button>
                    </div>
                </div>    
            </div>    
        </div>
        
        <div class="devices-grid" id="devices-grid"></div>
    </div>
    
    <script>
        let devicesData = [];
        let currentView = 'grid';
        
        async function loadDevices() {
            try {
                const response = await fetch('/api/devices');
                devicesData = await response.json();
                renderDevices();
                updateStats();
                updateUptime();
            } catch (error) {
                showToast('載入設備失敗: ' + error.message, 'error');
            }
        }
        
        function renderDevices() {
            const grid = document.getElementById('devices-grid');
            
            if (currentView === 'list') {
                grid.className = 'devices-list';
                const header = `
                    <div class="list-header">
                        <div>設備名稱</div>
                        <div>狀態</div>
                        <div>IP / 腳本</div>
                        <div>統計 (運/在/離)</div>
                    </div>`;
                
                const items = devicesData.map((device, index) => `
                    <div class="device-list-item">
                        <div class="list-col-name">
                            <label style="font-weight:bold;">${device.name}</label>
                        </div>
                        <div class="list-col-status">
                            <span class="status-badge status-${device.status}">
                                ${getStatusText(device.status)}
                            </span>
                        </div>
                        <div class="list-col-info" style="font-size:0.85em; color:#666;">
                            ${device.ip}<br>
                            <span style="opacity:0.8">${device.script || '-'}</span>
                        </div>
                        <div class="list-col-stats" style="font-family:monospace; font-size:0.85em;">
                            <div style="color:#065f46">▶️ 運行:${device.stats.running}</div>
                            <div style="color:#92400e">🟡 在線:${device.stats.online}</div>
                            <div style="color:#991b1b">🔴 離線:${device.stats.offline}</div>
                        </div>
                    </div>
                `).join('');
                
                grid.innerHTML = header + items;
            } else {
                grid.className = 'devices-grid';
                grid.innerHTML = devicesData.map((device, index) => `
                    <div class="device-card">
                        <div class="device-header">
                            <div>
                                <label class="device-name">${device.name}</label>
                            </div>
                            <span class="status-badge status-${device.status}">
                                ${getStatusText(device.status)}
                            </span>
                        </div>
                        <div class="device-info">
                            📍 ${device.ip}<br>
                            📄 ${device.script || 'N/A'}
                        </div>
                        <div class="device-stats">
                            <div class="stats-row">
                                <span class="stats-label stats-running">▶️ 運行:</span>
                                <span class="stats-value stats-running">${device.stats.running}</span>
                            </div>
                            <div class="stats-row">
                                <span class="stats-label stats-online">🟡 在線:</span>
                                <span class="stats-value stats-online">${device.stats.online}</span>
                            </div>
                            <div class="stats-row">
                                <span class="stats-label stats-offline">🔴 離線:</span>
                                <span class="stats-value stats-offline">${device.stats.offline}</span>
                            </div>
                        </div>
                    </div>
                `).join('');
            }
        }
        
        function getStatusText(status) {
            const map = { 'running': '✅ 運行中', 'online': '🟡 在線', 'offline': '🔴 離線' };
            return map[status] || status;
        }
        
        function updateStats() {
            const online = devicesData.filter(d => d.online).length;
            const running = devicesData.filter(d => d.app_running).length;
            document.getElementById('online-devices').textContent = online;
            document.getElementById('running-apps').textContent = running;
        }
        
        async function updateUptime() {
            try {
                const response = await fetch('/api/uptime');
                const data = await response.json();
                document.getElementById('uptime').textContent = data.uptime;
                document.getElementById('start-time').textContent = data.start_time;
            } catch (error) {
                console.error('更新運行時間失敗:', error);
            }
        }
        
        async function refreshStatus() {
            await loadDevices();
        }

        function switchView(view) {
            currentView = view;
            document.getElementById('btn-grid-view').classList.toggle('active', view === 'grid');
            document.getElementById('btn-list-view').classList.toggle('active', view === 'list');
            renderDevices();
        }
        
        function showToast(message, type = 'info') {
            const colors = {success: '#10b981', error: '#ef4444', warning: '#f59e0b', info: '#3b82f6'};
            const toast = document.createElement('div');
            toast.className = 'toast';
            toast.style.borderLeft = `5px solid ${colors[type]}`;
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }
        
        // 初始載入
        loadDevices();
        setInterval(refreshStatus, 30000); // 每30秒自動更新
        setInterval(updateUptime, 1000); // 每秒更新運行時間
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """主頁面"""
    return render_template_string(HTML_TEMPLATE, total=len(controller.devices))

@app.route('/api/devices')
def get_devices():
    """獲取所有設備狀態（多線程優化）"""
    # 使用 ThreadPoolExecutor 來並行執行 get_device_status
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(controller.get_device_status, controller.devices))
    return jsonify(results)

@app.route('/api/uptime')
def get_uptime():
    """獲取系統運行時間"""
    return jsonify({
        'uptime': controller.time_tracker.get_uptime(),
        'start_time': controller.time_tracker.get_start_time()
    })

if __name__ == '__main__':
    import sys
    
    # 允許通過命令行參數指定端口
    port = 8081  # Viewer 預設使用 8081 避免衝突
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("❌ 無效的端口號，使用預設端口 8081")
    
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║     Raspberry Pi 監控檢視器 (Viewer) 已啟動               ║
║                                                           ║
║     訪問地址: http://localhost:{port}                      
║     區域網路: http://你的樹莓派IP:{port}                   
║                                                           ║
║     監控 {len(controller.devices)} 台設備                                        
╚═══════════════════════════════════════════════════════════╝

提示：
  - 如需更改端口，請使用: python3 main_viewer.py 端口號
  - 按 Ctrl+C 停止服務
    """)
    
    try:
        app.run(host='0.0.0.0', port=port, debug=True)
    except OSError as e:
        print(f"❌ 啟動失敗：{e}")
        sys.exit(1)