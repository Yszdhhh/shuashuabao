# 中介层（Mediator）

## 角色

```
官方实机行为 / 日志文案
        ↓ 对照
  config/scenes.json + Settings
        ↓
     Mediator（本层）
    ╱    │    ╲
 see   phase  act
 截屏   阶段   点击/按键
    ╲    │    ╱
   本地挂机循环
```

- **不**直接替代官方授权 exe  
- **只**把已恢复的流水变成可跑、可改的本地调度  
- Jobs（AutoJob 等）可逐步改为只调 `med.see / find / act_*`

## 阶段 Phase

| Phase | 对齐日志 |
|-------|----------|
| BOOT / WAIT_EXIT / PREPARE | 验证环境、等退出、开始准备 |
| WAIT_UI | 等待进入游戏UI（超时=软失败） |
| MAIN_LINE | 开始主线、卡都找完了 |
| ANCHOR_BOSS | 锚点BOSS名称 / 找到锚点Boss |
| LONGZHU | 开始查找龙珠N、退出倒计时 |
| QUIT / NEXT | QuitGame → 下一局 |

## 用法

```powershell
cd GameScript-Local
python main.py dry-run --steps 30          # 中介空跑
python main.py run --steps 50              # 真点击（慎用）
python main.py dry-run --legacy --steps 10 # 旧 AutoJob
```

配置：`config/default_settings.json`  
场景：`config/scenes.json`

## 文件

- `src/gamescript/mediator.py` — 中介实现  
- `src/gamescript/jobs/auto_job.py` — 旧路径（`--legacy`）  
