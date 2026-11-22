import React from 'react';
import {staticFile} from 'remotion';

/* 三套字：正文用霞鹜文楷（中文）/ Literata（拉丁），标签用 APL385。
   字体随 public/fonts 提交，渲染时不依赖本机字体。 */
export const FontFaces: React.FC = () => {
  return (
    <style>{`
      @font-face {
        font-family: 'APL385 Unicode';
        src: url('${staticFile('fonts/APL385.ttf')}') format('truetype');
        font-display: block;
      }
      @font-face {
        font-family: 'LXGW WenKai GB';
        src: url('${staticFile('fonts/LXGWWenKaiGB-Subset.ttf')}') format('truetype');
        font-display: block;
        font-weight: 400;
      }
      @font-face {
        font-family: 'Literata';
        font-style: normal;
        font-weight: 400;
        src: url('${staticFile('fonts/literata-normal-latin.woff2')}') format('woff2');
        font-display: block;
      }
      @font-face {
        font-family: 'Literata';
        font-style: italic;
        font-weight: 400;
        src: url('${staticFile('fonts/literata-italic-latin.woff2')}') format('woff2');
        font-display: block;
      }
    `}</style>
  );
};
