## Velopack 安装与自动更新

- `desktop_entry.py` 接入 Velopack，备份资料与程序后应用更新。
- `desktop_migration.py` 导入旧资料，保留原 VBS 备份并将入口指向新安装。
- `hr_paths.py`、`app_launcher.py`、`heartrate_live.py`、`heartrate_hud.py` 和 `hr_runtime.py` 支持安装版独立数据目录和 EXE 子进程。
- `build_desktop.py`、`requirements-build.txt` 和 `RELEASE_VERSION` 支持生成 Windows 安装包及 Velopack 更新资产。

# 本轮改动文件

基线：GitHub 6e465a0。修复曲线描边、尖角和亮点超出画布的问题。

## 修改

- `CHANGED_FILES.md`
- `CHANGELOG.md`
- `MANIFEST.sha256`
- `README.md`
- `heartrate_hud.py`
- `hr_visual.py`
- `tests/check_trace.cjs`
- `tests/check_trace_native.py`
- `tests/test_trace.py`
- `web/pixel.html`

## 新增

- `TRACE_EDGE_FIX.md`
- `evidence/trace-edge/browser-trace.json`
- `evidence/trace-edge/native-trace.txt`
- `evidence/trace-edge/unit-tests.txt`

原有游戏记录、曲线时间范围、心率/突刺算法与素材保持。
