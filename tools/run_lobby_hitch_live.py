import time, win32gui, cv2, mss, numpy as np

# 这是一个自闭环的找房+准备执行器
class LobbyHitchLiveRunner:
    def __init__(self, hwnd=1052412, search_key="3"):
        self.hwnd = hwnd
        self.search_key = search_key
        self.w, self.h = 1334, 947

    def click(self, x, y, dbl=False):
        lParam = (int(y) << 16) | (int(x) & 0xFFFF)
        win32gui.SendMessage(self.hwnd, 0x0201, 1, lParam)
        time.sleep(0.05)
        win32gui.SendMessage(self.hwnd, 0x0202, 0, lParam)
        if dbl:
            time.sleep(0.05)
            win32gui.SendMessage(self.hwnd, 0x0203, 1, lParam)
            time.sleep(0.05)
            win32gui.SendMessage(self.hwnd, 0x0202, 0, lParam)

    def search_and_join(self):
        print(f"1. 激活搜索框并输入 [{self.search_key}]...")
        # 点击搜索框 (x: 1060, y: 140)
        self.click(1060, 140)
        time.sleep(0.2)
        # 全选清空
        win32gui.SendMessage(self.hwnd, 0x0100, 0x11, 0) # CTRL
        win32gui.SendMessage(self.hwnd, 0x0100, ord('A'), 0)
        win32gui.SendMessage(self.hwnd, 0x0101, ord('A'), 0)
        win32gui.SendMessage(self.hwnd, 0x0101, 0x11, 0)
        time.sleep(0.1)
        # 输入字符
        for ch in self.search_key:
            win32gui.SendMessage(self.hwnd, 0x0102, ord(ch), 0)
            time.sleep(0.05)
        # 回车确认
        win32gui.SendMessage(self.hwnd, 0x0100, 0x0D, 0)
        win32gui.SendMessage(self.hwnd, 0x0101, 0x0D, 0)
        time.sleep(1.0)

        print("2. 双击进入第一个匹配房间...")
        self.click(600, 260, dbl=True)
        time.sleep(2.0)

        print("3. 点击右下角准备按钮...")
        self.click(1180, 880)
        time.sleep(0.5)
        print("找房与准备动作执行完毕！")

if __name__ == '__main__':
    runner = LobbyHitchLiveRunner(1052412, "3")
    runner.search_and_join()
