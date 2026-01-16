#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raspberry Pi Web 控制介面（整合時數追蹤）
在原有 main_new.py 基礎上添加時數統計功能
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
    
    def start_application(self, device: Dict, pdf_file: str = None) -> Dict:
        """啟動應用程式 (可選: 上傳並開啟 PDF)"""
        client = self.connect_ssh(device)
        if not client:
            return {'success': False, 'message': '無法連接到設備'}
        
        try:
            cmd_suffix = ""
            # 如果有指定 PDF 檔案，先上傳到遠端
            if pdf_file and pdf_file.strip():
                if not os.path.exists(pdf_file):
                    client.close()
                    return {'success': False, 'message': f'找不到本機檔案: {pdf_file}'}
                
                try:
                    filename = os.path.basename(pdf_file)
                    remote_path = f"/home/{device['user']}/{filename}"
                    
                    sftp = client.open_sftp()
                    sftp.put(pdf_file, remote_path)
                    sftp.close()
                    
                    cmd_suffix = f" '{remote_path}'"
                except Exception as e:
                    client.close()
                    return {'success': False, 'message': f'檔案傳輸失敗: {str(e)}'}

            if self.check_process_running(device):
                client.close()
                if pdf_file:
                    return {'success': False, 'message': '應用程式已在運行，請使用「重啟應用」來載入新檔案'}
                return {'success': True, 'message': '應用程式已在運行'}
            
            venv_activate = device.get('venv_activate', '')
            script_path = device['script_path']
            display = device.get('display', ':0')
            
            if venv_activate and venv_activate != "true":
                # 優化：嘗試直接使用 venv 的 python 執行檔，比 source activate 更穩定
                if venv_activate.endswith('/bin/activate'):
                    python_exec = venv_activate.replace('/bin/activate', '/bin/python3')
                    command = f"export DISPLAY={display} && nohup {python_exec} {script_path}{cmd_suffix} > /dev/null 2>&1 &"
                else:
                    # 回退到 source 方式 (將 source 改為 . 以提高兼容性)
                    command = f"export DISPLAY={display} && . {venv_activate} && nohup python3 {script_path}{cmd_suffix} > /dev/null 2>&1 &"
            else:
                if script_path.endswith('.sh'):
                    command = f"export DISPLAY={display} && nohup bash {script_path}{cmd_suffix} > /dev/null 2>&1 &"
                else:
                    command = f"export DISPLAY={display} && nohup python3 {script_path}{cmd_suffix} > /dev/null 2>&1 &"
            
            stdin, stdout, stderr = client.exec_command(command)
            time.sleep(2)
            
            if self.check_process_running(device):
                return {'success': True, 'message': '應用程式啟動成功'}
            else:
                return {'success': False, 'message': '應用程式啟動失敗'}
        except Exception as e:
            return {'success': False, 'message': f'錯誤: {str(e)}'}
        finally:
            client.close()
    
    def stop_application(self, device: Dict) -> Dict:
        """停止應用程式"""
        client = self.connect_ssh(device)
        if not client:
            return {'success': False, 'message': '無法連接到設備'}
        
        try:
            keyword = device.get('process_keyword', 'pdf_viewer')
            command = f"pkill -f '{keyword}'"
            stdin, stdout, stderr = client.exec_command(command)
            time.sleep(1)
            
            if not self.check_process_running(device):
                return {'success': True, 'message': '應用程式已停止'}
            else:
                return {'success': False, 'message': '停止失敗'}
        except Exception as e:
            return {'success': False, 'message': f'錯誤: {str(e)}'}
        finally:
            client.close()
    
    def restart_application(self, device: Dict, pdf_file: str = None) -> Dict:
        """重啟應用程式"""
        self.stop_application(device)
        
        # 等待程序確實停止 (最多等待 5 秒)
        for _ in range(5):
            if not self.check_process_running(device):
                break
            time.sleep(1)
            
        return self.start_application(device, pdf_file)
    
    def reboot_device(self, device: Dict) -> Dict:
        """重啟設備"""
        client = self.connect_ssh(device)
        if not client:
            return {'success': False, 'message': '無法連接到設備'}
        
        try:
            stdin, stdout, stderr = client.exec_command('sudo reboot')
            return {'success': True, 'message': '重啟命令已發送'}
        except Exception as e:
            return {'success': False, 'message': f'錯誤: {str(e)}'}
        finally:
            client.close()
    
    def shutdown_device(self, device: Dict) -> Dict:
        """關閉設備"""
        client = self.connect_ssh(device)
        if not client:
            return {'success': False, 'message': '無法連接到設備'}
        
        try:
            stdin, stdout, stderr = client.exec_command('sudo shutdown -h now')
            return {'success': True, 'message': '關機命令已發送'}
        except Exception as e:
            return {'success': False, 'message': f'錯誤: {str(e)}'}
        finally:
            client.close()

