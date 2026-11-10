"""Build the Windows x64 installer and update feed with PyInstaller and Velopack."""
import argparse
from importlib import metadata
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def copy_licenses(app):
    licenses = app/'licenses'
    licenses.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'LICENSE', licenses/'FishHeartHit.txt')
    shutil.copyfile(ROOT/'docs'/'Velopack-LICENSE.txt', licenses/'Velopack.txt')
    shutil.copyfile(Path(sys.base_prefix)/'LICENSE.txt', licenses/'Python.txt')
    for package in metadata.distributions():
        for item in package.files or ():
            if not any(part.lower().endswith('.dist-info') for part in item.parts):
                continue
            if not item.name.lower().startswith(('license', 'licence', 'copying', 'notice')):
                continue
            folder = licenses/package.metadata['Name']
            folder.mkdir(exist_ok=True)
            shutil.copyfile(item.locate(), folder/item.name)


def build(output, vpk):
    version = (ROOT/'RELEASE_VERSION').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('RELEASE_VERSION must be a stable semantic version.')
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--console',
        '--hide-console', 'hide-early', '--name', 'FishHeartHit',
        '--add-data', f'{ROOT/"web"};web', '--add-data', f'{ROOT/"RELEASE_VERSION"};.',
        '--collect-submodules', 'winrt', '--distpath', str(output/'app'),
        '--workpath', str(output/'obj'), '--specpath', str(output),
        str(ROOT/'desktop_entry.py'),
    ], cwd=ROOT, check=True)
    copy_licenses(output/'app'/'FishHeartHit')
    prefix = ['dotnet', str(vpk)] if vpk.suffix.lower() == '.dll' else [str(vpk)]
    subprocess.run([
        *prefix, 'pack', '--packId', 'FishHeartHit', '--packVersion', version,
        '--packTitle', 'FishHeartHit', '--mainExe', 'FishHeartHit.exe',
        '--packDir', str(output/'app'/'FishHeartHit'), '--outputDir', str(output/'release'),
        '--runtime', 'win-x64', '--channel', 'win',
    ], cwd=ROOT, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--vpk', required=True, type=Path)
    args = parser.parse_args()
    build(args.output.resolve(), args.vpk.resolve())
