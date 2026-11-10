"""Windows package entry and Velopack startup integration."""
from contextlib import contextmanager
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import tempfile
from urllib.request import getproxies

from hr_paths import DATA_DIR

RELEASE_FEED = 'https://github.com/ZhaiNanHangTime/fish-heart-hit/releases/latest/download/'


@contextmanager
def system_proxy():
    """Give Velopack Windows proxy settings when the user set them only in Settings."""
    added = []
    proxies = getproxies()
    for scheme in ('http', 'https'):
        key = scheme.upper()+'_PROXY'
        if key not in os.environ and proxies.get(scheme):
            os.environ[key] = proxies[scheme]
            added.append(key)
    if added and 'NO_PROXY' not in os.environ:
        os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
        added.append('NO_PROXY')
    try:
        yield
    finally:
        for key in added:
            os.environ.pop(key, None)


def backup_before_update():
    backups = DATA_DIR.parent/'backups'
    backups.mkdir(exist_ok=True)
    name = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    with tempfile.TemporaryDirectory(prefix='backup-', dir=backups) as temporary:
        staging = Path(temporary)/name
        staging.mkdir()
        shutil.copytree(DATA_DIR, staging/'profile', symlinks=True)
        shutil.copytree(Path(sys.executable).parent, staging/'program', symlinks=True)
        staging.rename(backups/name)
    return backups/name


def port_in_use(port):
    with socket.socket() as probe:
        probe.settimeout(.5)
        return probe.connect_ex(('127.0.0.1', port)) == 0


def prepare_start(args):
    from desktop_migration import initialize_profile
    program = Path(sys.executable)
    if not DATA_DIR.exists() and port_in_use(args.port):
        raise RuntimeError('旧心率后台仍在运行。请先从旧总控结束本次运行，再打开新版导入数据。')
    if not initialize_profile(program.parent.parent/program.name):
        return False
    if args.no_update or args.panel or port_in_use(args.port):
        return True

    import velopack
    folder = DATA_DIR.parent/'runtime'
    handler = RotatingFileHandler(folder/'velopack.log', maxBytes=256*1024, backupCount=1, encoding='utf-8')
    log = logging.getLogger('fish-heart-hit.desktop')
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        with system_proxy():
            source = velopack.HttpSource(RELEASE_FEED, velopack.HttpOptions([], 6000))
            manager = velopack.UpdateManager(source)
            update = manager.check_for_updates()
            if update is None:
                return True
            version = update.TargetFullRelease.Version
            log.info('Downloading %s', version)
            source = velopack.HttpSource(RELEASE_FEED, velopack.HttpOptions([], 90000))
            manager = velopack.UpdateManager(source)
            manager.download_updates(update)
        if port_in_use(args.port):
            log.info('A service is running. Deferring update until the next launch.')
            return True
        backup = backup_before_update()
        log.info('Applying %s after backing up to %s', version, backup)
        manager.apply_updates_and_restart_with_args(update, [*sys.argv[1:], '--no-update'])
        return False
    except Exception as exc:
        log.warning('Update deferred: %s', re.sub(r'https?://\S+', '[URL]', str(exc)))
        return True
    finally:
        log.removeHandler(handler)
        handler.close()


def main():
    role = sys.argv[1] if len(sys.argv) > 1 else ''
    if role == '--service-child':
        sys.argv.pop(1)
        import heartrate_live
        return heartrate_live.main()
    if role == '--hud-child':
        sys.argv.pop(1)
        import heartrate_hud
        return heartrate_hud.main()
    import app_launcher
    if role == '--launcher-child':
        sys.argv.pop(1)
        return app_launcher.main()

    import velopack
    # Back up before every apply, including updates downloaded during an earlier run.
    velopack.App().set_auto_apply_on_startup(False).run()
    if '--stop' not in sys.argv and '--check' not in sys.argv and '--hud' not in sys.argv:
        sys.argv.append('--hud')
    return app_launcher.main(before_start=prepare_start)


if __name__ == '__main__':
    raise SystemExit(main())
