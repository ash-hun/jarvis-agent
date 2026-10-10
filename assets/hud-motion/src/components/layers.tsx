// 다섯 층 중 바닥(배경 메시)과 꼭대기(그레이드·그레인·비네트).
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { theme } from "../theme";

// ponytail: 메시와 별은 정지. GIF 는 프레임 전체가 바뀌면 압축이 안 돼 배경 드리프트만으로 수 MB 가 는다. mp4 로 바꾸면 frame 기반 드리프트를 되살린다
export const BgMesh: React.FC = () => {
  const d1 = 0;
  const d2 = 0;
  return (
    <AbsoluteFill style={{ background: theme.colors.bg }}>
      <div style={{ position: "absolute", width: 1100, height: 1100, borderRadius: "50%",
        top: -500, left: -350 + d1, filter: "blur(60px)",
        background: `radial-gradient(circle, ${theme.colors.primary}2A, transparent 62%)` }} />
      <div style={{ position: "absolute", width: 900, height: 900, borderRadius: "50%",
        bottom: -450, right: -300 - d2, filter: "blur(70px)",
        background: `radial-gradient(circle, ${theme.colors.accent}1F, transparent 65%)` }} />
      <Stars />
    </AbsoluteFill>
  );
};

// 결정적 별 — 프레임마다 같은 자리. 느리게 깜빡인다.
const STARS = Array.from({ length: 70 }, (_, i) => {
  const s = Math.sin(i * 12.9898) * 43758.5453;
  const t = Math.sin(i * 78.233) * 43758.5453;
  return { x: (s - Math.floor(s)) * 100, y: (t - Math.floor(t)) * 100, r: 1 + (i % 3) * 0.5, ph: i * 0.7 };
});

const Stars: React.FC = () => (
  <AbsoluteFill>
    {STARS.map((st, i) => (
      <div key={i} style={{ position: "absolute", left: `${st.x}%`, top: `${st.y}%`,
        width: st.r * 2, height: st.r * 2, borderRadius: "50%", background: theme.colors.text,
        opacity: 0.25 + Math.sin(st.ph) * 0.2 }} />
    ))}
  </AbsoluteFill>
);

export const Grade: React.FC = () => (
  <AbsoluteFill style={{ pointerEvents: "none" }}>
    <AbsoluteFill style={{ backgroundColor: theme.colors.primary, mixBlendMode: "soft-light", opacity: 0.16 }} />
    <AbsoluteFill style={{ background:
      "linear-gradient(180deg, rgba(0,0,0,0.12), transparent 28%, transparent 72%, rgba(0,0,0,0.26))" }} />
  </AbsoluteFill>
);

export const Grain: React.FC = () => {
  const frame = useCurrentFrame();
  const noise = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='220'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='220' height='220' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E")`;
  return (
    <AbsoluteFill style={{ pointerEvents: "none", backgroundImage: noise, backgroundSize: "220px",
      backgroundPosition: `${(frame * 7) % 220}px ${(frame * 13) % 220}px`,
      opacity: 0.06, mixBlendMode: "overlay" }} />
  );
};

export const Vignette: React.FC = () => (
  <AbsoluteFill style={{ pointerEvents: "none",
    background: "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.3) 100%)" }} />
);
