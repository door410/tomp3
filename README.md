# tomp3

貼上影片網址 → 轉成 MP3。可選音質，存到你指定的資料夾或交給瀏覽器下載。
全部在自己的電腦／手機上執行，不需要帳號、不用付費。

## 安裝與更新（同一行指令）

| 裝置 | 第一次安裝、之後更新都貼這一行 |
|---|---|
| 電腦（PowerShell） | `irm https://raw.githubusercontent.com/door410/tomp3/main/install.ps1 \| iex` |
| 手機（Termux） | `pkg install -y curl && bash <(curl -fsSL https://raw.githubusercontent.com/door410/tomp3/main/android/install.sh)` |

- **電腦**：按 Win 鍵 → 輸入 `powershell` → Enter → 貼上指令。會裝到 `C:\Users\你的帳號\tomp3`，
  桌面出現 **tomp3** 捷徑。轉檔工具 ffmpeg 會跟著自動裝好（只給 tomp3 用，不改系統設定）。
- **手機**：Termux 請從 F-Droid 安裝。會裝到 `~/tomp3`；之後在 Termux 輸入 `tomp3` 就能啟動。
  第一次會問「允許存取檔案」，請按允許（MP3 預設存到手機的 `Download/tomp3`）。
- 更新前先把 tomp3 的瀏覽器分頁關掉。

## 使用

1. 雙擊桌面 **tomp3**（手機輸入 `tomp3`），瀏覽器會自動打開。
2. 貼上影片網址 → 按 **下載 MP3**。
3. 想改音質或存放位置：點 **設定 ▸** 展開。改過會記住，沒改就一直用預設。

| 設定 | 預設 | 說明 |
|---|---|---|
| 音質 | 192 kbps | 128／192／320 kbps，或「原始最佳」（MP3 最高品質的可變位元率） |
| 存放方式 | 存到資料夾 | 或「瀏覽器下載」：存到瀏覽器的下載位置 |
| 資料夾 | 電腦 `下載\tomp3`、手機 `Download/tomp3` | 可直接改路徑；電腦可按「選資料夾」 |

音質上限取決於影片本身的聲音，選再高也不會比原本更好；一般 192 就夠。

## 和 transcript 的關係

完全獨立：不同資料夾、不同網址（連接埠 8766，transcript 是 8756）、不同捷徑，可以同時開。
只共用電腦／手機上的 Python 和 yt-dlp（任一個更新 yt-dlp，兩個都受惠）。

## 檔案

| 檔案 | 用途 |
|---|---|
| `tomp3.py` | 本機伺服器：下載音訊、轉 MP3、存檔 |
| `ui.html`、`tokens.css` | 畫面 |
| `install.ps1`、`start.vbs`、`make_shortcut.vbs` | 電腦安裝、無黑窗啟動、桌面捷徑 |
| `android/install.sh` | 手機安裝／更新 |
| `settings.json` | 你的設定（自動產生，不進版控） |
