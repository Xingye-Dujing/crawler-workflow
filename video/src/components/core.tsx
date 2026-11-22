import React, {ReactNode} from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
} from 'remotion';
import {C, EASE, FONT_LITERATA, FONT_MONO, FONT_SERIF} from '../theme';

const ease = Easing.bezier(EASE[0], EASE[1], EASE[2], EASE[3]);

export const clamp = {
  extrapolateLeft: 'clamp',
  extrapolateRight: 'clamp',
} as const;

export const inOut = (frame: number, start: number, duration: number) => {
  return interpolate(frame, [start, start + duration], [0, 1], {
    ...clamp,
    easing: ease,
  });
};

export const fadeInOut = (
  frame: number,
  duration: number,
  inDuration = 18,
  outDuration = 18,
) => {
  const fadeIn = interpolate(frame, [0, inDuration], [0, 1], {
    ...clamp,
    easing: ease,
  });
  const fadeOut = interpolate(
    frame,
    [duration - outDuration, duration],
    [1, 0],
    {...clamp, easing: ease},
  );
  return Math.min(fadeIn, fadeOut);
};

export const Reveal: React.FC<{
  children: ReactNode;
  delay?: number;
  duration?: number;
  y?: number;
  x?: number;
  blur?: number;
  style?: React.CSSProperties;
}> = ({children, delay = 0, duration = 24, y = 22, x = 0, blur = 0, style}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + duration], [0, 1], {
    ...clamp,
    easing: ease,
  });
  return (
    <div
      style={{
        opacity: p,
        transform: `translate3d(${(1 - p) * x}px, ${(1 - p) * y}px, 0)`,
        filter: blur ? `blur(${(1 - p) * blur}px)` : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const Rule: React.FC<{
  delay?: number;
  duration?: number;
  color?: string;
  thickness?: number;
  style?: React.CSSProperties;
}> = ({delay = 0, duration = 34, color = C.borderStrong, thickness = 1, style}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + duration], [0, 1], {
    ...clamp,
    easing: ease,
  });
  return (
    <svg
      width="100%"
      height={thickness}
      viewBox="0 0 100 1"
      preserveAspectRatio="none"
      style={{display: 'block', overflow: 'visible', ...style}}
    >
      <line
        x1={0}
        y1={0.5}
        x2={100 * p}
        y2={0.5}
        stroke={color}
        strokeWidth={thickness}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
};

/* 一条被画出来的工作流：五个节点、一条分叉、一条汇合。
   和画布一样，它只画结构，不解释数据。 */
export const FlowGlyph: React.FC<{
  size?: number;
  delay?: number;
  duration?: number;
  accent?: string;
  style?: React.CSSProperties;
}> = ({size = 300, delay = 0, duration = 34, accent = C.text, style}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + duration], [0, 1], {
    ...clamp,
    easing: ease,
  });
  const nodes = [
    {x: 8, y: 26, w: 46, h: 18},
    {x: 78, y: 8, w: 46, h: 18},
    {x: 78, y: 44, w: 46, h: 18},
    {x: 148, y: 26, w: 46, h: 18},
    {x: 218, y: 26, w: 46, h: 18},
  ];
  // Every wire joins two nodes: one source fans out to two parallel boxes,
  // they merge into one, then reach the output. No wire ends on empty space.
  const wires = [
    'M54 35 C66 35 66 17 78 17',
    'M54 35 C66 35 66 53 78 53',
    'M124 17 C136 17 136 35 148 35',
    'M124 53 C136 53 136 35 148 35',
    'M194 35 H218',
  ];
  return (
    <svg
      viewBox="0 0 272 70"
      style={{
        width: size,
        display: 'block',
        overflow: 'visible',
        opacity: 0.9,
        ...style,
      }}
    >
      {wires.map((d, i) => (
        <path
          key={i}
          d={d}
          fill="none"
          stroke={C.borderStrong}
          strokeWidth={1.1}
          strokeDasharray="240"
          strokeDashoffset={240 * (1 - p)}
        />
      ))}
      {nodes.map((n, i) => {
        const appear = interpolate(
          frame,
          [delay + i * 5, delay + i * 5 + 16],
          [0, 1],
          clamp,
        );
        return (
          <g key={i} opacity={appear}>
            <rect
              x={n.x}
              y={n.y}
              width={n.w}
              height={n.h}
              fill={C.bg}
              stroke={i === 3 ? accent : C.borderStrong}
              strokeWidth={i === 3 ? 1.3 : 1}
            />
            <line
              x1={n.x}
              y1={n.y}
              x2={n.x + 3}
              y2={n.y}
              stroke={i === 3 ? accent : C.text}
              strokeWidth={2}
            />
          </g>
        );
      })}
    </svg>
  );
};

export const Typewriter: React.FC<{
  text: string;
  delay?: number;
  speed?: number;
  style?: React.CSSProperties;
  cursor?: boolean;
  cursorColor?: string;
}> = ({text, delay = 0, speed = 1.1, style, cursor = true, cursorColor = C.text}) => {
  const frame = useCurrentFrame();
  const count = Math.max(
    0,
    Math.min(text.length, Math.floor(Math.max(0, frame - delay) * speed)),
  );
  const visible = text.slice(0, count);
  const done = count >= text.length;
  const blink = Math.floor(frame / 9) % 2 === 0;
  return (
    <span style={{whiteSpace: 'pre-wrap', ...style}}>
      {visible}
      {cursor && (!done || blink) ? (
        <span style={{color: cursorColor, opacity: done && !blink ? 0 : 1}}>▌</span>
      ) : null}
    </span>
  );
};

