# Birdfy / Netvue app — hidden developer menu (translated)

A map of the official Birdfy Android app's (`com.birdfy.smarthome`) hidden
**开发调试设置 = "Developer Debug Settings"** menu, with English translations,
built from navigating it live. Chinese label → English (notes).

## How to open it

Normally this menu is gated behind an **undocumented unlock gesture** (compiled
into the app; not publicly known). **You don't need it.** The app registers a
`birdfy://` deep-link scheme, marked `BROWSABLE` in its `AndroidManifest`, and the
dev menu is reachable by firing a `birdfy://developer_debug` intent — which skips
the gesture entirely.

**Prerequisites**
- Official Birdfy app (`com.birdfy.smarthome`) installed and signed in.
- Verified on Android app **v1.24.2**. Route names may differ on other versions.

**Always force-stop the app first.** If Birdfy is already running, the deep link
just brings the current screen forward without routing to the menu.

### Method A — phone only, no computer
1. Force-stop Birdfy: Android **Settings → Apps → Birdfy → Force stop**.
2. Open a `birdfy://developer_debug` link — any of these fire the intent because
   the scheme is `BROWSABLE`:
   - paste it into a notes/messaging app and tap it;
   - make a **QR code** of `birdfy://developer_debug` and scan it;
   - save a file `open.html` containing
     `<a href="birdfy://developer_debug">open dev menu</a>` and tap the link in a browser.
3. The **开发调试设置 (Developer Debug Settings)** menu opens.

### Method B — with adb (what we used)
```sh
adb shell am force-stop com.birdfy.smarthome
adb shell am start -a android.intent.action.VIEW -d "birdfy://developer_debug"
```

### Directly-linkable pages (standalone links)
Only `/developer_debug/*` routes open directly — handy as their own QR/links:
- `birdfy://developer_debug` — the whole menu
- `birdfy://developer_debug/domain_settings` — Domain Settings
- `birdfy://developer_debug/domain_diagnostics` — Domain Diagnostics (dumps live domain JSON)

### Caveats
- Leaf pages under `/debug/...` (e.g. **Photo Recognition Debug**) are **not**
  directly linkable — such a link falls back to Domain Settings. Reach them by
  opening `birdfy://developer_debug` and scrolling to the section
  (e.g. 拍鸟识别 → 接口调试).
- `退出页面` at the bottom = **Exit page**.
- Toggling items changes the live app — note what you flip so you can flip it back.

---

## Root menu — 开发调试设置 (Developer Debug Settings)

Top of page:
- **udid** — the app's device UID (e.g. `android-bf02344f-8db8-4768-…`), with a copy button.

**日志 = Logs**
- 上传日志 — **Upload logs** (sends logs to their server)
- 分享日志 — **Share logs** (Android share sheet; log file likely contains auth headers)

Collapsible category sections (each expands):

| Chinese | English | Notes |
|---|---|---|
| 域名 | **Domain** | Opens the Domain Settings / Diagnostics (see below). The wifi-ish icon. |
| 推送/消息盒子 | **Push / Message Box** | notification + inbox debug (expanded below) |
| Joy V2 / LiveKit | *(as-is)* | live-stream/chat stack (LiveKit) |
| 设备连接和客户端解码测试 | **Device connection & client-decode test** | video connection/decoder testing |
| 弹窗 | **Popups / Dialogs** | dialog gallery |
| 控件 | **Widgets** | UI widget gallery |
| 列表广告 | **List ads** | in-list advertising |
| 添加流程 | **Add-device flow** | device onboarding/pairing screens |
| 远程配置 | **Remote config** | remote-config overrides |
| 直播 | **Live streaming** | live view debug |
| RTMP | *(as-is)* | RTMP push ("go live") settings |
| 设备列表 | **Device list** | |
| 设备设置 | **Device settings** | |
| 社区 | **Community** | |
| birdData | *(as-is)* | bird database |
| In App Purchase 应用内购 | **In-App Purchase** | (StoreKit, PlayBilling…) |
| 事件列表 MOMENTS | **Event list / Moments** | expanded below |
| 拍鸟识别 | **Photo Bird Recognition** | the species-ID tools (expanded below) |
| 音视频工具 | **Audio/Video tools** | |
| Baby | *(as-is)* | "baby" camera mode |
| 客服测试 | **Customer-service test** | support chat |
| RecapLink | *(as-is)* | |
| Story | *(as-is)* | "stories" feature |
| 收藏 | **Favorites / Collection** | |
| 蓝牙 | **Bluetooth** | BLE debug |
| 用户评分 | **User rating** | app-rating prompt |
| Ume | *(as-is)* | |
| Firebase | *(as-is)* | |
| 域名设置/异常 | **Domain settings / Exceptions** | |
| 其它 | **Other** | catch-all (expanded below) |

Bottom actions:
- 清除 shared preferences — **Clear shared preferences**
- 清图片缓存 — **Clear image cache**
- 退出页面 — **Exit page**

---

