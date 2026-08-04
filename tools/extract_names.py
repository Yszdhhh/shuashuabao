# -*- coding: utf-8 -*-
import json, re
from pathlib import Path
import dnfile

exe = Path(r"C:\Users\10639\Desktop\🎮 影音游戏\1.3.3.3\GameScript.exe")
out = Path(r"C:\Users\10639\Desktop\🎮 影音游戏\GameScript-Local\docs")
pe = dnfile.dnPE(str(exe))
md = pe.net.mdtables

methods = [str(r.Name) for r in md.MethodDef.rows]
fields = [str(r.Name) for r in md.Field.rows]
# PascalCase / readable
readable_m = sorted({m for m in methods if re.match(r'^[A-Z][A-Za-z0-9_]+$', m) and len(m) > 2})
readable_f = sorted({f for f in fields if re.match(r'^[A-Za-z][A-Za-z0-9_]+$', f) and not f.startswith('<')})
# compiler display class hints (method names inside)
hints = sorted({m for m in methods if m.startswith('<') and m.endswith('>b__') is False})
# better: names like <SelectStage>b__0
closure = sorted({re.search(r'<([^>]+)>', m).group(1) for m in methods if re.search(r'<([^>]+)>', m)})
closure = sorted(c for c in closure if re.match(r'^[A-Za-z]', c) and not c.startswith(''))

(out / "methods_readable.txt").write_text("\n".join(readable_m), encoding="utf-8")
(out / "fields_readable.txt").write_text("\n".join(readable_f), encoding="utf-8")
(out / "closure_hints.txt").write_text("\n".join(closure), encoding="utf-8")
print("methods", len(methods), "readable", len(readable_m), "closures", len(closure))
print("--- closures sample ---")
for c in closure:
    if any(k in c for k in ['Select','Close','Quit','Entry','Change','Run','Click','Find','Card','Skill','Boss','Stage','Game','Start','Stop','License','Cert','Room','Long','Wood','Secret','Clean','Press','Capture','Timer','Recal']):
        print(c)