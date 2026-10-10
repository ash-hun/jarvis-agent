// BODY 의 한 비트 — 왼쪽 설명, 오른쪽에 그 기능이 보이는 HUD 화면.
import React from "react";
import { AbsoluteFill } from "remotion";
import { Caption } from "../components/Caption";
import { Screen } from "../components/Screen";
import { SceneExit } from "../components/motion";

const CAPTION_LEFT = 64;
const CAPTION_TOP = 150;
const CAPTION_WIDTH = 330;
const SCREEN = { left: 440, top: 52, width: 700, height: 571 } as const;  // 16:9 보다 세로를 약간 더 — 대화 열이 길다

export type FeatureProps = {
  kicker: string;
  title: string;
  hero?: string;
  lines: string[];
  shot: string;
  focus: string;
  zoomFrom: number;
  zoomTo: number;
};

export const Feature: React.FC<FeatureProps> = ({ kicker, title, hero, lines, shot, focus, zoomFrom, zoomTo }) => (
  <SceneExit>
    <AbsoluteFill>
      <Screen src={shot} focus={focus} zoomFrom={zoomFrom} zoomTo={zoomTo} delay={2} style={SCREEN} />
      <Caption kicker={kicker} title={title} hero={hero} lines={lines} delay={8}
        style={{ left: CAPTION_LEFT, top: CAPTION_TOP, width: CAPTION_WIDTH }} />
    </AbsoluteFill>
  </SceneExit>
);
