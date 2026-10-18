# 本次蓝牙功能文件清单

相对上一完整包（SHA256 `771b9c0dafb42fcb17b32335b4b6ffaa45fbcbb2aa2300b13484a239e1032e44`）。

## 产品代码

- `heartrate_live.py`：设备管理接口、单一连接入口及CSV会话隔离。
- `hr_devices.py`：扫描、选择、GATT验证、重连、持久记忆。
- `web/console.html`：集成设备面板与顶部入口。
- `web/devices.js`：可视化操作、状态与错误反馈。
- `web/control.css`：设备列表样式与窄屏适配。

## 全部新增/修改（含说明、测试、证据）

- `.gitattributes`
- `BLUETOOTH_GUIDE.md`
- `BLUETOOTH_VERIFICATION.md`
- `CHANGELOG.md`
- `evidence/bluetooth/bluetooth-browser.json`
- `evidence/bluetooth/bluetooth-mobile.png`
- `evidence/bluetooth/bluetooth-panel.png`
- `evidence/bluetooth/browser-results.json`
- `evidence/bluetooth/burst-overlay.png`
- `evidence/bluetooth/console.png`
- `evidence/bluetooth/control-actions-results.json`
- `evidence/bluetooth/control-demo-accessible.png`
- `evidence/bluetooth/control-mobile-tabs.png`
- `evidence/bluetooth/control-tools-accessible.png`
- `evidence/bluetooth/effects-integrated.png`
- `evidence/bluetooth/hud-preview.png`
- `evidence/bluetooth/hud-size-controls.png`
- `evidence/bluetooth/install.json`
- `evidence/bluetooth/installed-http.json`
- `evidence/bluetooth/invariants.json`
- `evidence/bluetooth/large-shared-obs.png`
- `evidence/bluetooth/layout-lower.png`
- `evidence/bluetooth/layout-overlay.png`
- `evidence/bluetooth/live-bluetooth.json`
- `evidence/bluetooth/live-overlay.png`
- `evidence/bluetooth/mobile.png`
- `evidence/bluetooth/state-alert_low.png`
- `evidence/bluetooth/state-alert_mid.png`
- `evidence/bluetooth/state-burst.png`
- `evidence/bluetooth/state-charge.png`
- `evidence/bluetooth/state-high.png`
- `evidence/bluetooth/state-idle.png`
- `evidence/bluetooth/state-recover.png`
- `evidence/bluetooth/state-tense.png`
- `evidence/bluetooth/unittest.txt`
- `evidence/bluetooth/xianyu-total-control.png`
- `heartrate_live.py`
- `hr_devices.py`
- `INSTALL_REPORT.md`
- `README.md`
- `tests/_ble_fakes.py`
- `tests/check_devices.cjs`
- `tests/README.md`
- `tests/synthetic_server.py`
- `tests/test_devices.py`
- `VERIFICATION.md`
- `web/console.html`
- `web/control.css`
- `web/devices.js`

另重生成CHANGED_FILES.md、MANIFEST.sha256；没有删除旧版文档或证据。
