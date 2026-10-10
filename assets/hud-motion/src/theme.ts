// 단일 테마 — 색·이징·스프링·폰트. 컴포넌트에 hex 나 이징을 직접 쓰지 않는다.
import { Easing } from "remotion";

export const theme = {
  colors: {
    bg: "#05080F",
    bgAlt: "#0B1220",
    primary: "#8DD6F5", // HUD 리액터의 하늘색. 프레임당 한 요소에만
    accent: "#D98CFF", // 🔔 proactive 의 보라
    text: "#EAF2F8",
    textDim: "#8FA3B5",
    hairline: "rgba(141, 214, 245, 0.18)",
    glow: "rgba(141, 214, 245, 0.45)",
  },
  fonts: {
    display: "'Noto Sans KR', 'Space Grotesk', sans-serif",
    mono: "'JetBrains Mono', 'Noto Sans KR', monospace",
  },
  ease: {
    out: Easing.bezier(0.16, 1, 0.3, 1),
    inOut: Easing.bezier(0.83, 0, 0.17, 1),
    in: Easing.bezier(0.7, 0, 0.84, 0),
  },
  spring: {
    snappy: { damping: 14, stiffness: 160, mass: 0.6 },
    smooth: { damping: 20, stiffness: 90, mass: 1 },
    bouncy: { damping: 11, stiffness: 170, mass: 0.7 },
  },
} as const;
