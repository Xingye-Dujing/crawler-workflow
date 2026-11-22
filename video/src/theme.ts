export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

/* 采析绘的纸面/墨色令牌，直接取自 backend/static/css/base.css：
 * paper white、#1a1a1a ink，节点类型各有一个低饱和强调色。 */
export const C = {
  bg: '#fbfbf9',
  paper: '#ffffff',
  text: '#1a1a1a',
  dim: 'rgba(26,26,26,0.52)',
  faint: 'rgba(26,26,26,0.26)',
  border: 'rgba(26,26,26,0.14)',
  borderStrong: 'rgba(26,26,26,0.42)',
  wash: 'rgba(26,26,26,0.045)',
  dark: '#14161b',
  darkPaper: '#1c2027',
  darkText: '#e7e5df',
  darkDim: 'rgba(231,229,223,0.52)',
  darkFaint: 'rgba(231,229,223,0.22)',
  darkBorder: 'rgba(231,229,223,0.18)',
  darkBorderStrong: 'rgba(231,229,223,0.44)',
  ok: '#4e8061',
  err: '#a85454',
  warn: '#9a7740',
  source: '#4a6fa5',
  upload: '#4a8fa5',
  process: '#a85454',
  analysis: '#9a7740',
  biblio: '#3d7a72',
  visualize: '#4e8061',
  compile: '#3d6b6b',
  output: '#6f7f8a',
  accent: '#9a7740',
} as const;

export const FONT_SERIF =
  '"LXGW WenKai GB", "Literata", "Songti SC", "SimSun", serif';
export const FONT_LITERATA = '"Literata", Georgia, "Times New Roman", serif';
export const FONT_MONO =
  '"APL385 Unicode", "LXGW WenKai GB", "Cascadia Mono", Consolas, monospace';

export const EASE = [0.16, 1, 0.3, 1] as const;

export const CHAPTER_ACCENTS = {
  intro: C.text,
  canvas: C.source,
  data: C.upload,
  parameters: C.analysis,
  run: C.process,
  graph: C.biblio,
  timeline: C.visualize,
  records: C.compile,
  resume: C.warn,
  report: C.analysis,
  ai: C.source,
  ending: C.text,
} as const;

export type ChapterKey = keyof typeof CHAPTER_ACCENTS;
