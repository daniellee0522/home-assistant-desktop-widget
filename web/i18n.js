"use strict";

// Source text is Traditional Chinese. Keeping the dictionary at the view
// boundary also translates labels built after websocket updates or opening a
// separate detail window, without changing Home Assistant entity names.
const EN_TEXT = {
  '尚未設定任何配件':'No devices added', '按這裡開始設定 Home Assistant':'Set up Home Assistant to get started',
  '開啟設定':'Open settings', '編輯':'Edit', '圖示':'Icon', 'MDI 圖示名稱':'MDI icon name',
  '例如 mdi:air-conditioner':'For example, mdi:air-conditioner', '名稱':'Name', '類別名稱':'Category label',
  '完成':'Done', '設定':'Settings', '未連線':'Disconnected', '已連線 (即時同步)':'Connected (live)',
  'Home Assistant 連線':'Home Assistant connection', '網址':'URL',
  '長效存取權杖 (Long-Lived Access Token)':'Long-lived access token', '貼上你的 token':'Paste your token',
  '測試連線':'Test connection', '外觀':'Appearance', '語言':'Language', '繁體中文':'Traditional Chinese',
  '主題':'Theme', '跟隨系統':'Follow system', '淺色':'Light', '深色':'Dark',
  '玻璃外觀':'Glass appearance', '經典毛玻璃':'Classic frost', '液態玻璃':'Liquid glass',
  'Windows 玻璃':'Windows glass', '每列數量':'Columns', '工作列面板':'Tray panel', '同上':'Same as widget',
  '毛玻璃來源':'Glass source', '系統繪製 (最省資源，即時)':'System rendered (live, efficient)',
  '畫面擷取 (widget 不出現在截圖／錄影)':'Screen capture (widget hidden from recordings)',
  '相容模式 (較耗資源，會出現在截圖)':'Compatibility (widget visible in recordings)',
  '毛玻璃是把視窗底下的桌面擷取下來再模糊畫上去的。擷取模式為了讀得夠快，會把 widget 從畫面擷取中排除，代價是截圖和錄影裡看不到它；相容模式不排除，但改用比較慢的方式取得桌布。':'Glass blurs a capture of the desktop behind the window. Screen capture excludes the widget for speed, so it will not appear in recordings. Compatibility mode keeps it visible but captures more slowly.',
  '縮放比例':'Scale', '毛玻璃更新率':'Glass sample rate',
  '越高越跟得上動態桌布，耗用也等比增加；靜止的桌布會自動放慢。工作列面板不受此限制——它開著的時候會跟著螢幕更新率跑。':'Higher rates track animated wallpaper more closely and use more resources. Still wallpaper slows automatically. The tray panel follows the display while open.',
  '行為':'Behavior', '鎖定位置 (無法拖曳移動)':'Lock position (disable dragging)',
  '離開桌面時淡化 (全螢幕時立刻淡化，回到桌面或點一下恢復)':'Dim away from desktop (immediately in full screen; return or click to restore)',
  '離開桌面多久後淡化':'Dim after leaving desktop', '開機時自動啟動':'Start with Windows',
  '固定視窗大小 (內容超出時可捲動)':'Fixed window size (scroll overflow)', '寬度 (px)':'Width (px)',
  '高度 (px)':'Height (px)', '配件':'Devices', '配件 (':'Devices (', '+ 新增配件':'+ Add device', '結束程式':'Quit',
  '新增配件':'Add device', '選擇一個實體':'Choose an entity', '搜尋實體 / 名稱...':'Search entities / names...',
  '燈光':'Light', '開關/插座':'Switch / outlet', '虛擬開關':'Virtual switch', '空調':'Climate',
  '風扇':'Fan', '窗簾/百葉':'Cover / blinds', '媒體播放器':'Media player', '門鎖':'Lock',
  '掃地機':'Robot vacuum', '場景':'Scene', '腳本':'Script', '自動化':'Automation',
  '感測器':'Sensor', '感測器 (開關型)':'Binary sensor', '冷氣':'Cooling', '暖氣':'Heating',
  '自動':'Auto', '除濕':'Dry', '送風':'Fan only', '關閉':'Off', '開啟':'Open', '已上鎖':'Locked',
  '未上鎖':'Unlocked', '偵測到':'Detected', '正常':'Normal', '無法連線':'Unavailable',
  '插座':'Outlet', '燈':'Light', '音樂':'Music', '螢幕':'Monitor', '門':'Door',
  '溫度':'Temperature', '濕度':'Humidity', '百葉窗':'Blinds', '窗簾':'Curtains',
  '顏色':'Color', '亮度':'Brightness', '色溫':'Color temperature', '風速':'Fan speed',
  '目前':'Current', '開':'Open', '停':'Stop', '關':'Close', '開合程度':'Position',
  '音量':'Volume', '暫停':'Pause', '開始':'Start', '回充':'Return to dock',
  '載入中…':'Loading…', '載入中...':'Loading...', '沒有紀錄':'No history',
  '讀不到紀錄':'Could not load history', '沒有符合的實體':'No matching entities',
  '雙擊重新命名':'Double-click to rename', '每次調整溫度的幅度':'Temperature step',
  '跟隨螢幕':'Follow display', '測試中...':'Testing...', '連線成功':'Connection successful',
  '未知錯誤':'Unknown error', '秒':'sec', '分鐘':'min', '小時':'hours',
};

