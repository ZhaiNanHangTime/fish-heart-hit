"""停止心率服务与桌面悬浮窗。

只按命令行精确匹配本项目脚本，不会误杀你其它的 python 进程。
"""
from __future__ import annotations

import subprocess
import sys

PS = (
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" | "
    "Where-Object { $c = $_.CommandLine; "
    "$c -like '*heartrate_live.py*' -or $c -like '*heartrate_hud.py*' } | "
    "ForEach-Object { Write-Host ('  已停止 PID ' + $_.ProcessId + '  ' + $_.Name); "
    "Stop-Process -Id $_.ProcessId -Force }"
)


def main() -> int:
    print("正在停止心率服务与悬浮窗 ...")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", PS],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (result.stdout or "").strip()
    print(out if out else "  没有找到正在运行的心率服务（可能已经停了）")
    if result.returncode != 0 and result.stderr:
        print("  错误:", result.stderr.strip()[:200])
        return 1
    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
