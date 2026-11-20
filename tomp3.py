# -*- coding: utf-8 -*-
"""
tomp3 — 貼上影片網址，轉成 MP3
================================

架構：本機網頁應用程式（伺服器只綁 127.0.0.1，不對外分享）。
  - 電腦：雙擊桌面捷徑 tomp3，自動開啟瀏覽器
  - 手機：Termux 裡輸入 tomp3，見 android/

流程：yt-dlp 只下載音訊 → ffmpeg 轉成 MP3 → 存到資料夾，或交給瀏覽器下載。
所有暫存檔放在系統暫存資料夾，完成或失敗都會清掉。
"""

import io
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8766            # 和 transcript（8756）錯開，兩個可以同時開
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
TMP_PREFIX = "tomp3_"

IS_TERMUX = "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir(
    "/data/data/com.termux")

STATIC_FILES = {
    "tokens.css":        "text/css; charset=utf-8",
    "manifest.json":     "application/manifest+json; charset=utf-8",
    "icon-192.png":      "image/png",
    "icon-512.png":      "image/png",
    "icon-maskable.png": "image/png",
}

# 音質選項 → 交給 ffmpeg 的參數。數字 = 固定位元率（kbps）；
# "best" = LAME 最高品質的可變位元率（V0，約 220–260 kbps），檔案比 320 小、聽感幾乎一樣。
QUALITIES = {"128": "128", "192": "192", "320": "320", "best": "0"}


# ==========================================================================
# 設定（存在程式資料夾的 settings.json；git 不追蹤，更新不會蓋掉）
# ==========================================================================

def default_folder():
    if IS_TERMUX:
        return "/sdcard/Download/tomp3"
    return os.path.join(os.path.expanduser("~"), "Downloads", "tomp3")


def default_settings():
    return {"quality": "192", "mode": "folder", "folder": default_folder()}


def load_settings():
    s = default_settings()
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("quality") in QUALITIES:
            s["quality"] = saved["quality"]
        if saved.get("mode") in ("folder", "browser"):
            s["mode"] = saved["mode"]
        if isinstance(saved.get("folder"), str) and saved["folder"].strip():
            s["folder"] = saved["folder"].strip()
    except Exception:
        pass
    return s


def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


# ==========================================================================
# 轉檔
# ==========================================================================

def find_ffmpeg():
    """電腦用跟著程式裝的 imageio-ffmpeg；手機（或電腦本來就有的）用系統的 ffmpeg。"""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ffmpeg_dir():
    """yt-dlp 認得的 ffmpeg 位置。

    imageio-ffmpeg 的執行檔叫 ffmpeg-win-x86_64-v7.1.exe 這種長名字，
    yt-dlp 只認 ffmpeg(.exe)。所以第一次用時複製一份到 bin/ffmpeg.exe，
    之後直接指向 bin 資料夾。
    """
    src = find_ffmpeg()
    if not src:
        return None
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    if os.path.basename(src).lower() == name:
        return os.path.dirname(src)
    bindir = os.path.join(BASE_DIR, "bin")
    dst = os.path.join(bindir, name)
    try:
        if not (os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src)):
            os.makedirs(bindir, exist_ok=True)
            shutil.copy2(src, dst)
        return bindir
    except OSError:
        return None


def safe_name(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name or "").strip(" .")
    return (name or "audio")[:150]


def unique_path(folder, filename):
    base, ext = os.path.splitext(filename)
    path = os.path.join(folder, filename)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


def convert(url, quality, log):
    """下載音訊並轉成 MP3。回傳 (暫存資料夾, mp3 路徑, 標題)。

    失敗時暫存資料夾會在這裡就清掉；成功時由呼叫端負責清。
    """
    import yt_dlp

    ff = ffmpeg_dir()
    if not ff:
        raise RuntimeError("找不到 ffmpeg（轉檔工具）。請重新執行一次安裝指令。")

    tmpdir = tempfile.mkdtemp(prefix=TMP_PREFIX)
    last = {"t": 0}

    def on_progress(d):
        if d.get("status") != "downloading":
            return
        now = time.time()
        if now - last["t"] < 0.8:
            return
        last["t"] = now
        done = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        mb = done / 1048576
        if total:
            log(f"下載音訊中… {done * 100 / total:.0f}%（{mb:.1f} / {total / 1048576:.1f} MB）")
        else:
            log(f"下載音訊中… {mb:.1f} MB")

    def on_post(d):
        if d.get("status") == "started" and d.get("postprocessor") == "ExtractAudio":
            log("轉成 MP3 中…（長影片需要一點時間）")

    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(tmpdir, "audio.%(ext)s"),
        "noplaylist": True,          # 播放清單網址只抓網址指到的那一部
        "quiet": True, "no_warnings": True, "noprogress": True,
        "ffmpeg_location": ff,
        "progress_hooks": [on_progress],
        "postprocessor_hooks": [on_post],
        "postprocessors": [{"key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": QUALITIES[quality]}],
    }
    try:
        log("讀取影片資訊…")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if info and info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            info = entries[0] if entries else info
        mp3 = os.path.join(tmpdir, "audio.mp3")
        if not os.path.exists(mp3):
            raise RuntimeError("轉檔失敗：沒有產生 MP3。")
        return tmpdir, mp3, (info or {}).get("title") or "audio"
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


