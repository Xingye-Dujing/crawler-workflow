import React from 'react';
import {AbsoluteFill, interpolate, Sequence, useCurrentFrame} from 'remotion';
import {C, FPS} from './theme';
import {Footage, StillFootage, type Caption, type Focus, type Profile} from './components/Footage';
import {ChapterCard} from './components/ChapterCard';
import {EffectsLayer, type Effect} from './components/Effects';
import {FontFaces} from './components/ui';

type Base = {
  seconds: number;
  no: string;
  effects?: Effect[];
};

type CardSegment = Base & {
  kind: 'card';
  kicker: string;
  title: string;
  formula?: string;
  flow?: string[];
  body?: string;
  accent?: string;
  glyph?: 'flow' | 'none';
};

type ClipSegment = Base & {
  kind: 'clip';
  scene: string;
  chapter: string;
  caption: Caption[];
  accent?: string;
  startFrom?: number;
  speed?: number;
  focus?: Focus;
};

type StillSegment = Base & {
  kind: 'still';
  image: string;
  dir?: string;
  chapter: string;
  caption: Caption[];
  accent?: string;
  fit?: 'cover' | 'contain';
  focus?: Focus;
};

type Segment = CardSegment | ClipSegment | StillSegment;

/* 一种图表一段，2 秒快速浏览；图片是 gallery 里产品自己渲染的实图。 */
const chartSeg = (type: string, title: string, seconds = 2): StillSegment => ({
  kind: 'still',
  image: `chart-${type}.png`,
  dir: 'gallery',
  seconds,
  no: '◆',
  chapter: `CHART · ${title}`,
  caption: [{zh: title}],
  accent: C.biblio,
  fit: 'contain',
});

/* 简单图表（控制台基础图）：先快速过一遍。 */
const SIMPLE_CHARTS: Segment[] = [
  chartSeg('bar', '柱状图 · 分类对比'),
  chartSeg('line', '折线图 · 趋势'),
  chartSeg('dual_line', '双轴折线 · 两个量级'),
  chartSeg('stack_pct', '占比堆叠 · 100% 构成'),
  chartSeg('pie', '饼图 · 份额'),
  chartSeg('scatter', '散点图 · 相关性'),
  chartSeg('histogram', '直方图 · 分布'),
  chartSeg('box', '箱线图 · 离散度'),
  chartSeg('wordcloud', '词云 · 高频词'),
  chartSeg('topic_terms', '显著词 · 主题内 vs 全库'),
];

/* 复杂图表：关系、地理、模型一致率，再递进到文献计量的网络/时间/叠加图。 */
const COMPLEX_CHARTS: Segment[] = [
  chartSeg('heatmap', '热力图 · 交叉矩阵'),
  chartSeg('sankey', '桑基图 · 流向'),
  chartSeg('network', '关系图 · 共现网络'),
  chartSeg('map', '地图 · 中国省份'),
  chartSeg('model_agreement', '模型一致率 · 两两对比'),
  chartSeg('topic_map', '主题距离图 · LDA 平面', 2.5),
  chartSeg('knowledge_graph', '知识图谱 · 关键词共现', 3),
  chartSeg('cluster_timeline', '聚类时间线 · 演进', 2.5),
  chartSeg('burst', '突现词 · 何时爆发'),
  chartSeg('timezone', '时区图 · 首现年份'),
  chartSeg('circular', '环形图谱 · 无坐标网络'),
  chartSeg('landscape', '景观图 · 年度山峰'),
  chartSeg('biblio_heatmap', '聚类 × 年份热力'),
  chartSeg('graph3d', '三维知识图谱', 2.5),
  chartSeg('concentric', '同心环 · 按首现年份'),
];

/* 字幕只保留中文；英文只做章节标签。
   语气像在桌边讲一条真实跑过的画布，不像产品发布会。 */
