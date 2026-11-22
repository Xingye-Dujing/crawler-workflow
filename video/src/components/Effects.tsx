import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_MONO, FONT_SERIF} from '../theme';

/** 叠加在画面上的“重点突出”动效。位置用归一化坐标（0..1）。 */
export type Effect =
  | {
      kind: 'spotlight';
      x: number;
      y: number;
      w: number;
      h: number;
      delay?: number;
      label?: string;
    }
  | {
      kind: 'callout';
      x: number;
      y: number;
      text: string;
      delay?: number;
      accent?: string;
    }
  | {
      kind: 'step';
      index: number;
      text: string;
      delay?: number;
      accent?: string;
    };

const ease = (f: number, a: number, b: number) =>
  interpolate(f, [a, b], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

/** 聚焦框：四块半透明遮罩挖出一个矩形亮区，描边随时间轻微呼吸。
 *  它叠在画面上但不遮挡被框住的内容——框内是全透明。 */
const Spotlight: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  delay: number;
  label?: string;
}> = ({x, y, w, h, delay, label}) => {
  const frame = useCurrentFrame();
  const p = ease(frame, delay, delay + 16);
  const breathe = 1 + Math.sin(frame / 22) * 0.012;
  const left = (x - w / 2) * 100;
  const top = (y - h / 2) * 100;
  const ww = w * 100 * breathe;
  const hh = h * 100 * breathe;
  const dim = 'rgba(20,21,24,0.42)';
  const edge = 3;
  return (
    <div style={{position: 'absolute', inset: 0, opacity: p, pointerEvents: 'none'}}>
      <div style={{position: 'absolute', left: 0, top: 0, width: '100%', height: `${top}%`, background: dim}} />
      <div style={{position: 'absolute', left: 0, top: `${top + hh}%`, width: '100%', bottom: 0, background: dim}} />
      <div style={{position: 'absolute', left: 0, top: `${top}%`, width: `${left}%`, height: `${hh}%`, background: dim}} />
      <div style={{position: 'absolute', left: `${left + ww}%`, top: `${top}%`, right: 0, height: `${hh}%`, background: dim}} />
      <div
        style={{
          position: 'absolute',
          left: `${left}%`,
          top: `${top}%`,
          width: `${ww}%`,
          height: `${hh}%`,
          border: `${edge}px solid ${C.bg}`,
          boxShadow: `0 0 0 2px rgba(26,26,26,0.5), 0 0 40px rgba(0,0,0,0.25)`,
          borderRadius: 2,
        }}
      />
      {label ? (
        <div
          style={{
            position: 'absolute',
            left: `${left}%`,
            top: `calc(${top}% - 40px)`,
            background: C.bg,
            color: C.text,
            fontFamily: FONT_MONO,
            fontSize: 18,
            letterSpacing: '0.12em',
            padding: '6px 12px',
            border: `1px solid ${C.borderStrong}`,
            whiteSpace: 'nowrap',
          }}
        >
          {label}
        </div>
      ) : null}
    </div>
  );
};

/** 重点标注：一张小卡贴在画面指定处，带一条短引线。 */
const Callout: React.FC<{
  x: number;
  y: number;
  text: string;
  delay: number;
  accent: string;
}> = ({x, y, text, delay, accent}) => {
  const frame = useCurrentFrame();
  const p = ease(frame, delay, delay + 14);
  return (
    <div
      style={{
        position: 'absolute',
        left: `${x * 100}%`,
        top: `${y * 100}%`,
        opacity: p,
        transform: `translateY(${(1 - p) * 12}px)`,
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: -14,
          width: 2,
          height: 14,
          background: accent,
        }}
      />
      <div
        style={{
          background: C.bg,
          border: `1px solid ${C.borderStrong}`,
          padding: '10px 14px',
          fontFamily: FONT_SERIF,
          fontSize: 26,
          color: C.text,
          whiteSpace: 'nowrap',
          boxShadow: '0 6px 24px rgba(0,0,0,0.12)',
        }}
      >
        {text}
      </div>
    </div>
  );
};

/** 步骤徽标：右上角一个序号圆点 + 文案，逐帧出现。 */
const Step: React.FC<{
  index: number;
  text: string;
  delay: number;
  accent: string;
}> = ({index, text, delay, accent}) => {
  const frame = useCurrentFrame();
  const p = ease(frame, delay, delay + 12);
  return (
    <div
      style={{
        position: 'absolute',
        top: 96,
        right: 72,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        opacity: p,
        transform: `translateY(${(1 - p) * -10}px)`,
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          border: `2px solid ${accent}`,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: FONT_MONO,
          fontSize: 20,
          color: accent,
          background: C.bg,
        }}
      >
        {String(index).padStart(2, '0')}
      </div>
      <div
        style={{
          fontFamily: FONT_MONO,
          fontSize: 18,
          letterSpacing: '0.12em',
          color: C.text,
          background: 'rgba(251,251,249,0.9)',
          padding: '6px 10px',
        }}
      >
        {text}
      </div>
    </div>
  );
};

/** 把一组动效叠到画面上。 */
export const EffectsLayer: React.FC<{effects: Effect[]}> = ({effects}) => {
  if (!effects?.length) return null;
  return (
    <div style={{position: 'absolute', inset: 0, zIndex: 5, pointerEvents: 'none'}}>
      {effects.map((e, i) => {
        if (e.kind === 'spotlight') {
          return (
            <Spotlight
              key={i}
              x={e.x}
              y={e.y}
              w={e.w}
              h={e.h}
              delay={e.delay ?? 18}
              label={e.label}
            />
          );
        }
        if (e.kind === 'callout') {
          return (
            <Callout
              key={i}
              x={e.x}
              y={e.y}
              text={e.text}
              delay={e.delay ?? 24}
              accent={e.accent ?? C.text}
            />
          );
        }
        return (
          <Step
            key={i}
            index={e.index}
            text={e.text}
            delay={e.delay ?? 14}
            accent={e.accent ?? C.text}
          />
        );
      })}
    </div>
  );
};