def clean_old_temp(max_age=3600):
    """清掉上次沒清乾淨的暫存資料夾（例如程式被強制關掉時留下的）。"""
    root = tempfile.gettempdir()
    try:
        names = os.listdir(root)
    except OSError:
        return
    for n in names:
        p = os.path.join(root, n)
        if n.startswith(TMP_PREFIX) and os.path.isdir(p):
            try:
                if time.time() - os.path.getmtime(p) > max_age:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass


def friendly_error(e):
    msg = str(e)
    msg = re.sub(r"\x1b\[[0-9;]*m", "", msg).replace("ERROR: ", "")
    low = msg.lower()
    if "unsupported url" in low or "no video formats" in low:
        return "這個網址找不到影片，請確認是影片頁面的網址。"
    if "404" in low or "unable to download webpage" in low:
        return "打不開這個網頁：網址可能打錯，或影片已被刪除。\n\n原始訊息：" + msg
    if "getaddrinfo" in low or "timed out" in low or "network" in low:
        return "連不上網路，請確認網路後再試一次。\n\n原始訊息：" + msg
    if "private" in low or "sign in" in low or "login" in low:
        return "這部影片需要登入或不公開，無法下載。\n\n原始訊息：" + msg
    if "permission" in low or "errno 13" in low or "access is denied" in low:
        hint = ("手機請先在 Termux 執行 termux-setup-storage 並允許存取檔案。"
                if IS_TERMUX else "請換一個資料夾。")
        return "沒有權限寫入這個資料夾。" + hint + "\n\n原始訊息：" + msg
    return msg


# ==========================================================================
# 工作（每次按「下載 MP3」就是一個工作，背景執行，前端輪詢進度）
# ==========================================================================

JOBS = {}
JOBS_LOCK = threading.Lock()
SERVER = None
IDLE_EXIT_SEC = 300
LAST_PING = None


def _set(job_id, **kw):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if j:
            j.update(kw)


def _run_job(job_id, url, quality, mode, folder):
    def log(msg):
        with JOBS_LOCK:
            j = JOBS.get(job_id)
            if j:
                j["log"].append(str(msg))
    try:
        if mode == "folder":
            # 先確認資料夾能寫，免得下載轉檔完才發現存不進去
            os.makedirs(folder, exist_ok=True)
            if not os.access(folder, os.W_OK):
                raise PermissionError(f"Permission denied: {folder}")
        tmpdir, mp3, title = convert(url, quality, log)
        filename = safe_name(title) + ".mp3"
        size_mb = os.path.getsize(mp3) / 1048576
        if mode == "folder":
            dst = unique_path(folder, filename)
            shutil.move(mp3, dst)
            shutil.rmtree(tmpdir, ignore_errors=True)
            _set(job_id, status="done", result={
                "mode": "folder", "path": dst, "folder": folder,
                "name": os.path.basename(dst), "mb": round(size_mb, 1)})
        else:
            _set(job_id, status="done", tmpdir=tmpdir, file=mp3, result={
                "mode": "browser", "name": filename, "mb": round(size_mb, 1)})
    except Exception as e:
        _set(job_id, status="error", error=friendly_error(e))


def _cleanup_jobs():
    """清掉一小時前結束的工作；瀏覽器下載模式沒被取走的暫存檔一起刪。"""
    with JOBS_LOCK:
        old = [k for k, v in JOBS.items()
               if v["status"] != "running" and time.time() - v["t"] > 3600]
        dirs = [JOBS.pop(k).get("tmpdir") for k in old]
    for d in dirs:
        if d:
            shutil.rmtree(d, ignore_errors=True)


