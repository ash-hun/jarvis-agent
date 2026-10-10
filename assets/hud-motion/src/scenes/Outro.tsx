// CTA — 한 줄 명령. 워드마크는 숨 쉬고, 명령 한 줄만 빛난다.
import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Entrance, WordReveal } from "../components/motion";

const COMMAND = "docker compose --profile web up -d";
const URL = "http://localhost:7777";

export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame, fps, config: theme.spring.smooth });
  const breathe = 1 + Math.sin(frame / 24) * 0.012;
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 26 }}>
      <div style={{ fontFamily: theme.fonts.mono, fontSize: 30, letterSpacing: "0.34em", color: theme.colors.textDim,
        opacity: p, transform: `scale(${interpolate(p, [0, 1], [0.92, 1]) * breathe})` }}>J.A.R.V.I.S.</div>
      <WordReveal text="한 줄이면 뜬다" hero="한" delay={8}
        style={{ fontFamily: theme.fonts.display, fontSize: 40, fontWeight: 700, color: theme.colors.text,
          letterSpacing: "-0.02em", justifyContent: "center" }} />
      <Entrance delay={20} from={16}>
        <div style={{ fontFamily: theme.fonts.mono, fontSize: 22, color: theme.colors.text,
          padding: "14px 26px", borderRadius: 10, border: `1px solid ${theme.colors.hairline}`,
          background: theme.colors.bgAlt }}>
          <span style={{ color: theme.colors.textDim }}>$ </span>{COMMAND}
        </div>
      </Entrance>
      <Entrance delay={30} from={12}>
        <div style={{ fontFamily: theme.fonts.mono, fontSize: 16, letterSpacing: "0.12em", color: theme.colors.textDim }}>{URL}</div>
      </Entrance>
    </AbsoluteFill>
  );
};
