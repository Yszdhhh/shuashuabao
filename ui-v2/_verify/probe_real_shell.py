import os, sys
from pathlib import Path
WT = Path(r"G:\刷刷宝\Worktrees\ui-kanban-port-20260912")
OUT = Path(os.environ["PROBE_OUT"])
sys.path.insert(0, str(WT / "src"))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from shuabao.shell.web_config_shell import WebConfigShell
w = WebConfigShell(app_data=Path(os.environ["SHUABAO_APP_DATA"]), root=WT)
w.show()
INFO = r"""JSON.stringify({theme:document.body.dataset.theme, appTheme:(document.getElementById('scene-app')||{}).dataset?.theme,
 scene:state.scene, broken:[...document.images].filter(i=>i.complete&&i.naturalWidth===0).map(i=>i.getAttribute('src')),
 win:[innerWidth,innerHeight], startErr:(document.getElementById('startErr')||{}).textContent||''})"""
steps = [
  (6000, "farm", None),
  (6500, None, "document.getElementById('btnTheme').click()"),
  (8000, "farm_dark", None),
  (8200, None, "setScene('hitch')"),
  (9800, "hitch_dark", None),
  (10000, None, "setScene('follow')"),
  (11600, "follow_dark", None),
  (11800, None, "setScene('lead')"),
  (13400, "lead_dark", None),
]
def shot(tag):
    w.page.runJavaScript(INFO, 0, lambda r, t=tag: (OUT / f"p2_{t}.json").write_text(r or "null", encoding="utf-8"))
    w.grab().save(str(OUT / f"p2_{tag}.png"))
for ms, tag, js in steps:
    if tag: QTimer.singleShot(ms, lambda t=tag: shot(t))
    else: QTimer.singleShot(ms, lambda j=js: w.page.runJavaScript(j))
QTimer.singleShot(14500, app.quit)
app.exec()
