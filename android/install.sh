#!/data/data/com.termux/files/usr/bin/bash
# =====================================================================
#  tomp3 — 手機（Termux）安裝／更新，同一行：
#
#      pkg install -y curl && bash <(curl -fsSL https://raw.githubusercontent.com/door410/tomp3/main/android/install.sh)
#
#  第一次：裝 python／ffmpeg／git，下載程式到 ~/tomp3，建立指令 tomp3 和桌面小工具捷徑。
#  之後再跑：更新到最新版。可以重複執行，已完成的步驟會跳過。
#  和 transcript 完全分開：不同資料夾、不同連接埠、不同捷徑；只共用 Termux 的 python／ffmpeg。
# =====================================================================

REPO="https://github.com/door410/tomp3"
APP="$HOME/tomp3"
FAIL=0
say() { echo "  $*"; }

echo ""
say "=== tomp3 ==="

say "[1/4] 檢查 python、ffmpeg、git…"
NEED=""
for p in python ffmpeg git; do
  command -v "$p" >/dev/null 2>&1 || NEED="$NEED $p"
done
if [ -n "$NEED" ]; then
  say "  安裝：$NEED"
  pkg install -y $NEED
fi
for p in python ffmpeg git; do
  command -v "$p" >/dev/null 2>&1 || { say "  $p 安裝失敗"; FAIL=1; }
done
# ffmpeg 光是存在不代表能跑，實際執行一次
if ! ffmpeg -version >/dev/null 2>&1; then
  say "  ffmpeg 無法執行，嘗試更新相關套件…"
  pkg upgrade -y
  ffmpeg -version >/dev/null 2>&1 || { say "  ffmpeg 仍然無法執行"; FAIL=1; }
fi

say "[2/4] 下載／更新程式…"
if [ -d "$APP/.git" ]; then
  git -C "$APP" pull --ff-only || { say "  更新失敗（見上方訊息）"; FAIL=1; }
else
  git clone "$REPO" "$APP" || { say "  下載失敗"; exit 1; }
fi

say "[3/4] 安裝 Python 套件（yt-dlp）…"
pip install --upgrade -r "$APP/requirements.txt" >/dev/null 2>&1 \
  || pip install --upgrade yt-dlp >/dev/null 2>&1
python -c "import yt_dlp" 2>/dev/null && say "  yt-dlp : OK" || { say "  yt-dlp : 失敗"; FAIL=1; }

say "[4/4] 建立指令與捷徑…"
BIN="${PREFIX:-/data/data/com.termux/files/usr}/bin/tomp3"
cat > "$BIN" <<'STARTER'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null
cd "$HOME/tomp3" || { echo "找不到 ~/tomp3，請重跑安裝指令"; exit 1; }
python tomp3.py
# transcript 還開著的話不要放掉喚醒鎖（兩個程式共用同一個鎖）
pgrep -f ytscript.py >/dev/null 2>&1 || termux-wake-unlock 2>/dev/null
STARTER
chmod +x "$BIN"
mkdir -p "$HOME/.shortcuts"
cp "$BIN" "$HOME/.shortcuts/tomp3"
chmod +x "$HOME/.shortcuts/tomp3"
say "  指令 tomp3、桌面小工具捷徑 tomp3：OK"

# 預設存到手機的 Download/tomp3，需要「存取檔案」權限
if [ ! -d "$HOME/storage" ]; then
  say ""
  say "  接下來手機會問「允許 Termux 存取檔案嗎？」請按「允許」。"
  termux-setup-storage
  sleep 3
fi

echo ""
if [ "$FAIL" = 0 ]; then
  say "完成！輸入 tomp3 就能啟動（或用桌面小工具的 tomp3）。"
else
  say "有步驟失敗（見上方訊息）。網路穩定後再貼一次同一行指令。"
fi
