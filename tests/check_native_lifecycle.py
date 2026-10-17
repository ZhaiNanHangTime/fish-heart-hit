"""Actual Tk child lifecycle, isolated from the installation's private files."""
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hr_runtime import RuntimeControl

async def main():
    product=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='fish-hud-lifecycle-') as folder:
        root=Path(folder)
        for name in ['heartrate_hud.py','hr_config.py','hr_client.py','hr_visual.py']:
            shutil.copy2(product/name,root/name)
        shutil.copytree(product/'web/assets',root/'web/assets')
        runtime=RuntimeControl(root,'http://127.0.0.1:18766',asyncio.Event())
        try:
            result=await runtime.set_hud(True)
            assert result['hud'],(root/'runtime/hud.log').read_text(errors='replace')
            pid=runtime.child.pid
            await runtime.set_hud(True)
            assert runtime.child.pid==pid
            await asyncio.sleep(.6)
            await runtime.set_hud(False)
            assert not runtime.status()['hud']
            assert (root/'hud.json').is_file(),'graceful exit must save the HUD position'
            assert json.loads((root/'hud.json').read_text())['scale']==3
            # Closing the parent also closes its one child, without process-name searches.
            await runtime.set_hud(True)
            child=runtime.child
            await runtime.close()
            assert child.poll()==0 and not runtime.status()['hud']
            print('PASS: real Tk child starts once; repeated show reuses PID; hide saves position; parent close exits child with code 0')
        finally:
            await runtime.close()

if __name__=='__main__':asyncio.run(main())
