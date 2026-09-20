/* ─── Statistics & Charts ─── */
const stats = {
    emotionChart: null,
    tendencyChart: null,

    init() {
        this.emotionChart = echarts.init(document.getElementById('chart-emotion'));
        this.tendencyChart = echarts.init(document.getElementById('chart-tendency'));
        window.addEventListener('resize', () => {
            this.emotionChart.resize();
            this.tendencyChart.resize();
        });
    },

    async refresh() {
        await Promise.all([this.loadEmotion(), this.loadTendency()]);
    },

    async loadEmotion() {
        try {
            const resp = await fetch('/api/stats/emotion');
            const result = await resp.json();
            if (result.ok && result.stats) {
                this.renderPie(this.emotionChart, 'Emotion Distribution', result.stats);
            }
        } catch (e) {
            console.error('Failed to load emotion stats:', e);
        }
    },

    async loadTendency() {
        try {
            const resp = await fetch('/api/stats/tendency');
            const result = await resp.json();
            if (result.ok && result.stats) {
                this.renderPie(this.tendencyChart, 'Tendency Distribution', result.stats);
            }
        } catch (e) {
            console.error('Failed to load tendency stats:', e);
        }
    },

    renderPie(chart, title, data) {
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
                    color: '#aaa', fontSize: 10,
                    formatter: '{b}\n{d}%',
                    fontFamily: 'JetBrains Mono, monospace',
                },
                labelLine: { lineStyle: { color: '#444' } },
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
    if (tab === 'emotion') {
        document.querySelector('.tab-btn:first-child').classList.add('active');
        document.getElementById('chart-emotion').style.display = 'block';
        stats.emotionChart.resize();
    } else {
        document.querySelector('.tab-btn:last-child').classList.add('active');
        document.getElementById('chart-tendency').style.display = 'block';
        stats.tendencyChart.resize();
    }
}
