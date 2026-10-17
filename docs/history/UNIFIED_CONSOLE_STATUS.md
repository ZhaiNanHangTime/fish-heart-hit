> 历史材料：描述旧版本。当前行为以根目录 README、CHANGELOG、DEPLOY 为准。

# 给 GPT：统一前端需求 —— 现状核对与合并请求

> 面向：接手修改的 AI（GPT）
> 日期：2026-10-14
> 背景：我提过"四个界面各忙各的"（见 `WEB_CONSOLE_AND_PARAMS.md` 需求 2），现在核对进展

---

## 一、结论先说

**你已经做了这件事，但做在了另一条分支上，而且两条分支互相冲突。**

| 包 | 时间 | 内容 | 我是否部署 |
|---|---|---|---|
| `fish-heart-hit-studio-gradient-*-20261013.zip` | 10-14 20:31 | **统一开播工作台 + `/monitor` + 五档迟滞 + gradient 素材** | ❌ **还没部署**（你当时没告诉我这个包的存在） |
| `fish-heart-hit-xianyu-material-integrated-*-20261014.zip` | 10-14 22:34 | 8 状态素材接入（idle/alert_low/alert_mid/tense/high/charge/burst/recover） | ✅ 已部署 |

**两个包都以 `pixel.html` 为改动对象，但基线不同**：

- `studio-gradient` 的 `pixel.html` = 34,610 B，用 **`gradient/` 子目录的 7 张图**（idle/light/alert/tense/charge/thrust/recover，每张 16~22 KB），带**五档迟滞**
- `material-integrated` 的 `pixel.html` = 33,437 B，用 **`xianyu/` 根目录的 8 张图**（每张 150~176 KB），**无迟滞**

→ **如果直接部署 studio-gradient，会覆盖掉我刚部署的 8 状态素材；反之则丢掉统一工作台。**

---

## 二、studio-gradient 做对了什么（我核对过代码）

### 1) 统一界面（正是我要的）

`web/console.html` 从 15,867 B → **20,098 B**，改成**标签页式开播工作台**：

```
咸鱼突刺 · 开播工作台      选皮肤 → 看效果 → 调尺寸 → 保存 → 添加到 OBS
├─ 开播设置          ① 选角色（红巾咸鱼 / 原版咸鱼 / 幽灵）
│                    ② 调显示大小（OBS 宽 520 高 170，含 520×170 / 640×200 / 420×140 预设）
│                    ③ 调节目效果（红温 / 弹动；注明"红色脉冲光已移除"）
│                    ④ 直播画面即时预览 + 五档手动切换（待机/轻警觉/警戒/紧张/高压）
│                       + ⚡模拟一次突刺 + ▶自动演示心率上升 + 恢复心率自动分档
│                    ⑤ 保存开播设置 / 我现在平静，校准基准 / 复制 OBS 地址
├─ 实时数据与回放     （原 /console 拆出到 /monitor）
├─ 视觉特效实验        （/effects）
├─ 高级参数            （/tune）
└─ 行为验收            （/test）
```

**这解决了"到处找入口"的问题** —— 一个页面五个标签，不用再记四个 URL。

### 2) 五档迟滞（解决了我实测出的"闪图"问题）

```js
const XIANYU_STAGES = ['idle','light','alert','tense','charge'];
// 逐级迟滞约 0.035，避免档位临界处反复换图片
```
⚠️ **这条是最有价值的改动**。我实测过：material 那套 6 档每档只有 3.5~4 bpm 宽，而心率读数天然抖动 ±1~2 bpm，**会在临界处疯狂换图**。studio 版加了迟滞，方向完全正确。

### 3) 素材体积

gradient 素材每张 **16~22 KB**（192×128），而 material 每张 **150~176 KB**（约 380×250）。
叠层显示尺寸才 100×65 左右 → **gradient 规格才是对的**，material 那套浪费了 85% 带宽。

### 4) 服务端新增字段

`DEFAULT_PARAMS` 新增 `fishScale`（角色大小）、`fxWarmth`、`fxKick`，平铺保存到 `/params`。
`heartrate_gui.py` 只改了按钮文案（`控制台` → `开播工作台`），功能未变。

---

## 三、但"各忙各的"这个问题**只解决了一半**

我实测的根因（**仍未修**）：

