# HA Widgets

把 Home Assistant 的配件做成 Windows 桌面上的一塊毛玻璃面板——像 Rainmeter 的元件那樣貼在桌面上，而不是一個會搶焦點、會出現在工作列的視窗。點工作列圖示可以叫出一個貼著工作列的面板，像音量控制那樣。

A frosted-glass desktop widget for Home Assistant on Windows. It sits on
the desktop like a Rainmeter skin rather than behaving like an
application window, and the tray icon opens it as a panel beside the
clock, the way the volume flyout does.

![widget](docs/widget.png)

## 它能做什麼

- **貼在桌面上**：釘在 z-order 最底層、不搶焦點、不出現在工作列，拖曳可移動並記住位置。
- **真的毛玻璃**：視窗本身不能透明（見下方「怎麼做到的」），所以背景是把桌面實際的畫面擷取下來畫進去的——四個圓角是真的透出後面的東西，不是畫上去的漸層。
- **即時更新**：透過 Home Assistant 的 WebSocket API 推送，不是輪詢。
- **二級菜單**：長按或右鍵任何配件，開出屬於它的控制卡片——亮度、色溫、顏色、溫度、風速、開合、音量；感測器則顯示 24 小時的紀錄圖表。
- **工作列面板**：左鍵點工作列圖示，widget 會以面板的形式從角落彈出，點別處就收起來。

| 工作列面板 | 開關／鎖 | 感測器歷史 |
|---|---|---|
| ![panel](docs/tray-panel.png) | ![switch](docs/detail-switch.png) | ![history](docs/detail-history.png) |

## 安裝

到 [Releases](../../releases) 下載 `HA-Widgets-Setup.exe` 執行即可；它裝在使用者目錄下，不需要系統管理員權限。

第一次啟動會開啟設定，填入 Home Assistant 的網址和一組 [長效存取權杖](https://www.home-assistant.io/docs/authentication/#your-account-profile)，然後挑選要顯示的配件。設定存在 `%APPDATA%\HA Widgets\`。

## 從原始碼執行

需要 Python 3.12 和 Windows 10/11（WebView2，Windows 11 內建）。

```bash
pip install -r requirements.txt
python main.py
```

## 自己打包

```bash
python packaging/build.py
```

產出 `dist/HA Widgets/`。接著兩條路：

- 有 [Inno Setup 6](https://jrsoftware.org/isdl.php) 的話，`ISCC.exe packaging\installer.iss` 會做出 `dist/HA-Widgets-Setup.exe`。
- 沒有的話，`powershell -ExecutionPolicy Bypass -File packaging\Install.ps1` 直接把它裝進 `%LOCALAPPDATA%`、建立開始功能表捷徑並設定開機啟動。`Uninstall.ps1` 反向操作。

## 怎麼做到的

幾個比較不直覺的地方，原始碼裡有更完整的註解：

- **視窗沒辦法是半透明的。** Mica/Acrylic、`SetWindowCompositionAttribute`、`WS_EX_LAYERED` 的色鍵、pywebview 的 `transparent=True`，在 WebView2 子視窗下全部量測過，出來的顏色不會跟著背後的桌布改變；`SetWindowRgn` 會裁出形狀，但被裁掉的區域合成出來是不透明的黑色。所以背景是自己畫的：把視窗底下那塊桌面擷取下來，鋪滿整個視窗，卡片內側用預先模糊過的版本，圓角外緣維持銳利——那四個角看起來才像真的鏤空。

- **有一條路只差最後一步。** Windows 11 22H2 以上，`DwmExtendFrameIntoClientArea`（整個 client area）加上 `DWMWA_SYSTEMBACKDROP_TYPE`，在一個「乾淨」的 pywebview 視窗上確實會讓它真的半透明（量過：背後圖樣平均 74.6/86.2/78.0，隔著玻璃看出來是 74.7/88.2/81.1 的模糊版）。這也是 Windhawk 的 Translucent Windows 模組的做法。但放進這個程式就不行了：把底下那個 WinForms form 的背景塗成紅色，卡片中間就變紅——代表頁面和 WebView2 表面都是真的透明，擋住 DWM 的是 form 自己畫的不透明底色。塗成黑色（在 extended frame 裡本來應該被當成 alpha=0）得到的是黑色卡片而不是玻璃。所以這個模式預設關閉，要設 `HA_WIDGET_SYSTEM_GLASS` 環境變數才會出現在設定裡；main.py 裡 `_SYSTEM_GLASS_SUPPORTED` 上面那段註解記了已經排除掉的每一個可能。

- **擷取要夠便宜。** 直接從螢幕 DC `BitBlt` 比 `PrintWindow` 快五倍，但前提是自己的視窗要先用 `WDA_EXCLUDEFROMCAPTURE` 從畫面擷取中排除，否則會把自己讀進去變成無限鏡像。代價是這個 widget 不會出現在截圖和錄影裡（設定裡可以關掉）。

- **只有四個角需要銳利。** 卡片蓋滿整個視窗，所以整張擷取裡真正看得到的只有圓角外的四個楔形。它們被打包成一張小方圖傳給頁面，bitmap 只有原本的 1/22——這是讓取樣維持在每幀 6ms 的主要原因。（想連擷取也只讀那四小塊反而更慢：一次螢幕 blit 不管大小都要約 5ms，四次小的量到 20ms，整個視窗一次只要 8ms。）

- **每個視窗獨立。** 二級菜單、設定、工作列面板各自是一個 WebView2 視窗，載入同一個頁面的不同 hash。三個視窗共用一個 renderer process（`--process-per-site`），而且不需要 GPU（`--disable-gpu`）——量測下來軟體路徑反而更省 CPU，也省掉 300MB。

## 授權

MIT，見 [LICENSE](LICENSE)。
