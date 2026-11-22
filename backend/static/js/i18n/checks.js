/* The validation vocabulary the browser still words itself.

 * The pre-run gate is the server's (`/api/workflow/validate`), so the per-node messages live in
 * the Python catalogue. What remains here is what the *diagnostics panel* words in the browser:
 * an analysis step's parameter answer, and the one refusal a validation request that could not
 * reach the server has to print. Part of the browser catalogue; loaded BEFORE app.js.
 */
(globalThis.I18N_CATALOGUES = globalThis.I18N_CATALOGUES || []).push({
    name: 'checks',
    en: {
        'validate.unavailable': 'The workflow could not be validated ({err}); fix the connection and try again',
        'validate.analysisParam': 'Analysis node "{title}": {op} needs {field}, which is empty',
        'validate.analysisParamOption': 'Analysis node "{title}": {op} has no {field} "{value}" (available: {allowed})',
        'validate.analysisPhaseLabels':
            'Analysis node "{title}": {op} has {edges} boundaries, so it needs {expected} phase names, but {given} are given',
        'validate.analysisRename': 'Analysis node "{title}": {op} gives these columns no new name: {cols}',
        'validate.analysisStepsShape': 'Analysis node "{title}": steps must be a list of steps, not an object',
        'validate.paramsShape': 'Node "{title}": its parameters were not saved as an object, so nothing can read them — set this node again',
    },
    zh: {
        'validate.unavailable': '无法校验工作流（{err}）；请检查连接后重试',
        'validate.analysisParam': '分析节点 "{title}"：{op} 的 {field} 还没有填写',
        'validate.analysisParamOption': '分析节点 "{title}"：{op} 的 {field} 没有 "{value}" 这个选项（可用：{allowed}）',
        'validate.analysisPhaseLabels': '分析节点 "{title}"：{op} 有 {edges} 个边界，需要 {expected} 个阶段名，现在填了 {given} 个',
        'validate.analysisRename': '分析节点 "{title}"：{op} 没有为这些列写新名字：{cols}',
        'validate.analysisStepsShape': '分析节点 "{title}"：steps 必须是步骤列表，不能是对象',
        'validate.paramsShape': '节点 "{title}"：参数不是以对象保存的，任何步骤都读不出来——请重新设置这个节点',
    },
});
