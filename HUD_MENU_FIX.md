# 悬浮窗右键隐藏

在桌面鱼图上右键，菜单第一项为「隐藏桌面悬浮窗（直播继续）」。此操作保存位置并关闭桌面窗口；后台心率服务和OBS来源保持运行。
恢复：打开总控，点「显示悬浮窗」；也可再次双击原「一键开播（总控+悬浮窗）.vbs」。右键菜单第二行也提供恢复指引。

## 本轮验证

- 隔离真实Tk菜单，调用第一项的真实命令回调，确认关闭HUD、保存位置并关闭本地订阅，无Tk回调异常。
- 真实受管Tk进程验证：重复显示复用PID，隐藏保存位置，重新显示成功，结束时只关闭所属窗口。
- 原生六个冻结方法（含心率算法与幽灵取整）AST相同，网页叠层逐字节相同。
- 安装时仅更新一个产品文件；心率后台会话标识保持、未重启后台，OBS来源HTTP仍为200，外观参数哈希保持。
- 本轮未重新运行蓝牙/浏览器测试或进行实际OBS录制；此前证据保留。

## 安装

已更新现用 `G:\downloads\heart-rate`；只重开了桌面悬浮窗，原可见状态已恢复。
完整备份 `G:\downloads\heart-rate-backups\before-hud-menu-20261018-150826`。历史CSV随原心率服务继续正常写入，未清理个人文件。

## 改动文件

- `heartrate_hud.py`：明确右键菜单隐藏选项、恢复指引，安全处理菜单随窗口销毁后的抓取释放。
- `tests/check_hud_menu.py`：隔离真实Tk菜单回调验证。
- `README.md`、`CHANGELOG.md`：操作说明。
- 本说明与 `evidence/hud-menu/`：本轮证据；MANIFEST.sha256、CHANGED_FILES.md重生成。

证据：[菜单](evidence/hud-menu/native-menu.txt)、[受管窗口](evidence/hud-menu/native-lifecycle.txt)、[安装](evidence/hud-menu/install.json)。