| 界面 | 取数方式 | 周期 |
|---|---|---|
| 桌面 GUI（tkinter） | 轮询 `/hr` | `after(5000)` = **5 秒** |
| 桌面悬浮窗（tkinter） | 独立线程 `_poll_loop` | **0.5 秒** |
| OBS 叠层（网页） | `EventSource /events` | 实时推送 |
| `/console` 工作台 | 自己的 `fetch('/hr')` | 各自周期 |

**问题**：服务端有 `/events`（SSE）能给"心率快照"，但**没有"配置变更广播"通道**。
所以：
- 在 `/console` 里改了皮肤/参数 → **悬浮窗要等它自己的检测周期才跟上**（实测 2 秒 + 它自己再判一次）
- GUI 控制台 **5 秒才刷新一次** → 最慢的一个
- 桌面悬浮窗还持有一份**本地参数副本**（`load_remote_params`），只在特定条件下重载

→ 表现就是「看起来各忙各的」。

### 建议的最小可行改法（供你判断）

1. **加一个配置版本号**：服务端维护 `params_version`，`/events` 的快照里带上它；
2. **所有前端统一从 `/events` 拿数据**（tkinter 两个界面可以起一个 SSE 或轮询同一接口但把周期降到 1 秒）；
3. **桌面悬浮窗去掉本地参数副本**，皮肤/参数变化一律以服务端为准；
4. **`/console` 保存后主动广播**（`/events` 立刻推一条带新 `params_version` 的快照），让所有前端同一帧内同步。

---

## 四、我需要的：一个合并版

请基于**最新代码**（仓库 https://github.com/ZhaiNanHangTime/fish-heart-hit ，最新提交 `7c0e1be`）产出一个版本，同时包含：

| 要素 | 来源 |
|---|---|
| 统一开播工作台 `/console`（五标签） | studio-gradient |
| `/monitor` 实时数据与回放 | studio-gradient |
| **五档迟滞**分档逻辑 | studio-gradient |
| `fishScale` / `fxWarmth` / `fxKick` 参数 | studio-gradient |
| **8 张详细状态图**（idle/alert_low/alert_mid/tense/high/charge/burst/recover） | material-integrated（我已部署） |
| `/test` 行为验收台 + `?test=1` 通道 | 我加的，**必须保留**（studio 版已保留，请继续保留） |
| `/effects`（已删脉冲光开关） | 两者都有 |

### 请明确回答两个设计选择

1. **档位数量**：material 用 6 档（每档仅 3.5~4 bpm 宽），studio 用 5 档 + 迟滞。
   我倾向：**保 5~6 档 + 强制迟滞**，并且**档位边界用绝对 bpm 差**（如 `${bpm−B}` 的 0/4/8/12/16）而不是归一化强度——这样档宽与 `R−B` 解耦，不会因为满红阈值不同而挤在一起。请判断。
2. **素材规格**：material 那套是 380×250 / 150KB，显示只有 100×65。
   请确认：是保留高清素材（清晰度优先，接受 1.3MB），还是**按 gradient 规格（192×128 / ~20KB）重出一套 8 状态图**（体积降 85%，但细节会少）。

### 不要动

- 心率算法（P90 / Attack-Release / burst 判据 / 满红迟滞）
- `heartrate_hud.py` 的绘制坐标取整与 1px 量化（**那是修闪烁的，见 README 第八节"改悬浮窗绘制前必读"**）
- `/assets` 的 `is_dir()` 守卫
- OBS 现有源的 URL 与尺寸（`http://127.0.0.1:8080/?skin=xianyu`，520×170）

---

## 五、附：我实测过的数据（供你判断档位设计）

真实心率（`logs/` 28 个会话、27586 样本）：**最低 54 / P50 72 / P90 81 / P99 92 / 最高 104**

我的 `R−B` 实测是 **22 bpm**（基线 93 那次是 12.7，因为 P90 在动）。按 `R−B = 22` 换算 material 的 6 档：

```
idle        72.0 ~  76.0 bpm   宽 4.0
alert_low   76.0 ~  79.5 bpm   宽 3.5
alert_mid   79.5 ~  83.4 bpm   宽 4.0
tense       83.4 ~  87.0 bpm   宽 3.5
high        87.0 ~  90.5 bpm   宽 3.5
charge      90.5 ~  94.0 bpm   宽 3.5     ← 档宽全部只有 4 bpm 左右
```

而实测心率相邻样本经常跳 1~3 bpm → 临界处必然反复换图。**迟滞是必需的，不是可选。**
