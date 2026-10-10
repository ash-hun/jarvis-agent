"""out/hud-motion.mp4 → ../hud-motion.gif. README 가 재생할 수 있는 건 레포 안 GIF 뿐이라 ffmpeg 팔레트로 줄인다.

폭·fps·색수는 10MB 아래로 맞춘 값. 구체 영상 구간이 프레임 전체를 바꿔서 여기서 크기가 결정된다.
"""

import subprocess
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "out" / "hud-motion.mp4"
DST = HERE.parent / "hud-motion.gif"
WIDTH = 880
FPS = 8
COLORS = 160

FILTER = (
    f"fps={FPS},scale={WIDTH}:-1:flags=lanczos,split[s0][s1];"
    f"[s0]palettegen=max_colors={COLORS}:stats_mode=diff[p];"
    f"[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
)

subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(SRC), "-vf", FILTER, str(DST)], check=True)
print(f"{DST.name}: {DST.stat().st_size / 1048576:.1f} MB")