const BILI_SEGMENTS: Segment[] = [
  {
    kind: 'card',
    seconds: 9,
    no: '00',
    kicker: 'CAIXIHUI · 采析绘',
    title: '把研究画成一条路',
    flow: ['采集', '清洗', '分析', '可视化', '成稿'],
    body: '画好之后，点一下就能跑。',
    accent: C.text,
    glyph: 'none',
  },
  {
    kind: 'clip',
    scene: 'canvas',
    seconds: 5,
    no: '01',
    chapter: 'CANVAS · 画布',
    caption: [
      {zh: '一条画布，17 个节点'},
      {zh: '采集、筛选、出图、成稿，连成一张图'},
    ],
    accent: C.source,
    startFrom: 3,
  },
  {
    kind: 'still',
    image: 'still-covernodes.png',
    seconds: 10,
    no: '02',
    chapter: 'GRAPH · 编排',
    caption: [{zh: '节点是盒子，连线是数据的去向'}],
    accent: C.source,
    effects: [{kind: 'spotlight', x: 0.29, y: 0.5, w: 0.24, h: 0.46, label: '并行分支'}],
  },
  {
    kind: 'still',
    image: 'still-source-platforms.png',
    seconds: 5,
    no: '03',
    chapter: 'SOURCE · 9 平台 + 知网',
    caption: [{zh: '知乎、微博、小红书、B 站、抖音…一份节点设置里选'}],
    accent: C.source,
    effects: [{kind: 'spotlight', x: 0.89, y: 0.46, w: 0.2, h: 0.32, label: '平台列表'}],
  },
  {
    kind: 'still',
    image: 'still-source.png',
    seconds: 10,
    no: '04',
    chapter: 'CATBUS · 第二后端',
    caption: [{zh: '同一节点可换采集引擎；CatBus 用自己的账号'}],
    accent: C.compile,
    effects: [
      {kind: 'spotlight', x: 0.79, y: 0.29, w: 0.34, h: 0.07, label: '采集引擎'},
      {kind: 'callout', x: 0.6, y: 0.45, text: '换引擎，不换画布', accent: C.compile, delay: 26},
    ],
  },
  {
    kind: 'clip',
    scene: 'data-scroll',
    seconds: 11,
    no: '05',
    chapter: 'DATA · 数据',
    caption: [{zh: '600 条真实评论，翻页看每一列都是下一步的入口'}],
    accent: C.upload,
    effects: [{kind: 'callout', x: 0.7, y: 0.06, text: '600 行评论', accent: C.upload, delay: 20}],
  },
  {
    kind: 'still',
    image: 'still-datasets.png',
    seconds: 10,
    no: '06',
    chapter: 'CLEAN · 清洗与去重',
    caption: [{zh: '多源合并、SimHash 近重复，按数据集版本管理'}],
    accent: C.upload,
    effects: [{kind: 'callout', x: 0.08, y: 0.62, text: '合并所选 · 比较所选', accent: C.upload, delay: 22}],
  },
  {
    kind: 'card',
    seconds: 11,
    no: '06b',
    kicker: 'SEMANTIC · 语义去重与检索',
    title: '意思相近\n也算重复',
    formula: '语义近重复去重 · 相似文本检索',
    body: '小中文向量模型跑在本地；不是只比字面，而是比意思。',
    accent: C.upload,
    glyph: 'none',
  },
  {
    kind: 'still',
    image: 'still-parameters.png',
    seconds: 11,
    no: '07',
    chapter: 'PARAMETERS · 口径',
    caption: [{zh: '口径写在节点里：选哪一列、用什么模型、怎么分档'}],
    accent: C.analysis,
    effects: [{kind: 'spotlight', x: 0.77, y: 0.5, w: 0.44, h: 0.88, label: '节点口径'}],
  },
  {
    kind: 'clip',
    scene: 'run',
    seconds: 6,
    no: '08',
    chapter: 'RUN · 运行',
    caption: [
      {zh: '点一下执行，它按连线跑'},
      {zh: '六个图表一起出，仪表盘自动打开'},
    ],
    accent: C.process,
    startFrom: 0,
    effects: [
      {kind: 'step', index: 1, text: '点击执行', accent: C.process, delay: 12},
      {kind: 'step', index: 2, text: '节点依次完成', accent: C.process, delay: 96},
      {kind: 'step', index: 3, text: '仪表盘出图', accent: C.process, delay: 220},
    ],
  },
  {
    kind: 'still',
    image: 'still-biblio.png',
    seconds: 10,
    no: '09',
    chapter: 'BIBLIOMETRICS · 文献计量',
    caption: [{zh: '知网导出件识别，按时间切片共建关键词网络'}],
    accent: C.biblio,
    effects: [{kind: 'callout', x: 0.08, y: 0.72, text: '共现 · 突现 · 聚类', accent: C.biblio, delay: 20}],
  },
  {
    kind: 'still',
    image: 'still-graph.png',
    seconds: 10,
    no: '10',
    chapter: 'GRAPH · 知识图谱',
    caption: [{zh: '图，不是装饰；它记得每个词从哪来'}],
    accent: C.biblio,
  },
  {
    kind: 'still',
    image: 'still-timeline.png',
    seconds: 9,
    no: '11',
    chapter: 'TIMELINE · 时间线',
    caption: [{zh: '同一份文献，换一个角度看：聚类 · 突现 · 时间线'}],
    accent: C.visualize,
  },
  {
    kind: 'still',
    image: 'still-dashboard.png',
    seconds: 10,
    no: '12',
    chapter: 'DASHBOARD · 仪表盘',
    caption: [{zh: '多张图在一屏，跑完自动汇总'}],
    accent: C.visualize,
  },
  {
    kind: 'still',
    image: 'still-records.png',
    seconds: 9,
    no: '13',
    chapter: 'RECORDS · 运行记录',
    caption: [{zh: '每个节点、多少行、什么时候结束，都有记录'}],
    accent: C.compile,
    effects: [{kind: 'spotlight', x: 0.47, y: 0.87, w: 0.86, h: 0.12, label: '16 / 16 · 331 行'}],
  },
  {
    kind: 'card',
    seconds: 11,
    no: '14',
    kicker: 'RESUME · 继续',
    title: '跑一半停下\n不用从头再来',
    formula: '继续 = 只补没跑完的那部分',
    body: '已采到的行、已经问过模型的话，都在。重开服务也一样。',
    accent: C.warn,
  },
  {
    kind: 'still',
    image: 'still-report-dialog.png',
    seconds: 9,
    no: '15',
    chapter: 'REPORT · 成稿',
    caption: [{zh: '把这一次运行，写成一份稿'}],
    accent: C.analysis,
  },
  {
    kind: 'still',
    image: 'still-report.png',
    seconds: 10,
    no: '16',
    chapter: 'REPORT · HTML',
    caption: [{zh: '图、表、运行信息，一份自带内容的 HTML'}],
    accent: C.analysis,
    effects: [{kind: 'spotlight', x: 0.5, y: 0.53, w: 0.6, h: 0.5, label: '图表 + 数据表'}],
  },
  {
    kind: 'still',
    image: 'still-exports.png',
    seconds: 9,
    no: '17',
    chapter: 'EXPORT · 导出',
    caption: [{zh: 'CSV / Excel / JSON / 图 / 报告，产物集中下载'}],
    accent: C.output,
    effects: [{kind: 'callout', x: 0.08, y: 0.72, text: '图表 · 数据 · 报告', accent: C.output, delay: 20}],
  },
  {
    kind: 'clip',
    scene: 'ai-chat',
    seconds: 5,
    no: '18',
    chapter: 'AI WORKSPACE · 本地 Ollama',
    caption: [
      {zh: '问它画布在做什么，本地 Ollama 当场回答'},
      {zh: '它读当前节点、连线、数据集与运行记录'},
    ],
    accent: C.source,
    speed: 3.4,
    effects: [
      {kind: 'step', index: 1, text: '提问', accent: C.source, delay: 12},
      {kind: 'step', index: 2, text: '本地模型回答', accent: C.source, delay: 120},
    ],
  },
  {
    kind: 'card',
    seconds: 11,
    no: '18b',
    kicker: 'MODEL · 本地模型',
    title: '模型跑在自己机器上',
    formula: 'BERT 情感 / 情绪 / 倾向 · 本地 Ollama',
    body: '跑不动会降级并说明实际用了什么；不会悄悄换一个模型还当作原来那个。',
    accent: C.analysis,
    glyph: 'none',
  },
  {
    kind: 'card',
    seconds: 9,
    no: '19',
    kicker: 'POOL · 账号与出口',
    title: '账号池 · 出口池',
    formula: '被风控就冷却换号 / 换 IP，粘性绑定',
    body: '只在“一条都没采到”时才换号，已采到的行不会丢。',
    accent: C.warn,
  },
  {
    kind: 'still',
    image: 'still-schedules.png',
    seconds: 9,
    no: '20',
    chapter: 'SCHEDULE · 定时任务',
    caption: [{zh: '预设或 cron 跑已存画布；需要模型的会标明'}],
    accent: C.compile,
    effects: [{kind: 'callout', x: 0.72, y: 0.1, text: '新建任务', accent: C.compile, delay: 20}],
  },
  {
    kind: 'card',
    seconds: 9,
    no: '21',
    kicker: 'CROSS-PLATFORM · 跨平台',
    title: 'Windows · macOS · Linux',
    formula: '源码运行 / 桌面安装包 / 云端',
    body: '桌面版双击即用；云端打开浏览器就能跑。',
    accent: C.text,
    glyph: 'none',
  },
  {
    kind: 'card',
    seconds: 3,
    no: '—',
    kicker: 'CHARTS · 可视化',
    title: '每一种图，都来自真数据',
    body: '下面的图，全部由画布节点/同一条渲染通道现场生成。',
    accent: C.visualize,
    glyph: 'none',
  },
  ...SIMPLE_CHARTS,
  {
    kind: 'card',
    seconds: 3,
    no: '—',
    kicker: 'COMPLEX · 复杂图',
    title: '从关系图，到文献网络',
    body: '知识图谱、时间线、叠加、三维——复杂结构也能画。',
    accent: C.biblio,
    glyph: 'none',
  },
  ...COMPLEX_CHARTS,
  {
    kind: 'card',
    seconds: 4,
    no: '22',
    kicker: 'CAIXIHUI · 采析绘',
    title: '把重复留给机器\n把判断留给你',
    body: 'github.com/Xingye-Dujing/crawler-workflow\nMIT · Windows / macOS / Linux',
    accent: C.text,
  },
];

