#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
時數追蹤模組
用於追蹤 Raspberry Pi 設備的運行、在線、離線時數
(已加入線程安全鎖)
"""

import json
import os
import time
import threading
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional

class TimeTracker:
    """設備時數追蹤器 (Thread-Safe)"""
    
    def __init__(self, data_file: str = "time_tracker.json"):
        """
        初始化時數追蹤器
        :param data_file: 數據保存文件路徑
        """
        self.data_file = data_file
        self.start_time = datetime.now()
        self._lock = threading.RLock()  # 使用 RLock 允許同一線程多次獲取鎖
        
        # 當前狀態 {device_name: {'status': 'running/online/offline', 'since': datetime}}
        self.current_status = {}
        
        # 累計時數 {device_name: {'running': timedelta, 'online': timedelta, 'offline': timedelta}}
        self.history = defaultdict(lambda: {
            'running': timedelta(),
            'online': timedelta(),
            'offline': timedelta()
        })
        
        # 每日記錄 {date: {device_name: {'running': seconds, 'online': seconds, 'offline': seconds}}}
        self.daily_records = defaultdict(lambda: defaultdict(lambda: {
            'running': 0,
            'online': 0,
            'offline': 0
        }))
        
        self.load_data()
        
    def load_data(self):
        """從文件載入歷史數據"""
        with self._lock:
            try:
                if os.path.exists(self.data_file):
                    with open(self.data_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    # 載入累計時數
                    if 'history' in data:
                        for device, statuses in data['history'].items():
                            for status, seconds in statuses.items():
                                self.history[device][status] = timedelta(seconds=seconds)
                    
                    # 載入每日記錄
                    if 'daily_records' in data:
                        for date, devices in data['daily_records'].items():
                            for device, statuses in devices.items():
                                self.daily_records[date][device] = statuses
                                
                    # 載入監控啟動時間
                    if 'start_time' in data:
                        try:
                            self.start_time = datetime.fromisoformat(data['start_time'])
                        except ValueError:
                            pass # 保持當前時間
                        
                    print(f"✅ 時數追蹤：已載入歷史數據")
            except Exception as e:
                print(f"⚠️  時數追蹤：載入數據失敗 - {e}")
    
    def save_data(self):
        """保存數據到文件 (Thread-Safe)"""
        with self._lock:
            try:
                # 準備要保存的數據結構
                data = {
                    'start_time': self.start_time.isoformat(),
                    'last_save': datetime.now().isoformat(),
                    'history': {
                        device: {
                            status: td.total_seconds()
                            for status, td in statuses.items()
                        }
                        for device, statuses in self.history.items()
                    },
                    'daily_records': dict(self.daily_records)
                }
                
                # 使用臨時文件進行原子寫入，防止寫入中斷導致文件損壞
                temp_file = f"{self.data_file}.tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # 寫入成功後替換原文件
                os.replace(temp_file, self.data_file)
                    
                return True
            except Exception as e:
                print(f"⚠️  時數追蹤：保存數據失敗 - {e}")
                return False
    
    def update_status(self, device_name: str, new_status: str):
        """
        更新設備狀態並計算時數
        :param device_name: 設備名稱
        :param new_status: 新狀態 ('running', 'online', 'offline')
        """
        with self._lock:
            now = datetime.now()
            today = now.strftime('%Y-%m-%d')
            
            # 如果設備有舊狀態，計算持續時間
            if device_name in self.current_status:
                old_status = self.current_status[device_name]['status']
                since = self.current_status[device_name]['since']
                duration = now - since
                
                # 防止時間倒流（系統時間變更時可能發生）
                if duration.total_seconds() < 0:
                    duration = timedelta(0)
                
                # 更新累計時數
                self.history[device_name][old_status] += duration
                
                # 更新每日記錄
                self.daily_records[today][device_name][old_status] += duration.total_seconds()
            
            # 記錄新狀態
            self.current_status[device_name] = {
                'status': new_status,
                'since': now
            }
    
    def get_device_stats(self, device_name: str) -> Dict:
        """
        獲取設備統計數據
        :param device_name: 設備名稱
        :return: 統計數據字典
        """
        with self._lock:
            # 計算當前狀態的持續時間
            current_duration = timedelta()
            current_status = 'offline'
            
            if device_name in self.current_status:
                current_status = self.current_status[device_name]['status']
                since = self.current_status[device_name]['since']
                current_duration = datetime.now() - since
                if current_duration.total_seconds() < 0:
                    current_duration = timedelta(0)
            
            # 複製累計時數（避免修改原始數據）
            # 注意：這裡使用 .get() 防止 KeyError，雖然 defaultdict 會處理，但安全第一
            device_history = self.history[device_name]
            total_running = device_history['running']
            total_online = device_history['online']
            total_offline = device_history['offline']
            
            # 將當前正在進行的時數加到顯示數據中（不存入歷史，直到狀態改變）
            if current_status == 'running':
                total_running += current_duration
            elif current_status == 'online':
                total_online += current_duration
            else:
                total_offline += current_duration
            
            return {
                'running': self._format_timedelta(total_running),
                'online': self._format_timedelta(total_online),
                'offline': self._format_timedelta(total_offline),
                'running_seconds': total_running.total_seconds(),
                'online_seconds': total_online.total_seconds(),
                'offline_seconds': total_offline.total_seconds(),
                'current_status': current_status,
                'current_duration': self._format_timedelta(current_duration)
            }
    
    def get_all_daily_records(self) -> Dict:
        """獲取所有每日記錄 (Thread-Safe) - 供 FineBI 報表使用"""
        with self._lock:
            # 回傳深拷貝，避免外部修改影響內部數據
            return json.loads(json.dumps(self.daily_records))

    def get_all_devices_stats(self) -> Dict:
        """獲取所有設備的統計數據"""
        with self._lock:
            # 獲取所有已知設備（包括歷史記錄中的和當前在線的）
            all_devices = set(self.current_status.keys()) | set(self.history.keys())
            return {
                device: self.get_device_stats(device)
                for device in all_devices
            }
    
    def get_daily_stats(self, date: str = None) -> Dict:
        """獲取指定日期的統計"""
        with self._lock:
            if date is None:
                date = datetime.now().strftime('%Y-%m-%d')
            return dict(self.daily_records.get(date, {}))
    
    def get_weekly_stats(self) -> Dict:
        """獲取本周統計"""
        with self._lock:
            today = datetime.now()
            week_start = today - timedelta(days=today.weekday())
            
            weekly_data = defaultdict(lambda: {'running': 0, 'online': 0, 'offline': 0})
            
            for i in range(7):
                date = (week_start + timedelta(days=i)).strftime('%Y-%m-%d')
                if date in self.daily_records:
                    for device, statuses in self.daily_records[date].items():
                        for status, seconds in statuses.items():
                            weekly_data[device][status] += seconds
            
            return dict(weekly_data)
    
    def get_monthly_stats(self, year: int = None, month: int = None) -> Dict:
        """獲取指定月份的統計"""
        with self._lock:
            if year is None or month is None:
                today = datetime.now()
                year = today.year
                month = today.month
            
            month_start = datetime(year, month, 1)
            if month == 12:
                month_end = datetime(year + 1, 1, 1)
            else:
                month_end = datetime(year, month + 1, 1)
            
            monthly_data = defaultdict(lambda: {'running': 0, 'online': 0, 'offline': 0})
            
            for date_str, devices in self.daily_records.items():
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    if month_start <= date_obj < month_end:
                        for device, statuses in devices.items():
                            for status, seconds in statuses.items():
                                monthly_data[device][status] += seconds
                except ValueError:
                    continue
            
            return dict(monthly_data)
    
    def get_uptime(self) -> str:
        """獲取監控系統運行時間"""
        uptime = datetime.now() - self.start_time
        return self._format_timedelta(uptime)
    
    def get_start_time(self) -> str:
        """獲取監控啟動時間"""
        return self.start_time.strftime('%Y-%m-%d %H:%M:%S')
    
    def export_to_csv(self, date_range: str = 'all') -> str:
        """導出數據為 CSV 格式"""
        import csv
        from io import StringIO
        
        with self._lock:
            output = StringIO()
            writer = csv.writer(output)
            
            # 寫入標題
            writer.writerow(['設備名稱', '日期', '運行時數', '在線時數', '離線時數', '總時數'])
            
            # 根據範圍選擇數據
            if date_range == 'today':
                dates = [datetime.now().strftime('%Y-%m-%d')]
            elif date_range == 'week':
                today = datetime.now()
                week_start = today - timedelta(days=today.weekday())
                dates = [(week_start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
            elif date_range == 'month':
                today = datetime.now()
                month_start = today.replace(day=1)
                dates = []
                current = month_start
                while current.month == today.month:
                    dates.append(current.strftime('%Y-%m-%d'))
                    current += timedelta(days=1)
            else:  # all
                dates = sorted(self.daily_records.keys())
            
            # 寫入數據
            for date in dates:
                if date in self.daily_records:
                    for device, stats in self.daily_records[date].items():
                        running_hours = stats['running'] / 3600
                        online_hours = stats['online'] / 3600
                        offline_hours = stats['offline'] / 3600
                        total_hours = running_hours + online_hours + offline_hours
                        
                        writer.writerow([
                            device,
                            date,
                            f"{running_hours:.2f}",
                            f"{online_hours:.2f}",
                            f"{offline_hours:.2f}",
                            f"{total_hours:.2f}"
                        ])
            
            return output.getvalue()
    
    def reset_stats(self, device_name: str = None):
        """重置統計數據"""
        with self._lock:
            if device_name:
                if device_name in self.history:
                    self.history[device_name] = {
                        'running': timedelta(),
                        'online': timedelta(),
                        'offline': timedelta()
                    }
                if device_name in self.current_status:
                    del self.current_status[device_name]
            else:
                self.history.clear()
                self.current_status.clear()
                self.daily_records.clear()
                self.start_time = datetime.now()
            
            self.save_data()
    
    def _format_timedelta(self, td: timedelta) -> str:
        """格式化時間差為 HH:MM:SS"""
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def _format_hours(self, seconds: float) -> str:
        """格式化秒數為小時（保留2位小數）"""
        hours = seconds / 3600
        return f"{hours:.2f}"


# 測試代碼
if __name__ == "__main__":
    # 創建時數追蹤器
    tracker = TimeTracker()
    
    print("開始測試...")
    
    # 模擬更新狀態
    tracker.update_status("PI-65", "offline")
    time.sleep(1)
    tracker.update_status("PI-65", "online")
    time.sleep(1)
    tracker.update_status("PI-65", "running")
    time.sleep(1)
    
    # 獲取統計
    stats = tracker.get_device_stats("PI-65")
    print(f"\nPI-65 統計:")
    print(f"  運行時數: {stats['running']}")
    print(f"  在線時數: {stats['online']}")
    print(f"  離線時數: {stats['offline']}")
    print(f"  當前狀態: {stats['current_status']}")
    
    # 保存數據
    if tracker.save_data():
        print("\n✅ 數據已保存")
    else:
        print("\n❌ 數據保存失敗")
