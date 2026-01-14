
import tkinter as tk
from tkinter import messagebox, filedialog
import subprocess
import os
import webbrowser
import sys

# 語系設定
languages = {
    "zh": {
        "title": "PDF / 網頁開啟工具",
        "label": "請掃描 QR Code 或輸入 PDF 路徑 / 網頁連結:",
        "open": "開啟",
        "exit": "退出",
        "browse": "📂 選擇檔案",
        "clear": "❌",
        "error": "錯誤",
        "invalid": "請輸入有效的 PDF 路徑或網頁連結。",
        "open_fail": "無法開啟 PDF 檔案。",
        "web_fail": "無法開啟網頁連結。"
    },
    "en": {
        "title": "PDF / Web Opener",
        "label": "Scan QR Code or enter PDF path / web link:",
        "open": "Open",
        "exit": "Exit",
        "browse": "📂 Browse File",
        "clear": "❌",
        "error": "Error",
        "invalid": "Please enter a valid PDF path or web link.",
        "open_fail": "Failed to open PDF file.",
        "web_fail": "Failed to open web link."
    }
}

current_lang = "zh"

def switch_language(lang):
    global current_lang
    current_lang = lang
    update_ui()

def update_ui():
    lang = languages[current_lang]
    root.title(lang["title"])
    label.config(text=lang["label"])
    open_button.config(text=lang["open"])
    exit_button.config(text=lang["exit"])
    browse_button.config(text=lang["browse"])
    clear_button.config(text=lang["clear"])

def log_opened_file(path):
    with open("log.txt", "a") as log_file:
        log_file.write(f"{path}\n")

def open_input():
    input_text = entry.get().strip()
    lang = languages[current_lang]

    if input_text.startswith("http://") or input_text.startswith("https://"):
        try:
            webbrowser.open(input_text)
            log_opened_file(input_text)
        except Exception as e:
            messagebox.showerror(lang["error"], f"{lang['web_fail']}\n{e}")
    elif os.path.isfile(input_text) and input_text.lower().endswith('.pdf'):
        try:
            subprocess.run(['xdg-open', input_text], check=True)
            log_opened_file(input_text)
        except subprocess.CalledProcessError:
            messagebox.showerror(lang["error"], lang["open_fail"])
    else:
        messagebox.showerror(lang["error"], lang["invalid"])

def clear_input():
    entry.delete(0, tk.END)

def browse_file():
    file_path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
    if file_path:
        entry.delete(0, tk.END)
        entry.insert(0, file_path)
        open_input() # 自動開啟選擇檔案

# 建立 GUI 視窗
root = tk.Tk()
root.title(languages[current_lang]["title"])
root.geometry("550x220")

# 語言選單
menu = tk.Menu(root)
lang_menu = tk.Menu(menu, tearoff=0)
lang_menu.add_command(label="中文", command=lambda: switch_language("zh"))
lang_menu.add_command(label="English", command=lambda: switch_language("en"))
menu.add_cascade(label="語言 / Language", menu=lang_menu)
root.config(menu=menu)

label = tk.Label(root, text=languages[current_lang]["label"])
label.pack(pady=5)

input_frame = tk.Frame(root)
input_frame.pack(pady=5)

entry = tk.Entry(input_frame, width=50)
entry.pack(side=tk.LEFT, padx=5)

clear_button = tk.Button(input_frame, text=languages[current_lang]["clear"], command=clear_input)
clear_button.pack(side=tk.LEFT)

browse_button = tk.Button(root, text=languages[current_lang]["browse"], command=browse_file)
browse_button.pack(pady=5)

button_frame = tk.Frame(root)
button_frame.pack(pady=5)

open_button = tk.Button(button_frame, text=languages[current_lang]["open"], command=open_input)
open_button.pack(side=tk.LEFT, padx=5)

exit_button = tk.Button(button_frame, text=languages[current_lang]["exit"], command=root.quit)
exit_button.pack(side=tk.LEFT, padx=5)

# 檢查是否有命令列參數（來自 main_new.py 的檔案路徑）
if len(sys.argv) > 1:
    file_path = sys.argv[1]
    entry.delete(0, tk.END)
    entry.insert(0, file_path)
    root.after(500, open_input)  # 延遲 500ms 等待視窗載入後自動開啟

root.mainloop()
