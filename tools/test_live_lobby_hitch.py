import os, sys, time, json
import cv2, numpy as np
import win32gui, win32con, win32api, win32process

# 查找 KK 对战平台窗口
def find_kk_window():
    found_hwnds = []
    def enum_cb(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if "KK官方对战平台" in title or "对战平台" in title:
                found_hwnds.append(hwnd)
        return True
    win32gui.EnumWindows(enum_cb, None)
    return found_hwnds[0] if found_hwnds else None

def capture_window(hwnd):
    rect = win32gui.GetWindowRect(hwnd)
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    
    hwndDC = win32gui.GetWindowDC(hwnd)
    import win32ui
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()
    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
    saveDC.SelectObject(saveBitMap)
    
    import ctypes
    windll = ctypes.windll.user32
    windll.PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)
    
    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4))
    
    win32gui.DeleteObject(saveBitMap.GetHandle())
    saveDC.DeleteDC()
    mfcDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwndDC)
    return img[:, :, :3], rect

def run_test(keyword="3"):
    hwnd = find_kk_window()
    if not hwnd:
        print("未找到 KK 对战平台窗口，请先打开对战平台！")
        return
    
    print(f"找到 KK 对战平台窗口: HWND {hwnd}")
    img, rect = capture_window(hwnd)
    os.makedirs("C:/tmp/lobby_test", exist_ok=True)
    cv2.imwrite("C:/tmp/lobby_test/current_lobby.jpg", img)
    print(f"已捕获当前画面: {img.shape}, 保存至 C:/tmp/lobby_test/current_lobby.jpg")

if __name__ == "__main__":
    kw = sys.argv[1] if len(sys.argv) > 1 else "3"
    run_test(kw)
