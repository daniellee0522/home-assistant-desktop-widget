# 自訂 Widget（widgetkit）

HA Widgets 除了內建的時鐘、日曆、天氣、攝影機、圖表與播放器，也能執行**你自己寫（或請 AI 寫）的 Widget**：倒數日、股價、相框、計數器、
電池、世界時鐘……不限於 Home Assistant。一個 Widget 就是一個 Python 檔，說明它**顯示什麼、資料從哪來、使用者能改什麼、按下去會怎樣**；
玻璃、待機變暗、設定視窗、權限詢問都由程式負責。

英文的完整參考在 [widgetkit.md](widgetkit.md)；要請 AI 幫你寫，見最後一節。

## 一、使用者：匯入與使用

1. 打開 **設定 → 開啟 Widget 編輯器**。左邊「時鐘、日曆、天氣…」下面有**「匯入的 Widget」**，第一格是虛線的 **＋**。
2. 按 **＋**，選一個 `.hawidget` 檔（也可以直接選一個 `.py` 檔，程式會自動包成套件）。匯入成功後它會以縮圖出現在這一區。
   縮圖只畫出外觀，不會連網，所以需要網路資料的 Widget 縮圖是空的，這是正常的。
3. 像拖時鐘一樣，把它**拖到桌面**。可以放很多個；每一個都有**自己的設定**。
4. 在編輯器右邊「我的 Widget」點它，下方會出現：
   - 預覽與它支援的尺寸（1x1、2x2、2x4、4x4 中它宣告的那些）。
   - **設定**：Widget 作者宣告了什麼就有什麼，開關、選單、數字、文字、清單、圖片都是程式的原生控制項。
   - **權限**：它想做的事（連到某個網站、使用麥克風、執行某個程式…），每項一個開關。**按「允許所選」才會生效**；有風險的項目預設關閉。
5. 想拿掉：匯入區裡把滑鼠移到縮圖上，按右上角的紅色叉叉，選「移除（含桌面上的複本）」。只想移除桌面上的一個，用「刪除此 Widget」。

注意：
- **Widget 是程式**。它在 HA Widgets 裡執行，權限只約束程式提供的動作（連線、啟動程式、錄音…），並不是沙箱。請只匯入你信任的人寫的 Widget。
- 匯入時會先載入它的程式碼一次，確認能用；載入失敗會顯示原因並自動移除。
- 資料夾 `widget_library/`（在設定檔旁邊）存放匯入的套件、你回答過的權限，以及每個 Widget 的記憶（例如計數器的數字）。
- 有些 Widget 自己接管右鍵（例如相框：右鍵換下一張），這時編輯器請從托盤進入。

## 二、作者：五分鐘寫一個 Widget

```python
from widgetkit.definition import Field, WidgetDef
from widgetkit.theme import text

def draw(p, th, W, H, ctx):                                   # p 是 QPainter；th 是主題；ctx 是它的設定、資料與記憶
    text(p, th, "display", str(ctx.config["goal"]), 24, 24)   # 文字一律用「角色」（display、body、caption…），不自己指定大小或顏色

WIDGET = WidgetDef(id="dev.me.hello", name={"en": "Hello", "zh": "你好"}, size="2x2",
                   config=[Field("goal", "number", 8, {"en": "Goal", "zh": "目標"})],     # 設定視窗由它自動做出來
                   sources=[], draw=draw)
```

存成 `hello.py`，馬上看到結果：

```
python -m widgetkit.studio hello.py            # 即時預覽：每個尺寸、亮暗主題、各語言並排；存檔就重新載入
python -m widgetkit.check hello.py --out preview.png --pack hello.hawidget
```

`check` 會載入、畫出所有尺寸（亮／暗，英文、繁中與一種「更長的假語言」）、列出問題並產生預覽圖；沒有錯誤時用 `--pack` 打包成
`.hawidget`。`ERROR` 一定要修；`cut` 是字被截斷、`overlap` 是字疊字、`overflow` 超出卡片、`tiny` 按鈕太小。

### 設定（Field）

`Field(key, type, default, label, ...)`，`type` 可以是：

| type | 使用者看到 |
| --- | --- |
| `text` / `secret` | 一行文字／遮住的文字（金鑰不會被匯出） |
| `number` | 數字，可設 `minimum`、`maximum`、`step` |
| `bool` | 開關 |
| `choice` | 選單（`options`，`choices` 給每個選項顯示的字） |
| `list` / `feeds` / `launchers` | 字串清單／名稱加網址／圖示加標籤加網址的按鈕 |
| `images` | 用檔案對話框選圖片，最多 `maximum` 張（預設 10） |

標籤、說明、選項字都可以寫成 `{"en": "...", "zh": "..."}`。在 `draw` 裡用 `ctx.config["key"]` 讀。