# 全局控制器實例
controller = RPiController("hosts.json")

# HTML 模板（包含時數顯示）
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Raspberry Pi 控制中心 - 時數追蹤</title>
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
        /* 建立左右佈局的容器 */
        .control-layout {
            display: flex;          /* 啟用彈性佈局 */
            justify-content: space-between; /* 左右對齊：一邊靠左，一邊靠右 */
            align-items: center;    /* 垂直置中對齊 */
            flex-wrap: wrap;        /* 螢幕太小時自動換行 */
            gap: 10px;              /* 左右兩區的間距 */
        }

        /* 左側區塊樣式：讓按鈕跟全選排成一排 */
            .left-panel {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* 右側區塊樣式：按鈕群組 */
            .right-panel {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
        }
        
        .control-buttons { display: flex; gap: 4px; flex-wrap: wrap; }
        
        .btn {
            padding: 4px 8px;
            border: none;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            color: white;
        }
        
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0,0,0,0.3); }
        
        .btn-start { background: #10b981; }
        .btn-stop { background: #ef4444; }
        .btn-restart { background: #f59e0b; }
        .btn-reboot { background: #8b5cf6; }
        .btn-shutdown { background: #6b7280; }
        .btn-refresh { background: #3b82f6; }
        .btn-export { background: #ec4899; }
        .btn-config { background: #6366f1; }
        
        .path-input {
            padding: 3px;
            border: 1px solid #ddd;
            border-radius: 6px;
            width: 300px;
            font-size: 12px;
            background: #f9fafb;
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
        
        .checkbox-group { margin: 10px 0; }
        .checkbox-label { display: inline-flex; align-items: center; margin-right: 15px; cursor: pointer; }
        .checkbox-label input { margin-right: 5px; }
        
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
        
        .stats-label {
            color: #6b7280;
            font-weight: 600;
        }
        
        .stats-value {
            color: #1f2937;
            font-weight: 500;
            font-family: 'Courier New', monospace;
        }
        
        .stats-running { color: #065f46; }
        .stats-online { color: #92400e; }
        .stats-offline { color: #991b1b; }
        
        .device-actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 5px;
            margin-top: 8px;
        }
        
        .device-btn {
            padding: 5px 8px;
            border: none;
            border-radius: 4px;
            font-size: 10px;
            cursor: pointer;
            transition: all 0.2s;
            font-weight: 500;
        }
        
        .hidden { display: none; }
        
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
            grid-template-columns: 200px 120px 1fr 200px 180px;
            align-items: center;
            gap: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        .list-col-actions { display: flex; gap: 5px; }

        @media (max-width: 1200px) {
            .devices-list { grid-template-columns: 1fr; }
        }
        @media (max-width: 800px) {
            .device-list-item { grid-template-columns: 1fr; gap: 8px; padding: 15px; }
            .list-col-actions { justify-content: flex-start; margin-top: 5px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🖥️ Raspberry Pi 控制中心 - 時數追蹤系統</h1>
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
            <h3 style="margin-bottom: 5px; font-size: 0.9em;">批次操作</h3>
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
                    <div class="checkbox-group">
                        <label class="checkbox-label">
                            <input type="file" id="pdf-file" class="path-input" accept=".pdf" style="margin-right: 20px;">
                        </label>
                    </div>
                </div>    
                <div class="right-panel">
                    <div class="checkbox-group">
                        <label class="checkbox-label">
                            <input type="checkbox" id="select-all" onchange="toggleSelectAll(this)">
                            全選
                        </label>
                    </div>
                    <div class="control-buttons">
                        <button class="btn btn-start" onclick="batchOperation('start')">▶️ 啟動選中</button>
                        <button class="btn btn-stop" onclick="batchOperation('stop')">⏹️ 停止選中</button>
                        <button class="btn btn-restart" onclick="batchOperation('restart')">🔄 重啟應用</button>
                        <button class="btn btn-reboot" onclick="batchOperation('reboot')">🔄 重啟設備</button>
                        <button class="btn btn-shutdown" onclick="batchOperation('shutdown')">⏻ 關機</button>
                        <button class="btn btn-refresh" onclick="refreshStatus()">🔄 重新整理</button>
                        <button class="btn btn-config" onclick="reloadConfig()">📂 載入設定</button>
                        <button class="btn btn-export" onclick="exportStats()">📊 匯出統計</button>
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
                        <div>操作</div>
                    </div>`;
                
                const items = devicesData.map((device, index) => `
                    <div class="device-list-item">
                        <div class="list-col-name">
                            <input type="checkbox" class="device-checkbox" data-index="${index}" 
                                   id="device-l-${index}" style="margin-right: 10px;">
                            <label for="device-l-${index}" style="font-weight:bold; cursor:pointer;">${device.name}</label>
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
                        <div class="list-col-actions">
                            <button class="device-btn btn-start" onclick="deviceAction('${device.name}', 'start')" title="啟動">▶️</button>
                            <button class="device-btn btn-stop" onclick="deviceAction('${device.name}', 'stop')" title="停止">⏹️</button>
                            <button class="device-btn btn-restart" onclick="deviceAction('${device.name}', 'restart')" title="重啟應用">🔄</button>
                            <button class="device-btn btn-reboot" onclick="deviceAction('${device.name}', 'reboot')" title="重啟設備">⚡</button>
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
                                <input type="checkbox" class="device-checkbox" data-index="${index}" 
                                       id="device-${index}" style="margin-right: 10px;">
                                <label for="device-${index}" class="device-name">${device.name}</label>
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
                        <div class="device-actions">
                            <button class="device-btn btn-start" onclick="deviceAction('${device.name}', 'start')">▶️ 啟動</button>
                            <button class="device-btn btn-stop" onclick="deviceAction('${device.name}', 'stop')">⏹️ 停止</button>
                            <button class="device-btn btn-restart" onclick="deviceAction('${device.name}', 'restart')">🔄 重啟</button>
                            <button class="device-btn btn-reboot" onclick="deviceAction('${device.name}', 'reboot')">🔄 設備</button>
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
        
        async function deviceAction(deviceName, action) {
            showToast(`正在執行: ${action}...`, 'info');
            
            const formData = new FormData();
            formData.append('device', deviceName);
            formData.append('action', action);
            
            const fileInput = document.getElementById('pdf-file');
            if (fileInput.files.length > 0) {
                formData.append('pdf_file', fileInput.files[0]);
            }

            try {
                const response = await fetch('/api/device/action', {
                    method: 'POST',
                    body: formData
                });
                const result = await response.json();
                showToast(result.message, result.success ? 'success' : 'error');
                setTimeout(refreshStatus, 2000);
            } catch (error) {
                showToast('操作失敗: ' + error.message, 'error');
            }
        }
        
        async function batchOperation(action) {
            const selected = Array.from(document.querySelectorAll('.device-checkbox:checked'))
                .map(cb => devicesData[cb.dataset.index].name);
            
            const formData = new FormData();
            formData.append('devices', JSON.stringify(selected));
            formData.append('action', action);
            
            const fileInput = document.getElementById('pdf-file');
            if (fileInput.files.length > 0) {
                formData.append('pdf_file', fileInput.files[0]);
            }
            
            if (selected.length === 0) {
                showToast('請先選擇要操作的設備', 'warning');
                return;
            }
            
            if (action === 'shutdown' || action === 'reboot') {
                if (!confirm(`確定要${action === 'shutdown' ? '關機' : '重啟'} ${selected.length} 台設備嗎？`)) return;
            }
            
            showToast(`正在對 ${selected.length} 台設備執行 ${action}...`, 'info');
            try {
                const response = await fetch('/api/batch/action', {
                    method: 'POST',
                    body: formData
                });
                const result = await response.json();
                showToast(`完成: ${result.success}/${selected.length} 台成功`, 'success');
                setTimeout(refreshStatus, 3000);
            } catch (error) {
                showToast('批次操作失敗: ' + error.message, 'error');
            }
        }
        
        function toggleSelectAll(checkbox) {
            document.querySelectorAll('.device-checkbox').forEach(cb => cb.checked = checkbox.checked);
        }
        
        async function refreshStatus() {
            showToast('正在重新整理...', 'info');
            await loadDevices();
            showToast('狀態已更新', 'success');
        }
        
        async function exportStats() {
            try {
                window.open('/api/export/csv', '_blank');
                showToast('正在下載統計報表...', 'success');
            } catch (error) {
                showToast('匯出失敗: ' + error.message, 'error');
            }
        }
        
        async function reloadConfig() {
            if (!confirm('確定要重新載入 hosts.json 設定檔嗎？')) return;
            showToast('正在讀取設定檔...', 'info');
            try {
                const response = await fetch('/api/config/reload', { method: 'POST' });
                const result = await response.json();
                showToast(result.message, result.success ? 'success' : 'error');
                if (result.success) setTimeout(refreshStatus, 1000);
            } catch (error) {
                showToast('請求失敗: ' + error.message, 'error');
            }
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

@app.route('/api/config/reload', methods=['POST'])
def reload_config():
    """重新載入設定檔"""
    return jsonify(controller.reload_config())

@app.route('/api/device/action', methods=['POST'])
def device_action():
    """單個設備操作"""
    pdf_file = None
    
    if request.is_json:
        data = request.json
        device_name = data.get('device')
        action = data.get('action')
        pdf_file = data.get('pdf_file')
    else:
        device_name = request.form.get('device')
        action = request.form.get('action')
        
        if 'pdf_file' in request.files:
            file = request.files['pdf_file']
            if file and file.filename:
                upload_dir = os.path.join(os.getcwd(), 'uploads')
                os.makedirs(upload_dir, exist_ok=True)
                pdf_file = os.path.join(upload_dir, file.filename)
                file.save(pdf_file)
    
    device = next((d for d in controller.devices if d['name'] == device_name), None)
    if not device:
        return jsonify({'success': False, 'message': '設備不存在'})
    
    actions = {
        'start': controller.start_application,
        'stop': controller.stop_application,
        'restart': controller.restart_application,
        'reboot': controller.reboot_device,
        'shutdown': controller.shutdown_device
    }
    
    if action == 'start':
        result = controller.start_application(device, pdf_file)
    elif action == 'restart':
        result = controller.restart_application(device, pdf_file)
    elif action in actions:
        result = actions[action](device)
    else:
        return jsonify({'success': False, 'message': '未知操作'})
    
    return jsonify(result)

@app.route('/api/batch/action', methods=['POST'])
def batch_action():
    """批次操作"""
    pdf_file = None
    device_names = []
    
    if request.is_json:
        data = request.json
        device_names = data.get('devices', [])
        action = data.get('action')
        pdf_file = data.get('pdf_file')
    else:
        device_names = json.loads(request.form.get('devices', '[]'))
        action = request.form.get('action')
        
        if 'pdf_file' in request.files:
            file = request.files['pdf_file']
            if file and file.filename:
                upload_dir = os.path.join(os.getcwd(), 'uploads')
                os.makedirs(upload_dir, exist_ok=True)
                pdf_file = os.path.join(upload_dir, file.filename)
                file.save(pdf_file)
    
    devices = [d for d in controller.devices if d['name'] in device_names]
    
    actions = {
        'start': controller.start_application,
        'stop': controller.stop_application,
        'restart': controller.restart_application,
        'reboot': controller.reboot_device,
        'shutdown': controller.shutdown_device
    }
    
    if action not in actions:
        return jsonify({'success': 0, 'total': 0, 'message': '未知操作'})
    
    success_count = 0
    for device in devices:
        if action == 'start':
            result = controller.start_application(device, pdf_file)
        elif action == 'restart':
            result = controller.restart_application(device, pdf_file)
        else:
            result = actions[action](device)
            
        if result.get('success'):
            success_count += 1
        time.sleep(0.5)
    
    return jsonify({
        'success': success_count,
        'total': len(devices),
        'message': f'完成 {success_count}/{len(devices)}'
    })

@app.route('/api/export/csv')
def export_csv():
    """匯出 CSV 統計報表 (每日明細 - 適合 FineBI)"""
    # 使用 DataExporter 生成 CSV
    csv_content = controller.exporter.generate_csv(controller.devices, controller.time_tracker)
    
    # 若要同時寫入資料庫，可在此呼叫 (需先設定 db_config)
    # controller.exporter.write_to_oracle(controller.devices, controller.time_tracker)
    
    output = make_response(csv_content)
    output.headers["Content-Disposition"] = "attachment; filename=device_stats.csv"
    output.headers["Content-type"] = "text/csv"
    return output
    
if __name__ == '__main__':
    import sys
    
    # 允許通過命令行參數指定端口
    port = 8080
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("❌ 無效的端口號，使用預設端口 8080")
    
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║     Raspberry Pi Web 控制中心已啟動                       ║
║                                                           ║
║     訪問地址: http://localhost:{port}                      
║     區域網路: http://你的樹莓派IP:{port}                   
║                                                           ║
║     管理 {len(controller.devices)} 台設備                                        
╚═══════════════════════════════════════════════════════════╝

提示：
  - 如需更改端口，請使用: python3 main_new.py 端口號
  - 例如: python3 main_new.py 9000
  - 按 Ctrl+C 停止服務
    """)
    
    try:
        app.run(host='0.0.0.0', port=port, debug=True)
    except OSError as e:
        if e.errno == 98:
            print(f"""
❌ 錯誤：端口 {port} 已被佔用！

解決方法：
1. 使用其他端口：python3 main_new.py 9000
2. 查看佔用端口的程式：sudo lsof -i :{port}
3. 終止佔用的程式：sudo kill -9 PID
            """)
        else:
            print(f"❌ 啟動失敗：{e}")
        sys.exit(1)