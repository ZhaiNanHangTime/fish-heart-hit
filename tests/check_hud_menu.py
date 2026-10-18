"""Exercise the actual Tk menu command in isolation, without clicking live UI."""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import heartrate_hud as hud


class Feed:
    def __init__(self, *args):
        self.closed = False
    def close(self):
        self.closed = True
    def wait_closed(self, *args):
        pass


with tempfile.TemporaryDirectory(prefix='fish-menu-test-') as folder:
    with patch.object(hud, 'SnapshotClient', Feed), patch.object(hud, 'SETTINGS', Path(folder)/'hud.json'):
        instance = hud.HeartHud('http://127.0.0.1:18766/hr', 3, opaque=True)
        instance.root.withdraw()
        labels = []
        errors = []
        instance.root.report_callback_exception = lambda *args: errors.append(str(args))
        original_menu = hud.tk.Menu
        class Menu(original_menu):
            def tk_popup(self, x, y):
                for index in range(self.index('end')+1):
                    if self.type(index) != 'separator':
                        labels.append(self.entrycget(index, 'label'))
                assert labels[0] == '隐藏桌面悬浮窗（直播继续）'
                assert labels[1] == '恢复显示：总控 → 显示悬浮窗'
                self.invoke(0)  # Actual Tk command dispatch calls the real HUD close handler.
        with patch.object(hud.tk, 'Menu', Menu):
            instance._menu(SimpleNamespace(x_root=1, y_root=1))
        assert not errors, errors
        assert instance.stream.closed
        assert (Path(folder)/'hud.json').is_file()
        assert instance.size_worker_stop.is_set()
        print(json.dumps({'native_menu_command_invoked': True, 'first_item_is_hide': True,
                          'restore_instruction_visible': True, 'position_saved': True,
                          'stream_closed': True, 'tk_callback_errors': errors,
                          'scope': 'isolated Tk HUD only; no service shutdown or personal files'}, ensure_ascii=False))
