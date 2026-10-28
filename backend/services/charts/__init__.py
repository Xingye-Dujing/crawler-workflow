"""The chart domain: what a figure is, how it is drawn, and its paper twin.

``contracts`` is the chart type/column contract (which types exist, what each reads), ``visualizer``
renders the ECharts option and owns ``ChartConfigError``/``ECHARTS_ONLY_TYPES``, ``tikz`` builds the
LaTeX figure + three-line table for each chart, ``pdf`` compiles a run's registered LaTeX sources
with xelatex, and ``outputs`` is the figure+table add-on layer the render route and the visualize
node share. Importing this package imports nothing; callers name ``services.charts.<module>``.
"""
