// 등장·퇴장·Ken Burns·단어 reveal — 모든 움직임은 여기 이징과 스프링을 쓴다.
import React from "react";
import { Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

export const Entrance: React.FC<{ delay?: number; from?: number; children: React.ReactNode; style?: React.CSSProperties }> =
({ delay = 0, from = 40, children, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: theme.spring.smooth });
  return (
    <div style={{ opacity: p,
      transform: `translateY(${interpolate(p, [0, 1], [from, 0])}px) scale(${interpolate(p, [0, 1], [0.94, 1])})`,
      ...style }}>{children}</div>
  );
};

// 장면 퇴장 — 등장보다 빠르다(12 프레임). 장면 래퍼에 건다.
export const SceneExit: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const a = durationInFrames - 12, b = durationInFrames - 2;
  const y = interpolate(frame, [a, b], [0, -36], { easing: theme.ease.in, ...CLAMP });
  const o = interpolate(frame, [a, b], [1, 0], { easing: theme.ease.in, ...CLAMP });
  const s = interpolate(frame, [a, b], [1, 1.04], { easing: theme.ease.in, ...CLAMP });
  return <div style={{ position: "absolute", inset: 0, opacity: o, transform: `translateY(${y}px) scale(${s})` }}>{children}</div>;
};

export const WordReveal: React.FC<{ text: string; delay?: number; per?: number; style?: React.CSSProperties; hero?: string }> =
({ text, delay = 0, per = 3, style, hero }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={{ display: "flex", flexWrap: "wrap", columnGap: 14, rowGap: 4, ...style }}>
      {text.split(" ").map((word, i) => {
        const p = spring({ frame: frame - delay - i * per, fps, config: theme.spring.snappy });
        const isHero = hero !== undefined && word === hero;
        return (
          <span key={i} style={{ display: "inline-block", opacity: p,
            transform: `translateY(${interpolate(p, [0, 1], [26, 0])}px)`,
            color: isHero ? theme.colors.primary : undefined,
            textShadow: isHero ? `0 0 28px ${theme.colors.glow}` : undefined }}>{word}</span>
        );
      })}
    </div>
  );
};

// 스틸은 전부 Ken Burns. focus 는 확대 중심(%, %), zoom 은 1 → zoomTo.
// focus 는 cover 로 자를 때의 기준점이자 확대 중심 — 둘이 같아야 보고 싶은 영역이 화면에 남는다.
export const KenBurns: React.FC<{ src: string; zoomFrom?: number; zoomTo?: number; focus?: string; panX?: number }> =
({ src, zoomFrom = 1, zoomTo = 1.08, focus = "50% 50%", panX = 0 }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  // 움직임은 장면 앞 45% 에서 끝나고 나머지는 정지(hold). GIF 는 정지 구간만 압축된다.
  const settle = Math.round(durationInFrames * 0.45);
  const scale = interpolate(frame, [0, settle], [zoomFrom, zoomTo], { easing: theme.ease.inOut, ...CLAMP });
  const pan = interpolate(frame, [0, settle], [0, panX], { easing: theme.ease.inOut, ...CLAMP });
  return (
    <Img src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: focus,
      transformOrigin: focus, transform: `scale(${scale}) translateX(${pan}px)` }} />
  );
};
