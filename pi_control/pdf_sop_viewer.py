import fitz  # PyMuPDF
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import os
import urllib.request
import tempfile
import re
import json
import sys

class PDFViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF 檢視器")
        
        # 基本屬性
        self.doc = None
        self.page_index = 0
        self.zoom = 1.0
        self.rotation = 0
        self.fullscreen = False
        self.pdf_filename = ""
        self.is_first_pdf = True
        
        # 自動換頁相關
        self.auto_page_job = None
        self.auto_start_page = 0
        self.auto_end_page = 0
        
        # 資源管理
        self.temp_files = []
        self.render_timer = None
        
        # 滾動和拖曳相關
        self.scroll_x = 0
        self.scroll_y = 0
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.is_dragging = False
        
        # 最近開啟檔案 - 確保在任何方法調用前初始化
        self.recent_files = []
        self.config_file = os.path.join(os.path.expanduser("~"), ".pdf_viewer_recent.json")
        
        # 初始化
        self._load_recent_files()
        self._setup_ui()
        self._setup_bindings()
        
        # 註冊清理函數
        self.root.protocol("WM_DELETE_WINDOW", self.cleanup_and_exit)

    def _setup_ui(self):
        """設置使用者介面"""
        self.canvas = tk.Canvas(self.root, bg="gray")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # 綁定滑鼠事件
        self.canvas.bind("<Button-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)  # Windows/macOS
        self.canvas.bind("<Button-4>", self._on_mouse_wheel)    # Linux 向上滾動
        self.canvas.bind("<Button-5>", self._on_mouse_wheel)    # Linux 向下滾動

        self.status = tk.Label(self.root, text="", anchor=tk.W)
        self.status.pack(fill=tk.X)

        self._create_toolbar()

    def _create_toolbar(self):
        """創建工具列"""
        self.toolbar = tk.Frame(self.root)
        self.toolbar.pack(fill=tk.X)

        # 檔案操作按鈕
        tk.Button(self.toolbar, text="📂 開啟 PDF", command=self.open_pdf).pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="📋 最近開啟", command=self.show_recent_files).pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="🔗 掃描 QR Code 開啟 PDF", command=self.scan_qrcode_open_pdf).pack(side=tk.LEFT)
        
        # 導航按鈕
        tk.Button(self.toolbar, text="⬅️ 上一頁", command=self.prev_page).pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="➡️ 下一頁", command=self.next_page).pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="⏮️ 第一頁", command=self.go_to_first_page).pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="⏭️ 最後一頁", command=self.go_to_last_page).pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="🔢 跳至頁碼", command=self.go_to_page).pack(side=tk.LEFT)
        
        # 檢視控制按鈕
        tk.Button(self.toolbar, text="🔍 放大", command=self.zoom_in).pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="🔎 縮小", command=self.zoom_out).pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="🔁 還原大小", command=self.reset_zoom).pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="🔄 旋轉頁面", command=self.rotate_page).pack(side=tk.LEFT)
        
        # 自動播放按鈕
        tk.Button(self.toolbar, text="⏱️ 自動換頁", command=self.start_auto_page_dialog).pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="🛑 停止換頁", command=self.stop_auto_page).pack(side=tk.LEFT)
        
        # 系統按鈕（靠右）
        tk.Button(self.toolbar, text="🖥️ 全螢幕", command=self.toggle_fullscreen).pack(side=tk.RIGHT)
        tk.Button(self.toolbar, text="❌ 離開程式", command=self.confirm_exit).pack(side=tk.RIGHT)

    def _setup_bindings(self):
        """設置鍵盤綁定"""
        self.root.bind("<Left>", lambda e: self.prev_page())
        self.root.bind("<Right>", lambda e: self.next_page())
        self.root.bind("<Up>", lambda e: self._scroll_up())
        self.root.bind("<Down>", lambda e: self._scroll_down())
        self.root.bind("<Configure>", self._on_window_resize)
        self.root.bind("<Key>", lambda e: self.stop_auto_page())

    def _on_window_resize(self, event):
        """視窗大小改變時的防抖動處理"""
        if self.render_timer:
            self.root.after_cancel(self.render_timer)
        self.render_timer = self.root.after(100, self.render_page)

    def cleanup_and_exit(self):
        """清理資源並退出"""
        self._save_recent_files()
        self.cleanup_resources()
        self.root.destroy()

    def cleanup_resources(self):
        """清理所有資源"""
        if self.doc:
            try:
                self.doc.close()
            except Exception as e:
                print(f"關閉 PDF 時發生錯誤: {e}")
        
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception as e:
                print(f"刪除臨時檔案時發生錯誤: {e}")
        
        self.temp_files.clear()

    # === 最近開啟檔案功能 ===
    def _load_recent_files(self):
        """載入最近開啟的檔案列表"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.recent_files = data.get('recent_files', [])
                    # 過濾掉不存在的檔案
                    self.recent_files = [f for f in self.recent_files if os.path.exists(f)]
        except Exception as e:
            print(f"載入最近檔案列表時發生錯誤: {e}")
            self.recent_files = []

    def _save_recent_files(self):
        """儲存最近開啟的檔案列表"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({'recent_files': self.recent_files}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"儲存最近檔案列表時發生錯誤: {e}")

    def _add_to_recent_files(self, file_path):
        """將檔案加入最近開啟列表"""
        # 取得絕對路徑
        file_path = os.path.abspath(file_path)
        
        # 如果檔案已在列表中，先移除
        if file_path in self.recent_files:
            self.recent_files.remove(file_path)
        
        # 將檔案加到列表開頭
        self.recent_files.insert(0, file_path)
        
        # 只保留最近 5 個檔案
        self.recent_files = self.recent_files[:5]

    def show_recent_files(self):
        """顯示最近開啟的檔案"""
        if not self.recent_files:
            messagebox.showinfo("提示", "沒有最近開啟的檔案")
            return
        
        RecentFilesDialog(self.root, self.recent_files, self._open_recent_file)

    def _open_recent_file(self, file_path):
        """開啟最近的檔案"""
        if os.path.exists(file_path):
            self.load_pdf(file_path)
            self.pdf_filename = os.path.basename(file_path)
            self._add_to_recent_files(file_path)
        else:
            messagebox.showerror("錯誤", f"檔案不存在：\n{file_path}")
            # 從列表中移除不存在的檔案
            if file_path in self.recent_files:
                self.recent_files.remove(file_path)

    # === 檔案操作 ===
    def open_pdf(self):
        """開啟本地 PDF 檔案"""
        file_path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if file_path:
            self.load_pdf(file_path)
            self.pdf_filename = os.path.basename(file_path)
            self._add_to_recent_files(file_path)

    def scan_qrcode_open_pdf(self):
        """透過 QR Code 掃描開啟 PDF"""
        qr_path = simpledialog.askstring("掃描 QR Code", "請使用掃描槍掃描 QR Code，或手動輸入 PDF 路徑：")
        if not qr_path:
            return
        
        cleaned_url = self.clean_url(qr_path)
        
        if cleaned_url.startswith("http"):
            self._load_remote_pdf(cleaned_url)
        elif os.path.exists(cleaned_url):
            self.load_pdf(cleaned_url)
            self.pdf_filename = os.path.basename(cleaned_url)
            self._add_to_recent_files(cleaned_url)
        else:
            messagebox.showerror("錯誤", f"找不到檔案：\n{cleaned_url}")

    def _load_remote_pdf(self, url):
        """載入遠端 PDF"""
        try:
            pdf_path = self.download_pdf(url)
            if pdf_path:
                self.load_pdf(pdf_path)
                self.pdf_filename = "遠端 PDF"
            else:
                messagebox.showerror("錯誤", "無法下載 PDF 或格式錯誤。")
        except Exception as e:
            messagebox.showerror("錯誤", f"下載 PDF 失敗：\n{e}")

    def clean_url(self, url):
        """清理和轉換 URL"""
        url = url.strip()
        url = re.sub(r"[#?].*$", "", url)
        
        if "drive.google.com/file/d/" in url:
            match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
            if match:
                file_id = match.group(1)
                url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        return url

    def download_pdf(self, url):
        """下載 PDF 檔案"""
        try:
            response = urllib.request.urlopen(url, timeout=30)
            content_type = response.headers.get("Content-Type", "")
            
            if "pdf" not in content_type.lower():
                return None
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_file.write(response.read())
            temp_file.close()
            
            self.temp_files.append(temp_file.name)
            return temp_file.name
            
        except urllib.error.URLError as e:
            print(f"下載 PDF 發生網路錯誤: {e}")
            return None
        except Exception as e:
            print(f"下載 PDF 發生錯誤: {e}")
            return None

    def load_pdf(self, path):
        """載入 PDF 檔案"""
        try:
            if self.doc:
                self.doc.close()
            
            self.doc = fitz.open(path)
            self.page_index = 0
            self.zoom = 1.0
            self.rotation = 0
            
            # 第一次開啟 PDF 時自動最大化視窗
            if self.is_first_pdf:
                self.maximize_window()
                self.is_first_pdf = False
            
            self.render_page()
            
        except Exception as e:
            messagebox.showerror("錯誤", f"無法開啟 PDF：\n{e}")

    def maximize_window(self):
        """最大化視窗（跨平台支援）"""
        try:
            # Windows 和 Linux
            self.root.state('zoomed')
        except tk.TclError:
            # macOS 或其他系統
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            self.root.geometry(f"{screen_width}x{screen_height}+0+0")

    def render_page(self):
        """渲染當前頁面"""
        if not self.doc:
            return
        
        try:
            page = self.doc.load_page(self.page_index)
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            
            if canvas_width <= 1 or canvas_height <= 1:
                return
            
            # 計算縮放比例
            zoom_x = (canvas_width / page.rect.width) * self.zoom
            zoom_y = (canvas_height / page.rect.height) * self.zoom
            zoom = min(zoom_x, zoom_y)
            
            # 提高渲染品質：使用更高的 DPI
            # 當放大時，使用額外的品質係數來保持清晰度
            quality_factor = max(1.5, self.zoom)  # 放大時提高渲染品質
            render_zoom = zoom * quality_factor
            
            mat = fitz.Matrix(render_zoom, render_zoom).prerotate(self.rotation)
            
            # 使用高品質渲染參數
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # 將渲染結果轉換為 PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # 如果使用了品質係數，需要縮放回正確的顯示大小
            if quality_factor > 1.0:
                display_width = int(pix.width / quality_factor)
                display_height = int(pix.height / quality_factor)
                # 使用高品質的重採樣方法
                img = img.resize((display_width, display_height), Image.Resampling.LANCZOS)
            
            # 計算圖片位置（考慮滾動偏移）
            img_width, img_height = img.size
            img_x = canvas_width // 2 - self.scroll_x
            img_y = canvas_height // 2 - self.scroll_y
            
            # 限制滾動範圍
            max_scroll_x = max(0, (img_width - canvas_width) // 2)
            max_scroll_y = max(0, (img_height - canvas_height) // 2)
            self.scroll_x = max(-max_scroll_x, min(max_scroll_x, self.scroll_x))
            self.scroll_y = max(-max_scroll_y, min(max_scroll_y, self.scroll_y))
            
            # 重新計算位置
            img_x = canvas_width // 2 - self.scroll_x
            img_y = canvas_height // 2 - self.scroll_y
            
            self.tk_img = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas.create_image(img_x, img_y, image=self.tk_img, anchor=tk.CENTER)

            self._update_status()
            
        except Exception as e:
            print(f"渲染頁面時發生錯誤: {e}")

    def _update_status(self):
        """更新狀態列"""
        status_text = f"檔案：{self.pdf_filename} | 第 {self.page_index + 1} 頁 / 共 {len(self.doc)} 頁"
        if self.zoom > 1.0:
            status_text += f" | 縮放: {self.zoom:.1f}x (可拖曳檢視)"
        self.status.config(text=status_text)

    # === 滾動和拖曳功能 ===
    def _on_mouse_down(self, event):
        """滑鼠按下事件"""
        self.stop_auto_page()
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.is_dragging = False
        self.canvas.config(cursor="hand2")

    def _on_mouse_drag(self, event):
        """滑鼠拖曳事件"""
        if self.zoom > 1.0:
            dx = event.x - self.drag_start_x
            dy = event.y - self.drag_start_y
            
            # 判斷是否真的在拖曳（移動距離超過 5 像素）
            if abs(dx) > 5 or abs(dy) > 5:
                self.is_dragging = True
                self.scroll_x -= dx
                self.scroll_y -= dy
                self.drag_start_x = event.x
                self.drag_start_y = event.y
                self.render_page()

    def _on_mouse_up(self, event):
        """滑鼠放開事件"""
        self.canvas.config(cursor="")
        # 如果沒有真正拖曳，則視為點擊
        if not self.is_dragging:
            self.stop_auto_page()

    def _on_mouse_wheel(self, event):
        """滑鼠滾輪事件"""
        self.stop_auto_page()
        
        if self.zoom > 1.0:
            # 放大狀態下，滾輪用於上下滾動
            if event.num == 4 or event.delta > 0:  # 向上滾動
                self._scroll_up()
            elif event.num == 5 or event.delta < 0:  # 向下滾動
                self._scroll_down()
        else:
            # 未放大狀態下，滾輪用於換頁
            if event.num == 4 or event.delta > 0:  # 向上滾動
                self.prev_page()
            elif event.num == 5 or event.delta < 0:  # 向下滾動
                self.next_page()

    def _scroll_up(self):
        """向上滾動"""
        if self.zoom > 1.0:
            self.scroll_y -= 50
            self.render_page()

    def _scroll_down(self):
        """向下滾動"""
        if self.zoom > 1.0:
            self.scroll_y += 50
            self.render_page()

    # === 導航功能 ===
    def prev_page(self):
        """上一頁"""
        self.stop_auto_page()
        if self.doc and self.page_index > 0:
            self.page_index -= 1
            self.scroll_x = 0
            self.scroll_y = 0
            self.render_page()

    def next_page(self):
        """下一頁"""
        self.stop_auto_page()
        if self.doc and self.page_index < len(self.doc) - 1:
            self.page_index += 1
            self.scroll_x = 0
            self.scroll_y = 0
            self.render_page()

    def go_to_first_page(self):
        """跳至第一頁"""
        self.stop_auto_page()
        if self.doc:
            self.page_index = 0
            self.scroll_x = 0
            self.scroll_y = 0
            self.render_page()

    def go_to_last_page(self):
        """跳至最後一頁"""
        self.stop_auto_page()
        if self.doc:
            self.page_index = len(self.doc) - 1
            self.scroll_x = 0
            self.scroll_y = 0
            self.render_page()

    def go_to_page(self):
        """跳至指定頁碼"""
        self.stop_auto_page()
        if not self.doc:
            return
            
        page_num = simpledialog.askinteger(
            "跳至頁碼", 
            f"請輸入頁碼（1 到 {len(self.doc)}）：", 
            minvalue=1, 
            maxvalue=len(self.doc)
        )
        if page_num:
            self.page_index = page_num - 1
            self.scroll_x = 0
            self.scroll_y = 0
            self.render_page()

    # === 檢視控制 ===
    def zoom_in(self):
        """放大"""
        self.stop_auto_page()
        self.zoom *= 1.2
        self.render_page()

    def zoom_out(self):
        """縮小"""
        self.stop_auto_page()
        self.zoom /= 1.2
        # 縮小時重設滾動位置
        if self.zoom <= 1.0:
            self.scroll_x = 0
            self.scroll_y = 0
        self.render_page()

    def reset_zoom(self):
        """重設縮放"""
        self.stop_auto_page()
        self.zoom = 1.0
        self.scroll_x = 0
        self.scroll_y = 0
        self.render_page()

    def rotate_page(self):
        """旋轉頁面"""
        self.stop_auto_page()
        self.rotation = (self.rotation + 90) % 360
        self.scroll_x = 0
        self.scroll_y = 0
        self.render_page()

    # === 自動播放功能 ===
    def start_auto_page_dialog(self):
        """開啟自動換頁對話框"""
        if not self.doc:
            messagebox.showinfo("提示", "請先載入 PDF")
            return

        AutoPageDialog(self.root, len(self.doc), self._start_auto_page)

    def _start_auto_page(self, seconds, start_page, end_page):
        """開始自動換頁"""
        self.auto_start_page = start_page - 1
        self.auto_end_page = end_page - 1
        self.page_index = self.auto_start_page
        self.render_page()
        self.stop_auto_page()
        self.auto_page_job = self.root.after(seconds * 1000, self.auto_next_page, seconds)

    def auto_next_page(self, seconds):
        """自動換至下一頁"""
        if self.page_index < self.auto_end_page:
            self.page_index += 1
        else:
            self.page_index = self.auto_start_page
        
        self.render_page()
        self.auto_page_job = self.root.after(seconds * 1000, self.auto_next_page, seconds)

    def stop_auto_page(self):
        """停止自動換頁"""
        if self.auto_page_job:
            self.root.after_cancel(self.auto_page_job)
            self.auto_page_job = None

    # === 系統功能 ===
    def toggle_fullscreen(self):
        """切換全螢幕模式"""
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        
        if self.fullscreen:
            self.root.after(100, lambda: self.root.attributes("-fullscreen", True))

    def confirm_exit(self):
        """確認退出"""
        if messagebox.askokcancel("離開確認", "確定要離開程式嗎？"):
            self.cleanup_and_exit()


class RecentFilesDialog:
    """最近開啟檔案對話框"""
    def __init__(self, parent, recent_files, callback):
        self.callback = callback
        self.recent_files = recent_files
        
        self.top = tk.Toplevel(parent)
        self.top.title("最近開啟的檔案")
        self.top.geometry("500x250")
        self.top.transient(parent)
        self.top.resizable(False, False)
        
        self._create_widgets()
        self._center_window(parent)
        
        self.top.lift()
        self.top.focus_force()

    def _create_widgets(self):
        """創建對話框元件"""
        tk.Label(self.top, text="選擇要開啟的檔案：", font=("Arial", 10, "bold")).pack(pady=10)
        
        # 建立列表框
        frame = tk.Frame(self.top)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.listbox = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 9))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)
        
        # 加入檔案到列表
        for i, file_path in enumerate(self.recent_files, 1):
            display_name = f"{i}. {os.path.basename(file_path)}"
            self.listbox.insert(tk.END, display_name)
        
        # 綁定雙擊事件
        self.listbox.bind("<Double-Button-1>", lambda e: self._open_selected())
        
        # 按鈕
        btn_frame = tk.Frame(self.top)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="開啟", command=self._open_selected, width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="取消", command=self.top.destroy, width=10).pack(side=tk.LEFT, padx=5)

    def _center_window(self, parent):
        """將對話框置中於父視窗"""
        self.top.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.top.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.top.winfo_height() // 2)
        self.top.geometry(f"+{x}+{y}")

    def _open_selected(self):
        """開啟選中的檔案"""
        selection = self.listbox.curselection()
        if selection:
            index = selection[0]
            file_path = self.recent_files[index]
            self.callback(file_path)
            self.top.destroy()
        else:
            messagebox.showwarning("提示", "請選擇一個檔案")