let interfaceLanguage = 'zh-TW';
const originalText = new WeakMap();
const originalAttributes = new WeakMap();

function translateInterfaceText(source) {
  if (interfaceLanguage !== 'en') return source;
  const trimmed = source.trim();
  let translated = EN_TEXT[trimmed];
  if (!translated) {
    const patterns = [
      [/^配件 \((\d+)\)$/, m => `Devices (${m[1]})`],
      [/^過去 (\d+) 小時$/, m => `Past ${m[1]} hours`],
      [/^目前 (.+)$/, m => `Current ${m[1]}`],
      [/^(\d+(?:\.\d+)?) 秒$/, m => `${m[1]} sec`],
      [/^(\d+(?:\.\d+)?) 分鐘$/, m => `${m[1]} min`],
      [/^找不到 MDI 圖示：(.+)$/, m => `MDI icon not found: ${m[1]}`],
      [/^操作失敗: (.+)$/, m => `Action failed: ${m[1]}`],
      [/^失敗: (.+)$/, m => `Failed: ${m[1]}`],
      [/^設定開機啟動失敗(?:: (.+))?$/, m => `Could not enable startup${m[1] ? ': ' + m[1] : ''}`],
    ];
    for (const [pattern, render] of patterns) {
      const match = trimmed.match(pattern);
      if (match) { translated = render(match); break; }
    }
  }
  if (!translated) return source;
  return source.replace(trimmed, translated);
}

function translateInterface(root = document.body) {
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const parent = node.parentElement;
    if (!parent || /^(SCRIPT|STYLE|TEXTAREA)$/.test(parent.tagName) ||
        parent.closest('.tile-room, .tr-room, .pi-name, #detail-room')) continue;
    const old = originalText.get(node);
    const source = old !== undefined && node.nodeValue === translateInterfaceText(old) ? old :
      interfaceLanguage === 'en' ? node.nodeValue : (old !== undefined ? old : node.nodeValue);
    originalText.set(node, source);
    const result = translateInterfaceText(source);
    if (node.nodeValue !== result) node.nodeValue = result;
  }
  const elements = [root, ...root.querySelectorAll('*')];
  for (const element of elements) {
    if (!(element instanceof Element)) continue;
    for (const attr of ['title', 'placeholder', 'aria-label']) {
      if (!element.hasAttribute(attr)) continue;
      let originals = originalAttributes.get(element);
      if (!originals) { originals = {}; originalAttributes.set(element, originals); }
      const current = element.getAttribute(attr);
      const old = originals[attr];
      const source = old !== undefined && current === translateInterfaceText(old) ? old :
        interfaceLanguage === 'en' ? current : (old !== undefined ? old : current);
      originals[attr] = source;
      const result = translateInterfaceText(source);
      if (current !== result) element.setAttribute(attr, result);
    }
  }
  document.documentElement.lang = interfaceLanguage;
}

function setInterfaceLanguage(language) {
  interfaceLanguage = language === 'en' ? 'en' : 'zh-TW';
  translateInterface();
}

new MutationObserver(mutations => {
  const roots = new Set();
  for (const mutation of mutations) {
    roots.add(mutation.type === 'characterData' ? mutation.target.parentElement : mutation.target);
  }
  for (const root of roots) if (root instanceof Element) translateInterface(root);
}).observe(document.documentElement, { subtree: true, childList: true, characterData: true });