### 尺寸

四種：`1x1`（160×161）、`2x2`（333×334）、`2x4`（678×334）、`4x4`（678×680）。`size` 是預設，`sizes=("2x4",)` 列出它還能變成的。
`draw` 拿到實際的 `W`、`H`，用 `ctx.size_name()` 或比例決定版面，**不要寫死像素**。

### 資料來源

```python
from widgetkit.sources import JsonSource
PRICE = JsonSource("p", "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                   {"price": "chart.result.0.meta.regularMarketPrice"}, every=60)    # {symbol} 是使用者的設定
# WidgetDef(..., sources=[PRICE], permissions=("network:query1.finance.yahoo.com",))
# draw 裡：ctx.data["p"]["price"]（還沒抓到時是 None，要畫出「載入中」）
```

另有 `RssSource`（新聞）、`ImageSource`（網路圖片）、`SystemSource`（電池／記憶體／磁碟／CPU，要 `system` 權限）、
`SystemMediaSource`（這台電腦正在播放什麼）。資料在背景抓，抓失敗時保留上一次的。

### 互動與記憶

- 可按的地方用 `ctx.hits.add(QRectF(...), "id")` 登記（或用 `controls.button(..., hits=ctx.hits, id="id")`），在 `on_tap(id, ctx)` 處理。
- 記憶放在 `ctx.state`，只在處理函式裡用 `ctx.set_state(count=...)` 改，重新開機後還在。
- 其他處理函式：`on_submit`（輸入框按 Enter）、`on_drop`（拖檔案進來）、`on_drag`、`on_scroll`、`on_context`（右鍵）。
- 處理函式**只改記憶並回傳動作**（`open_url`、`copy`、`request`、`launch`、`open_app`、`media`、`record_start`…），不直接做事；動作要「宣告了權限且使用者允許」才會執行。
- 會動的東西：`tick=秒`（定時重畫）、`ctx.redraw_in(秒)`（下一張圖、下一個動畫影格）、`ctx.spring(...)`（緩動）。

### 玻璃、背景與待機

- 玻璃是程式的共用主題，Widget 不自己畫玻璃。預設 `background="solid"`：亮著時程式在 Widget 下面畫一張實心底（淺色白、深色近黑）；待機時是透明玻璃。
  沒有自己底色、想直接疊在玻璃上的才宣告 `background="glass"`。
- 待機時文字、圖示、強調色**自動變白**（用 `th.ink1`、`th.ink2`、`th.accent(...)` 就會）；圖片用 `mono=th.dim` 變成白色、暗處透明的單色。
  所以請不要自己寫死顏色，也不要只靠顏色區分兩件事。
- 待機時程式很少重畫；`standby_tick` 可以調整（`0` 表示完全不畫）。

### 打包與分享

資料夾裡放 `manifest.json` 與 `main.py`：

```json
{"id": "dev.me.hello", "name": {"en": "Hello", "zh": "你好"}, "version": "1.0", "kit": 1, "entry": "main.py",
 "author": "me", "permissions": []}
```

`python -m widgetkit.check 資料夾 --pack hello.hawidget` 就會產生 `.hawidget`（本質是 zip）。程式碼要的權限不能比 manifest 多。
可參考的完整範例：`widgetkit/examples/`（價格、清單、問答、相簿、計時器、世界時鐘、電池、地圖、錄音、快捷列、時鐘、日曆、播放器、喝水）
與 `widgetkit/packages/photoframe/`（相框：10 張圖、GIF／WebP 動圖、右鍵換圖、自動輪播、待機單色）。

## 三、請 AI 幫你寫

專案內附了一個 Claude 技能 **`ha-widget-author`**（`.claude/skills/ha-widget-author/`；另有可獨立安裝的 `docs/ha-widget-author.skill`）。
在這個專案裡用 Claude Code，直接說：

- 「幫我做一個倒數到跨年的 widget，圓環顯示進度，名稱和日期可以設定」
- 附上一張 iOS widget 的截圖：「照這張做一個，資料用 Yahoo 的股價」

它會依序：決定尺寸／資料／權限／設定項目 → 寫 `main.py` 與 `manifest.json` → 執行 `python -m widgetkit.check` → **看預覽圖**修到沒有錯誤 → 打包出
`.hawidget`，並告訴你它需要哪些權限。你只要在「匯入的 Widget」按 ＋ 匯入即可。技能內含完整的 API 速查、設計規則（含「怎麼把圖片變成版面」）與三個
已檢查過的範例。

在沒有原始碼的環境（只裝了程式）也能用：AI 會產生 `main.py` 與 `manifest.json` 並壓成 `.hawidget`，但無法預覽，匯入時才會看到錯誤。
