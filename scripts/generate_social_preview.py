#!/usr/bin/env python3
"""
Generate social preview image for DMAF GitHub repository.
Output: 1280x640 PNG (GitHub's recommended social preview size)

Requirements:
    pip install pillow

Usage:
    python scripts/generate_social_preview.py
    
Output: assets/social-preview.png
"""

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Please install Pillow: pip install pillow")
    exit(1)


def create_social_preview(output_path: Path) -> None:
    """Create a social preview image for GitHub."""
    # GitHub recommended dimensions
    width, height = 1280, 640
    
    # Create image with gradient background
    img = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(img)
    
    # Create gradient (purple to blue)
    for y in range(height):
        # Interpolate between colors
        r = int(102 + (118 - 102) * (y / height))  # 667eea -> 764ba2
        g = int(126 + (75 - 126) * (y / height))
        b = int(234 + (162 - 234) * (y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    
    # Try to load a nice font, fall back to default
    try:
        # Try common font paths
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]
        title_font = None
        for font_path in font_paths:
            if Path(font_path).exists():
                title_font = ImageFont.truetype(font_path, 120)
                subtitle_font = ImageFont.truetype(font_path, 40)
                tagline_font = ImageFont.truetype(font_path, 32)
                break
        if title_font is None:
            raise OSError("No font found")
    except OSError:
        title_font = ImageFont.load_default()
        subtitle_font = title_font
        tagline_font = title_font
    
    # Draw face detection brackets (large, decorative)
    bracket_color = (0, 255, 136)  # Green glow color
    bracket_width = 8
    bracket_size = 80
    
    # Center area for brackets
    bx, by = 100, 180
    bw, bh = 400, 300
    
    # Top-left bracket
    draw.line([(bx, by + bracket_size), (bx, by), (bx + bracket_size, by)], 
              fill=bracket_color, width=bracket_width)
    # Top-right bracket  
    draw.line([(bx + bw - bracket_size, by), (bx + bw, by), (bx + bw, by + bracket_size)],
              fill=bracket_color, width=bracket_width)
    # Bottom-left bracket
    draw.line([(bx, by + bh - bracket_size), (bx, by + bh), (bx + bracket_size, by + bh)],
              fill=bracket_color, width=bracket_width)
    # Bottom-right bracket
    draw.line([(bx + bw - bracket_size, by + bh), (bx + bw, by + bh), (bx + bw, by + bh - bracket_size)],
              fill=bracket_color, width=bracket_width)
    
    # Draw stylized face (simple oval with features)
    face_center_x = bx + bw // 2
    face_center_y = by + bh // 2
    face_width, face_height = 180, 220
    
    # Face outline
    draw.ellipse(
        [(face_center_x - face_width//2, face_center_y - face_height//2),
         (face_center_x + face_width//2, face_center_y + face_height//2)],
        outline=(255, 255, 255, 200), width=4
    )
    
    # Eyes
    eye_y = face_center_y - 30
    for eye_x in [face_center_x - 40, face_center_x + 40]:
        draw.ellipse([(eye_x - 15, eye_y - 15), (eye_x + 15, eye_y + 15)], 
                     fill=(255, 255, 255))
        draw.ellipse([(eye_x - 6, eye_y - 6), (eye_x + 6, eye_y + 6)], 
                     fill=(51, 51, 51))
    
    # Smile
    smile_y = face_center_y + 40
    draw.arc([(face_center_x - 50, smile_y - 30), (face_center_x + 50, smile_y + 30)],
             start=0, end=180, fill=(255, 255, 255), width=4)
    
    # Checkmark badge
    badge_x, badge_y, badge_r = bx + bw - 20, by + bh - 20, 35
    draw.ellipse([(badge_x - badge_r, badge_y - badge_r), 
                  (badge_x + badge_r, badge_y + badge_r)], fill=(0, 200, 83))
    # Checkmark
    draw.line([(badge_x - 15, badge_y), (badge_x - 2, badge_y + 15), (badge_x + 20, badge_y - 15)],
              fill=(255, 255, 255), width=6)
    
    # Text content (right side)
    text_x = 580
    
    # Main title
    draw.text((text_x, 180), "DMAF", fill=(255, 255, 255), font=title_font)
    
    # Subtitle
    draw.text((text_x, 310), "Don't Miss A Face", fill=(200, 220, 255), font=subtitle_font)
    
    # Tagline lines
    taglines = [
        "🔍 Face Recognition",
        "📱 WhatsApp Media Watcher",  
        "☁️ Google Photos Backup",
        "🐍 Python • Open Source"
    ]
    
    y_offset = 400
    for tagline in taglines:
        draw.text((text_x, y_offset), tagline, fill=(220, 230, 255), font=tagline_font)
        y_offset += 45
    
    # Save
    img.save(output_path, "PNG", quality=95)
    print(f"✅ Social preview saved to: {output_path}")


def main():
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    assets_dir = project_root / "assets"
    assets_dir.mkdir(exist_ok=True)
    
    output_path = assets_dir / "social-preview.png"
    create_social_preview(output_path)
    
    print("\n📋 Next steps:")
    print("1. Go to your GitHub repo → Settings → General")
    print("2. Scroll to 'Social preview'")
    print("3. Click 'Edit' and upload assets/social-preview.png")


if __name__ == "__main__":
    main()