def _idle_watchdog():
    """關掉瀏覽器分頁幾分鐘後自動結束，免得背景一直留著程式。"""
    while True:
        time.sleep(30)
        if LAST_PING is None or time.time() - LAST_PING < IDLE_EXIT_SEC:
            continue
        with JOBS_LOCK:
            if any(v["status"] == "running" for v in JOBS.values()):
                continue
        if SERVER:
            threading.Thread(target=SERVER.shutdown, daemon=True).start()
        return


# ==========================================================================
# 只有電腦有的小功能：選資料夾、開啟資料夾
# ==========================================================================

PICK_LOCK = threading.Lock()


def pick_folder(initial):
    with PICK_LOCK:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            d = filedialog.askdirectory(
                parent=root, title="選擇 MP3 要存放的資料夾",
                initialdir=initial if os.path.isdir(initial) else os.path.expanduser("~"))
        finally:
            root.destroy()
        return os.path.normpath(d) if d else ""


def open_folder(path):
    if sys.platform == "win32" and os.path.isdir(path):
        os.startfile(path)
        return True
    return False


# ==========================================================================
# 網頁伺服器
# ==========================================================================

def load_asset(name):
    try:
        with open(os.path.join(BASE_DIR, name), "rb") as f:
            return f.read()
    except OSError:
        return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def do_GET(self):
        global LAST_PING
        u = urllib.parse.urlparse(self.path)
        path = u.path
        qs = urllib.parse.parse_qs(u.query)

        if path in ("/", "/index.html"):
            body = load_asset("ui.html")
            if body is None:
                return self._send(500, "找不到 ui.html", "text/plain; charset=utf-8")
            return self._send(200, body, "text/html; charset=utf-8")

        if path.lstrip("/") in STATIC_FILES:
            name = path.lstrip("/")
            body = load_asset(name)
            return self._send(200 if body else 404, body or b"", STATIC_FILES[name])

        if path == "/api/ping":
            LAST_PING = time.time()
            return self._send(200, {"ok": True, "phone": IS_TERMUX, "build": BUILD,
                                    "settings": load_settings(),
                                    "defaults": default_settings()})

        if path == "/api/status":
            jid = (qs.get("id") or [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(jid)
                if not job:
                    return self._send(404, {"error": "查無此工作"})
                payload = {"status": job["status"], "log": job["log"][-1:]}
                if job["status"] == "done":
                    payload["result"] = job["result"]
                elif job["status"] == "error":
                    payload["error"] = job["error"]
            return self._send(200, payload)

        if path == "/api/file":
            # 瀏覽器下載模式：把 MP3 交給瀏覽器，送完就刪暫存檔
            jid = (qs.get("id") or [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(jid)
                f = job and job.get("file")
                tmpdir = job and job.get("tmpdir")
                name = job and job["result"] and job["result"].get("name")
            if not f or not os.path.exists(f):
                return self._send(404, {"error": "檔案已不存在，請重新下載"})
            quoted = urllib.parse.quote(name or "audio.mp3")
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(os.path.getsize(f)))
            self.send_header("Content-Disposition",
                             f"attachment; filename=\"audio.mp3\"; filename*=UTF-8''{quoted}")
            self.end_headers()
            try:
                with open(f, "rb") as fh:
                    shutil.copyfileobj(fh, self.wfile, 1 << 20)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass
            shutil.rmtree(tmpdir, ignore_errors=True)
            _set(jid, file=None, tmpdir=None)
            return

        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            data = self._json_body()
        except Exception as e:
            return self._send(400, {"error": f"請求格式錯誤：{e}"})

        if path == "/api/quit":
            self._send(200, {"ok": True})
            threading.Timer(0.3, lambda: SERVER and SERVER.shutdown()).start()
            return

        if path == "/api/settings":
            s = load_settings()
            if data.get("reset"):
                s = default_settings()
            else:
                if data.get("quality") in QUALITIES:
                    s["quality"] = data["quality"]
                if data.get("mode") in ("folder", "browser"):
                    s["mode"] = data["mode"]
                if isinstance(data.get("folder"), str):
                    s["folder"] = data["folder"].strip() or default_folder()
            try:
                save_settings(s)
            except OSError as e:
                return self._send(500, {"error": f"設定存不進去：{e}"})
            return self._send(200, {"settings": s})

        if path == "/api/pick":
            if IS_TERMUX:
                return self._send(400, {"error": "手機請直接輸入資料夾路徑"})
            try:
                return self._send(200, {"folder": pick_folder(load_settings()["folder"])})
            except Exception as e:
                return self._send(500, {"error": f"無法開啟選資料夾視窗：{e}"})

        if path == "/api/open":
            ok = open_folder(data.get("folder") or load_settings()["folder"])
            return self._send(200, {"ok": ok})

        if path == "/api/start":
            url = (data.get("url") or "").strip()
            if not re.match(r"^https?://", url, re.I):
                return self._send(400, {"error": "請貼上完整的影片網址（http 或 https 開頭）"})
            s = load_settings()
            jid = uuid.uuid4().hex[:12]
            with JOBS_LOCK:
                JOBS[jid] = {"status": "running", "log": [], "result": None,
                             "error": None, "t": time.time()}
            _cleanup_jobs()
            threading.Thread(target=_run_job,
                             args=(jid, url, s["quality"], s["mode"], s["folder"]),
                             daemon=True).start()
            return self._send(200, {"id": jid})

        return self._send(404, {"error": "not found"})


# ==========================================================================
# 啟動
# ==========================================================================

def _dialog(title, msg, error=False):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title, msg)
        root.destroy()
    except Exception:
        print(msg)


def _deps_ok():
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return bool(find_ffmpeg())


def ensure_deps():
    """缺套件就自動安裝（用小視窗顯示，雙擊捷徑啟動時沒有黑色視窗可看）。"""
    if _deps_ok():
        return True
    import subprocess
    win = None
    try:
        import tkinter as tk
        win = tk.Tk()
        win.title("tomp3")
        win.geometry("400x130")
        win.resizable(False, False)
        win.eval("tk::PlaceWindow . center")
        tk.Label(win, text="首次啟動，正在安裝必要元件…",
                 font=("Microsoft JhengHei UI", 12)).pack(pady=(32, 8))
        tk.Label(win, text="約需 1 分鐘，完成後會自動開啟", fg="#666",
                 font=("Microsoft JhengHei UI", 9)).pack()
        win.update()
    except Exception:
        win = None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "-r",
                        os.path.join(BASE_DIR, "requirements.txt")],
                       creationflags=flags, capture_output=True, timeout=900)
    except Exception:
        pass
    if win:
        try:
            win.destroy()
        except Exception:
            pass
    if _deps_ok():
        return True
    _dialog("無法安裝必要元件",
            "自動安裝失敗。請重新執行一次安裝指令（見 README）。", error=True)
    return False


