import { Composition } from "remotion";
import { HudPromo, PROMO_FRAMES, FPS, WIDTH, HEIGHT } from "./HudPromo";

export const Root: React.FC = () => (
  <Composition
    id="HudPromo"
    component={HudPromo}
    durationInFrames={PROMO_FRAMES}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
  />
);
