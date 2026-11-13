"""The desktop shell's words: tray menu entries and the text of a system notification.

Part of the zh/en message catalogue, merged by ``backend/i18n.py``. Only the packaged launchers and
the engine's two notification points ask for these — the browser never does, so there is no
``static/js/i18n/desktop.js`` twin. Keys are sorted, and both tables must hold the same set
(``tests/unit/i18n/test_i18n.py``).
"""

ZH = {
    'desktop.openData': '打开数据目录',
    'desktop.quit': '退出',
    'desktop.runDoneBody': '工作流“{name}”已在后台完成（{done}/{total} 个节点）。',
    'desktop.runDoneTitle': '运行完成',
    'desktop.runFailedBody': '工作流“{name}”有 {failed} 个节点失败（{done}/{total} 个完成）。',
    'desktop.runFailedTitle': '运行失败',
    'desktop.schedStartBody': '定时任务“{name}”已开始运行。',
    'desktop.schedStartTitle': '定时任务已开始',
    'desktop.show': '显示主窗口',
    'desktop.untitled': '未命名工作流',
}

EN = {
    'desktop.openData': 'Open data folder',
    'desktop.quit': 'Quit',
    'desktop.runDoneBody': 'Workflow “{name}” finished in the background ({done}/{total} nodes).',
    'desktop.runDoneTitle': 'Run finished',
    'desktop.runFailedBody': 'Workflow “{name}” finished with {failed} failed node(s) ({done}/{total} done).',
    'desktop.runFailedTitle': 'Run failed',
    'desktop.schedStartBody': 'Scheduled task “{name}” has started.',
    'desktop.schedStartTitle': 'Scheduled task started',
    'desktop.show': 'Show window',
    'desktop.untitled': 'Untitled workflow',
}
