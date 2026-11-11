"""Pool wording: the console lines a rotation prints, and the management answers.

The state itself is data (``services.pool.store``); this module only gives it words. Every
sentence a user can read lives here in both languages, including the one that names WHY a
login or an exit was benched — that reason is the whole point of the feature, and an
untranslated code word would put ``risk`` in a Chinese console.
"""

ZH = {
    'pool.reason.loginWall': '登录态失效',
    'pool.reason.risk': '风控/验证码',
    'pool.reason.network': '网络不可达',
    'pool.reason.manual': '手动停用',
    'pool.exhausted': '账号池已无可用账号（{platform}）：{detail}',
    'pool.catbusUnsupported': '账号池只适用于本机浏览器采集；CatBus 节点请用它自己的账号',
    'pool.noCandidates': '账号池（{platform}）现在没有可用账号：请检查登录、冷却时间或停用状态',
    'pool.rotating': '[账号池] {platform} · {account} 不可用（{reason}），改用 {next}',
    'pool.nextAttempt': '下一个候选账号',
    'pool.attempt': '[账号池] {platform} 第 {n} 次尝试：{account}{exit}',
    'pool.exit.unavailable': '出口池（{platform}）没有可用出口，已按设置拒绝直连',
    'pool.exit.saved': '出口已保存：{name}',
    'pool.exit.deleted': '出口已删除：{name}',
    'pool.exit.notFound': '没有这个出口：{id}',
    'pool.exit.badScheme': '不支持的出口协议：{scheme}（只支持 http / https / socks5）',
    'pool.exit.badHost': '出口地址不能为空，且不能包含空格或斜杠',
    'pool.exit.badPort': '出口端口无效：{port}',
    'pool.exit.imported': '已导入 {n} 个出口，跳过 {skipped} 行',
    'pool.account.reset': '已解冻：{platform} · {account}',
    'pool.account.disabled': '已停用：{platform} · {account}',
    'pool.account.enabled': '已启用：{platform} · {account}',
    'pool.account.resetAll': '已解冻 {n} 条记录',
    'pool.bind.done': '已把 {platform} · {account} 绑定到出口 {exit}',
    'pool.bind.cleared': '已恢复 {platform} · {account} 的出口自动分配',
    'pool.badAccount': '账号名无效：{account}',
    'pool.adminOnly': '账号池与出口由管理员维护',
}

EN = {
    'pool.reason.loginWall': 'login wall',
    'pool.reason.risk': 'risk control / captcha',
    'pool.reason.network': 'network unreachable',
    'pool.reason.manual': 'disabled by hand',
    'pool.exhausted': 'No usable account left in the pool ({platform}): {detail}',
    'pool.catbusUnsupported': ('The account pool applies to browser crawls; a CatBus node uses its own account files'),
    'pool.noCandidates': (
        'The pool ({platform}) has no usable account right now: check the logins, '
        'the cooldown times or the disabled flags'
    ),
    'pool.rotating': '[pool] {platform} · {account} is unusable ({reason}); switching to {next}',
    'pool.nextAttempt': 'the next candidate',
    'pool.attempt': '[pool] {platform} attempt {n}: {account}{exit}',
    'pool.exit.unavailable': 'No usable exit for {platform}; direct connection refused by the setting',
    'pool.exit.saved': 'Exit saved: {name}',
    'pool.exit.deleted': 'Exit deleted: {name}',
    'pool.exit.notFound': 'No such exit: {id}',
    'pool.exit.badScheme': 'Unsupported proxy scheme: {scheme} (http / https / socks5)',
    'pool.exit.badHost': 'The proxy host is required and may not contain spaces or slashes',
    'pool.exit.badPort': 'Invalid proxy port: {port}',
    'pool.exit.imported': 'Imported {n} exits, skipped {skipped} lines',
    'pool.account.reset': 'Unfrozen: {platform} · {account}',
    'pool.account.disabled': 'Disabled: {platform} · {account}',
    'pool.account.enabled': 'Enabled: {platform} · {account}',
    'pool.account.resetAll': 'Unfroze {n} record(s)',
    'pool.bind.done': 'Bound {platform} · {account} to exit {exit}',
    'pool.bind.cleared': 'Restored automatic exit assignment for {platform} · {account}',
    'pool.badAccount': 'Invalid account: {account}',
    'pool.adminOnly': 'The account and exit pools are maintained by the administrator',
}
