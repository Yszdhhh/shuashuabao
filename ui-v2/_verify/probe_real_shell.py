"""正式网页壳实测探针：隔离 SHUABAO_APP_DATA，不点开始运行。
依次截图：单刷 → 切深色 → 蹭车 → 跟车 → 带车 → 单刷，记录主题/场景/坏图/窗口尺寸/按钮可见性。
环境变量：PROBE_WT（仓库根）、PROBE_OUT（输出目录）、SHUABAO_APP_DATA（隔离配置目录）。
"""
import os
import sys
from pathlib import Path

WT = Path(os.environ.get("PROBE_WT", r"G:\刷刷宝\GameScript-Local"))
OUT = Path(os.environ["PROBE_OUT"])
TAG = os.environ.get("PROBE_TAG", "p3")
sys.path.insert(0, str(WT / "src"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from shuabao.shell.web_config_shell import WebConfigShell  # noqa: E402

w = WebConfigShell(app_data=Path(os.environ["SHUABAO_APP_DATA"]), root=WT)
w.show()

INFO = r"""JSON.stringify({
  theme: document.body.dataset.theme, scene: state.scene,
  broken: [...document.images].filter(i => i.complete && i.naturalWidth === 0).map(i => i.getAttribute('src')),
  inner: [innerWidth, innerHeight],
  pill: (document.getElementById('statusPill') || {}).textContent,
  logInDrawer: !!document.querySelector('#runLogFold #odRunLog'),
  minBtn: getComputedStyle(document.getElementById('btnMin')).display,
  maxBtn: getComputedStyle(document.getElementById('btnMax')).display,
  modeIcons: [...document.querySelectorAll('.mode-bar-btn .ph')].filter(e => getComputedStyle(e).display !== 'none').length
})"""

steps = [
    (6000, "farm", None),
    (6300, None, "document.getElementById('btnTheme').click()"),
    (8000, "farm_dark", None),
    (8200, None, "switchScene('hitch')"),
    (10000, "hitch", None),
    (10200, None, "switchScene('follow')"),
    (12000, "follow", None),
    (12200, None, "switchScene('lead')"),
    (14000, "lead", None),
]


def shot(tag):
    def save(res, t=tag):
        (OUT / f"{TAG}_{t}.json").write_text(
            (res or "null")[:-1] + f', "window": "{w.width()}x{w.height()}"}}', encoding="utf-8")
    w.page.runJavaScript(INFO, 0, save)
    w.grab().save(str(OUT / f"{TAG}_{tag}.png"))


for ms, tag, js in steps:
    if tag:
        QTimer.singleShot(ms, lambda t=tag: shot(t))
    else:
        QTimer.singleShot(ms, lambda j=js: w.page.runJavaScript(j))
QTimer.singleShot(15000, app.quit)
app.exec()
