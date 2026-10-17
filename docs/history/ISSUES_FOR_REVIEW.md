> 历史材料：描述旧版本。当前行为以根目录 README、CHANGELOG、DEPLOY 为准。

# fish-heart-hit — 部署实测问题报告

> 作者：部署方（AI）｜v3 部分：2026-10-12｜xianyu 皮肤部分：2026-10-13
> 对象：`web/pixel.html` v3 突刺特效 + `xianyu`（咸鱼突刺）图片皮肤
> 环境：Windows 10 19045｜Chrome 155（真实渲染引擎）｜OBS 32.2.2｜服务 `heartrate_live.py` @ 8080
> 本文件是**问题清单**，不是修复方案。所有坐标/像素/尺寸结论都来自实测或代码定位，不是推测。
>
> **第 9 章是新增的 `xianyu` 图片皮肤审查结果**；第 1~8 章是上一轮 v3 特效的问题（仍然成立）。

---

## 0. 部署与验证的事实基线

| 项 | 状态 |
|---|---|
| v3 已部署到 `web/pixel.html`（24200 B） | ✅ 服务 `http://127.0.0.1:8080/` 正在返回它 |
| v3 相对发布版只改了 `web/pixel.html`（+23/−4） | ✅ 其余 18 个文件逐字节相同（SHA256 比对） |
| `<script>` 语法（`node --check`） | ✅ 通过 |
| v3 的初始化顺序修复（几何量先算） | ✅ 已确认（`pixel.html:571-577` 在效果块 `:582` 之前） |
| OBS 场景集合 `fish-heart-hit`（520×170 浏览器源） | ✅ 已配好，日志确认 CEF 127 + 源已加载 |
| 浏览器内 burst 状态实测 | ✅ 在真实引擎里抓到 `burst` 达到 0.95 |
| **OBS 预览画面** | ❌ **未确认**。OBS 预览是 GPU 渲染，`PrintWindow` 抓到的是全黑，属抓图限制，不能据此判断画面 |

**已在真实浏览器里抓到的 burst 帧**（视口 504×173，与 OBS 的 520×170 同量级）见 `_preview/v2-calm-vs-burst.png`（上=平静 060bpm，下=burst 125bpm）。
说明：那张是 v2 帧，v3 的水花/残影几何与之基本一致（仅残影条更宽），因此可用于判断"特效与环境的关系"。

---

## 1. 严重：文档给的测试地址是 404

`heartrate_live.py:549-550` 只注册了两个页面路由：

```python
app.router.add_get("/", index)       # → web/pixel.html
app.router.add_get("/plain", plain)
```

**没有 `/pixel.html` 路由**。而交接说明里给的测试地址是：

```
http://127.0.0.1:8080/pixel.html?demo=1&skin=fish      ← 404
```

正确地址（已实测 200）：

```
http://127.0.0.1:8080/?demo=1&skin=fish&burstRise=1
```

`burstRise` 确实在 `TUNABLE` 里，这个调试参数本身有效（`pixel.html` TUNABLE 数组）。

**建议**：要么改文档，要么给服务端加一条 `/pixel.html` 的别名路由。

---

## 2. 严重：`dash` 包络用反了 —— 爆发最强时鱼不动

`pixel.html:379`（`drawFish` 内）：

```js
const dash = burst > 0.05 ? (Math.sin((1 - burst) * Math.PI) * 3.0) : 0;
```

`sin((1−burst)·π)` 的行为：

| burst | 1−burst | sin | dash |
|---|---|---|---|
| 0.05 | 0.95 | 0.156 | 0.47 |
| **0.5** | **0.5** | **1.000** | **3.00 ← 峰值** |
| 0.95 | 0.05 | 0.156 | 0.47 |
| 1.00 | 0.00 | 0.000 | **0.00 ← 爆发满值，位移归零** |

因为 burst 是**脉冲**（`updateAlgo` 里 `burst = max(0, burst − dt*1.1)`，约 0.9 秒从 1 衰减到 0），
实际观感是：**鱼先冲出去，再自己退回来**，而且"最激烈的那一刻"位移是 0。

**建议**：改成 `Math.sin(burst * Math.PI)`，或直接用 `burst` 本身当包络（单调递增）。

---

## 3. 严重：水花被心率线淹没（**不是 z-order 问题**）

`pixel.html:590-593`：

```js
const sx = fishX + fishW + i * 5 * SCALE;
const sy = centerY + (i % 2 ? -1 : 1) * (6 + i) * SCALE;
```

