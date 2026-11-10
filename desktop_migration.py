"""One-time import from a legacy script installation."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from hr_paths import DATA_DIR

LEGACY_ENTRY = '一键开播（总控+悬浮窗）.vbs'
PERSONAL_FILES = ('params.json', 'devices.json', 'hud.json')


def is_legacy(folder):
    return (folder/'heartrate_live.py').is_file() and (folder/'heartrate_hud.py').is_file() and (folder/'web').is_dir()


def previous_install():
    local = DATA_DIR.parent.parent
    candidates = []
    try:
        preference = json.loads((local/'FishHeartHit'/'installation.json').read_text(encoding='utf-8'))
        candidates.append(Path(preference['installation']))
    except (OSError, ValueError, TypeError, KeyError):
        pass
    candidates.extend([Path.home()/'Downloads'/'heart-rate', Path('G:/downloads/heart-rate')])
    return next((path for path in candidates if is_legacy(path)), Path.home())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').digest()


def is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def import_profile(source, profile):
    """Stage then atomically publish the profile. Source data stays available in the old folder."""
    if profile.exists():
        raise FileExistsError('已有资料，不能覆盖。')
    if source is None:
        profile.mkdir()
        return
    if not is_legacy(source):
        raise ValueError('请选择包含 heartrate_live.py、heartrate_hud.py 和 web 的旧程序目录。')
    with tempfile.TemporaryDirectory(prefix='import-', dir=profile.parent) as temporary:
        staging = Path(temporary)/'profile'
        staging.mkdir()
        inputs = [source/name for name in PERSONAL_FILES if (source/name).exists()]
        logs = source/'logs'
        if logs.exists():
            if not logs.is_dir() or is_link(logs):
                raise ValueError('旧版记录目录使用了链接，请先整理为普通文件夹。')
            for path in logs.rglob('*'):
                if is_link(path):
                    raise ValueError('旧版记录含链接，请先整理为普通文件夹。')
                if path.is_file():
                    inputs.append(path)
        for original in inputs:
            if not original.is_file() or is_link(original):
                raise ValueError('旧版配置含链接或异常文件，请先检查。')
            destination = staging/original.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
            if digest(original) != digest(destination):
                raise OSError('复制后的配置或记录校验失败，请退出旧后台后重试。')
        staging.rename(profile)


def redirect_legacy_entry(source, stable_exe):
    """Keep the old double-click shortcut, retaining a separate copy of the old script."""
    entry = source/LEGACY_ENTRY
    if not entry.is_file() or not stable_exe.is_file():
        return
    if is_link(entry):
        raise ValueError('原启动文件是链接，已保留。')
    backup = source/'一键开播（旧版备用）.vbs'
    with backup.open('xb') as stream:
        stream.write(entry.read_bytes())
    script = ('Option Explicit\r\nSet sh = CreateObject("WScript.Shell")\r\n'
              'sh.Run Chr(34) & "'+str(stable_exe)+'" & Chr(34), 0, False\r\n')
    script = script.replace('Option Explicit\r\n', 'Option Explicit\r\nDim sh\r\n', 1)
    with tempfile.NamedTemporaryFile(dir=source, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(script.encode('utf-16'))
    try:
        temporary.replace(entry)
    finally:
        temporary.unlink(missing_ok=True)


def initialize_profile(stable_exe):
    if DATA_DIR.exists():
        return True
    import tkinter as tk
    from tkinter import filedialog, messagebox
    window = tk.Tk()
    window.withdraw()
    try:
        while True:
            migrate = messagebox.askyesnocancel('咸鱼突刺 · 首次启动',
                '是否导入旧版设备、外观和心率记录？\n\n'
                '是：选择旧程序文件夹。\n否：创建新的空资料。\n取消：暂不启动。',
                parent=window)
            if migrate is None:
                return False
            source = None
            if migrate:
                selected = filedialog.askdirectory(parent=window, initialdir=str(previous_install()),
                                                    title='选择旧版咸鱼突刺程序目录')
                if not selected:
                    continue
                source = Path(selected)
            try:
                import_profile(source, DATA_DIR)
            except (OSError, ValueError) as exc:
                messagebox.showerror('迁移未完成', str(exc), parent=window)
                continue
            if source is not None:
                try:
                    redirect_legacy_entry(source, stable_exe)
                except (OSError, ValueError) as exc:
                    messagebox.showwarning('资料已导入',
                        f'原 VBS 无法切换到新版。请使用 Velopack 创建的桌面快捷方式。\n{exc}',
                        parent=window)
            return True
    finally:
        window.destroy()
