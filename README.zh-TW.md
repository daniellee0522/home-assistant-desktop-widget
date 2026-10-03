# Home Assistant 桌面小工具（Windows）— HA Widgets

[English](README.md) | 繁體中文

把 Home Assistant 的控制項放到 Windows 10/11 桌面上。輕量的桌面 widget，
具有毛玻璃或液態玻璃背景與透明圓角，並提供系統匣面板方便快速操作。使用 Qt 開發。

**[下載最新安裝檔](https://github.com/daniellee0522/home-assistant-desktop-widget/releases/latest)**
（`HA-Widgets-Setup-<版本>.exe`；升級時會保留你的設定）。

## 外觀

下列截圖使用示範裝置，呈現實際的 Qt 介面。玻璃效果會隨桌布而不同。

| 外觀 | 淺色 | 深色 |
| --- | --- | --- |
| 經典毛玻璃 | ![經典淺色](docs/theme-classic-light.png) | ![經典深色](docs/theme-classic-dark.png) |
| 液態玻璃 | ![液態淺色](docs/theme-liquid-light.png) | ![液態深色](docs/theme-liquid-dark.png) |
| Windows 玻璃 | ![Windows 淺色](docs/theme-windows-light.png) | ![Windows 深色](docs/theme-windows-dark.png) |

| 系統匣面板 | 裝置控制 | 感測器歷史 |
| --- | --- | --- |
| ![系統匣面板](docs/tray-panel.png) | ![裝置控制](docs/detail-switch.png) | ![感測器歷史](docs/detail-history.png) |

![Widget 編輯器](docs/widget-editor.png)

## 功能

- **多個 widget：** 可放任意數量、四種尺寸（1x1、2x2、2x4、4x4）的 widget，各自有自己的裝置。磁貼會依 widget 大小以小方塊、長條或大方塊填滿，大小與間距一致，並可互相吸附、貼齊螢幕邊緣。
- **視覺化編輯器：** 設定 → 開啟 Widget 編輯器。把尺寸拖到桌面即新增 widget，拖曳配置圖上的方塊移動位置，拖曳配件調整順序；也可以直接在桌面上對 widget 按右鍵編輯。
- **桌面控制：** 把裝置放在桌面上，可拖曳重新擺放，也能鎖定位置。
- **即時更新：** 透過 Home Assistant 的 WebSocket API 即時更新裝置狀態。
- **快速存取：** 點擊系統匣圖示，在工作列旁開啟面板。面板可有自己的配件清單（在 Widget 編輯器選「系統匣面板」編輯，或讓它顯示所有 widget 的配件），一次顯示兩列，超過八個可捲動。也可在設定 → **面板樣式** 改成 **Home 風格**：所有裝置依房間（Home Assistant 的區域，可在裝置詳情卡片中逐一改房間）分組，頂端是分類膠囊（環境溫濕度、燈光、保全系統（門鎖與攝影機）、媒體音訊，沒有該類配件就不顯示），房間也是膠囊，可自行新增房間，操作方式（點擊、長按、右鍵）與一般磁貼相同。按下膠囊時房間畫面會縮入淡出，該類配件浮現；再按一次膠囊或空白處即可退回。溫度與濕度以狀態顯示，同一房間有多個時顯示範圍。按「編輯」可拖曳房間（膠囊或房間標題）調整順序、隱藏整個房間、拖曳磁貼到其他房間、拉磁貼右下角改成方塊／長條／大方塊、移除磁貼（「＋」可加回）、選擇主畫面顯示哪些房間，也可以按房間膠囊上的 **✕** 刪除房間（裡面的配件會歸到「未分類」，未分類預設不在主畫面顯示；「＋」可還原刪除的房間）。在面板裡長按或右鍵磁貼，控制項會直接浮現在面板中、蓋在磁貼上方；按 **‹**、旁邊的空白處或 Esc 返回。設定 → **面板背景圖片** 可在面板後方放自己的圖片（先套用模糊）。面板在不同顯示器上佔畫面的比例大致相同（大螢幕或高解析度時放大、小螢幕時縮小，且不會超出可用範圍）。
- **裝置詳情：** 右鍵或長按磁貼，開啟更多控制項與感測器歷史。
- **快捷鍵：** 在任何地方按 **Ctrl + Alt + H** 即可開關系統匣面板。可在設定 → 行為按下其他組合，或清除。
- **警示通知（預設關閉）：** 在設定 → 通知開啟後，widget 或面板上的門鎖被解鎖、打開或卡住，或安全感測器觸發（門窗打開、漏水、煙霧、瓦斯、一氧化碳等）時，以 Windows 通知提醒。只通知變化，不會通知啟動時的狀態，同一件事一分鐘內只提醒一次。
- **個人化：** 淺色／深色主題；經典、液態、Windows 三種玻璃；可調縮放與固定 widget 大小。
- **省資源：** 所有視窗都直接原生繪製，程式裡完全沒有瀏覽器引擎：桌面 widget、詳情卡、系統匣面板與設定都是。常駐約 50 MB 記憶體，桌面靜止時 CPU 接近 0 %；開啟面板或設定時約 70～90 MB（開啟時才建立，閒置一段時間後釋放）。使用影片桌布時，可把「毛玻璃更新」設為靜態，只在移動 widget 時取樣。
- **自動變暗：** 桌面被其他視窗蓋住時 widget 會變暗，回到桌面或點擊時恢復。
  點擊工作列、開始功能表或 widget 自己的面板，不會取消變暗。
- **語言：** 繁體中文與英文。

在裝置的詳情畫面中開啟編輯面板，可以選擇圖示，或輸入 Material Design Icons
名稱，例如 `mdi:air-conditioner`。未選擇時會使用 Home Assistant 提供的 `mdi:`
圖示。圖示已內建，可離線使用。

## 毛玻璃來源

設定 → **毛玻璃來源**：

- **畫面擷取**（預設）：速度快，但 widget 不會出現在螢幕截圖與錄影中。
- **相容模式**：widget 可出現在錄影中，但桌布渲染較慢。系統匣面板後方某些
  由 GPU 繪製的程式，可能不會出現在面板的玻璃中。

液態玻璃移植自 [KMPLiquidGlass 的 Lens.kt](https://github.com/Kashif-E/KMPLiquidGlass/blob/master/backdrop/src/skiaMain/kotlin/com/kashif_e/backdrop/effects/Lens.kt)；折射環只取決於卡片形狀，因此預先算好成網格，每張新畫面只要經過網格扭曲一次（不需要 GPU）。設定 → **液態玻璃模糊度** 從 0（最透明、折射最清楚）到 100（接近經典毛玻璃）。

螢幕擷取使用 DXGI Desktop Duplication：Windows 會回報螢幕哪些區域有變化，
只有視窗後方的畫面改變時才會更新玻璃，最高約每秒 30 次；畫面靜止時完全不會擷取。
設定 → **毛玻璃更新**：*動態* 隨每次變化更新（Wallpaper Engine 這類動態桌布會一直變化，暫停時則不擷取）；*靜態* 只取樣一次，之後只在 widget 移動或調整大小時重新取樣。

## 安裝與執行

安裝版：執行 `HA-Widgets-Setup-<版本>.exe`。要升級時直接執行新版安裝檔，設定會保留。

從原始碼執行（Windows 10/11、Python 3.12）：

```powershell
pip install -r requirements.txt
python main.py
```

開啟設定，輸入你的 Home Assistant 網址與
[長期存取權杖](https://www.home-assistant.io/docs/authentication/#your-account-profile)，
再選擇要顯示的裝置。設定檔在原始碼執行時存於 `main.py` 旁的
`ha_widgets_config.json`，安裝版則存於 `%APPDATA%\HA Widgets`。

## 開發

- 測試：見 [tests/README.md](tests/README.md)。
- 安裝檔：見 [packaging/README.md](packaging/README.md)。

## 授權

[MIT](LICENSE)

內建的 Material Design Icons 路徑資料：[Apache 2.0](nativeui/mdi-LICENSE)。