以 520×170 计：`centerY = 85`，水花 y 落在 **76 ~ 95**，x 落在 **104 ~ 129**。

而 `drawTrace(history.samples, centerY, H * 0.44)` 画的心率线**正好贯穿这一带**（幅度受数据调制，实测锯齿波峰可铺满约 70~100）。
所以水花是**画在红色锯齿上**。

**关键**：把水花改到 `drawTrace()` **之前**画也解决不了——它会被整条红线盖住。
必须**换位置**。实测画布里的空白带是：

- 上方：`y ≈ 30 ~ 60`
- 下方：`y ≈ 100 ~ 165`

另外水花 x 起点 `fishX + fishW = 104`，与鱼的令旗/矛头（实测最高到 x≈107）重叠。

---

## 4. 严重：残影只有约 4×5 像素露在画布内（结构性约束）

`pixel.html:586`：

```js
px(fishX - i * 6 * SCALE, fishY + unitFish * 4, fishW * 0.25, unitFish, '#ff3b30');
```

520×170、SCALE=1 下：`pad = 8`、`fishX = pad + round(4*SCALE) = 12`、`unitFish = 5`、`fishW = 90`。

| i | x | 结果 |
|---|---|---|
| 1 | 6 | 与鱼尾重叠（鱼后画，盖住大部分） |
| 2 | 0 | 仅在画布最左边缘 |
| 3 | −6 | **完全在画布外** |

实测"可见面积"约 **7×5 像素**。

**这是布局层面的约束，不是参数问题**：`fishX = 12`，鱼左侧总共只有 12px 边距，做不出任何有长度的拖尾。
三条残影的间距（6px）和宽度（`fishW*0.25 = 22.5px`）都远大于可用边距，所以三条基本叠在一起、且大部分在画布外。

**可选方向**（择一，都需要改布局而不是改特效数值）：

1. 加宽 OBS 浏览器源（520 → 640+），给鱼左侧让出空间；
2. 重排垂直布局：鱼偏上、数字偏下，把中间带留给特效；
3. 放弃"向左拖尾"，把残影改成**鱼身后方的竖直速度线**（画在鱼身上方或下方）。

---

## 5. 中等：两个作用域各有一个 `dash`，且重复调用了同一函数

- `pixel.html:379`（`drawFish` 内）：`const dash = burst > 0.05 ? (Math.sin((1 - burst) * Math.PI) * 3.0) : 0;`
- `pixel.html:583`（`frame` 内）：`const dash = Math.sin((1 - a.burst) * Math.PI);`

两者合法（块级作用域），但：

- 只有第一个乘了 `3.0`；第二个算出来**没被使用**（死变量）；
- 同名不同义，下一轮改动极易改错其中一个。

**建议**：统一成一个来源（例如 `frame` 算好传给 `drawCharacter` 的 opts 里，像现在的 `burst` 一样）。

---

## 6. 轻微：页面 `<title>` 已改，顶部注释仍是旧描述

- `<title>` 已改为 `fish-heart-hit`（部署方改的）
- `pixel.html:14` 注释仍是「咸鱼突刺 · 心率（极简透明版）」，v3 只在末尾加了半句「爆发时增加突刺反馈」

既然在做 IP，注释/标题/仓库名应当统一。

---

## 7. 中等：burst 位移与心跳相位不同步

鱼的常规游动是 `thrust = sin(beat·2π)³ · vigor`（**与心跳相位同步**，`pixel.html:377`），
而 burst 位移 `dash` 是**独立包络**（`:379-381`）。

两者相加时方向一致但节奏不同 → 观感是"抖着往前挪"，而不是"一次干净的前刺"。

**建议**：让 dash 乘一个与 `beat` 相关的门控（例如只在心跳相位的前 1/3 发力），使位移与突刺动作同相。

---

## 8. 值得先想清楚的：520×170 里的"中线拥挤"是两版共同的根问题

这是本次部署最值得注意的结构性观察：

- 鱼占 `y = 55 ~ 120`（`unitFish = 5`）
- 数字（`dot = max(3, round(H/16)) = 11`，5 行）占中间带
- 心率线以 `centerY = 85` 为中心、幅度 0.44·H

**三者都压在水平中线上**。结果是：任何画在 y≈75~100 的特效（v2/v3 的水花都在这里）都会被心率线的锯齿吃掉。

这个问题比"粒子数量/颜色"重要得多——**不改布局，特效调多漂亮都看不见**。

三条路线（择一）：

