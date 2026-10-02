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
  '毛玻璃更新':'Glass updates', '動態 (桌布變動時即時更新)':'Live (follows every wallpaper change)', '靜態 (只在移動 widget 時更新，最省資源)':'Still (updates only when the widget moves, lightest)',
  '使用動態桌布 (如 Wallpaper Engine) 時，動態會隨每個畫面重新取樣。桌布暫停或靜止時兩者都不耗資源；想在動態桌布播放時也省資源，選靜態。':'With an animated wallpaper (such as Wallpaper Engine), live re-samples on every frame. Neither costs anything while the wallpaper is paused or still; choose still to save resources while it plays.',
  '面板樣式':'Panel style', '配件方塊':'Device tiles', 'Home 風格 (依房間)':'Home style (by room)',
  '房間':'Room', '沿用 Home Assistant 的區域':'Use the Home Assistant area', '全部':'All', '其他':'Other',
  '這個房間沒有配件':'No devices in this room', '正在載入配件…':'Loading devices…', '一切正常':'Everything is normal',
  '門鎖皆已上鎖':'All locks are locked',
  '環境':'Climate', '電燈':'Lights', '門鎖':'Locks', '窗簾':'Blinds', '媒體':'Media', '新增配件':'Add devices',
  '編輯':'Edit', '調整配件的大小、位置與顯示的房間':'Resize, move and choose the rooms shown',
  '已移除的配件':'Removed devices', '沒有已移除的配件':'No removed devices', '溫度與濕度感測器 (房間)':'Temperature and humidity sensors (room)',
  '沒有可顯示的配件':'No devices to show', '未指定':'Unassigned', '全部關閉':'All off', '全部已鎖上':'All locked',
  '全部開啟':'All open', '播放中':'Playing', '已暫停':'Paused', '關閉':'Off', '待機':'Standby', '無法連線':'Unavailable',
  '暫停':'Pause', '播放':'Play', '面板背景圖片':'Panel background picture', '選擇圖片':'Choose picture', '更換圖片':'Change picture',
  '圖片模糊程度':'Picture blur', '選擇面板背景圖片':'Choose a panel background picture',
  '在系統匣面板的玻璃位置顯示你選的圖片（先套用一層模糊），取代桌面的毛玻璃。':'Shows your picture (blurred first) in place of the desktop glass behind the tray panel.',
  '燈光':'Lights', '保全系統':'Security', '媒體音訊':'Media & audio', '無資料':'No data', '閒置':'Idle',
  '＋ 房間':'+ Room', '房間名稱':'Room name', '刪除房間':'Delete room', '把配件拖曳到這裡':'Drop devices here',
  '這個房間還沒有配件':'No devices in this room yet', '沒有已移除的配件。被移除的配件會列在這裡，按一下加回。':'Nothing removed. Removed devices are listed here; press one to bring it back.',
  '我的家':'My home',
  '隱藏房間':'Hide room', '已隱藏的房間':'Hidden rooms', '已移除的配件':'Removed devices', '顯示':'Show',
  '按 − 不顯示該配件，按 ＋ 加回':'Press − to leave a device out, ＋ to bring it back',
  '不在這個膠囊顯示':'Leave out of this capsule', '加回這個膠囊':'Put back in this capsule',
  '系統匣面板':'Tray panel', '改為顯示所有 Widget 的配件':"Show every widget's devices instead",
  '開啟 Widget 編輯器':'Open widget editor', 'Widget 編輯器':'Widget editor',
  '用拖曳新增、擺放 Widget，並編排每個 Widget 顯示的配件。也可以在桌面上對 Widget 按右鍵。':'Drag to add and place widgets, and arrange the devices each one shows. You can also right-click a widget on the desktop.',
  '拖曳新增、擺放，並編排配件':'Drag to add, place and arrange devices', '拖曳到桌面新增':'Drag onto the desktop to add',
  '桌面配置（拖曳移動）':'Desktop layout (drag to move)', '鎖定位置 (桌面上無法拖曳移動)':'Lock position (cannot be dragged on the desktop)',
  '我的 Widget':'My widgets', '預覽（拖曳配件調整順序）':'Preview (drag devices to reorder)', '拖曳到桌面':'Drag onto the desktop',
  '移除':'Remove', '尚無配件，按下方「新增配件」':'No devices yet; use Add device below',
  '毛玻璃來源':'Glass source', '系統繪製 (最省資源，即時)':'System rendered (live, efficient)',
  '畫面擷取 (widget 不出現在截圖／錄影)':'Screen capture (widget hidden from recordings)',
  '相容模式 (較耗資源，會出現在截圖)':'Compatibility (widget visible in recordings)',
  '毛玻璃是把視窗底下的桌面擷取下來再模糊畫上去的。擷取模式為了讀得夠快，會把 widget 從畫面擷取中排除，代價是截圖和錄影裡看不到它；相容模式不排除，但改用比較慢的方式取得桌布。':'Glass blurs a capture of the desktop behind the window. Screen capture excludes the widget for speed, so it will not appear in recordings. Compatibility mode keeps it visible but captures more slowly.',
  '縮放比例':'Scale',
  '桌面 Widget':'Desktop widgets', '+ 新增 Widget':'+ Add widget', '刪除此 Widget':'Delete this widget',
  '新增 Widget 失敗':'Could not add the widget',
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
  '測試中...':'Testing...', '連線成功':'Connection successful',
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
      [/^已超過 (\d+) 個 Widget，每多一個都會多用一份記憶體 \(約 60 MB\)。$/, m => `More than ${m[1]} widgets: each extra one uses about 60 MB more memory.`],
      [/^(\d+) 個開著$/, m => `${m[1]} on`],
      [/^(\d+) 個未鎖上$/, m => `${m[1]} unlocked`],
      [/^(\d+) 個開啟$/, m => `${m[1]} open`],
      [/^(\d+) 個播放中$/, m => `${m[1]} playing`],
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
