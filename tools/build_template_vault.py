from __future__ import annotations
import glob
import os
import struct
import cv2
import numpy as np

def build_vault(project_root: str) -> str:
    images_dir = os.path.join(project_root, 'assets', 'Images')
    models_dir = os.path.join(project_root, 'models')
    os.makedirs(models_dir, exist_ok=True)
    vault_path = os.path.join(models_dir, 'templates.vault')

    img_files = glob.glob(os.path.join(images_dir, '**', '*.png'), recursive=True)
    print(f'[vault] Scanning {len(img_files)} PNG templates in {images_dir}...')

    vault_data = {}
    for p in img_files:
        rel_name = os.path.relpath(p, images_dir).replace(chr(92), '/')
        data = np.fromfile(p, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if img is not None:
            h, w = img.shape[:2]
            c = img.shape[2] if len(img.shape) > 2 else 1
            success, buf = cv2.imencode('.png', img)
            if success:
                vault_data[rel_name] = {
                    'h': h, 'w': w, 'c': c, 'buf': bytes(buf)
                }

    print(f'[vault] Encoded {len(vault_data)} templates into memory.')

    with open(vault_path, 'wb') as f:
        f.write(b'SBVT')
        f.write(struct.pack('<I', len(vault_data)))
        for name, item in vault_data.items():
            name_bytes = name.encode('utf-8')
            f.write(struct.pack('<H', len(name_bytes)))
            f.write(name_bytes)
            f.write(struct.pack('<HHB', item['h'], item['w'], item['c']))
            buf = item['buf']
            key = 0x5A
            masked_buf = bytes([b ^ key for b in buf])
            f.write(struct.pack('<I', len(masked_buf)))
            f.write(masked_buf)

    sz = os.path.getsize(vault_path) / (1024 * 1024)
    print(f'[vault] Successfully generated {vault_path} ({sz:.2f} MB)')
    return vault_path

if __name__ == '__main__':
    build_vault(r'G:/刷刷宝/GameScript-Local')
