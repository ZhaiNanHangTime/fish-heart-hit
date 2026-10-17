> 历史材料：描述旧版本。当前行为以根目录 README、CHANGELOG、DEPLOY 为准。

# 咸鱼突刺 · 红温/心跳补丁

本补丁以 `fish-heart-hit-xianyu-sway-fix-20261013` 为基线。没有改 BLE、P90、burst 触发算法、旧鱼或幽灵绘制函数、OBS 页面布局、原有图片。

## 安装覆盖版（推荐已部署用户）

1. 先备份项目目录下的 `heartrate_live.py` 和 `web/pixel.html`。
2. 将补丁 ZIP 内的 `heartrate_live.py` 和 `web/` 文件夹**覆盖到现有项目根目录**（不要把 ZIP 解压成第二层同名目录）。原来 `web/assets/skins/xianyu/*.png` 保留即可。
3. 重启 Python 心率服务以注册 `/effects` 路由，然后刷新 OBS 浏览器源。
4. 打开 `http://127.0.0.1:8080/effects` 体验：心率滑块、平静/紧张场景、模拟升速、手动突刺，及三个效果的开关对比。

## 实际变更

- `web/pixel.html`：只对 `skin=xianyu` 加入红温染色、随每次 BPM 周期上弹后缓落、心跳脉冲红光；增加受 `?demo=1&controlled=1` 限制的预览消息接口。
- `web/effects.html`：新增实时验证网页，采用 iframe 渲染真正的 pixel.html，模拟数据不会覆盖实时心率、保存参数或 OBS 皮肤设置。
- `heartrate_live.py`：仅新增静态页面路由 `/effects`。原来的 `/`、`/params`、`/events`、`/assets` 均保持不变。

## 体验要点

- 默认入口 `http://127.0.0.1:8080/` **仍是正式直播叠层**。
- 验证页面 `/effects` 不会修改设备数据/保存配置，只作为本地效果对比工具。
- 新皮肤在冷静期仍是原始贴图；随现有视觉强度 `pSmooth` 增加红温与脉冲。
- 真实心率数字仍根据 BPM 立即显示；只有角色视觉运动和颜色缓动。
- 你可依次点击 `75 → 140`，等约 3 秒让视觉强度跟上；点击「手动触发突刺」观察爆发帧。

## 已执行的验证

- Python `py_compile` 通过；pixel/effects/console/tune 内联 JavaScript 均通过 `node --check`。
- aiohttp 本地 HTTP 返回：`/effects` 200、`/?demo=1&skin=xianyu` 200、原有 sprite PNG 200。
- 在 Chromium 离线 `srcdoc` 浏览器环境里实际操作：75 和 140 BPM、三个效果开关、强制突刺、自动渐进演示通过，未产生 JS 异常。
- 当前执行环境阻止浏览器直接访问本地 HTTP 地址，所以 HTTP 与浏览器交互测试分别完成；没有在用户的 OBS 上进行最终验收。

## 注意

不要把演示 URL (`?demo=1&controlled=1`) 放在 OBS 正式浏览器源里。调试时打开 `/effects` 即可。