1. **加宽画布**（OBS 源 520 → 640），右侧/左侧都腾出空间；
2. **垂直分层**：鱼偏上（y≈25~90）、数字偏下（y≈100~165）、心率线走最下部；
3. **特效改画到上方空白带**（y≈30~60）。

---

## 9. `xianyu`（咸鱼突刺）图片皮肤审查

**部署事实**：本皮肤已部署并实测运行（服务 `connected=True`，`bpm=83~86`，`skin=xianyu`）。
改动面 = `web/pixel.html` + `web/console.html` + `web/tune.html` + `heartrate_live.py`（新增 `/assets` 路由）+ `web/assets/skins/xianyu/*.png`（5 张）。**BLE / 算法 / 参数系统 / OBS 接口未改动**（逐字节核实）。

**安全审查：通过**（实测，非推断）

| 项 | 结果 |
|---|---|
| `build_app()` 是否因新静态路由抛异常 | ✅ 正常启动 |
| 5 张皮肤图 | ✅ 全部 HTTP 200 / `image/png` |
| 目录列表 `/assets/` | ✅ 403 拒绝 |
| 路径穿越 `/assets/..%2fheartrate_live.py`、`/assets/%2e%2e/heartrate_live.py` | ✅ 404，**无源码泄漏** |
| 原有路由 `/` `/console` `/tune` `/plain` `/params` `/hr` | ✅ 全部还在 |
| 原有 `fish` / `ghost` 皮肤 | ✅ 代码路径未动，不受影响 |

### 9.1 严重：没有关闭图片平滑 → 像素画会被插值糊掉

`web/pixel.html:387`：
```js
ctx.drawImage(img, Math.round(ox), Math.round(oy), Math.round(w), Math.round(h));
```
Canvas 2D 的 `imageSmoothingEnabled` **默认 `true`**。而资源是 **381×253 的高清图**（`idle.png`），显示目标只有 **100×65**（缩放比 0.24）。双线性缩小会把大块像素的边缘糊成渐变，破坏像素风，与程序化绘制的 `fish`/`ghost` 观感割裂。

**建议**：绘制前 `ctx.imageSmoothingEnabled = false;`（绘完恢复），或把资源预缩到目标尺寸的整数倍。

### 9.2 严重：4 张状态图宽高比不一致，切换时横向拉伸

| 文件 | 尺寸 | 宽高比 |
|---|---|---|
| `idle.png` | 381×253 | 1.51 |
| `alert.png` | 389×245 | 1.59 |
| `attack.png` | 555×240 | **2.31** |
| `burst.png` | 371×263 | **1.41** |

代码把 4 张图**统一画进 `SKIN_DEFS.xianyu = {w:20, h:13}`** 对应的框（520×170 下为 100×65，比例 1.54）。于是 `attack` 会被**压扁约 33%**、`burst` 被**拉宽约 8%**，状态切换时角色形状明显跳变。

**建议**：所有帧统一画布尺寸与角色锚点（例如对齐"脚底中心"），否则动画会抖。

### 9.3 中等：`burst` 帧几乎看不到

`web/pixel.html:382` 帧选择用 **`burst > 0.55`**：
```js
if (burst > 0.55) frame = 'burst';
```
但 `burst` 的衰减是 `burst -= dt * 1.1`（见 `updateAlgo`），从 1.0 掉到 0.55 只有约 **0.41 秒**。`burst.png` 的实际可见时间不到半秒。

**建议**：阈值降到 0.2~0.3（**注意：不要为了这个改动 `updateAlgo` 的算法参数**，那只影响视觉的帧选择）。

### 9.4 中等：帧选择混用了两个不同的"状态源"

`web/pixel.html:380-384`：
```js
if (burst > 0.55) frame = 'burst';
else if (burst > 0.08 || zone === 'danger') frame = 'attack';
else if (zone === 'warn' || flush > 0.55) frame = 'alert';
```
`zone` 来自**服务端阈值**（`warn=120` / `danger=150`），而 `flush` / `burst` 来自**前端算法**。两者不同步：实测 `bpm=83` 时 `zone='rest'`，但 `flush` 可以已经很高。会出现"动作与配色不一致"。

**建议**：统一用前端的 `flush` / `burst` 驱动帧选择。

### 9.5 中等：切换皮肤瞬间可能闪回程序化的旧鱼

`web/pixel.html:386`：
```js
if (!img || !img.complete || !img.naturalWidth) return drawFish(ox, oy, unit, opts);
```
图片是**异步加载**的。若图未就绪就切到 `xianyu`，会先画程序化旧鱼、图加载完再跳成图片 —— 一次可见突变。（单帧 76~108KB，首次加载需要时间。）

