import React from 'react';
import {
  AbsoluteFill,
  Img,
  interpolate,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {C, FONT_MONO, FONT_SERIF} from '../theme';
import {FontFaces} from './ui';

export type Profile = 'bili' | 'douyin';

/** 归一化焦点：素材是 16:9 全屏帧时才可用的固定取景（x/y 居中点，zoom 倍数）。 */
export type Focus = {x: number; y: number; zoom: number};

export type Caption = {
  zh: string;
};

type Chrome = {
  padX: number;
  barBottom: number;
  barPadV: number;
  barPadH: number;
  captionFont: number;
};

/* 画面铺满整帧，讲解文字压成底部一行细条：占面积极小，几乎不压住演示内容。
 * 局部在采集端已裁成 16:9，铺满时既不缩小也不裁掉内容。 */
const BILI: Chrome = {
  padX: 72,
  barBottom: 40,
  barPadV: 12,
  barPadH: 22,
  captionFont: 34,
};

const DOUYIN: Chrome = {
  padX: 48,
  barBottom: 100,
  barPadV: 18,
  barPadH: 26,
  captionFont: 40,
};

const Screen: React.FC<{
  focus?: Focus;
  children: React.ReactNode;
}> = ({focus, children}) => {
  const z = focus?.zoom ?? 1;
  if (z <= 1) {
    return (
      <AbsoluteFill>
        <div style={{width: '100%', height: '100%', display: 'flex'}}>{children}</div>
      </AbsoluteFill>
    );
  }
  const cx = focus?.x ?? 0.5;
  const cy = focus?.y ?? 0.5;
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <div
        style={{
          position: 'absolute',
          left: `${50 - cx * z * 100}%`,
          top: `${50 - cy * z * 100}%`,
          width: `${z * 100}%`,
          height: `${z * 100}%`,
        }}
      >
        {children}
      </div>
    </AbsoluteFill>
  );
};

const CaptionCard: React.FC<{
  chrome: Chrome;
  caption: Caption[];
  frame: number;
  reveal: boolean;
}> = ({chrome, caption, frame, reveal}) => {
  const text = caption.map((line) => line.zh).join('  ·  ');
  const appear = reveal
    ? interpolate(frame, [0, 14], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      })
    : 1;
  return (
    <div
      style={{
        position: 'absolute',
        left: chrome.padX,
        bottom: chrome.barBottom,
        maxWidth: 'calc(100% - ' + chrome.padX * 2 + 'px)',
        padding: `${chrome.barPadV}px ${chrome.barPadH}px`,
        background: 'rgba(251,251,249,0.94)',
        border: `1px solid ${C.border}`,
        borderRadius: 3,
        boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
        opacity: appear,
        transform: `translateY(${(1 - appear) * 10}px)`,
        fontFamily: FONT_SERIF,
        fontSize: chrome.captionFont,
        lineHeight: 1.25,
        color: C.text,
        whiteSpace: 'nowrap',
      }}
    >
      {text}
    </div>
  );
};

export type FootageProps = {
  profile: Profile;
  scene: string;
  caption: Caption[];
  startFrom?: number;
  speed?: number;
  focus?: Focus;
};

/** Real browser footage with Chinese subtitles. */
export const Footage: React.FC<FootageProps> = ({
  profile,
  scene,
  caption,
  startFrom = 0,
  speed = 1,
  focus,
}) => {
  const frame = useCurrentFrame();
  const chrome = profile === 'douyin' ? DOUYIN : BILI;

  return (
    <AbsoluteFill style={{background: C.bg}}>
      <FontFaces />
      <Screen focus={focus}>
        <OffthreadVideo
          src={staticFile(`real/film/clip-${scene}.mp4`)}
          startFrom={Math.round(startFrom * 30)}
          playbackRate={speed}
          muted
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      </Screen>
      <CaptionCard chrome={chrome} caption={caption} frame={frame} reveal />
    </AbsoluteFill>
  );
};

export type StillProps = {
  profile: Profile;
  image: string;
  dir?: string;
  caption: Caption[];
  fit?: 'cover' | 'contain';
  focus?: Focus;
};

/** A page still, shown full-frame; the crop is prepared at capture time. */
export const StillFootage: React.FC<StillProps> = ({
  profile,
  image,
  dir = 'film',
  caption,
  fit = 'cover',
  focus,
}) => {
  const frame = useCurrentFrame();
  const chrome = profile === 'douyin' ? DOUYIN : BILI;

  return (
    <AbsoluteFill style={{background: C.paper}}>
      <FontFaces />
      <Screen focus={focus}>
        <Img
          src={staticFile(`real/${dir}/${image}`)}
          style={{width: '100%', height: '100%', objectFit: fit}}
        />
      </Screen>
      <CaptionCard chrome={chrome} caption={caption} frame={frame} reveal={false} />
    </AbsoluteFill>
  );
};
