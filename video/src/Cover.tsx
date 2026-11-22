import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {C, FONT_LITERATA, FONT_MONO, FONT_SERIF} from './theme';
import {Label, Rule, Stage} from './components/core';
import {FontFaces} from './components/ui';

const NODE_LEGEND = [
  {label: '数据源', color: C.source},
  {label: '上传', color: C.upload},
  {label: '处理', color: C.process},
  {label: '分析', color: C.analysis},
  {label: '文献', color: C.biblio},
  {label: '可视化', color: C.visualize},
  {label: '编译', color: C.compile},
  {label: '输出', color: C.output},
];

export const Cover: React.FC = () => {
  return (
    <Stage>
      <FontFaces />

      <div
        style={{
          position: 'absolute',
          top: 64,
          left: 80,
          right: 80,
          display: 'flex',
          justifyContent: 'space-between',
          borderBottom: `1px solid ${C.border}`,
          paddingBottom: 18,
          fontFamily: FONT_MONO,
          fontSize: 16,
          letterSpacing: '0.18em',
          color: C.faint,
          textTransform: 'uppercase',
        }}
      >
        <span>A CANVAS FOR RESEARCH · 2026</span>
        <span>采析绘 · CAIXIHUI</span>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 120,
          top: 238,
          width: 980,
        }}
      >
        <Label color={C.faint}>从采集到成稿</Label>
        <div
          style={{
            marginTop: 26,
            fontFamily: FONT_SERIF,
            fontSize: 118,
            lineHeight: 1.24,
            color: C.text,
            whiteSpace: 'pre-line',
          }}
        >
          {'把研究画成一条路'}
        </div>
        <div
          style={{
            marginTop: 26,
            fontFamily: FONT_LITERATA,
            fontSize: 36,
            letterSpacing: '0.06em',
            color: C.dim,
          }}
        >
          画好之后，点一下就能跑。
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          right: 120,
          top: 250,
          width: 560,
        }}
      >
        <div
          style={{
            border: `1px solid ${C.borderStrong}`,
            background: C.paper,
            padding: 10,
            boxShadow: '0 18px 48px rgba(26,26,26,0.10)',
          }}
        >
          <Img
            src={staticFile('real/film/still-covernodes.png')}
            style={{width: '100%', height: 300, objectFit: 'cover', display: 'block'}}
          />
        </div>
        <div
          style={{
            marginTop: 18,
            fontFamily: FONT_MONO,
            fontSize: 16,
            lineHeight: 1.8,
            color: C.faint,
            textAlign: 'right',
            letterSpacing: '0.04em',
          }}
        >
          节点连成流程 · 中断处接着跑
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 120,
          right: 120,
          bottom: 168,
        }}
      >
        <Rule delay={-20} duration={1} color={C.border} />
        <div
          style={{
            marginTop: 22,
            display: 'flex',
            gap: 28,
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          {NODE_LEGEND.map((item) => (
            <span
              key={item.label}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                fontFamily: FONT_MONO,
                fontSize: 15,
                letterSpacing: '0.08em',
                color: C.dim,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  background: item.color,
                  display: 'inline-block',
                }}
              />
              {item.label}
            </span>
          ))}
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 80,
          right: 80,
          bottom: 52,
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: FONT_MONO,
          fontSize: 14,
          letterSpacing: '0.16em',
          color: C.faint,
          textTransform: 'uppercase',
        }}
      >
        <span>github.com/Xingye-Dujing/crawler-workflow</span>
        <span style={{display: 'flex', gap: 18}}>
          <span>1920 × 1080</span>
          <span>采析绘</span>
        </span>
      </div>
    </Stage>
  );
};
