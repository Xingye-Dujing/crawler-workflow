import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_MONO, FONT_SERIF} from '../theme';
import {FontFaces} from './ui';
import type {Profile} from './Footage';
import {FlowGlyph} from './core';

export type ChapterCardProps = {
  profile: Profile;
  no: string;
  kicker: string;
  title: string;
  formula?: string;
  flow?: string[];
  body?: string;
  accent?: string;
  glyph?: 'flow' | 'none';
};

/** 一条由卡片与箭头组成的流程带：开头用图形讲流程，不再用一句话复述。 */
const FlowStrip: React.FC<{
  items: string[];
  accent: string;
  vertical: boolean;
  opacity: number;
}> = ({items, accent, vertical, opacity}) => (
  <div
    style={{
      display: 'flex',
      alignItems: 'stretch',
      flexWrap: vertical ? 'wrap' : 'nowrap',
      gap: vertical ? 12 : 0,
      opacity,
    }}
  >
    {items.map((item, i) => (
      <React.Fragment key={item}>
        <div
          style={{
            border: `1px solid ${C.border}`,
            background: 'rgba(255,255,255,0.86)',
            padding: vertical ? '14px 18px' : '16px 24px',
            fontFamily: FONT_SERIF,
            fontSize: vertical ? 30 : 38,
            lineHeight: 1.1,
            color: i === items.length - 1 ? accent : C.text,
            whiteSpace: 'nowrap',
          }}
        >
          {item}
        </div>
        {i < items.length - 1 ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: vertical ? 22 : 46,
              flexShrink: 0,
              color: C.faint,
              fontFamily: FONT_MONO,
              fontSize: vertical ? 28 : 38,
            }}
          >
            →
          </div>
        ) : null}
      </React.Fragment>
    ))}
  </div>
);

/** 概念转场卡：纯纸面，让录屏段落之间有一次干净的停顿 */
export const ChapterCard: React.FC<ChapterCardProps> = ({
  profile,
  no,
  kicker,
  title,
  formula,
  flow,
  body,
  accent = C.text,
  glyph = 'flow',
}) => {
  const frame = useCurrentFrame();
  const vertical = profile === 'douyin';

  const rise = (delay: number) =>
    interpolate(frame, [delay, delay + 18], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });

  const padX = vertical ? 72 : 150;
  const titleSize = vertical ? 76 : 100;

  return (
    <AbsoluteFill style={{background: C.bg}}>
      <FontFaces />

      {glyph === 'flow' ? (
        <FlowGlyph
          size={vertical ? 360 : 280}
          delay={4}
          duration={36}
          accent={accent}
          style={{
            position: 'absolute',
            right: vertical ? 60 : 150,
            top: vertical ? 190 : 82,
            opacity: 0.55,
          }}
        />
      ) : null}

      <div
        style={{
          position: 'absolute',
          top: vertical ? 214 : 74,
          left: padX,
          right: padX,
          display: 'flex',
          alignItems: 'baseline',
          gap: vertical ? 18 : 26,
          opacity: rise(2),
          fontFamily: FONT_MONO,
          fontSize: vertical ? 25 : 18,
          letterSpacing: '0.2em',
          color: C.dim,
        }}
      >
        <span style={{color: C.faint}}>{no}</span>
        <span
          style={{
            width: vertical ? 34 : 42,
            height: 2,
            background: accent,
            display: 'inline-block',
            transform: 'translateY(-4px)',
            opacity: 0.8,
          }}
        />
        <span>{kicker}</span>
      </div>

      <div
        style={{
          position: 'absolute',
          top: vertical ? 360 : 248,
          left: padX,
          right: padX,
          opacity: rise(8),
          transform: `translateY(${(1 - rise(8)) * 20}px)`,
          fontFamily: FONT_SERIF,
          fontSize: titleSize,
          lineHeight: 1.36,
          color: C.text,
          whiteSpace: 'pre-line',
        }}
      >
        {title}
      </div>

      {flow ? (
        <div
          style={{
            position: 'absolute',
            top: vertical ? 790 : 610,
            left: padX,
            right: padX,
          }}
        >
          <FlowStrip
            items={flow}
            accent={accent}
            vertical={vertical}
            opacity={rise(18)}
          />
        </div>
      ) : formula ? (
        <div
          style={{
            position: 'absolute',
            top: vertical ? 760 : 542,
            left: padX,
            right: padX,
            opacity: rise(18),
            padding: vertical ? '26px 30px' : '22px 32px',
            border: `1px solid ${C.border}`,
            background: 'rgba(255,255,255,0.84)',
            fontFamily: FONT_SERIF,
            fontSize: vertical ? 32 : 34,
            lineHeight: 1.6,
            color: C.text,
            whiteSpace: 'pre-line',
          }}
        >
          {formula}
        </div>
      ) : null}

      {body ? (
        <div
          style={{
            position: 'absolute',
            left: padX,
            right: padX,
            bottom: vertical ? 330 : 96,
            opacity: rise(flow || formula ? 28 : 20),
            fontFamily: FONT_SERIF,
            fontSize: vertical ? 40 : 30,
            lineHeight: 1.72,
            color: C.dim,
            whiteSpace: 'pre-line',
          }}
        >
          {body}
        </div>
      ) : null}

      <div
        style={{
          position: 'absolute',
          left: padX,
          right: padX,
          bottom: vertical ? 252 : 56,
          height: 1,
          background: C.border,
          opacity: 0.8,
        }}
      />
    </AbsoluteFill>
  );
};
