import csv
from io import StringIO
from typing import List, Dict, Any
from datetime import datetime

class DataExporter:
    """
    數據匯出與資料庫整合模組
    負責生成報表 (CSV) 及寫入 Oracle 19c 數據庫
    """
    
    def __init__(self, db_config: Dict[str, str] = None):
        """
        初始化匯出器
        :param db_config: Oracle 資料庫連線設定 (預留)
        """
        self.db_config = db_config

    def _get_daily_rows(self, devices: List[Dict], time_tracker) -> List[List[Any]]:
        """
        獲取每日明細數據，供 CSV 和 Database 使用 (FineBI 格式)
        """
        rows = []
        # 獲取所有歷史每日數據
        daily_records = time_tracker.get_all_daily_records()
        
        # 建立設備資訊查找表 (用名稱找 IP/Script)
        device_map = {d['name']: d for d in devices}
        
        # 排序日期 (新到舊)
        sorted_dates = sorted(daily_records.keys(), reverse=True)
        
        for date_str in sorted_dates:
            day_data = daily_records[date_str]
            for device_name, stats in day_data.items():
                device_info = device_map.get(device_name, {})
                
                # 將秒數轉換為小時 (保留2位小數)，方便 BI 加總
                run_h = round(stats.get('running', 0) / 3600, 2)
                online_h = round(stats.get('online', 0) / 3600, 2)
                offline_h = round(stats.get('offline', 0) / 3600, 2)
                
                row = [
                    date_str,                           # 1. 日期 (維度)
                    device_name,                        # 2. 設備名稱 (維度)
                    device_info.get('ip', 'N/A'),       # 3. IP地址 (維度)
                    device_info.get('script_path', 'N/A'), # 4. 執行腳本 (維度)
                    run_h,                              # 5. 運行時數-小時 (指標)
                    online_h,                           # 6. 在線時數-小時 (指標)
                    offline_h                           # 7. 離線時數-小時 (指標)
                ]
                rows.append(row)
        return rows

    def generate_csv(self, devices: List[Dict], time_tracker) -> str:
        """生成 CSV 內容"""
        si = StringIO()
        si.write('\ufeff')  # 寫入 BOM 以防止 Excel 開啟時中文亂碼
        cw = csv.writer(si)
        
        # 定義 CSV 標題 (對應 FineBI 欄位)
        headers = ['日期', '設備名稱', 'IP地址', '執行腳本', '運行時數(小時)', '在線時數(小時)', '離線時數(小時)']
        cw.writerow(headers)
        
        rows = self._get_daily_rows(devices, time_tracker)
        cw.writerows(rows)
            
        return si.getvalue()

    def write_to_oracle(self, devices: List[Dict], time_tracker):
        """
        將數據寫入 Oracle 19c 數據庫
        """
        rows = self._get_daily_rows(devices, time_tracker)
        print(f"[DataExporter] 準備寫入 {len(rows)} 筆數據到 Oracle...")
        
        # TODO: 實作 Oracle 連接與寫入邏輯
        # 範例代碼 (需安裝 cx_Oracle 或 oracledb):
        """
        try:
            import cx_Oracle
            # 建立連線
            dsn = cx_Oracle.makedsn(self.db_config['host'], self.db_config['port'], service_name=self.db_config['service_name'])
            with cx_Oracle.connect(user=self.db_config['user'], password=self.db_config['password'], dsn=dsn) as connection:
                with connection.cursor() as cursor:
                    # 假設資料表為 DEVICE_STATS
                    sql = "INSERT INTO DEVICE_STATS (EXPORT_TIME, DEVICE_NAME, IP, SCRIPT, RUN_TIME, ONLINE_TIME, OFFLINE_TIME) VALUES (:1, :2, :3, :4, :5, :6, :7)"
                    cursor.executemany(sql, rows)
                    connection.commit()
                    print(f"成功寫入 {len(rows)} 筆數據")
        except Exception as e:
            print(f"寫入 Oracle 失敗: {e}")
        """
        pass
