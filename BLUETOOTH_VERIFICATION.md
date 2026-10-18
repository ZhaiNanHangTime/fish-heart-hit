# 蓝牙扫描与可视化连接：本轮验证

## 已实现

总控「连接心率设备」面板，或直接打开 `/devices`：扫描附近广播、停止扫描、选择连接、断开、忘记、成功后记住设备及断线重连。未知服务设备可选中验证；不自动探测连接所有周边设备。同一实例一次接入一台标准BLE心率设备，其他人在自己的电脑使用同一干净完整包。

切换设备重置本次基准和统计，旧CSV保留并另开新会话文件；皮肤、倍率和输出尺寸不变。设备名以纯文本显示；设备列表与地址不进入公开OBS/SSE。

## 实际运行的检查

- 46项后端测试通过，其中17项为扫描、选择、切换、GATT通知、失败、持久化与鉴权测试。蓝牙单元测试使用替身。
- 12组原有可见Chrome回归、12组实际按钮回归通过。
- 8组可见Chrome蓝牙流程通过，含未声明服务但支持通知的设备、不支持设备、停止、断开/忘记、换源、错误重试、不可信设备名和390px界面；测试使用合成扫描器与GATT客户端。
- 亲自查看了实际浏览器截图，修复扫描按钮禁用状态被通用渲染覆盖的问题。
- 原始像素页、原生HUD、心率/基准算法、共享比例和素材渲染均逐字节保持，BAT为GBK/936/CRLF，VBS为UTF16，无新增运行依赖。
- 使用现用Windows蓝牙适配器完成真实扫描，发现12条广播；未连接任何其他人的设备。当前所选设备在扫描中没有出现，未取得新的真实心率；更新前服务日志也已连续报告设备不在广播。因此真实新设备的端到端接入尚未核验，不能把替身测试当作真机接入成功。

## 安装与保留

已更新 `G:\downloads\heart-rate`，原一键VBS可用，受管悬浮窗已启动。
完整备份 `G:\downloads\heart-rate-backups\before-bluetooth-chooser-20261017-231442`；正常停止后校验43个个人配置/历史文件哈希一致再更新。`devices.json`在成功连接后会写入新增选择信息，属于本地设备记忆；不会加入分享包。
用户150%鱼图宽度、135%角色大小及381×95悬浮窗保留。现用页面首次F5载入新面板。

## 证据与复现

[后端](evidence/bluetooth/unittest.txt)、[原浏览器](evidence/bluetooth/browser-results.json)、[原按钮](evidence/bluetooth/control-actions-results.json)、[蓝牙UI](evidence/bluetooth/bluetooth-browser.json)、[真机扫描与限制](evidence/bluetooth/live-bluetooth.json)、[安装](evidence/bluetooth/install.json)。

[桌面截图](evidence/bluetooth/bluetooth-panel.png)、[窄屏截图](evidence/bluetooth/bluetooth-mobile.png)均为合成数据，其中故意包含设备名HTML字符串以验证按文本显示，不代表真实设备。
复现命令见 `tests/README.md`。本轮未重跑108组鱼图对照，保留此前证据。