**建议**：等 4 张图 `onload` 后再允许切换到该皮肤，或加一个"加载中"占位而不是回退到另一种画风。

### 9.6 中等：资源分辨率与目标尺寸严重不匹配

目标显示区 **100×65**，资源却是 371~555 px 宽；5 张图共 **854 KB**（状态帧 76~108KB，`preview.png` 490KB）。
localhost/OBS 场景下无碍，但放到公网服务（README 描述的场景）就是明显浪费。

**建议**：按目标尺寸 2 倍导出（约 200×130），单帧可降到 5~10KB。

### 9.7 轻：`SKIN_DEFS.xianyu.w = 20` 与真实图片比例不符

`frame()` 用 `skin.w` 计算 `fishW`，用于数字位置（`tx`）与 burst 残影宽度（`fishW * 0.25`）。`20` 格 = 100px 是估值，与图片真实比例（1.41~2.31）都对不上。

### 9.8 轻：命名冲突 —— "咸鱼突刺"既是项目名又是皮肤名

`web/console.html:124` 与 `web/tune.html:85`：
```html
<option value="xianyu">咸鱼突刺</option>
```
而"咸鱼突刺"是**整个项目的中文名**（README 标题、`.bat` 窗口标题）。下拉里"咸鱼 / 幽灵 / 咸鱼突刺"三个选项难以区分第一和第三个。

**建议**：给新皮肤一个能区分的名字（如"咸鱼·突刺版"或直接用 `Xianyu`）。

### 9.9 轻：`preview.png` 490KB，且控制台每次切皮肤都重新下载

`web/console.html:340`：`prev.src = '/?bg=1&skin=' + v + '&_=' + Date.now();`
不影响直播画面（那只用 4 张状态图，不含 preview），但控制台每切一次皮肤就重下 490KB。

### 9.10 轻（运维陷阱）：`add_static` 要求目录必须存在，否则服务起不来

`heartrate_live.py:554`：
```python
app.router.add_static('/assets', HERE / 'web' / 'assets')
```
aiohttp 的 `add_static` 会在 `build_app()` 阶段检查目标目录，**目录不存在就直接抛异常**——表现是"服务完全起不来"，而不是"图片 404"。
本次因为资源随包一起部署所以没事，但**以后单独删除/移动资源目录会导致整个服务启动失败**。

**建议**：加守卫
```python
assets = HERE / 'web' / 'assets'
if assets.is_dir():
    app.router.add_static('/assets', assets)
else:
    log.warning("assets 目录不存在，图片皮肤将不可用：%s", assets)
```

---

## 附：本次实测用到的可复现手段

（都在 `_debug/`，供复现，不属于交付代码）

| 脚本 | 作用 |
|---|---|
| `_mock_hr_server.py` | 假心率服务：喂"平静 62 → 冲高 125"的周期性数据，让 burst 必然触发 |
| `_cdp_shot2.py` / `_cdp_shot3.py` | 连 Chrome DevTools Protocol，轮询 `burst` 值并在峰值截图 |
| `_cdp_ab_effects.py` | 同一会话抓"平静帧"和"burst 帧"，做像素差分统计 |
| `_cdp_probe.py` | 实测页面内部 `window.innerWidth/Height`、`unitFish`（**这一步很关键**：视口不对时 `unitFish` 会从 5 掉到 2，观感完全不同） |
| `_setup_obs.py` | 建 OBS 场景集合 `fish-heart-hit`（520×170 浏览器源） |
| `_test_assets_route.py` | `/assets` 路由的启动安全 + 路径穿越测试（用 aiohttp 异步客户端；**用同步客户端请求自己起的 asyncio 服务会全部超时**，已踩过） |

**踩过的坑（供后来者）**：

1. **改 OBS 配置必须在 OBS 退出后进行**。运行中的 OBS 退出时会用内存里的值覆盖 `user.ini`（实测把 `SceneCollection` 改回了旧值）。
2. **页面尺寸决定观感**：`unitFish = max(2, round(H * 0.030))`。H=74 → unitFish=2（鱼缩到最小）；H=170 → unitFish=5。任何"效果验收"都必须在 520×170 下做。
3. Chrome 无头模式默认视口是 **504×74**，`--window-size` 不生效、`Emulation.setDeviceMetricsOverride` 也无效；要真实视口需用可见窗口并补偿窗口 chrome 高度（约 95px），或强制 `--force-device-scale-factor=1`（本机桌面 125% 缩放）。