## 推送/消息盒子 = Push / Message Box
- 推送提示音调试 — **Push tone/sound debug**
- 推送测试 — **Push test**
- 消息盒子调试 — **Message-box (inbox) debug**
- 消息盒子 Dummy UI — **Message-box Dummy UI**
- 消息盒子 — **Message box (inbox)**

## 事件列表 MOMENTS = Event list / Moments
- 模拟首页推送打开详情页 — **Simulate a home-screen push opening the event detail page** (has an event-id value)
- 显示调试信息 — **Show debug info** *(toggle; overlays raw event/AI data on moments)*
- 开启 TV Cast 按钮 — **Enable TV Cast button** *(toggle)*
- Moment Search 多设备信息 — **Moment Search multi-device info** *(toggle)*
- 强制显示球机视频 — **Force-show PTZ/dome-camera video** *(toggle)*
- 高帧率-SlowMotion — **High frame-rate / SlowMotion** *(toggle)*
- 手动 AI 识别 Mock — **Manual AI-recognition Mock**

## 拍鸟识别 = Photo Bird Recognition
- 接口调试 — **API Debug** → opens the "Photo Recognition Debug" page (see below)
- 拍照页 — **Capture / take-photo page**
- 裁剪图片页 — **Crop-image page**
- 识别结果页 – 成功 — **Result page – Success**
- 识别结果页 – 识别中 — **Result page – In progress**
- 识别结果页 – 无结果 — **Result page – No result**
- 识别结果页 – 达到限额 — **Result page – Limit reached**
- 选择鸟种页 — **Select bird-species page**
- 识别历史页 — **Recognition history page**
- 识别历史页 – Mock — **Recognition history – Mock**

## 其它 = Other
- UI 测试 — **UI test**
- 各种提示选项 — **Various prompt / toast options**
- Alexa OAuth 页面 UI — **Alexa OAuth page UI**
- Alexa 测试链接 — **Alexa test link** *(toggle)*
- 启用 TikTok 分享入口 — **Enable TikTok share entry** *(toggle)*
- 会员制调试 — **Membership debug** (see below)
- loading — *(a loading-screen test)*
- 反转超大图片调试显示 — **Invert oversized-image debug display** *(toggle; was ON)*
- 强制使用新设备睡眠模式页面 — **Force new-device sleep-mode page** *(toggle)*

## 会员制调试 = Membership Debug
*(relevant to the paid "unlimited ID" subscription)*
- **dynamic_settings override**
  - 启用会员入口 — **Enable membership entry** *(toggle)*
  - 刷新 dynamic_settings — **Refresh dynamic_settings**
  - oauth test — *(OAuth test)*
- **激活码兑换 = Activation-code redemption**
  - 引导页 — **Intro/guide page**
  - 兑换页 — **Redeem page**
- **会员状态 override = Membership-status override**
  - 跟随真实订阅状态 — **Follow real subscription status** *(current: 当前 = "Current")*
  - 覆盖为未知状态 — **Override to Unknown**
  - 覆盖为 Basic — **Override to Basic**
  - 覆盖为 Plus — **Override to Plus**
  - 覆盖为 Pro — **Override to Pro**

---

## Domain pages (under 域名 / 域名设置)

### 域名设置 = Domain Settings
- **域名切换 = Domain Switching**
  - 启用备用域名 Fallback — **Enable fallback domain**
  - Central API TEST / 测试环境 — **Central API TEST / test environment**
  - Central API 切回旧 Endpoint — **Central API — revert to old endpoint**
- **诊断 = Diagnostics**
  - 域名诊断 — **Domain diagnostics** →

### 域名诊断 = Domain Diagnostics (dumps live JSON)
- `remoteUrl: https://resource.netvue.com/app/res/birdfy/domains.json`
- strategy: `activeProfile=primary, switchMode=autoOnFailure, failureThreshold=5, coolDownSeconds=300`
- services (each `{primary, fallbacks[], legacyInputs[]}`): `localWeb, api2, localApi2, centralWeb, capi2, capi3, centralApi` — all on `*.nvts.co`
- rules: `defaultHostSuffix=nvts.co, hardcodedFallbackSuffix=netvue.co, allowAutoSwitch=true, resourceHostBypass=true`

---

## Photo Recognition Debug (接口调试 under 拍鸟识别)
English-labeled page. Lets you run the species-ID API directly:
- **Create recognition** — Select one image, Capture time (ms), Location label, Longitude/Latitude, Select date and location, **Create**
- **Task status** — Task IDs (comma-separated), **Query tasks**, **Load fake task ID**
- **Subject operations** — Task ID, File key, Subject ID, Species ID, Box x/y/width/height, **Retry subject**, **Update species**
- **History** — Task IDs to delete, **Refresh history**, **Load more**, **Delete**
- **Species cache** — **Load cache**, **Clear cache**
- **State** — Active tasks / Task results / History counts
- **Response / error** — raw JSON dump of the last API call (how we captured the contract)

---

*Note:* toggling items here changes the live app's behavior. The only ones left
on during investigation were `显示调试信息` (Show debug info) under Moments and
`反转超大图片调试显示` (invert oversized-image display) under Other — both harmless
and reversible in the same menu.