const DOUYIN_SEGMENTS: Segment[] = [
  {
    kind: 'card',
    seconds: 6,
    no: '00',
    kicker: 'CAIXIHUI',
    title: '把研究画成一条路',
    flow: ['采集', '清洗', '分析', '可视化', '成稿'],
    body: '画好之后，点一下就能跑。',
    accent: C.text,
    glyph: 'none',
  },
  {
    kind: 'clip',
    scene: 'canvas',
    seconds: 8,
    no: '01',
    chapter: 'CANVAS · 画布',
    caption: [{zh: '采集、清洗、出图、成稿，一条画布'}],
    accent: C.source,
    startFrom: 3,
  },
  {
    kind: 'still',
    image: 'still-source-platforms.png',
    seconds: 8,
    no: '02',
    chapter: 'SOURCE · 采集',
    caption: [{zh: '9 个平台 + 知网，还能换 CatBus 引擎'}],
    accent: C.source,
    effects: [{kind: 'spotlight', x: 0.89, y: 0.46, w: 0.2, h: 0.32, label: '平台列表'}],
  },
  {
    kind: 'clip',
    scene: 'data-scroll',
    seconds: 7,
    no: '03',
    chapter: 'DATA · 数据',
    caption: [{zh: '600 条真实评论，翻页看'}],
    accent: C.upload,
  },
  {
    kind: 'clip',
    scene: 'run',
    seconds: 11,
    no: '04',
    chapter: 'RUN · 运行',
    caption: [{zh: '点执行，按连线跑，六张图一起出'}],
    accent: C.process,
    startFrom: 0,
    effects: [{kind: 'step', index: 1, text: '点击执行', accent: C.process, delay: 12}],
  },
  {
    kind: 'card',
    seconds: 8,
    no: '04b',
    kicker: 'BIBLIOMETRICS · 文献计量',
    title: '知网导出件\n直接读',
    body: '关键词共现、突现、聚类，按时间切片建网络。',
    accent: C.biblio,
    glyph: 'none',
  },
  {
    kind: 'still',
    image: 'still-graph.png',
    seconds: 8,
    no: '05',
    chapter: 'GRAPH · 知识图谱',
    caption: [{zh: '图，不是装饰；它记得每个词从哪来'}],
    accent: C.biblio,
  },
  {
    kind: 'still',
    image: 'still-timeline.png',
    seconds: 7,
    no: '06',
    chapter: 'TIMELINE · 时间线',
    caption: [{zh: '聚类 · 突现 · 时间线'}],
    accent: C.visualize,
  },
  {
    kind: 'card',
    seconds: 7,
    no: '07',
    kicker: 'RESUME · 继续',
    title: '跑一半停下\n不用从头再来',
    formula: '继续 = 只补没跑完的那部分',
    body: '已完成的节点和行，都在。',
    accent: C.warn,
  },
  {
    kind: 'still',
    image: 'still-report.png',
    seconds: 8,
    no: '08',
    chapter: 'REPORT · 成稿',
    caption: [{zh: '图表与正文，合成一份可以交的稿'}],
    accent: C.analysis,
  },
  {
    kind: 'clip',
    scene: 'ai-chat',
    seconds: 10,
    no: '09',
    chapter: 'AI · 本地 Ollama',
    caption: [{zh: '用本地 Ollama 回答一个画布问题'}],
    accent: C.source,
    speed: 4,
    effects: [{kind: 'step', index: 1, text: '提问 · 本地回答', accent: C.source, delay: 40}],
  },
  {
    kind: 'still',
    image: 'still-schedules.png',
    seconds: 8,
    no: '10',
    chapter: 'SCHEDULE · 定时',
    caption: [{zh: '预设或 cron，定时跑已存画布'}],
    accent: C.compile,
  },
  {
    kind: 'card',
    seconds: 9,
    no: '10b',
    kicker: 'POOL · 账号与出口',
    title: '换号不换 IP',
    body: '被风控就冷却换号，粘性绑定出口；已采到的行不丢。',
    accent: C.warn,
    glyph: 'none',
  },
  chartSeg('bar', '柱状图', 1.5),
  chartSeg('line', '折线图', 1.5),
  chartSeg('pie', '饼图', 1.5),
  chartSeg('heatmap', '热力图', 1.5),
  chartSeg('sankey', '桑基图', 1.5),
  chartSeg('wordcloud', '词云', 1.5),
  chartSeg('knowledge_graph', '知识图谱', 2.5),
  chartSeg('cluster_timeline', '聚类时间线', 2),
  chartSeg('graph3d', '三维图谱', 2),
  {
    kind: 'card',
    seconds: 4,
    no: '11',
    kicker: 'CAIXIHUI · 采析绘',
    title: '把重复留给机器\n把判断留给你',
    body: 'github.com/Xingye-Dujing/crawler-workflow',
    accent: C.text,
  },
];

