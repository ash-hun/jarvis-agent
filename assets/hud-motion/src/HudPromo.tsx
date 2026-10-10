// 합성 — 장면 순서와 길이. 모든 길이는 fps 에서 유도한다.
import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { loadFont as loadNotoSansKR } from "@remotion/google-fonts/NotoSansKR";
import { loadFont as loadJetBrainsMono } from "@remotion/google-fonts/JetBrainsMono";
import { BgMesh, Grade, Vignette } from "./components/layers";
import { Intro } from "./scenes/Intro";
import { Feature, FeatureProps } from "./scenes/Feature";
import { Outro } from "./scenes/Outro";

loadNotoSansKR("normal", { weights: ["700"], subsets: ["korean", "latin"], ignoreTooManyRequestsWarning: true });
loadJetBrainsMono("normal", { weights: ["400", "600"], subsets: ["latin"] });

export const FPS = 30;
export const WIDTH = 1200;
export const HEIGHT = 675;

const sec = (s: number) => Math.round(s * FPS);
const OVERLAP = sec(0.25);  // 앞 장면의 퇴장과 다음 장면의 등장이 겹치는 구간

const FEATURES: FeatureProps[] = [
  {
    kicker: "01 · Request",
    title: "묻기 전에 먼저 생각한다",
    hero: "생각한다",
    lines: ["💭 내적 사고 한 줄이 응답 앞에", "도구 실행은 흔적으로 남는다", "승인 없이 돌아가는 건 읽기뿐"],
    shot: "hud_tool.png", focus: "100% 88%", zoomFrom: 1.5, zoomTo: 1.6,
  },
  {
    kicker: "02 · Answer",
    title: "응답은 마크다운, 비용은 숫자로",
    hero: "숫자로",
    lines: ["목록·코드블록·강조 그대로", "토큰과 비용이 턴마다 쌓인다", "큰 코드블록은 패널로 빠진다"],
    shot: "hud_answer.png", focus: "100% 62%", zoomFrom: 1.6, zoomTo: 1.5,
  },
  {
    kicker: "03 · Proactive",
    title: "열린 약속을 보고 먼저 말을 건다",
    hero: "먼저",
    lines: ["성찰 데몬이 2분마다 돌아본다", "🔔 도움이 됐나요? 네 / 아니오", "답이 임계치를 학습한다"],
    shot: "hud_proactive.png", focus: "100% 96%", zoomFrom: 1.5, zoomTo: 1.6,
  },
  {
    kicker: "04 · Approval",
    title: "위험한 건 묻고, 한 번 답하면 기억한다",
    hero: "기억한다",
    lines: ["bash 는 실행 전 승인", "ALWAYS 한 번이면 다음엔 통과", "규칙은 approvals.yaml 에"],
    shot: "hud_approval.png", focus: "50% 50%", zoomFrom: 1.22, zoomTo: 1.3,
  },
];

const INTRO = sec(2.8);
const FEATURE = sec(3.6);
const OUTRO = sec(3.0);

export const PROMO_FRAMES = INTRO + FEATURES.length * (FEATURE - OVERLAP) + OUTRO;

export const HudPromo: React.FC = () => {
  let cursor = 0;
  const at = (len: number) => { const from = cursor; cursor += len - OVERLAP; return from; };
  return (
    <AbsoluteFill>
      <BgMesh />
      <Sequence from={at(INTRO)} durationInFrames={INTRO}><Intro /></Sequence>
      {FEATURES.map((f) => (
        <Sequence key={f.kicker} from={at(FEATURE)} durationInFrames={FEATURE}><Feature {...f} /></Sequence>
      ))}
      <Sequence from={cursor} durationInFrames={OUTRO}><Outro /></Sequence>
      <Grade />
      {/* ponytail: 그레인 층 생략. 프레임마다 바뀌는 노이즈가 GIF 압축을 깨 44MB 가 된다. mp4 로 바꾸면 되살린다 */}
      <Vignette />
    </AbsoluteFill>
  );
};
