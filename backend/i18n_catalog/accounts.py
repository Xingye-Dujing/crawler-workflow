"""Login accounts, sessions and the account-management panel."""

ZH = {
    'accounts.accountBusy': '这个账号还有运行中的任务（{run}），请先等待或停止后再禁用或删除',
    'accounts.accountDisabled': '该账号已被禁用，请联系管理员',
    'accounts.adminRequired': '只有管理员可以执行这个操作',
    'accounts.bootstrapCreated': '已创建初始管理员账号「{user}」，请登录后修改密码',
    'accounts.bootstrapEnvIgnored': '账号库已有账号，环境变量里的引导密码被忽略（不会重置任何密码）',
    'accounts.bootstrapNeeded': (
        '还没有任何账号：cloud 模式首次启动必须设置 CRAWLER_ADMIN_PASSWORD'
        '（旧变量 CRAWLER_AUTH_PASSWORD 仍可用）来创建初始管理员'
    ),
    'accounts.cannotDeleteSelf': '不能删除当前登录的账号',
    'accounts.cannotDisableSelf': '不能禁用当前登录的账号',
    'accounts.confirmMismatch': '确认用户名不一致，没有做任何修改',
    'accounts.csrfRequired': '请求缺少或携带了错误的 CSRF 令牌，请刷新页面后重试',
    'accounts.currentPasswordWrong': '当前密码不正确',
    'accounts.lastAdmin': '这是最后一个启用的管理员账号，不能禁用或删除',
    'accounts.lockedOut': '登录失败次数过多，请 {minutes} 分钟后再试',
    'accounts.mustChangePassword': '这个账号需要先修改密码才能继续使用',
    'accounts.notFound': '账号不存在或已被删除',
    'accounts.passwordSameAsUsername': '密码不能与用户名相同',
    'accounts.passwordTooLong': '密码不能超过 {n} 个字符',
    'accounts.passwordTooShort': '密码至少需要 {n} 个字符',
    'accounts.passwordUnchanged': '新密码不能与当前密码相同',
    'accounts.roleInvalid': '未知的角色：只能是 admin 或 user',
    'accounts.statusInvalid': '未知的状态：只能是 active 或 disabled',
    'accounts.tooManyAttempts': '来自这个地址的登录失败次数过多，请稍后再试',
    'accounts.usernameInvalid': '用户名需要 3–32 个字符，只能包含字母、数字、下划线、点和短横线',
    'accounts.usernameTaken': '用户名「{user}」已被占用',
}

EN = {
    'accounts.accountBusy': (
        'This account still owns a run ({run}); wait for it or stop it before disabling or deleting the account'
    ),
    'accounts.accountDisabled': 'This account is disabled. Ask an administrator.',
    'accounts.adminRequired': 'Only an administrator may do that',
    'accounts.bootstrapCreated': 'Created the initial administrator "{user}"; sign in and change its password',
    'accounts.bootstrapEnvIgnored': (
        'Accounts already exist; the bootstrap password in the environment was ignored (no password was reset)'
    ),
    'accounts.bootstrapNeeded': (
        'There are no accounts yet: the first cloud boot must set CRAWLER_ADMIN_PASSWORD'
        ' (the old CRAWLER_AUTH_PASSWORD still works) to create the initial administrator'
    ),
    'accounts.cannotDeleteSelf': 'You cannot delete the account you are signed in with',
    'accounts.cannotDisableSelf': 'You cannot disable the account you are signed in with',
    'accounts.confirmMismatch': 'The confirmation username did not match; nothing was changed',
    'accounts.csrfRequired': 'Missing or wrong CSRF token; reload the page and try again',
    'accounts.currentPasswordWrong': 'The current password is incorrect',
    'accounts.lastAdmin': 'This is the last enabled administrator; it cannot be disabled or deleted',
    'accounts.lockedOut': 'Too many failed sign-ins; try again in {minutes} minutes',
    'accounts.mustChangePassword': 'This account must change its password before it can continue',
    'accounts.notFound': 'No such account (it may have been deleted)',
    'accounts.passwordSameAsUsername': 'The password cannot equal the username',
    'accounts.passwordTooLong': 'The password may be at most {n} characters',
    'accounts.passwordTooShort': 'The password must be at least {n} characters',
    'accounts.passwordUnchanged': 'The new password must differ from the current one',
    'accounts.roleInvalid': 'Unknown role: only admin or user',
    'accounts.statusInvalid': 'Unknown status: only active or disabled',
    'accounts.tooManyAttempts': 'Too many failed sign-ins from this address; try again later',
    'accounts.usernameInvalid': 'A username is 3–32 characters: letters, digits, underscore, dot or dash',
    'accounts.usernameTaken': 'The username "{user}" is already taken',
}