class AutoPageDialog:
    """自動換頁對話框"""
    def __init__(self, parent, total_pages, callback):
        self.callback = callback
        self.total_pages = total_pages
        
        self.top = tk.Toplevel(parent)
        self.top.title("自訂自動換頁")
        self.top.geometry("320x220")
        self.top.transient(parent)
        self.top.resizable(False, False)
        
        self._create_widgets()
        self._center_window(parent)
        
        self.top.lift()
        self.top.focus_force()

    def _create_widgets(self):
        """創建對話框元件"""
        # 秒數設定
        tk.Label(self.top, text="換頁間隔（秒）：").pack(pady=5)
        self.entry_seconds = tk.Entry(self.top, width=20)
        self.entry_seconds.insert(0, "5")
        self.entry_seconds.pack()

        # 起始頁設定
        tk.Label(self.top, text=f"起始頁（1 到 {self.total_pages}）：").pack(pady=5)
        self.entry_start = tk.Entry(self.top, width=20)
        self.entry_start.insert(0, "1")
        self.entry_start.pack()

        # 結束頁設定
        tk.Label(self.top, text=f"結束頁（起始頁 到 {self.total_pages}）：").pack(pady=5)
        self.entry_end = tk.Entry(self.top, width=20)
        self.entry_end.insert(0, str(self.total_pages))
        self.entry_end.pack()

        # 按鈕
        btn_frame = tk.Frame(self.top)
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="開始", command=self._submit, width=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="取消", command=self.top.destroy, width=8).pack(side=tk.LEFT, padx=5)

    def _center_window(self, parent):
        """將對話框置中於父視窗"""
        self.top.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.top.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.top.winfo_height() // 2)
        self.top.geometry(f"+{x}+{y}")

    def _submit(self):
        """提交設定"""
        try:
            seconds = int(self.entry_seconds.get())
            start_page = int(self.entry_start.get())
            end_page = int(self.entry_end.get())
            
            if seconds < 1:
                raise ValueError("秒數必須大於 0")
            if start_page < 1 or start_page > self.total_pages:
                raise ValueError(f"起始頁必須在 1 到 {self.total_pages} 之間")
            if end_page < start_page or end_page > self.total_pages:
                raise ValueError(f"結束頁必須在 {start_page} 到 {self.total_pages} 之間")
            
            self.callback(seconds, start_page, end_page)
            self.top.destroy()
            
        except ValueError as e:
            messagebox.showerror("輸入錯誤", str(e))


if __name__ == "__main__":
    root = tk.Tk()
    
    # 設定初始視窗大小為螢幕大小
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    root.geometry(f"{screen_width}x{screen_height}+0+0")
    
    viewer = PDFViewer(root)
    
    # 延遲執行最大化，確保視窗完全初始化
    root.after(100, lambda: viewer.maximize_window())
    
    # 檢查是否有命令列參數（來自 main_new.py 的檔案路徑）
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        
        # 寫入日誌以便排查問題
        try:
            log_file = os.path.join(os.path.expanduser("~"), "pdf_startup.log")
            with open(log_file, "w") as f:
                f.write(f"Received args: {sys.argv}\n")
                f.write(f"File path: {file_path}\n")
                f.write(f"File exists: {os.path.exists(file_path)}\n")
        except:
            pass

        if os.path.exists(file_path):
            def open_startup_file():
                try:
                    viewer.load_pdf(file_path)
                    viewer.pdf_filename = os.path.basename(file_path)
                    viewer._add_to_recent_files(file_path)
                except Exception as e:
                    print(f"Auto open failed: {e}")
            
            # 增加延遲時間至 1000ms，確保視窗初始化完成
            root.after(1000, open_startup_file)
    
    root.mainloop()