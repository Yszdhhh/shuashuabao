import os
import shutil
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw

def process_and_standardize_icon(img_path: str, target_size=(128, 128), border_radius=14):
    im = Image.open(img_path).convert('RGBA')
    w, h = im.size
    
    # 1. 兼容条形截图或残缺截图：等比缩放并居中到暗黑/游戏底板上
    if h < 50 or w < 50 or abs(w - h) > 15:
        # 创建暗色拟态游戏背景
        base = Image.new('RGBA', (max(w, h, 70), max(w, h, 70)), (18, 20, 26, 255))
        off_x = (base.width - w) // 2
        off_y = (base.height - h) // 2
        base.paste(im, (off_x, off_y), im)
        inner = base
    else:
        # 去除原始截图四周 2px 不均匀杂边
        crop_margin = 2 if min(w, h) >= 64 else 0
        if crop_margin > 0:
            inner = im.crop((crop_margin, crop_margin, w - crop_margin, h - crop_margin))
        else:
            inner = im

    # 2. 高质量重采样 (Lanczos 超分清晰化)
    resized = inner.resize(target_size, Image.Resampling.LANCZOS)
    
    # 3. 细节增强：锐度提升 + 微对比度优化
    enhancer_sharp = ImageEnhance.Sharpness(resized)
    sharp = enhancer_sharp.enhance(1.25)
    
    enhancer_con = ImageEnhance.Contrast(sharp)
    boosted = enhancer_con.enhance(1.06)
    
    # 4. 统一中框圆角遮罩
    mask = Image.new('L', target_size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle([(0, 0), (target_size[0]-1, target_size[1]-1)], radius=border_radius, fill=255)
    
    output = Image.new('RGBA', target_size, (0, 0, 0, 0))
    output.paste(boosted, (0, 0), mask)
    
    # 5. 淡化统一微边框（半透明现代边框）
    draw_out = ImageDraw.Draw(output)
    draw_out.rounded_rectangle(
        [(0, 0), (target_size[0]-1, target_size[1]-1)],
        radius=border_radius,
        outline=(255, 255, 255, 40),
        width=1
    )
    
    return output

def main():
    workspace_root = Path(r"G:\刷刷宝\Worktrees\GameScript-WebShell-20260826")
    supp_root = Path(r"C:\Users\10639\Desktop\新建文件夹\boss补充")
    
    supp_boss = supp_root / "boss"
    supp_cjb = supp_root / "chuanjiaobao"
    
    target_boss_dir = workspace_root / "ui-v2" / "public" / "assets" / "boss"
    target_cjb_dir = workspace_root / "ui-v2" / "public" / "assets" / "chuanjiaobao"
    
    target_boss_dir.mkdir(parents=True, exist_ok=True)
    target_cjb_dir.mkdir(parents=True, exist_ok=True)
    
    processed_boss = 0
    # 1. 优先处理补充目录的 boss
    if supp_boss.exists():
        for item in sorted(supp_boss.glob("*.png")):
            out_img = process_and_standardize_icon(str(item))
            out_img.save(str(target_boss_dir / item.name), "PNG")
            processed_boss += 1
            
    # 如果已有目录中有补充目录没有的 boss，也一并高清统一化
    for item in sorted(target_boss_dir.glob("*.png")):
        out_img = process_and_standardize_icon(str(item))
        out_img.save(str(target_boss_dir / item.name), "PNG")

    processed_cjb = 0
    # 2. 处理传家宝
    if supp_cjb.exists():
        for item in sorted(supp_cjb.glob("*.png")):
            out_img = process_and_standardize_icon(str(item))
            out_img.save(str(target_cjb_dir / item.name), "PNG")
            processed_cjb += 1
            
    for item in sorted(target_cjb_dir.glob("*.png")):
        out_img = process_and_standardize_icon(str(item))
        out_img.save(str(target_cjb_dir / item.name), "PNG")
        
    print(f"Batch processing complete: {processed_boss} boss icons and {processed_cjb} chuanjiaobao icons standardized to 128x128.")

if __name__ == "__main__":
    main()
