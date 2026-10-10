"""out/hud-motion.mp4 → ../hud-motion.gif. README 가 재생할 수 있는 건 레포 안 GIF 뿐이라 ffmpeg 팔레트로 줄인다."""

import subprocess
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "out" / "hud-motion.mp4"
DST = HERE.parent / "hud-motion.gif"
WIDTH = 800
FPS = 10
COLORS = 128

FILTER = (
    f"fps={FPS},scale={WIDTH}:-1:flags=lanczos,split[s0][s1];"
    f"[s0]palettegen=max_colors={COLORS}:stats_mode=diff[p];"
    f"[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
)

subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(SRC), "-vf", FILTER, str(DST)], check=True)
print(f"{DST.name}: {DST.stat().st_size / 1048576:.1f} MB")
