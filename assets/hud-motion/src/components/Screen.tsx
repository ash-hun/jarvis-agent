// HUD 스크린샷을 둥근 카드에 담아 Ken Burns 로 보여준다. 카드 자체는 느리게 숨 쉰다.
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { KenBurns } from "./motion";

export const Screen: React.FC<{
  src: string;
  focus?: string;
  zoomFrom?: number;
  zoomTo?: number;
  delay?: number;
  style?: React.CSSProperties;
}> = ({ src, focus, zoomFrom, zoomTo, delay = 0, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: theme.spring.smooth });
  // ponytail: 카드 숨쉬기(sin 스케일·부유) 생략. 화면의 58% 가 매 프레임 바뀌어 GIF 가 2배로 는다. mp4 로 바꾸면 되살린다
  const breathe = 1;
  const float = 0;
  return (
    <div
      style={{
        position: "absolute",
        overflow: "hidden",
        borderRadius: 18,
        border: `1px solid ${theme.colors.hairline}`,
        boxShadow: "0 40px 90px -30px rgba(0,0,0,0.75)",
        opacity: p,
        transform: `translateY(${interpolate(p, [0, 1], [50, 0]) + float}px) scale(${interpolate(p, [0, 1], [0.95, 1]) * breathe})`,
        ...style,
      }}
    >
      <KenBurns src={src} focus={focus} zoomFrom={zoomFrom} zoomTo={zoomTo} />
    </div>
  );
};