export const Label: React.FC<{
  children: ReactNode;
  color?: string;
  style?: React.CSSProperties;
}> = ({children, color = C.dim, style}) => (
  <div
    style={{
      fontFamily: FONT_MONO,
      fontSize: 15,
      letterSpacing: '0.22em',
      textTransform: 'uppercase',
      color,
      lineHeight: 1.4,
      ...style,
    }}
  >
    {children}
  </div>
);

export const Pill: React.FC<{
  children: ReactNode;
  active?: boolean;
  style?: React.CSSProperties;
}> = ({children, active = false, style}) => (
  <span
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      border: `1px solid ${active ? C.borderStrong : C.border}`,
      color: active ? C.text : C.dim,
      fontFamily: FONT_MONO,
      fontSize: 18,
      lineHeight: 1,
      padding: '10px 14px 11px',
      borderRadius: 2,
      whiteSpace: 'nowrap',
      ...style,
    }}
  >
    {children}
  </span>
);

export const Panel: React.FC<{
  children: ReactNode;
  style?: React.CSSProperties;
  padding?: number | string;
}> = ({children, style, padding = 28}) => (
  <div
    style={{
      border: `1px solid ${C.border}`,
      background: C.paper,
      borderRadius: 2,
      padding,
      ...style,
    }}
  >
    {children}
  </div>
);

export const CodeLine: React.FC<{
  children: ReactNode;
  size?: number;
  color?: string;
  style?: React.CSSProperties;
}> = ({children, size = 30, color = C.text, style}) => (
  <div
    style={{
      fontFamily: FONT_MONO,
      fontSize: size,
      lineHeight: 1.8,
      color,
      whiteSpace: 'pre',
      ...style,
    }}
  >
    {children}
  </div>
);

export const CodeBlock: React.FC<{
  lines: ReactNode[];
  size?: number;
  color?: string;
  gap?: number;
  style?: React.CSSProperties;
}> = ({lines, size = 30, color = C.text, gap = 0, style}) => (
  <div style={{display: 'flex', flexDirection: 'column', gap, ...style}}>
    {lines.map((line, i) => (
      <CodeLine key={i} size={size} color={color}>
        {line}
      </CodeLine>
    ))}
  </div>
);

export const Stage: React.FC<{
  children: ReactNode;
  grid?: boolean;
  style?: React.CSSProperties;
}> = ({children, grid = true, style}) => (
  <AbsoluteFill
    style={{
      background: C.bg,
      color: C.text,
      fontFamily: FONT_SERIF,
      overflow: 'hidden',
      ...style,
    }}
  >
    {grid ? (
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `linear-gradient(to right, ${C.wash} 1px, transparent 1px), linear-gradient(to bottom, ${C.wash} 1px, transparent 1px)`,
          backgroundSize: '96px 96px',
          maskImage:
            'radial-gradient(ellipse at 50% 45%, black 0%, black 58%, transparent 100%)',
        }}
      />
    ) : null}
    <div style={{position: 'absolute', inset: 0}}>{children}</div>
  </AbsoluteFill>
);

export const SceneMeta: React.FC<{
  chapter: string;
  index: string;
  right?: string;
}> = ({chapter, index, right = 'CAIXIHUI   采析绘'}) => (
  <>
    <div
      style={{
        position: 'absolute',
        top: 56,
        left: 80,
        right: 80,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        borderBottom: `1px solid ${C.border}`,
        paddingBottom: 18,
        color: C.faint,
        fontFamily: FONT_MONO,
        fontSize: 15,
        letterSpacing: '0.18em',
        textTransform: 'uppercase',
      }}
    >
      <span style={{display: 'flex', gap: 18, alignItems: 'baseline'}}>
        <span>{index}</span>
        <span>{chapter}</span>
      </span>
      <span>{right}</span>
    </div>
    <div
      style={{
        position: 'absolute',
        bottom: 48,
        left: 80,
        right: 80,
        display: 'flex',
        justifyContent: 'space-between',
        color: C.faint,
        fontFamily: FONT_MONO,
        fontSize: 14,
        letterSpacing: '0.16em',
        textTransform: 'uppercase',
      }}
    >
      <span>采析绘 · A CANVAS FOR RESEARCH</span>
      <span>采集 → 清洗 → 分析 → 可视化 → 成稿</span>
    </div>
  </>
);

export const Kicker: React.FC<{
  children: ReactNode;
  delay?: number;
}> = ({children, delay = 0}) => (
  <Reveal delay={delay} y={10} duration={18}>
    <Label color={C.faint}>{children}</Label>
  </Reveal>
);

export const Display: React.FC<{
  children: ReactNode;
  size?: number;
  style?: React.CSSProperties;
}> = ({children, size = 82, style}) => (
  <div
    style={{
      fontFamily: FONT_SERIF,
      fontSize: size,
      lineHeight: 1.28,
      fontWeight: 400,
      letterSpacing: '0.01em',
      ...style,
    }}
  >
    {children}
  </div>
);

export const Latin: React.FC<{
  children: ReactNode;
  size?: number;
  style?: React.CSSProperties;
}> = ({children, size = 82, style}) => (
  <div
    style={{
      fontFamily: FONT_LITERATA,
      fontSize: size,
      lineHeight: 1.2,
      fontWeight: 400,
      letterSpacing: '-0.01em',
      ...style,
    }}
  >
    {children}
  </div>
);
