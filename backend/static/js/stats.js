/* ─── Statistics & Charts ─── */
const stats = {
    emotionChart: null,
    tendencyChart: null,
    /* True when the CDN copy of ECharts never arrived. Every entry point below then
       declines quietly instead of throwing, because the boot is one DOMContentLoaded
       body and a throw here used to take the rest of start-up down with it. */
    unavailable: false,

    init() {
        /* ECharts arrives from a CDN (index.html) and this is a local, sometimes
           offline tool. With no `echarts` the old code threw right here — and that
           one throw skipped CustomSelect.init, Capabilities.load,
           dataNodes.reconcileDatasets, the autosave interval and resumeBar.refresh:
           every 数据源 node then showed 「无法获取平台能力」 and the 断点续跑 banner never
           appeared, with nothing on screen saying a chart library was the cause.
           Same lesson Settings.load already documents. */
        if (typeof echarts === 'undefined') {
            this.unavailable = true;
            this._noteMissingLibrary();
            return;
        }
        this.emotionChart = echarts.init(document.getElementById('chart-emotion'));
        this.tendencyChart = echarts.init(document.getElementById('chart-tendency'));
        window.addEventListener('resize', () => {
            this.emotionChart.resize();
            this.tendencyChart.resize();
        });
    },

    _noteMissingLibrary() {
        /* textContent, never innerHTML: this string comes from the language
           catalogue, but a message table is still text, not markup to parse. */
        ['chart-emotion', 'chart-tendency'].forEach((id) => {
            const box = document.getElementById(id);
            if (!box) return;
            box.textContent = '';
            const note = document.createElement('div');
            note.className = 'chart-missing';
            note.textContent = I18n.t('stats.noChartLibrary');
            box.appendChild(note);
        });
    },

    async refresh() {
        if (this.unavailable) return;
        await Promise.all([this.loadEmotion(), this.loadTendency()]);
    },

    async loadEmotion() {
        if (this.unavailable) return;
        try {
            const resp = await fetch('/api/stats/emotion');
            const result = await resp.json();
            if (result.ok && result.stats) {
                this.renderPie(this.emotionChart, result.stats);
            }
        } catch (e) {
            console.error('Failed to load emotion stats:', e);
        }
    },

    async loadTendency() {
        if (this.unavailable) return;
        try {
            const resp = await fetch('/api/stats/tendency');
            const result = await resp.json();
            if (result.ok && result.stats) {
                this.renderPie(this.tendencyChart, result.stats);
            }
        } catch (e) {
            console.error('Failed to load tendency stats:', e);
        }
    },

    /* The label above each pie is the panel's own heading, already translated in
       index.html; a second, English-only copy passed in here could only be either
       redundant or wrong, so the argument never existed for a reason. */
    renderPie(chart, data) {
        if (!chart) return;
        const colors = {
            'Anger': '#e74c3c', 'Joy': '#f1c40f', 'Sadness': '#3498db',
            'Fear': '#9b59b6', 'Neutral': '#95a5a6',
            'Objective Statement': '#95a5a6', 'Praise/Affirmation': '#2ecc71',
            'Criticism/Questioning': '#e74c3c', 'Controversy/Reflection': '#f39c12',
            'Advocacy/Call-to-action': '#3498db', 'Satire/Mockery': '#9b59b6',
        };

        const option = {
            backgroundColor: 'transparent',
            tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
            series: [{
                type: 'pie',
                radius: ['35%', '65%'],
                center: ['50%', '50%'],
                avoidLabelOverlap: true,
                itemStyle: { borderRadius: 0, borderColor: 'transparent', borderWidth: 0 },
                label: {
                    /* Read from the page, not hardcoded: the pie labels sit on the
                       app background, which is a user setting, and a dark-theme grey
                       on a light card is unreadable. Same reason
                       historyPanel._renderChart re-reads --font. */
                    color: 'var(--text-dim)',
                    fontSize: 10,
                    formatter: '{b}\n{d}%',
                    fontFamily: 'var(--font)',
                },
                labelLine: { lineStyle: { color: 'var(--border)' } },
                data: (data.labels || []).map((label, i) => ({
                    name: label,
                    value: (data.values || [])[i] || 0,
                    itemStyle: { color: colors[label] || '#666' },
                })),
            }],
        };

        chart.setOption(option);
        chart.resize();
    },
};

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.chart-container').forEach(c => c.style.display = 'none');
    /* The buttons live in the panel and stay clickable even with no chart library;
       resizing a chart that was never built threw there. */
    const chart = tab === 'emotion' ? stats.emotionChart : stats.tendencyChart;
    if (tab === 'emotion') {
        document.querySelector('.tab-btn:first-child').classList.add('active');
        document.getElementById('chart-emotion').style.display = 'block';
    } else {
        document.querySelector('.tab-btn:last-child').classList.add('active');
        document.getElementById('chart-tendency').style.display = 'block';
    }
    if (chart) chart.resize();
}
