# -*- coding: utf-8 -*-
import re, sys
from pathlib import Path
import dnfile

# 原版 C# 程序（参考用，非本项目产物）；路径可用 argv[1] 覆盖。
ROOT = Path(__file__).resolve().parents[1]
exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "参考" / "1.3.3.3" / "GameScript.exe"
out = ROOT / "docs"
pe = dnfile.dnPE(str(exe))
methods = [str(r.Name) for r in pe.net.mdtables.MethodDef.rows]
fields = [str(r.Name) for r in pe.net.mdtables.Field.rows]

# <Name>b__xx or <Name>d__xx
closure = []
for m in methods:
    for g in re.findall(r"<([^>]+)>", m):
        if g and not g.startswith(">"):
            closure.append(g)
closure = sorted(set(closure))
(out / "closure_hints.txt").write_text("\n".join(closure), encoding="utf-8")
print("closures", len(closure))
for c in closure:
    print(c)

# Image-like string references from method/field - also scan #Strings heap via names that look like png stems
# Scan PE for .png references ascii/utf16
data = exe.read_bytes()
ascii_png = set(re.findall(rb"[\w./\\-]{3,80}\.png", data, flags=re.I))
# utf16 le
uni = data.decode("utf-16-le", errors="ignore")
uni_png = set(re.findall(r"[\w./\\-]{3,80}\.png", uni, flags=re.I))
png_refs = sorted({p.decode("ascii", errors="ignore") if isinstance(p, bytes) else p for p in list(ascii_png) + list(uni_png)})
(out / "png_refs_in_exe.txt").write_text("\n".join(png_refs), encoding="utf-8")
print("png refs", len(png_refs))
for p in png_refs[:80]:
    print(p)

# also scan for Images\ or Images/
paths = set(re.findall(rb"Images[\\/][\w./\\-]{1,80}", data, flags=re.I))
paths_u = set(re.findall(r"Images[\\/][\w./\\-]{1,80}", uni, flags=re.I))
allp = sorted({x.decode("ascii", errors="ignore") if isinstance(x, bytes) else x for x in list(paths)+list(paths_u)})
(out / "images_path_refs.txt").write_text("\n".join(allp), encoding="utf-8")
print("path refs", len(allp))
for p in allp[:100]:
    print(p)