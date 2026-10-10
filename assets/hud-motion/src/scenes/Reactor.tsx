// 구체 클로즈업 — 녹화한 리액터가 대기 → 생각 → 도구 실행으로 바뀌는 동안 왼쪽 설명이 따라온다.
import React from "react";
import { AbsoluteFill, OffthreadVideo, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Caption } from "../components/Caption";
import { SceneExit } from "../components/motion";

const CAPTION_LEFT = 64;
const CAPTION_TOP = 150;
const CAPTION_WIDTH = 340;
const SPHERE = { left: 520, top: 28, size: 620 } as const;  // 정사각 소재(760x760)를 원형으로 자른다

export const Reactor: React.FC<{ startFromSec: number }> = ({ startFromSec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - 2, fps, config: theme.spring.smooth });
  return (
    <SceneExit>
      <AbsoluteFill>
        <div style={{ position: "absolute", left: SPHERE.left, top: SPHERE.top, width: SPHERE.size, height: SPHERE.size,
          borderRadius: "50%", overflow: "hidden", opacity: p,
          transform: `scale(${interpolate(p, [0, 1], [0.9, 1])})`,
          boxShadow: `0 0 90px ${theme.colors.glow}` }}>
          <OffthreadVideo src={staticFile("sphere.mp4")} startFrom={Math.round(startFromSec * fps)} muted
            style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
        <Caption kicker="00 · Reactor" title="상태가 구체에 보인다" hero="구체에" delay={8}
          lines={["대기: 천천히 돈다", "생각: 빨라지고 번진다", "실행: 눈금이 켜진다"]}
          style={{ left: CAPTION_LEFT, top: CAPTION_TOP, width: CAPTION_WIDTH }} />
      </AbsoluteFill>
    </SceneExit>
  );
};
