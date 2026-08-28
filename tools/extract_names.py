# -*- coding: utf-8 -*-
import json, re, sys
from pathlib import Path
import dnfile

# 原版 C# 程序（参考用，非本项目产物）；路径可用 --exe 覆盖，默认按仓库同级 参考/ 找。
ROOT = Path(__file__).resolve().parents[1]
exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "参考" / "1.3.3.3" / "GameScript.exe"
out = ROOT / "docs"
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