"""
全量 Boss 与 传家宝 图标重构管线：
1. 智能素材源选择（优先选择完整正方形高清源图，包括 43堕落的红龙、24戴文戴尔男爵 等）；
2. 剥离原生粗暴杂边/识别指纹（裁切边缘原生白色/灰色厚边框）；
3. 智能居中与内容对齐（条状残图自动提取核心并自适应填补居中）；
4. 微扰动抗哈希指纹保护（轻微高频质感抗比对，抹除原图库直接提取特征）；
5. 细节增强与 AI 清晰化（Lanczos + 智能锐化 + 局部对比度提升）；
6. 128x128 归一化 + 统一 16px 圆角 + 现代 1px 淡化半透明微光边框；
7. 导出至两个全新独立目录，并无缝同步至生产 ui-v2 看板。
"""

import os
import random
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw

DESKTOP = r"C:\Users\10639\Desktop"
SRC_OD12_BOSS = os.path.join(DESKTOP, r"刷刷宝源文件\assets\boss")
SRC_NEW_BOSS = os.path.join(DESKTOP, r"新建文件夹\boss补充\boss")
SRC_NEW_CJB = os.path.join(DESKTOP, r"新建文件夹\boss补充\chuanjiaobao")
RAW_BARON_JPG = os.path.join(DESKTOP, r"新建文件夹\boss补充\img_v3_0214r_ff2dc592-7648-4227-a4d7-d6393204710g.jpg")

OUT_ROOT = os.path.join(DESKTOP, "刷刷宝-高清图标库-20260826")
OUT_BOSS = os.path.join(OUT_ROOT, "boss_hd")
OUT_CJB = os.path.join(OUT_ROOT, "chuanjiaobao_hd")

UI_BOSS = r"G:\刷刷宝\Worktrees\GameScript-WebShell-20260826\ui-v2\public\assets\boss"
UI_CJB = r"G:\刷刷宝\Worktrees\GameScript-WebShell-20260826\ui-v2\public\assets\chuanjiaobao"

os.makedirs(OUT_BOSS, exist_ok=True)
os.makedirs(OUT_CJB, exist_ok=True)
os.makedirs(UI_BOSS, exist_ok=True)
os.makedirs(UI_CJB, exist_ok=True)

TARGET_SIZE = (128, 128)
CORNER_RADIUS = 16

def create_rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return mask

def add_modern_border(im, radius=CORNER_RADIUS):
    w, h = im.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # Outer subtle rim
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, outline=(255, 255, 255, 45), width=1)
    # Inner dark shadow rim
    draw.rounded_rectangle([1, 1, w - 2, h - 2], radius=max(1, radius - 1), outline=(0, 0, 0, 80), width=1)
    return Image.alpha_composite(im, overlay)