const PaperCut: React.FC<{cuts: number[]}> = ({cuts}) => {
  const frame = useCurrentFrame();
  let opacity = 0;
  for (const cut of cuts) {
    const d = frame - cut;
    if (d >= -5 && d <= 6) {
      opacity = Math.max(opacity, 1 - Math.abs(d) / 6);
    }
  }
  return (
    <AbsoluteFill style={{background: C.bg, opacity: opacity * 0.7, pointerEvents: 'none'}} />
  );
};

const EFFECT_FOR_SEGMENT = (effects: Effect[] | undefined) => effects ?? [];

/* 宣传片节奏：所有段统一加速，快速浏览。clip 段同步加速播放以匹配短时长。 */
const PACE = 0.42;

export const FootageFilm: React.FC<{profile: Profile; segments: Segment[]}> = ({
  profile,
  segments,
}) => {
  const lengths = segments.map((s) => Math.max(1, Math.round(s.seconds * PACE * FPS)));
  const starts: number[] = [];
  let acc = 0;
  for (const len of lengths) {
    starts.push(acc);
    acc += len;
  }
  const total = acc;
  const cuts = starts.slice(1);

  return (
    <AbsoluteFill style={{background: C.bg}}>
      <FontFaces />

      {segments.map((segment, i) => (
        <Sequence key={i} from={starts[i]} durationInFrames={lengths[i]}>
          {segment.kind === 'card' ? (
            <ChapterCard profile={profile} {...segment} />
          ) : segment.kind === 'still' ? (
            <>
              <StillFootage
                profile={profile}
                image={segment.image}
                dir={segment.dir}
                caption={segment.caption}
                fit={segment.fit}
                focus={segment.focus}
              />
              <EffectsLayer effects={EFFECT_FOR_SEGMENT(segment.effects)} />
            </>
          ) : (
            <>
              <Footage
                profile={profile}
                scene={segment.scene}
                caption={segment.caption}
                startFrom={segment.startFrom}
                speed={(segment.speed ?? 1) / PACE}
                focus={segment.focus}
              />
              <EffectsLayer effects={EFFECT_FOR_SEGMENT(segment.effects)} />
            </>
          )}
        </Sequence>
      ))}

      <PaperCut cuts={cuts} />
    </AbsoluteFill>
  );
};

export const BiliPromo: React.FC = () => (
  <FootageFilm profile="bili" segments={BILI_SEGMENTS} />
);

export const DouyinPromo: React.FC = () => (
  <FootageFilm profile="douyin" segments={DOUYIN_SEGMENTS} />
);

export const BILI_FRAMES = Math.round(BILI_SEGMENTS.reduce((a, s) => a + s.seconds, 0) * PACE * FPS);
export const DOUYIN_FRAMES = Math.round(DOUYIN_SEGMENTS.reduce((a, s) => a + s.seconds, 0) * PACE * FPS);
