# 低饱和像素总控：交付与验证

## 已实现

- 灰绿底、纸色面板、旧铜细节、宋体标题；像素菜单图标与按下反馈。
- 预览与调节分栏；更多工具加宽；窄屏自动纵向排列。
- 皮肤识别图、心率线布局示意、宽窄预设选中态；精简重复说明。
- 历史、高级参数、行为验收工具统一灰绿配色；增加验收页viewport。
- 不改心率算法、8张原始PNG、叠层绘制与一键VBS；保留用户150%宽度、135%角色大小、381×95悬浮窗。

## 本轮实际运行

- 29项后端单元测试通过。
- 12组原有可见Chrome回归通过，含保存同步、两种布局、8种姿态、桌面预览。
- 12组真实Chrome按钮操作通过，含遮挡检查、断线恢复、失败重试、会话重启；复制与校准采用替身。
- 4组视觉专项通过：380/390/768/1024/1440窗口、三个入口、工具主题、对比度、键盘焦点、减少动画及无外部资源。
- 正文对比度8.93:1，顶栏结束按钮6.09:1；无未捕获页面错误。
- 人工查看了桌面总控、模拟、工具和窄屏实际浏览器截图，修正结束按钮对比度。截图均为独立18766合成数据。
- 冻结算法、原图、7份GBK BAT、UTF16 VBS、依赖和双script启动行检查通过。

## 安装

已安装到`G:\downloads\heart-rate`并正常重启，通过原`一键开播（总控+悬浮窗）.vbs`启动。
完整备份：`G:\downloads\heart-rate-backups\before-classical-design-20261016-222350`。
42个个人配置与历史文件在停止后校验哈希一致。未向现用服务写测试参数。
安装后只读HTTP核验7份前端资源与交付完全一致；受管悬浮窗已启动；核验时手表已连接。进程核验服务、受管悬浮窗各一个。
现有总控页需首次按F5载入新前端。本轮未自动操作现用窗口，未进行OBS实际录制验收；108组鱼图像素对照为上一轮历史证据，本次未重跑。

## 证据

[桌面](evidence/design/design-live.png) / [试效果](evidence/design/design-demo.png) / [工具](evidence/design/design-tools.png) / [窄屏](evidence/design/design-mobile.png)

[视觉专项](evidence/design/design-results.json)、[按钮检查](evidence/design/control-actions-results.json)、[后端](evidence/design/unittest.txt)、[安装](evidence/design/install.json)、[现用HTTP](evidence/design/installed-http.json)。