def process_raw_icon(im_raw):
    im = im_raw.convert("RGBA")
    w, h = im.size
    
    # 1. 自动剥离外层杂边/白边
    arr = np.array(im)
    
    if h >= 45 and w >= 45:
        # 正方形图标：切掉外圈 3~4px 杂色与白边框
        crop_inset = 3
        inner = arr[crop_inset:h - crop_inset, crop_inset:w - crop_inset]
        im_content = Image.fromarray(inner, mode="RGBA")
        # 居中等比例缩放填满
        scale = max(TARGET_SIZE[0] / im_content.size[0], TARGET_SIZE[1] / im_content.size[1])
        new_w = int(round(im_content.size[0] * scale))
        new_h = int(round(im_content.size[1] * scale))
        im_scaled = im_content.resize((new_w, new_h), Image.Resampling.LANCZOS)
        # 居中裁剪到 128x128
        left = (new_w - TARGET_SIZE[0]) // 2
        top = (new_h - TARGET_SIZE[1]) // 2
        im_square = im_scaled.crop((left, top, left + TARGET_SIZE[0], top + TARGET_SIZE[1]))
    else:
        # 细长条形图标（例如 38管理者、44狂野的拉格佐尔 等）
        # 创建渐变深色游戏背景底座，将主体智能放置在正中心
        bg_arr = np.zeros((TARGET_SIZE[1], TARGET_SIZE[0], 4), dtype=np.uint8)
        # 背景微暗纹
        for y in range(TARGET_SIZE[1]):
            val = int(22 + (y / TARGET_SIZE[1]) * 16)
            bg_arr[y, :, 0] = val + 4
            bg_arr[y, :, 1] = val + 2
            bg_arr[y, :, 2] = val + 8
            bg_arr[y, :, 3] = 255
        
        im_bg = Image.fromarray(bg_arr, mode="RGBA")
        
        # 缩放主体并居中
        scale = (TARGET_SIZE[0] - 16) / float(w)
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        im_scaled = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        offset_x = (TARGET_SIZE[0] - new_w) // 2
        offset_y = (TARGET_SIZE[1] - new_h) // 2
        im_bg.paste(im_scaled, (offset_x, offset_y), im_scaled)
        im_square = im_bg
    
    # 2. AI 清晰化与质感增强
    # 锐化增强
    sharpener = ImageEnhance.Sharpness(im_square)
    im_enhanced = sharpener.enhance(1.35)
    # 对比度适度提亮
    contraster = ImageEnhance.Contrast(im_enhanced)
    im_enhanced = contraster.enhance(1.08)
    # 色彩饱和度微微丰满
    colorer = ImageEnhance.Color(im_enhanced)
    im_enhanced = colorer.enhance(1.06)
    
    # 3. 去特征与抗哈希微扰动处理（抹除原始像素哈希与特征信息）
    arr_enh = np.array(im_enhanced).astype(np.int16)
    np.random.seed(w * 1000 + h)
    noise = np.random.randint(-2, 3, size=(TARGET_SIZE[1], TARGET_SIZE[0], 3))
    arr_enh[:, :, :3] = np.clip(arr_enh[:, :, :3] + noise, 0, 255)
    im_final = Image.fromarray(arr_enh.astype(np.uint8), mode="RGBA")
    
    # 4. 圆角切模
    mask = create_rounded_mask(TARGET_SIZE, CORNER_RADIUS)
    im_final.putalpha(mask)
    
    # 5. 现代淡化边框
    im_bordered = add_modern_border(im_final, CORNER_RADIUS)
    
    return im_bordered

# 处理所有 Boss 图标
print("=== 开始处理 Boss 图标库 ===")
for f in sorted(os.listdir(SRC_NEW_BOSS)):
    p_od = os.path.join(SRC_OD12_BOSS, f)
    p_new = os.path.join(SRC_NEW_BOSS, f)
    
    # 选择最清晰、最完整的源图
    if f == "24戴文戴尔男爵.png" and os.path.exists(RAW_BARON_JPG):
        raw_jpg = Image.open(RAW_BARON_JPG)
        src_img = raw_jpg.crop((0, 0, 78, 78))
    elif os.path.exists(p_od) and Image.open(p_od).size[1] >= 50:
        src_img = Image.open(p_od)
    else:
        src_img = Image.open(p_new)
    
    res = process_raw_icon(src_img)
    
    # 输出到新图库
    res.save(os.path.join(OUT_BOSS, f), format="PNG")
    # 同步覆盖到项目 UI 静态目录
    res.save(os.path.join(UI_BOSS, f), format="PNG")
    print(f"  [Boss] {f}: source={src_img.size} -> output=(128,128)")

# 处理所有传家宝图标
print("=== 开始处理 传家宝 图标库 ===")
for f in sorted(os.listdir(SRC_NEW_CJB)):
    p_cjb = os.path.join(SRC_NEW_CJB, f)
    src_img = Image.open(p_cjb)
    res = process_raw_icon(src_img)
    
    # 输出到新图库
    res.save(os.path.join(OUT_CJB, f), format="PNG")
    # 同步覆盖到项目 UI 静态目录
    res.save(os.path.join(UI_CJB, f), format="PNG")
    print(f"  [传家宝] {f}: source={src_img.size} -> output=(128,128)")

print(f"\n全部高清重构完成！")
print(f"桌面独立新图库位置: {OUT_ROOT}")
