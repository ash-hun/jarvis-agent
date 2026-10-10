// 장면 설명 패널 — 제목 한 줄(한 단어만 강조)과 짧은 줄 몇 개가 엇갈려 들어온다.
import React from "react";
import { theme } from "../theme";
import { Entrance, WordReveal } from "./motion";

const TITLE_SIZE = 44;
const LINE_SIZE = 20;
const LINE_STAGGER = 5;

export const Caption: React.FC<{
  kicker: string;
  title: string;
  hero?: string;
  lines: string[];
  delay?: number;
  style?: React.CSSProperties;
}> = ({ kicker, title, hero, lines, delay = 0, style }) => (
  <div style={{ position: "absolute", display: "flex", flexDirection: "column", gap: 14, ...style }}>
    <Entrance delay={delay} from={18}>
      <div style={{ fontFamily: theme.fonts.mono, fontSize: 13, letterSpacing: "0.3em",
        color: theme.colors.textDim, textTransform: "uppercase" }}>{kicker}</div>
    </Entrance>
    <WordReveal text={title} hero={hero} delay={delay + 4} per={3}
      style={{ fontFamily: theme.fonts.display, fontSize: TITLE_SIZE, fontWeight: 700,
        letterSpacing: "-0.02em", lineHeight: 1.15, color: theme.colors.text }} />
    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
      {lines.map((line, i) => (
        <Entrance key={i} delay={delay + 14 + i * LINE_STAGGER} from={16}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, fontFamily: theme.fonts.mono,
            fontSize: LINE_SIZE, color: theme.colors.textDim, lineHeight: 1.4 }}>
            <span style={{ width: 18, height: 1, background: theme.colors.textDim, flexShrink: 0 }} />
            <span>{line}</span>
          </div>
        </Entrance>
      ))}
    </div>
  </div>
);