def open_url(url):
    if IS_TERMUX:
        import subprocess
        for cmd in (["termux-open-url", url],
                    ["am", "start", "-a", "android.intent.action.VIEW", "-d", url]):
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=15)
                return
            except Exception:
                continue
        print(f"\n   請用手機瀏覽器開啟：{url}\n")
        return
    try:
        webbrowser.open(url)
    except Exception:
        pass


def free_port(start):
    for p in range(start, start + 30):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def _build_id():
    import hashlib
    try:
        with open(os.path.abspath(__file__), "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()[:12]
    except Exception:
        return ""


BUILD = _build_id()


def _replace_old_instance():
    """預設連接埠上若還跑著「舊版」的 tomp3，請它結束，讓新版用回同一個網址。"""
    base = f"http://127.0.0.1:{DEFAULT_PORT}"
    try:
        with urllib.request.urlopen(base + "/api/ping", timeout=2) as r:
            j = json.loads(r.read().decode("utf-8"))
    except Exception:
        return False
    if not j.get("ok") or "settings" not in j or j.get("build") == BUILD:
        return False
    try:
        req = urllib.request.Request(base + "/api/quit", data=b"{}", method="POST")
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        return False
    for _ in range(25):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", DEFAULT_PORT)) != 0:
                break
        time.sleep(0.2)
    return True


def serve(open_browser=True):
    global SERVER
    if not ensure_deps():
        return
    clean_old_temp()
    _replace_old_instance()
    port = free_port(DEFAULT_PORT)
    try:
        SERVER = srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        _dialog("無法啟動", f"連接埠 {port} 無法使用：{e}", error=True)
        return

    print()
    print("   tomp3 已啟動")
    print(f"   在瀏覽器開啟：  http://localhost:{port}")
    print("   關掉瀏覽器分頁幾分鐘後，程式會自動結束。")
    print()

    threading.Thread(target=_idle_watchdog, daemon=True).start()
    if open_browser:
        threading.Timer(0.8, lambda: open_url(f"http://localhost:{port}")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n   已結束。")
    finally:
        _cleanup_all()


def _cleanup_all():
    with JOBS_LOCK:
        dirs = [v.get("tmpdir") for v in JOBS.values()]
    for d in dirs:
        if d:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    serve(open_browser="--no-browser" not in sys.argv[1:])
