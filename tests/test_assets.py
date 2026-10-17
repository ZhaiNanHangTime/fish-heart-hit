"""Check the user's supplied eight PNGs without adding runtime image dependencies."""
import hashlib,json,struct,unittest
from pathlib import Path

class AssetTests(unittest.TestCase):
    def test_all_user_pngs_match_import_manifest_and_need_no_frame_offsets(self):
        root=Path(__file__).resolve().parents[1]/'web/assets/skins/xianyu'
        meta=json.loads((root/'frames.json').read_text(encoding='utf-8'))
        self.assertTrue(meta['baked_effects'])
        self.assertEqual(set(meta['frames']),{'idle','alert_low','alert_mid','tense','high','charge','burst','recover'})
        for name,frame in meta['frames'].items():
            with self.subTest(frame=name):
                data=(root/(name+'.png')).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(),frame['sha256'])
                self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
                width,height,depth,color=struct.unpack('>IIBB',data[16:26])
                self.assertEqual((width,height,depth,color),(576,384,8,6))
                self.assertEqual(frame['size'],meta['canvas'])
                self.assertEqual(frame['anchor'],meta['anchor'])
