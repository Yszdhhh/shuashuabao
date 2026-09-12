"""
Vite Dev (mockBridge) 端到端自动化验收套件
严格覆盖《执行Agent提示词》第 4 节全部指标：
1. 四场景 × 深浅主题截图
2. 零外网请求与零 /api/ 请求
3. 抽屉 scrollLeft 恒为 0
4. 折叠状态保持
5. 主题切换无残留 class
6. 礼花 canvas 回收
7. 运行态与 HUD 联动 + F12 急停
"""

import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:5173/index.html"
OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZES = {
    "farm": (1080, 820),
    "lead": (1080, 820),
    "hitch": (360, 900),
    "follow": (360, 900),
}

def run_verification():
    results = {}
    print(f"=== 正在连接 Vite Dev: {BASE_URL} ===")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        
        # -------------------------------------------------------------
        # 1. 零外网请求 & 四场景 × 深浅主题截图
        # -------------------------------------------------------------
        print("\n[Check 1/6] 检查四场景 × 深浅主题截图 & 零外网请求...")
        all_requests = []
        page_errors = []
        
        for theme in ["dark", "light"]:
            for scene, (w, h) in SIZES.items():
                pg = browser.new_page(viewport={"width": w, "height": h})
                pg.on("request", lambda r: all_requests.append(r.url))
                pg.on("pageerror", lambda e: page_errors.append(str(e)))
                
                pg.goto(BASE_URL)
                pg.wait_for_timeout(400)
                
                if theme == "light":
                    # 切换浅色
                    current_theme = pg.evaluate("document.body.dataset.theme")
                    if current_theme != "light":
                        pg.click("#btnTheme")
                        pg.wait_for_timeout(300)
                
                # 切换场景
                pg.evaluate(f"document.querySelector('#ctrl-{scene}').click()")
                pg.wait_for_timeout(400)
                
                info = pg.evaluate("""() => ({
                    theme: document.body.dataset.theme,
                    scene: state.scene,
                    win: document.body.dataset.win,
                    compactH: (typeof compactContentHeight === 'function') ? compactContentHeight() : null,
                })""")
                
                if info["win"] == "compact" and info["compactH"]:
                    pg.set_viewport_size({"width": w, "height": info["compactH"]})
                    pg.wait_for_timeout(200)
                
                shot_path = OUT_DIR / f"{theme}_{scene}.png"
                pg.screenshot(path=str(shot_path))
                pg.close()
        
        # 检查外网请求
        external_reqs = [u for u in all_requests if not (u.startswith("http://localhost:5173") or u.startswith("http://127.0.0.1:5173"))]
        api_reqs = [u for u in all_requests if "/api/" in u]
        results["zero_external_requests"] = len(external_reqs) == 0
        results["zero_api_requests"] = len(api_reqs) == 0
        results["scene_screenshots_saved"] = True
        print(f"  - 总请求数: {len(all_requests)}, 外网请求数: {len(external_reqs)}, /api/ 请求数: {len(api_reqs)}")
        print(f"  - 四场景深浅截图已保存至: {OUT_DIR}")
        
        # -------------------------------------------------------------
        # 2. 抽屉 scrollLeft 恒为 0 检查
        # -------------------------------------------------------------
        print("\n[Check 2/6] 检查宝物设置抽屉 (scrollLeft 恒为 0)...")
        pg = browser.new_page(viewport={"width": 1080, "height": 820})
        pg.on("pageerror", lambda e: page_errors.append(str(e)))
        pg.goto(BASE_URL)
        pg.wait_for_timeout(400)
        
        # 监控 scrollLeft
        pg.evaluate("""() => {
            window.__scrollLog = [];
            const app = document.querySelector('#scene-app');
            const d = document.querySelector('#drawer');
            const t0 = performance.now();
            function check() {
                window.__scrollLog.push([Math.round(performance.now() - t0), app.scrollLeft, Math.round(d.getBoundingClientRect().left)]);
                if (performance.now() - t0 < 1200) requestAnimationFrame(check);
            }
            requestAnimationFrame(check);
        }""")
        
        pg.click("#btnMore")
        pg.wait_for_timeout(400)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(500)
        
        scroll_log = pg.evaluate("window.__scrollLog || []")
        max_scroll_left = max((r[1] for r in scroll_log), default=0)
        drawer_closed = not pg.evaluate("Boolean(state.drawer)")
        results["drawer_max_scroll_left_zero"] = (max_scroll_left == 0)
        results["drawer_closed_after_esc"] = drawer_closed
        print(f"  - 最大 scrollLeft: {max_scroll_left} (必须恒为 0)")
        print(f"  - Esc 后抽屉关闭状态: {drawer_closed}")
        pg.close()
        
        # -------------------------------------------------------------
        # 3. 折叠状态保持
        # -------------------------------------------------------------
        print("\n[Check 3/6] 检查折叠状态保持 (re-render 后不收拢)...")
        pg = browser.new_page(viewport={"width": 1080, "height": 820})
        pg.on("pageerror", lambda e: page_errors.append(str(e)))
        pg.goto(BASE_URL)
        pg.wait_for_timeout(400)
        
        # 展开技能与排序
        pg.click("details[data-fold=skills] > summary")
        pg.click("details[data-fold=rank] > summary")
        pg.wait_for_timeout(200)
        
        # 触发重绘：点击开关与排序卡片
        pg.click("#swSecret")
        pg.wait_for_timeout(200)
        pg.click(".rank-card[data-code=asjg] [data-move='-1']")
        pg.wait_for_timeout(200)
        
        skills_open = pg.evaluate("Boolean(document.querySelector('details[data-fold=skills]')?.open)")
        rank_open = pg.evaluate("Boolean(document.querySelector('details[data-fold=rank]')?.open)")
        results["fold_state_preserved"] = (skills_open and rank_open)
        print(f"  - 重绘后 skills 保持展开: {skills_open}")
        print(f"  - 调序后 rank 保持展开: {rank_open}")
        pg.close()
        
        # -------------------------------------------------------------
        # 4. 主题切换无残留 class
        # -------------------------------------------------------------
        print("\n[Check 4/6] 检查主题切换无残留 theme-switching class...")
        pg = browser.new_page(viewport={"width": 1080, "height": 820})
        pg.on("pageerror", lambda e: page_errors.append(str(e)))
        pg.goto(BASE_URL)
        pg.wait_for_timeout(400)
        
        pg.click("#btnTheme")
        pg.wait_for_timeout(600)
        has_switching_1 = pg.evaluate("document.documentElement.classList.contains('theme-switching')")
        
        pg.click("#btnTheme")
        pg.wait_for_timeout(600)
        has_switching_2 = pg.evaluate("document.documentElement.classList.contains('theme-switching')")
        
        results["theme_no_leftover_class"] = (not has_switching_1 and not has_switching_2)
        print(f"  - 切换浅色后残留 class: {has_switching_1}")
        print(f"  - 切换深色后残留 class: {has_switching_2}")
        pg.close()
        
        # -------------------------------------------------------------
        # 5. 礼花 Canvas 回收与订阅激活
        # -------------------------------------------------------------
        print("\n[Check 5/6] 检查礼花 Canvas 动画结束后彻底回收...")
        pg = browser.new_page(viewport={"width": 1080, "height": 820})
        pg.on("pageerror", lambda e: page_errors.append(str(e)))
        pg.goto(BASE_URL)
        pg.wait_for_timeout(400)
        
        pg.click("#btnActivateKey")
        pg.wait_for_timeout(300)
        pg.fill("#subscriptionKey", "TEST-LICENSE-KEY-2026")
        pg.click("[data-activate-subscription]")
        
        # 等待礼花动画并完成淡出回收 (约 2000ms)
        pg.wait_for_timeout(2200)
        canvas_exists = pg.evaluate("Boolean(document.querySelector('canvas.confetti'))")
        pill_text = pg.evaluate("document.querySelector('#subscriptionPill')?.textContent")
        results["confetti_canvas_recycled"] = (not canvas_exists)
        print(f"  - 动画后 canvas 彻底移除: {not canvas_exists}")
        print(f"  - 订阅胶囊当前文案: {pill_text}")
        pg.close()
        
        # -------------------------------------------------------------
        # 6. 运行态与 HUD 联动 + F12 急停
        # -------------------------------------------------------------
        print("\n[Check 6/6] 检查运行态与局内 HUD 联动及 F12 急停...")
        pg = browser.new_page(viewport={"width": 1080, "height": 820})
        pg.on("pageerror", lambda e: page_errors.append(str(e)))
        pg.goto(BASE_URL)
        pg.wait_for_timeout(400)
        
        # 点击开始运行
        pg.click("#btnStart")
        pg.wait_for_timeout(600)
        
        running_before = pg.evaluate("document.body.dataset.running === 'true'")
        headline = pg.evaluate("document.querySelector('#hudHeadline')?.textContent")
        stop_btn_text = pg.evaluate("document.querySelector('#btnStartTextStop')?.textContent")
        print(f"  - 启动后 running 属性: {running_before}")
        print(f"  - HUD 局内标语: {headline}")
        print(f"  - 停止按钮文案: {stop_btn_text}")
        
        # F12 急停
        pg.keyboard.press("F12")
        pg.wait_for_timeout(700)
        
        running_after = pg.evaluate("document.body.dataset.running === 'true'")
        results["run_start_and_f12_stop"] = (running_before and not running_after)
        print(f"  - F12 急停后 running 属性: {running_after}")
        pg.close()
        
        browser.close()
    
    results["zero_page_errors"] = len(page_errors) == 0
    if page_errors:
        print(f"[Warning] 页面出现错误: {page_errors}")
    
    print("\n==================================================")
    print("           Vite Dev 浏览器端自动化验收报告         ")
    print("==================================================")
    all_ok = True
    for item, ok in results.items():
        symbol = "✓ PASS" if ok else "✗ FAIL"
        if not ok:
            all_ok = False
        print(f" {symbol} : {item}")
    print("==================================================")
    print(f"最终结果: {'ALL PASSED' if all_ok else 'SOME CHECKS FAILED'}")
    return all_ok

if __name__ == "__main__":
    ok = run_verification()
    sys.exit(0 if ok else 1)
