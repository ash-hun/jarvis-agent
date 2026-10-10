// HOOK — 어두운 HUD 위로 워드마크와 한 줄 주장. 첫 15 프레임 안에 움직인다.
import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { KenBurns, WordReveal, Entrance, SceneExit } from "../components/motion";

const WORDMARK = "J.A.R.V.I.S.";

export const Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const mark = spring({ frame, fps, config: theme.spring.smooth });
  const glowPulse = 0.7 + Math.sin(frame / 18) * 0.3;
  return (
    <SceneExit>
      <AbsoluteFill style={{ opacity: 0.55 }}>
        <KenBurns src="hud_idle.png" zoomFrom={1.02} zoomTo={1.1} focus="50% 45%" panX={0} />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(5,8,15,0.35), rgba(5,8,15,0.75))" }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 22 }}>
        <div style={{ fontFamily: theme.fonts.mono, fontSize: 64, fontWeight: 600, letterSpacing: "0.32em",
          color: theme.colors.primary, opacity: mark,
          transform: `scale(${interpolate(mark, [0, 1], [0.9, 1])}) translateY(${interpolate(mark, [0, 1], [24, 0])}px)`,
          textShadow: `0 0 ${40 * glowPulse}px ${theme.colors.glow}` }}>{WORDMARK}</div>
        <WordReveal text="먼저 말을 거는 개인 AI 비서" hero="먼저" delay={10} per={3}
          style={{ fontFamily: theme.fonts.display, fontSize: 40, fontWeight: 700, color: theme.colors.text,
            letterSpacing: "-0.02em", justifyContent: "center" }} />
        <Entrance delay={26} from={14}>
          <div style={{ fontFamily: theme.fonts.mono, fontSize: 15, letterSpacing: "0.34em",
            color: theme.colors.textDim, textTransform: "uppercase" }}>Web HUD</div>
        </Entrance>
      </AbsoluteFill>
    </SceneExit>
  );
};
