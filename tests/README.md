# 可复现检查

在项目根目录执行。所有数据为合成数据，不会寻找手环或读取私人CSV。

## 后端/基准

```powershell
python -m unittest discover -s tests -v
```

依赖与服务相同。检查API、参数广播、错误参数、校准/重置、离线门槛、基准纠偏、回放参数隔离和素材路由。

## 原生Tk绘制

```powershell
python tests/check_desktop.py
```

需要有可用Tcl/Tk的桌面Python，检查窗口在创建后隐藏，使用合成快照，临时替换位置恢复，不写hud.json。覆盖2/3/4/5倍率、三皮肤、八张图、0.7/1/1.3大小、幽灵原点量化与原半像素区间。

## 可见Chrome浏览器

可选开发工具为 Node + Playwright 与已安装Chrome；它们不属于运行时依赖。`browser_check.cjs` 使用 `require('playwright')`，请在自己的开发环境提供该模块或通过NODE_PATH指定现有模块目录。

终端一：

```powershell
python tests/synthetic_server.py
```

终端二：

```powershell
node tests/browser_check.cjs
```

fixture只监听127.0.0.1:18766；其控制入口 `/__test` 仅存在于此测试脚本，正式服务没有此路由。参数写入系统临时目录，退出时清理，不读取项目params.json。运行时保持浏览器可见，验证脚本会断言visibilityState为visible；自动截图保存到 `test-evidence/`，可用 `EVIDENCE_DIR` 改位置。完成后关闭终端一的fixture。

这些检查不能代替真实设备连接、原始CSV回放频率评估或OBS录制验收。原生绘制检查也不等于人工目视检查透明桌面合成。

## 原生子进程生命周期

`python tests/check_native_lifecycle.py` 会在系统临时副本真正启动Tk悬浮窗，检查重复打开复用PID、隐藏时保存位置、总控退出关闭子进程。不修改安装目录的私人文件。

## 原生尺寸交互

`python tests/check_hud_resize.py` 启动隔离的HTTP/SSE服务和真实Tk窗口，用鼠标事件检查拖角即时反馈、松手保存211×119等奇数尺寸、远程同步、失败显示/重试、角点光标、滚轮缩放、双击预设、尺寸边界和同一窗口。所有配置写入系统临时目录，不读取设备或真实CSV；需要可用的Windows桌面Tcl/Tk。

新增覆盖：50%–400%角色、HUD1920×1080上限、原生共享皮肤/倍率面板、第二SSE输出、远程更新和保存失败重试；浏览器400%实际几何与OBS同步。所有数据隔离。

最新对照：先启动synthetic_server.py；运行check_visual_parity.py输出真实Tk图像RGBA哈希，再用可见Chrome运行check_visual_parity.cjs，逐项比对布局和Canvas鱼图RGBA。两端都关闭暖色及心跳，固定帧，隔离个人数据。新版应用按钮提交完整当前草稿，不再只提交尺寸。

素材宽度对照扩为108组，含75%/100%/125%；验证只改横向、预览隔离、应用保存、OBS同步及恢复原始比例。

前端自查：synthetic_server.py启动后执行check_control_actions.cjs，覆盖实际点击、遮挡、重连/新会话、非JSON失败等；复制/校准使用替身，避免系统剪贴板或基准变动。
