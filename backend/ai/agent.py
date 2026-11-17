"""The turn loop: plan, read, ask, propose, answer.

A turn is not one model call. It may contain several provider rounds, tool results and a question
that pauses until the user answers. Each round is its own assistant row so the provider can see
the required ``assistant tool_use`` → ``tool result`` pairing; the transcript groups the rows by
``turn_id`` and renders them as one agent trace.

The agent may read and propose. It has no write tool: a workflow, analysis plan, chart, report,
skill or plugin leaves as an artifact, and the user applies it through the app's normal route.
"""

import hashlib
import json
import threading
import time
from datetime import datetime

from runtime import account_context
from runtime.settings import get_setting

from ai import approvals, environment, references, skills, store, tools, vocabulary, workflow_draft
from ai import context as context_builder
from ai.errors import AIError
from ai.providers import get_provider
from ai.types import new_id, usage_totals
from i18n import get_lang, t

ACTIVE_STREAMS: dict[str, threading.Event] = {}
_STREAM_LOCK = threading.RLock()


def _active(conversation_id: str) -> threading.Event:
    with _STREAM_LOCK:
        event = ACTIVE_STREAMS.get(conversation_id)
        if event is None:
            event = threading.Event()
            ACTIVE_STREAMS[conversation_id] = event
        return event


def clear_active(conversation_id: str) -> None:
    with _STREAM_LOCK:
        ACTIVE_STREAMS.pop(conversation_id, None)


def stop(conversation_id: str) -> bool:
    with _STREAM_LOCK:
        event = ACTIVE_STREAMS.get(conversation_id)
        if event is None:
            return False
        event.set()
        return True


def _user_key() -> str:
    return hashlib.sha1(account_context.scope_key().encode('utf-8')).hexdigest()[:16]


def _latest_reminder(locale: str, location: str = '') -> str:
    now = datetime.now().astimezone()
    weekdays_zh = ('星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日')
    weekdays_en = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
    zh = str(locale or 'zh').lower().startswith('zh')
    weekday = (weekdays_zh if zh else weekdays_en)[now.weekday()]
    language = '中文' if zh else 'English'
    return f'{now.date().isoformat()},{weekday},{location or ""},Web,{language}'


def _fallback_title(text: str) -> str:
    cleaned = ' '.join(str(text or '').split())
    return cleaned[:42] + ('…' if len(cleaned) > 42 else '') or t('ai.untitled')


def _system_prompt(skill, provider, model: str, agent_mode: str = 'build') -> str:
    capability_words = ', '.join(sorted(provider.spec.capabilities)) or 'none'
    mode_line = (
        'Agent mode: PLAN. Read, profile, validate and propose only. Do not write files, run commands, apply or '
        'run a workflow; publish a plan plus the concrete artifact (workflow draft / analysis plan) the user can '
        'apply themselves.'
        if agent_mode == 'plan'
        else 'Agent mode: BUILD. You may act through the tools you were given (apply a validated workflow, import '
        'a table, write in the working folder, run one allow-listed command) and must verify the result before '
        'claiming it worked.'
    )
    ask_line = (
        'Ask policy: ask whenever the goal, scope, cost or permission is ambiguous.'
        if skill.ask_policy in ('auto', 'always')
        else 'Ask policy: ask only when a required fact is genuinely missing.'
    )
    tools_line = (
        'The provider supports tool calls; use the read-only tools and the control tools.'
        if provider.supports('tools', model)
        else 'This provider cannot call tools; ask in plain text and answer from the supplied context.'
    )
    return (
        f'{skills.GLOBAL_POLICY}\n\n'
        f'{vocabulary.prompt_block()}\n\n'
        f'你与采析绘的应用是双向的：工作流草案可以用 apply_workflow 直接校验、保存并载入画布（用户要求运行时再加 '
        f'run=true）；失败的运行可以用 rerun_node 只重跑那个失败节点及其下游'
        f'（读已保存的工作流文件，不替换用户的画布）；'
        f'本地文件可以用 workspace_* 读取、写回、导入为数据集；run_cmd 在你的工作文件夹里执行一个白名单'
        f'程序（不是 shell）；app_errors 读后端日志与最近失败运行。做完一件事就调用一个工具，不要只描述。'
        f'“自动同意本机操作”关闭时，run_cmd / workspace_write / workspace_import / rerun_node 会先被拒绝：'
        f'用 request_approval 提出同样的确切参数，用户同意后再原样重试那个调用。\n\n'
        f'Active skill: {skill.id}\n{skill.prompt}\n\n'
        f'Provider: {provider.spec.id} / {model}. Declared capabilities: {capability_words}.\n'
        f'{environment.prompt_line()}\n'
        f'{mode_line}\n'
        f'{tools_line}\n{ask_line}'
    )


def _validate_provider(provider_id: str, model: str, api_key: str, thinking: bool, web_search: bool):
    provider = get_provider(provider_id)
    selected = (model or '').strip()
    if not selected:
        selected = provider.spec.models[0].id if provider.spec.models else ''
    if provider.spec.requires_key and not str(api_key or '').strip():
        raise AIError('ai.noKey', kind='auth')
    if thinking and not provider.supports('thinking', selected):
        raise AIError(
            'ai.capabilityRefused', kind='capability', provider=provider.spec.id, model=selected, capability='thinking'
        )
    if web_search and not provider.supports('web_search', selected):
        raise AIError(
            'ai.capabilityRefused',
            kind='capability',
            provider=provider.spec.id,
            model=selected,
            capability='web_search',
        )
    return provider, selected


def _append_block(blocks: list, block: dict) -> dict:
    blocks.append(block)
    return block


def _current_text(blocks: list) -> str:
    return ''.join(str(block.get('text') or '') for block in blocks if block.get('type') == 'text')


def _current_thinking(blocks: list) -> str:
    return ''.join(str(block.get('thinking') or '') for block in blocks if block.get('type') == 'thinking')


def _last_text(blocks: list) -> dict | None:
    for block in reversed(blocks):
        if block.get('type') == 'text':
            return block
    return None


def _meta_event(conversation: dict, message: dict, skill, reason: str, run_id: str, context_meta: dict) -> dict:
    return {
        'type': 'meta',
        'conversation_id': conversation['id'],
        'message_id': message['id'],
        'turn_id': (message.get('meta') or {}).get('turn_id') or message['id'],
        'run_id': run_id,
        'provider': message.get('provider') or conversation.get('provider') or '',
        'model': message.get('model') or conversation.get('model') or '',
        'skill': skill.id,
        'skill_name_key': skill.name_key,
        'skill_reason': reason,
        'context': context_meta,
    }


class AgentService:
    """One turn, with its provider rounds, tools and pending question."""

    def send(self, conversation_id: str, payload: dict):
        text = str(payload.get('text') or '').strip()
        raw_attachments = payload.get('attachments') or []
        if not text and not raw_attachments:
            raise AIError('ai.apiNoText', kind='bad_request')
        provider_id = str(payload.get('provider') or 'deepseek')
        model = str(payload.get('model') or '')
        api_key = str(payload.get('api_key') or '')
        thinking = bool(payload.get('thinking'))
        web_search = bool(payload.get('web_search'))
        provider, model = _validate_provider(provider_id, model, api_key, thinking, web_search)
        conversation = store.get_conversation(conversation_id) if conversation_id else None
        if conversation is None:
            conversation = store.create_conversation(provider_id, model, str(payload.get('skill') or 'auto'))
        requested_skill = str(payload.get('skill') or 'auto')
        skill_id = requested_skill
        agent_mode = 'plan' if str(payload.get('agent_mode') or '').lower() == 'plan' else 'build'
        if skill_id == 'auto':
            skill_id = skills.route(text, str((payload.get('context') or {}).get('page') or ''))
        skill = skills.get_skill(skill_id)
        available, reason = skills.availability(skill, provider, model)
        if not available:
            parsed = skills.reason_text(reason)
            if parsed:
                raise AIError(parsed[0], kind='capability', **parsed[1])
            raise AIError('ai.skillUnknown', kind='capability', skill=skill_id)
        _abandon_pending(conversation['id'])
        lang = str(payload.get('locale') or 'zh')
        reminder = (
            _latest_reminder(lang, str(payload.get('location') or ''))
            if provider.supports('latest_reminder', model)
            else ''
        )
        context_payload = dict(payload.get('context') or {})
        if payload.get('scope'):
            context_payload['scope'] = str(payload['scope'])
        context_text, context_meta = context_builder.build_context(text, context_payload)
        references_text, reference_files = references.resolve(payload.get('references') or [])
        if references_text:
            context_text = f'{context_text}\n\n{references_text}'.strip()
        skill_meta = {
            'skill': skill.id,
            'skill_reason': requested_skill,
            'provider': provider_id,
            'model': model,
            'thinking': thinking,
            'web_search': web_search,
            'safety': str(payload.get('safety') or get_setting('ai_safety_level') or 'high'),
            'locale': lang,
            'agent_mode': agent_mode,
            'context_text': context_text,
            'context_meta': context_meta,
            'latest_reminder': reminder,
        }
        attachments = []
        # A file named with `@` lives in a conversation of its own; the caller picked it from a
        # list this account owns, so that row is allowed through the same check as a fresh upload.
        referenced_ids = {str(row.get('id') or '') for row in reference_files}
        for attachment_id in payload.get('attachments') or ():
            row = store.get_attachment(str(attachment_id))
            if row is None or (row.get('conversation_id') != conversation['id'] and row['id'] not in referenced_ids):
                raise AIError('ai.fileUnsupported', kind='bad_request')
            if not provider.supports('files', model):
                raise AIError(
                    'ai.capabilityRefused',
                    kind='capability',
                    provider=provider.spec.id,
                    model=model,
                    capability='files',
                )
            attachments.append(
                {
                    'id': row['id'],
                    'file_id': row.get('file_id') or '',
                    'kind': 'image' if str(row.get('mime') or '').startswith('image/') else 'document',
                    'name': row.get('name') or 'file',
                    'purpose': row.get('purpose') or '',
                }
            )
        for row in reference_files:
            if not provider.supports('files', model) or not row.get('file_id'):
                continue
            attachments.append(
                {
                    'id': str(row.get('id') or ''),
                    'file_id': row.get('file_id') or '',
                    'kind': 'image' if str(row.get('mime') or '').startswith('image/') else 'document',
                    'name': row.get('name') or 'file',
                    'purpose': row.get('purpose') or '',
                }
            )
        if attachments:
            skill_meta['attachments'] = attachments
        # An automatic turn started by a run monitor is marked so the transcript can say so —
        # and so a reader can tell a machine notice from something the user typed.
        if payload.get('monitor_event_id'):
            skill_meta['monitor_event'] = str(payload['monitor_event_id'])[:80]
        # A note posted by the workspace itself (a failed apply, a failed run) is marked so the
        # transcript can show it as machine feedback rather than something the user typed.
        if payload.get('feedback'):
            skill_meta['feedback'] = True
        user = store.append_message(
            conversation['id'],
            'user',
            text,
            status='done',
            provider=provider_id,
            model=model,
            meta=skill_meta,
        )
        turn_id = user['id']
        if not conversation.get('title'):
            store.touch_conversation(conversation['id'], title=_fallback_title(text), title_source='fallback')
        run = store.create_run(conversation['id'], user['id'])
        return self._loop(
            conversation=conversation,
            turn_id=turn_id,
            skill=skill,
            skill_reason=requested_skill,
            provider=provider,
            model=model,
            api_key=api_key,
            thinking=thinking,
            web_search=web_search,
            safety=skill_meta['safety'],
            context_text=context_text,
            context_meta=context_meta,
            run_id=run['id'],
            agent_mode=agent_mode,
        )

    def retry(self, conversation_id: str, api_key: str = ''):
        """Run the last user turn again, with the settings that turn was sent with.

        A Codex/Claude-Code staple: when an answer is wrong or the provider failed, you retry
        instead of retyping the question. It is ONE new run of the SAME turn (same skill, model,
        thinking, context), not a second user message — so the transcript's history stays honest.
        """
        conversation = store.get_conversation(conversation_id)
        if conversation is None:
            raise AIError('ai.apiNoConversation', kind='not_found', conversation=conversation_id)
        user = None
        for message in reversed(store.list_messages(conversation_id, limit=400)):
            if message['role'] == 'user':
                user = message
                break
        if user is None:
            raise AIError('ai.apiNoText', kind='bad_request')
        meta = user.get('meta') or {}
        provider, model = _validate_provider(
            meta.get('provider') or 'deepseek',
            meta.get('model') or '',
            api_key,
            bool(meta.get('thinking')),
            bool(meta.get('web_search')),
        )
        skill = skills.get_skill(meta.get('skill') or 'auto')
        run = store.create_run(conversation_id, user['id'])
        return self._loop(
            conversation=conversation,
            turn_id=user['id'],
            skill=skill,
            skill_reason=str(meta.get('skill_reason') or meta.get('skill') or skill.id),
            provider=provider,
            model=model,
            api_key=api_key,
            thinking=bool(meta.get('thinking')),
            web_search=bool(meta.get('web_search')),
            safety=str(meta.get('safety') or 'high'),
            context_text=str(meta.get('context_text') or ''),
            context_meta=meta.get('context_meta') or {},
            run_id=run['id'],
            agent_mode='plan' if str(meta.get('agent_mode') or '') == 'plan' else 'build',
        )

    def answer(self, conversation_id: str, message_id: str, question_id: str, answers: list, api_key: str = ''):
        question = store.get_question(question_id)
        if question is None or question.get('conversation_id') != conversation_id:
            raise AIError('ai.apiNoQuestion', kind='bad_request', question=question_id)
        if question.get('status') != 'pending':
            raise AIError('ai.apiAlreadyAnswered', kind='bad_request')
        answered = store.answer_question(question_id, {'answers': answers})
        if answered is None:
            raise AIError('ai.apiAlreadyAnswered', kind='bad_request')
        # An approval question becomes a grant (or not) BEFORE the turn resumes. ``settle`` only
        # matches the two allow labels, so a denial, a cancel and a custom answer grant nothing.
        custom = next(
            (str(item.get('custom') or '') for item in answers or () if isinstance(item, dict) and item.get('custom')),
            '',
        )
        approvals.settle(conversation_id, str(question.get('tool_use_id') or ''), answers, custom=custom)
        assistant = store.get_message(message_id)
        if assistant is None:
            raise AIError('ai.apiNoMessage', kind='bad_request', message=message_id)
        tool_result = {
            'kind': 'answer_to_pending_question',
            'tool': 'ask_user_question',
            'call_id': question.get('tool_use_id') or '',
            'questions': question.get('questions') or [],
            'answers': answers,
        }
        store.append_message(
            conversation_id,
            'tool',
            json.dumps(tool_result, ensure_ascii=False),
            status='done',
            meta={'turn_id': (assistant.get('meta') or {}).get('turn_id') or message_id},
        )
        tool_call_id = question.get('tool_use_id') or ''
        # The tool result has to name the call; the store helper takes the content but the
        # serializer reads meta.tool_call_id.
        last = store.list_messages(conversation_id, limit=1)
        if last and last[-1]['role'] == 'tool':
            store.update_message(
                last[-1]['id'],
                meta={
                    'turn_id': (assistant.get('meta') or {}).get('turn_id') or message_id,
                    'tool_call_id': tool_call_id,
                },
            )
        store.update_message(assistant['id'], status='done')
        store.update_run((assistant.get('meta') or {}).get('run_id') or '', status='running')
        user = _turn_user(conversation_id, (assistant.get('meta') or {}).get('turn_id') or '')
        if user is None:
            raise AIError('ai.apiNoMessage', kind='bad_request', message=message_id)
        meta = user.get('meta') or {}
        provider, model = _validate_provider(
            meta.get('provider') or 'deepseek',
            meta.get('model') or '',
            api_key,
            bool(meta.get('thinking')),
            bool(meta.get('web_search')),
        )
        skill = skills.get_skill(meta.get('skill') or 'auto')
        return self._loop(
            conversation=store.get_conversation(conversation_id) or {},
            turn_id=(assistant.get('meta') or {}).get('turn_id') or user['id'],
            skill=skill,
            skill_reason=meta.get('skill_reason') or meta.get('skill') or skill.id,
            provider=provider,
            model=model,
            api_key=api_key,
            thinking=bool(meta.get('thinking')),
            web_search=bool(meta.get('web_search')),
            safety=str(meta.get('safety') or 'high'),
            context_text=str(meta.get('context_text') or ''),
            context_meta=meta.get('context_meta') or {},
            run_id=(assistant.get('meta') or {}).get('run_id') or '',
            agent_mode='plan' if str(meta.get('agent_mode') or '') == 'plan' else 'build',
        )

    def _loop(
        self,
        *,
        conversation: dict,
        turn_id: str,
        skill,
        skill_reason: str,
        provider,
        model: str,
        api_key: str,
        thinking: bool,
        web_search: bool,
        safety: str,
        context_text: str,
        context_meta: dict,
        run_id: str,
        agent_mode: str = 'build',
    ):
        cancel_event = _active(conversation['id'])
        # 0 means "no ceiling": the workspace is a harness, and a task with many files legitimately
        # needs many tools. A finite value is a SOFT stop — the assistant asks the user whether to
        # continue, which is how a limit stays flexible instead of failing the turn.
        max_rounds = max(0, int(get_setting('ai_max_tool_rounds') or 0))
        allow_code = bool(get_setting('ai_allow_code_context'))
        allow_python = bool(get_setting('ai_allow_python')) and environment.capabilities()['code_plugins']
        allow_files = bool(environment.capabilities()['user_files'])
        tool_schemas = tools.schemas(allow_code=allow_code, allow_python=allow_python, allow_files=allow_files)
        offered = set()
        if provider.supports('tools', model) and skill.tools:
            offered = set(skill.tools) | {
                'ask_user_question',
                'update_plan',
                'present_artifact',
                'apply_workflow',
                'rerun_node',
                'request_approval',
                'workflow_schema',
                'workflow_validate',
                'app_errors',
                'workspace_info',
                'workspace_list',
                'workspace_read',
            }
            if allow_files:
                offered |= {'workspace_set', 'workspace_write', 'workspace_import', 'run_cmd'}
            tool_schemas = [tool for tool in tool_schemas if tool['name'] in offered]
        else:
            tool_schemas = []
        if agent_mode == 'plan':
            # Plan is read-only by CONSTRUCTION, not by the model's goodwill: the mutating tools are
            # not offered, so `tools.execute` refuses a replayed call for the same reason.
            blocked = {
                'apply_workflow',
                'rerun_node',
                'workspace_set',
                'workspace_write',
                'workspace_import',
                'run_cmd',
                'python_run',
                'python_save_script',
                'python_write',
            }
            offered -= blocked
            tool_schemas = [tool for tool in tool_schemas if tool['name'] not in blocked]
        system = _system_prompt(skill, provider, model, agent_mode)
        rounds = 0
        state: dict = {}
        try:
            while True:
                if cancel_event.is_set():
                    raise AIError('ai.cancelled', kind='cancelled')
                if max_rounds and rounds > max_rounds:
                    # The budget is a decision for the user, not a wall. Ask once; the answer resumes
                    # the turn with a fresh budget, and "stop" lets the model summarise what it has.
                    asked = yield from self._ask_budget(conversation, state, run_id, rounds)
                    if asked:
                        yield {'type': 'paused', 'message_id': state['message']['id'], 'reason': 'tool_budget'}
                        return
                history = _history(conversation['id'])
                request = {
                    'provider': provider.spec.id,
                    'model': model,
                    'api_key': api_key,
                    'system': system,
                    'messages': history,
                    'tools': tool_schemas,
                    'thinking': thinking,
                    'web_search': web_search,
                    'safety': safety,
                    'title': rounds == 0 and not (conversation.get('title') or ''),
                    'context_text': context_text if rounds == 0 else '',
                    'reasoning_effort': 'high',
                    'max_tokens': 8192,
                    'timeout': int(get_setting('ai_request_timeout') or 180),
                    'cancel_event': cancel_event,
                    'session_id': f'ses_{conversation["id"]}',
                    'user_id': _user_key(),
                    'host': str(get_setting('ollama_host') or ''),
                }
                state = yield from self._round(
                    conversation=conversation,
                    turn_id=turn_id,
                    provider=provider,
                    request=request,
                    skill=skill,
                    skill_reason=skill_reason,
                    run_id=run_id,
                    context_meta=context_meta,
                    seed=rounds == 0,
                )
                if state.get('error'):
                    return
                calls = state.get('tool_calls') or []
                if not calls:
                    yield {
                        'type': 'done',
                        'stop_reason': state.get('stop_reason') or 'end_turn',
                        'title': state.get('title') or '',
                    }
                    return
                rounds += 1
                paused_for_approval = False
                if any(call['name'] == 'ask_user_question' for call in calls):
                    waiting = self._ask_user(conversation, state, calls, run_id)
                    yield waiting['event']
                    yield {'type': 'paused', 'message_id': state['message']['id'], 'reason': 'awaiting_user'}
                    return
                for call in calls:
                    if call['name'] == 'ask_user_question':
                        continue
                    if call['name'] == 'update_plan':
                        yield from self._plan_event(conversation, state, call, run_id)
                        continue
                    if call['name'] == 'present_artifact':
                        yield from self._artifact_event(conversation, state, call, run_id)
                        continue
                    if call['name'] == 'apply_workflow':
                        yield from self._apply_workflow_event(conversation, state, call, run_id)
                        continue
                    if call['name'] == 'rerun_node':
                        yield from self._rerun_event(conversation, state, call, run_id)
                        continue
                    if call['name'] == 'request_approval':
                        # The turn pauses on the question; the answer resumes it exactly like the tool
                        # budget's. Finishing the loop first keeps every other tool_use paired.
                        asked = yield from self._approval_event(conversation, state, call, run_id)
                        paused_for_approval = paused_for_approval or asked
                        continue
                    yield from self._tool_event(
                        conversation, state, call, turn_id, api_key, provider.spec.id, model, offered
                    )
                if paused_for_approval:
                    yield {'type': 'paused', 'message_id': state['message']['id'], 'reason': 'awaiting_approval'}
                    return
        finally:
            clear_active(conversation['id'])

    def _round(
        self,
        *,
        conversation: dict,
        turn_id: str,
        provider,
        request: dict,
        skill,
        skill_reason: str,
        run_id: str,
        context_meta: dict,
        seed: bool = False,
    ):
        assistant = store.append_message(
            conversation['id'],
            'assistant',
            '',
            blocks=[],
            status='streaming',
            provider=provider.spec.id,
            model=request['model'],
            meta={'turn_id': turn_id, 'run_id': run_id, 'skill': skill.id},
        )
        yield _meta_event(conversation, assistant, skill, skill_reason, run_id, context_meta)
        blocks = list(assistant.get('blocks') or [])
        if seed:
            # First row of the turn: say which skill answered and why, IN the transcript's order.
            # Without it a conversation reopened from the store could not tell an automatic route
            # from a user's choice — the fact lived only in the meta of a user row.
            blocks.append({'type': 'skill', 'name': skill.id, 'reason': skill_reason or skill.id})
        usage = dict(assistant.get('usage') or {})
        stop_reason = ''
        title = ''
        tool_calls = []
        current_kind = ''
        last_flush = time.monotonic()

        def flush(force: bool = False) -> None:
            nonlocal last_flush
            if not force and time.monotonic() - last_flush < 1.0:
                return
            last_flush = time.monotonic()
            store.update_message(
                assistant['id'],
                status='streaming',
                content=_current_text(blocks),
                blocks=blocks,
                usage=usage,
            )

        try:
            for event in provider.stream(request):
                kind = str(event.get('type') or '')
                if kind == 'thinking_delta':
                    text = str(event.get('text') or '')
                    if not text:
                        continue
                    if current_kind != 'thinking' or not blocks or blocks[-1].get('type') != 'thinking':
                        _append_block(blocks, {'type': 'thinking', 'thinking': '', 'signature': ''})
                        current_kind = 'thinking'
                    blocks[-1]['thinking'] = str(blocks[-1].get('thinking') or '') + text
                    yield {'type': 'thinking', 'text': text}
                    flush()
                elif kind == 'thinking_signature':
                    if blocks and blocks[-1].get('type') == 'thinking':
                        blocks[-1]['signature'] = str(event.get('signature') or '')
                    flush(force=True)
                elif kind == 'text_delta':
                    text = str(event.get('text') or '')
                    if not text:
                        continue
                    if current_kind != 'text' or not blocks or blocks[-1].get('type') != 'text':
                        _append_block(blocks, {'type': 'text', 'text': '', 'citations': []})
                        current_kind = 'text'
                    blocks[-1]['text'] = str(blocks[-1].get('text') or '') + text
                    yield {'type': 'text', 'text': text}
                    flush()
                elif kind == 'citation':
                    citation = event.get('citation') or {}
                    block = _last_text(blocks)
                    if block is not None:
                        block.setdefault('citations', []).append(citation)
                    yield {'type': 'citation', 'citation': citation}
                elif kind == 'server_tool':
                    block = event.get('block') or {}
                    _append_block(blocks, block)
                    yield {'type': 'server_tool', 'block': block}
                    flush(force=True)
                elif kind == 'tool_call':
                    call = {
                        'id': str(event.get('id') or new_id('call')),
                        'name': str(event.get('name') or ''),
                        'arguments': event.get('arguments') if isinstance(event.get('arguments'), dict) else {},
                        'raw_arguments': str(event.get('raw_arguments') or ''),
                    }
                    _append_block(
                        blocks,
                        {'type': 'tool_use', 'id': call['id'], 'name': call['name'], 'input': call['arguments']},
                    )
                    tool_calls.append(call)
                    yield {'type': 'tool_call', 'id': call['id'], 'name': call['name'], 'arguments': call['arguments']}
                    flush(force=True)
                elif kind == 'usage':
                    usage = {**usage, **usage_totals(event.get('usage') or {})}
                    store.save_usage(conversation['id'], assistant['id'], provider.spec.id, request['model'], usage)
                    yield {'type': 'usage', 'usage': usage}
                elif kind == 'title':
                    title = str(event.get('title') or '').strip()
                    if title:
                        store.touch_conversation(conversation['id'], title=title, title_source='provider')
                        conversation['title'] = title
                        yield {'type': 'title', 'title': title}
                elif kind == 'refusal':
                    for block in blocks:
                        if block.get('type') in ('text', 'thinking'):
                            block['type'] = 'refused'
                    blocks = [block for block in blocks if block.get('type') != 'refused']
                    stop_reason = 'refusal'
                    yield {'type': 'refusal', 'reason': str(event.get('reason') or '')}
                elif kind == 'done':
                    stop_reason = str(event.get('stop_reason') or stop_reason or 'end_turn')
                    break
            flush(force=True)
            store.update_message(
                assistant['id'],
                status='done',
                content=_current_text(blocks),
                blocks=blocks,
                usage=usage,
                meta={**(assistant.get('meta') or {}), 'stop_reason': stop_reason, 'tool_calls': tool_calls},
            )
            if not conversation.get('title') and title == '':
                store.touch_conversation(
                    conversation['id'],
                    title=_fallback_title(_current_text(blocks) or t('ai.newConversation')),
                    title_source='fallback',
                )
            return {
                'message': store.get_message(assistant['id']) or assistant,
                'blocks': blocks,
                'usage': usage,
                'stop_reason': stop_reason,
                'tool_calls': tool_calls,
                'title': title,
            }
        except AIError as exc:
            store.update_message(
                assistant['id'],
                status='error',
                content=_current_text(blocks),
                blocks=blocks,
                meta={**(assistant.get('meta') or {}), 'error': exc.localized()},
            )
            if exc.kind == 'cancelled':
                yield {'type': 'done', 'stop_reason': 'cancelled'}
                return {
                    'message': assistant,
                    'blocks': blocks,
                    'usage': usage,
                    'stop_reason': 'cancelled',
                    'tool_calls': [],
                    'error': 'cancelled',
                }
            raise

    def _ask_budget(self, conversation: dict, state: dict, run_id: str, rounds: int):
        """A soft tool budget: the assistant ASKS before it is stopped, and the answer resumes.

        The question is attached to the round that just completed as an assistant ``tool_use`` so the
        provider's tool-pair rule stays valid after the answer: assistant(tool_use X) → tool result X.
        """
        call = {
            'id': new_id('call'),
            'name': 'ask_user_question',
            'arguments': {
                'questions': [
                    {
                        'id': 'tool_budget',
                        'header': t('ai.toolBudgetHeader'),
                        'question': t('ai.toolBudgetQuestion', rounds=rounds),
                        'options': [
                            {'label': t('ai.toolBudgetContinue'), 'description': t('ai.toolBudgetContinueHint')},
                            {'label': t('ai.toolBudgetStop'), 'description': t('ai.toolBudgetStopHint')},
                        ],
                    }
                ]
            },
        }
        waiting = self._attach_question(conversation, state, call, run_id)
        yield waiting['event']
        return True

    def _attach_question(self, conversation: dict, state: dict, call: dict, run_id: str) -> dict:
        """Add a synthesized ``ask_user_question`` tool_use to the finished round and ask it.

        Shared by the tool budget and the approval card: both pause a turn that already produced its
        answer blocks, and the provider requires that every ``tool_use`` block has a tool result.
        """
        message = store.get_message(state['message']['id']) or state['message']
        blocks = list(message.get('blocks') or [])
        blocks.append({'type': 'tool_use', 'id': call['id'], 'name': 'ask_user_question', 'input': call['arguments']})
        meta = dict(message.get('meta') or {})
        meta['tool_calls'] = list(meta.get('tool_calls') or []) + [call]
        store.update_message(message['id'], blocks=blocks, meta=meta)
        return self._ask_user(conversation, {'message': {**message, 'blocks': blocks, 'meta': meta}}, [call], run_id)

    def _ask_user(self, conversation: dict, state: dict, calls: list, run_id: str) -> dict:
        call = next((item for item in calls if item['name'] == 'ask_user_question'), None)
        if call is None:
            raise AIError('ai.toolUnknown', kind='bad_request', tool='ask_user_question')
        questions = call['arguments'].get('questions') if isinstance(call.get('arguments'), dict) else None
        if not isinstance(questions, list) or not questions:
            raise AIError('ai.toolRefused', kind='bad_request', tool='ask_user_question', reason='questions is missing')
        normalized = []
        for item in questions[:5]:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    'id': str(item.get('id') or new_id('q')),
                    'question': str(item.get('question') or ''),
                    'header': str(item.get('header') or ''),
                    'options': [
                        {
                            'label': str(option.get('label') or ''),
                            'description': str(option.get('description') or ''),
                            # A runtime-synthesized choice may name itself stably ('once'/'session'/
                            # 'deny') so the browser can style a denial without matching a sentence.
                            'value': str(option.get('value') or ''),
                        }
                        for option in item.get('options') or []
                        if isinstance(option, dict) and option.get('label')
                    ],
                    'multi_select': bool(item.get('multi_select')),
                    # An approval question is painted as a danger-toned card; the browser keys on
                    # this token, never on a translated sentence.
                    'kind': str(item.get('kind') or ''),
                }
            )
        if not normalized:
            raise AIError('ai.toolRefused', kind='bad_request', tool='ask_user_question', reason='no valid question')
        question = store.create_question(conversation['id'], state['message']['id'], call['id'], normalized)
        store.update_message(
            state['message']['id'],
            status='waiting',
            meta={**(state['message'].get('meta') or {}), 'question_id': question['id']},
        )
        store.update_run(run_id, status='waiting')
        store.add_step(
            run_id, t('ai.stepAwaiting'), tool='ask_user_question', args={'questions': normalized}, status='running'
        )
        return {
            'event': {
                'type': 'question',
                'question_id': question['id'],
                'message_id': state['message']['id'],
                'tool_call_id': call['id'],
                'questions': normalized,
            }
        }

    def _plan_event(self, conversation: dict, state: dict, call: dict, run_id: str):
        steps = call.get('arguments', {}).get('steps') if isinstance(call.get('arguments'), dict) else []
        plan = [
            {'title': str(step.get('title') or ''), 'status': str(step.get('status') or 'pending')}
            for step in steps or []
            if isinstance(step, dict) and step.get('title')
        ]
        store.update_run(run_id, plan=plan)
        for step in plan:
            store.add_step(run_id, step['title'], status='done' if step['status'] == 'done' else 'pending')
        # Keep the plan IN the turn's block stream: the transcript then shows "what it planned"
        # at the point it planned it, even after a reload (the tool row alone reads like a log).
        message = store.get_message(state['message']['id'])
        if message is not None:
            blocks = list(message.get('blocks') or [])
            blocks.append({'type': 'plan', 'steps': plan})
            store.update_message(message['id'], blocks=blocks, content=_current_text(blocks))
        store.append_message(
            conversation['id'],
            'tool',
            json.dumps({'ok': True, 'plan': plan}, ensure_ascii=False),
            status='done',
            meta={'turn_id': state['message'].get('meta', {}).get('turn_id') or '', 'tool_call_id': call['id']},
        )
        yield {'type': 'plan', 'steps': plan, 'run_id': run_id}

    def _artifact_event(self, conversation: dict, state: dict, call: dict, run_id: str):
        args = call.get('arguments') if isinstance(call.get('arguments'), dict) else {}
        artifact = {
            'id': new_id('art'),
            'title': str(args.get('title') or t('ai.artifact')),
            'kind': str(args.get('kind') or 'markdown'),
            'payload': args.get('payload') if isinstance(args.get('payload'), dict) else {},
            'summary': str(args.get('summary') or ''),
        }
        meta = {'turn_id': state['message'].get('meta', {}).get('turn_id') or '', 'tool_call_id': call['id']}
        if artifact['kind'] in ('workflow', 'workflow_draft'):
            # A draft the canvas cannot load is refused by name, with the offending node — applying
            # it used to leave blank boxes and a 500 on every diagnostics poll. Structure AND the
            # engine's run validation are asked, so "it loads" and "it can run" agree.
            #
            # The refusal goes back to the MODEL as this call's tool result, never up as an AIError.
            # Raising ended the turn with the tool_use unpaired: the user saw “工作流草稿无法载入” and
            # nothing repaired the draft, and the NEXT message was refused by the provider
            # (“unresolved tool call”) because that call never got an answer.
            report = workflow_draft.validate(artifact['payload'])
            if not report['ok']:
                problems = (report['structural'] + report['engine'])[:8]
                message = t('ai.workflowDraftInvalid', detail='; '.join(problems))
                store.append_message(
                    conversation['id'],
                    'tool',
                    json.dumps({'ok': False, 'error': message, 'problems': report}, ensure_ascii=False),
                    status='done',
                    meta={**meta, 'is_error': True, 'name': 'present_artifact'},
                )
                store.add_step(
                    run_id, t('ai.stepTool', tool='present_artifact'), tool='present_artifact', status='failed'
                )
                yield {
                    'type': 'tool_result',
                    'id': call['id'],
                    'name': 'present_artifact',
                    'ok': False,
                    'error': message,
                }
                return
        store.append_message(
            conversation['id'],
            'tool',
            json.dumps({'ok': True, 'artifact': artifact}, ensure_ascii=False),
            status='done',
            meta=meta,
        )
        store.add_step(run_id, artifact['title'], tool='present_artifact', args=artifact, status='done')
        yield {'type': 'artifact', 'artifact': artifact}

    def _apply_workflow_event(self, conversation: dict, state: dict, call: dict, run_id: str):
        """Validate → save → load on the canvas, in that order.

        ``present_artifact`` leaves a proposal the user must click; this is the assistant actually
        doing it, which is what a harness is for. Nothing is applied until the file is legal for the
        engine, and every problem is answered to the MODEL as a tool result, so it can repair its own
        draft in the same turn instead of the user reporting a blank canvas.
        """
        args = call.get('arguments') if isinstance(call.get('arguments'), dict) else {}
        payload = args.get('workflow') if isinstance(args.get('workflow'), dict) else None
        meta = {'turn_id': state['message'].get('meta', {}).get('turn_id') or '', 'tool_call_id': call['id']}
        if payload is None:
            message = t('ai.workflowDraftInvalid', detail='workflow is missing')
            store.append_message(
                conversation['id'],
                'tool',
                json.dumps({'ok': False, 'error': message}, ensure_ascii=False),
                status='done',
                meta={**meta, 'is_error': True, 'name': 'apply_workflow'},
            )
            yield {'type': 'tool_result', 'id': call['id'], 'name': 'apply_workflow', 'ok': False, 'error': message}
            return
        report = workflow_draft.validate(payload)
        if not report['ok']:
            detail = '; '.join((report['structural'] + report['engine'])[:8])
            message = t('ai.workflowDraftInvalid', detail=detail)
            store.append_message(
                conversation['id'],
                'tool',
                json.dumps({'ok': False, 'error': message, 'problems': report}, ensure_ascii=False),
                status='done',
                meta={**meta, 'is_error': True, 'name': 'apply_workflow'},
            )
            store.add_step(run_id, t('ai.stepTool', tool='apply_workflow'), tool='apply_workflow', status='failed')
            yield {'type': 'tool_result', 'id': call['id'], 'name': 'apply_workflow', 'ok': False, 'error': message}
            return
        try:
            saved = workflow_draft.save(payload, str(args.get('name') or ''))
        except Exception as exc:  # a disk that cannot write is a named refusal, not a traceback
            message = t('ai.workflowSaveFailed', detail=str(exc)[:200])
            store.append_message(
                conversation['id'],
                'tool',
                json.dumps({'ok': False, 'error': message}, ensure_ascii=False),
                status='done',
                meta={**meta, 'is_error': True, 'name': 'apply_workflow'},
            )
            yield {'type': 'tool_result', 'id': call['id'], 'name': 'apply_workflow', 'ok': False, 'error': message}
            return
        result = {
            'ok': True,
            'name': saved['name'],
            'run': bool(args.get('run')),
            'summary': str(args.get('summary') or ''),
        }
        store.append_message(
            conversation['id'],
            'tool',
            json.dumps(result, ensure_ascii=False),
            status='done',
            meta={**meta, 'name': 'apply_workflow'},
        )
        store.add_step(run_id, saved['name'], tool='apply_workflow', args=result, status='done')
        yield {'type': 'tool_result', 'id': call['id'], 'name': 'apply_workflow', 'ok': True, 'result': result}
        yield {'type': 'workflow_apply', 'workflow': payload, 'name': saved['name'], 'run': bool(args.get('run'))}

    def _rerun_event(self, conversation: dict, state: dict, call: dict, run_id: str):
        """Re-run one failed subtree from the SAVED workflow file — never from a canvas load.

        A monitor's failure answer should be able to fix the run the user is looking at without the
        assistant replacing what is on their canvas. The file is the authority: it must still match
        the run record's fingerprint, or the rerun would mix two canvases under one run id.
        """
        args = call.get('arguments') if isinstance(call.get('arguments'), dict) else {}
        meta = {'turn_id': state['message'].get('meta', {}).get('turn_id') or '', 'tool_call_id': call['id']}
        failed_run = str(args.get('run_id') or '').strip()
        workflow_name = str(args.get('workflow_name') or '').strip()
        node_id = str(args.get('node_id') or '').strip()

        def refuse(message: str, name: str = 'rerun_node'):
            store.append_message(
                conversation['id'],
                'tool',
                json.dumps({'ok': False, 'error': message}, ensure_ascii=False),
                status='done',
                meta={**meta, 'is_error': True, 'name': name},
            )
            store.add_step(run_id, t('ai.stepTool', tool=name), tool=name, status='failed')
            return {'type': 'tool_result', 'id': call['id'], 'name': name, 'ok': False, 'error': message}

        if not failed_run or not workflow_name or not node_id:
            yield refuse(t('ai.rerunArgs'))
            return
        try:
            tools.require_approval('rerun_node', args, {'conversation_id': conversation['id']})
        except AIError as exc:
            yield refuse(exc.localized())
            return
        from runtime.stores import get_workflow_manager

        try:
            workflow = get_workflow_manager().load(workflow_name)
        except OSError as exc:  # a disk that cannot read is a named refusal, not a traceback
            yield refuse(t('ai.rerunNoWorkflow', name=workflow_name) + ' ' + str(exc)[:160])
            return
        if not workflow:
            yield refuse(t('ai.rerunNoWorkflow', name=workflow_name))
            return
        from engine.workflow_rerun import RerunRefusalError, rerun_node

        try:
            answer = rerun_node(workflow, node_id, failed_run, workflow_name=workflow_name, lang=get_lang())
        except RerunRefusalError as exc:
            yield refuse(tools.rerun_refusal_message(exc))
            return
        body = answer.get('body') or {}
        if not body.get('ok'):
            yield refuse(str(body.get('error') or t('ai.toolFailed', detail='rerun refused')))
            return
        result = {
            'ok': True,
            'run_id': failed_run,
            'node_id': node_id,
            'workflow_name': workflow_name,
            'invalidated': list(body.get('invalidated') or []),
            'queued': bool(body.get('queued')),
        }
        store.append_message(
            conversation['id'],
            'tool',
            json.dumps(result, ensure_ascii=False),
            status='done',
            meta={**meta, 'name': 'rerun_node'},
        )
        store.add_step(run_id, t('ai.stepTool', tool='rerun_node'), tool='rerun_node', args=result, status='done')
        yield {'type': 'tool_result', 'id': call['id'], 'name': 'rerun_node', 'ok': True, 'result': result}
        yield {
            'type': 'rerun_started',
            'run_id': failed_run,
            'node_id': node_id,
            'workflow_name': workflow_name,
            'invalidated': result['invalidated'],
        }

    def _approval_event(self, conversation: dict, state: dict, call: dict, run_id: str):
        """Ask 允许一次 / 本次会话允许 / 拒绝 before a mutating tool runs.

        The question is a normal ``ask_user_question`` card (so the answer resumes the turn the same
        way the tool budget's does), and the answer is turned into a grant by ``ai.approvals`` at
        resume time. Its id, header and ``kind`` mark it for the danger-toned card in the browser.
        """
        args = call.get('arguments') if isinstance(call.get('arguments'), dict) else {}
        meta = {'turn_id': state['message'].get('meta', {}).get('turn_id') or '', 'tool_call_id': call['id']}
        action = str(args.get('action') or '').strip()
        detail = args.get('detail')
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except ValueError:
                detail = None
        if not action or not isinstance(detail, dict):
            message = t('ai.approvalNoArgs')
            store.append_message(
                conversation['id'],
                'tool',
                json.dumps({'ok': False, 'error': message}, ensure_ascii=False),
                status='done',
                meta={**meta, 'is_error': True, 'name': 'request_approval'},
            )
            yield {'type': 'tool_result', 'id': call['id'], 'name': 'request_approval', 'ok': False, 'error': message}
            return False
        labels = {'once': t('ai.approvalOnce'), 'session': t('ai.approvalSession'), 'deny': t('ai.approvalDeny')}
        summary = str(args.get('summary') or '').strip()
        ask = {
            'id': new_id('call'),
            'name': 'ask_user_question',
            'arguments': {
                'questions': [
                    {
                        'id': 'approval',
                        'kind': 'approval',
                        'header': t('ai.approvalHeader', tool=action),
                        'question': t('ai.approvalQuestion', tool=action, summary=summary),
                        'options': [
                            {'label': labels['once'], 'value': 'once', 'description': t('ai.approvalOnceHint')},
                            {
                                'label': labels['session'],
                                'value': 'session',
                                'description': t('ai.approvalSessionHint'),
                            },
                            {'label': labels['deny'], 'value': 'deny', 'description': t('ai.approvalDenyHint')},
                        ],
                    }
                ]
            },
        }
        approvals.request(conversation['id'], action, detail, ask['id'], labels)
        waiting = self._attach_question(conversation, state, ask, run_id)
        yield waiting['event']
        return True

    def _tool_event(
        self,
        conversation: dict,
        state: dict,
        call: dict,
        turn_id: str,
        api_key: str = '',
        provider: str = '',
        model: str = '',
        offered=None,
    ):
        name = call['name']
        step = store.add_step(
            (state['message'].get('meta') or {}).get('run_id') or '',
            t('ai.stepTool', tool=name),
            tool=name,
            args=call.get('arguments') or {},
            status='running',
        )
        yield {
            'type': 'tool_start',
            'id': call['id'],
            'name': name,
            'arguments': call.get('arguments') or {},
            'step_id': step['id'],
        }
        try:
            result = tools.execute(
                name,
                call.get('arguments') or {},
                {
                    'turn_id': turn_id,
                    'conversation_id': conversation['id'],
                    'api_key': api_key,
                    'provider': provider,
                    'model': model,
                },
                offered,
            )
            text = json.dumps(result, ensure_ascii=False, default=str)
            # The tool result is what the provider is billed for. A dataset or script output can be
            # enormous; the workspace's own tools are bounded, and this is the last backstop. The cap
            # is a setting (default 12k) rather than a constant: a turn that truly needs more asks
            # the user to raise it instead of being silently cut.
            limit_chars = max(2000, int(get_setting('ai_max_tool_result_chars') or 12000))
            if len(text) > limit_chars:
                text = (
                    text[:limit_chars]
                    + f'\n…[truncated at {limit_chars} chars by the workspace; use a narrower page, or ask the user'
                    ' to raise ai_max_tool_result_chars]'
                )
            is_error = False
            store.update_step(step['id'], status='done', result=result)
            # The browser renders the tool card from this event; the cap above only bounded what the
            # model and the store receive, so an enormous result still crossed the wire.
            shown = result if len(text) <= limit_chars else {'truncated': text}
        except AIError as exc:
            text = json.dumps({'error': exc.localized(), 'key': exc.key}, ensure_ascii=False)
            is_error = True
            store.update_step(step['id'], status='failed', result={'error': exc.localized()})
            yield {'type': 'tool_result', 'id': call['id'], 'name': name, 'ok': False, 'error': exc.localized()}
        except Exception as exc:  # a malformed argument is a tool result, not a broken conversation
            # Without this, a ValueError from `int(args['rows'])` escaped after the assistant's
            # tool_use was stored, leaving a call with no result: every later turn fails the
            # provider's tool-pair validation, and the conversation cannot be used again.
            message = t('ai.toolFailed', detail=str(exc)[:300])
            text = json.dumps({'error': message, 'key': 'ai.toolFailed'}, ensure_ascii=False)
            is_error = True
            store.update_step(step['id'], status='failed', result={'error': message})
            yield {'type': 'tool_result', 'id': call['id'], 'name': name, 'ok': False, 'error': message}
        else:
            yield {'type': 'tool_result', 'id': call['id'], 'name': name, 'ok': True, 'result': shown}
        store.append_message(
            conversation['id'],
            'tool',
            text,
            status='done',
            meta={'turn_id': turn_id, 'tool_call_id': call['id'], 'name': name, 'is_error': is_error},
        )


def _history(conversation_id: str) -> list:
    messages = store.list_messages(conversation_id, limit=200)
    out = []
    for message in messages:
        if message['status'] in ('error', 'interrupted'):
            continue
        role = message['role']
        if role == 'tool':
            meta = message.get('meta') or {}
            out.append(
                {
                    'role': 'tool',
                    'content': message.get('content') or '',
                    'tool_call_id': meta.get('tool_call_id') or '',
                    'is_error': bool(meta.get('is_error')),
                    'meta': meta,
                }
            )
        elif role in ('user', 'assistant'):
            out.append(
                {
                    'role': role,
                    'content': message.get('content') or '',
                    'blocks': message.get('blocks') or [],
                    'meta': message.get('meta') or {},
                }
            )
    return _repair_tool_pairs(out)


def _repair_tool_pairs(messages: list) -> list:
    """Make every ``tool_use`` in the replay have exactly one result, in place.

    A turn can die between “the model asked for a tool” and “the tool answered”: a stop, a
    crash, a provider fault, an action whose handler raised. The assistant row keeps its
    ``tool_use`` block, no ``tool`` row follows — and every provider then refuses the NEXT
    message with 400 “unresolved tool call”, so one failed turn poisoned the whole
    conversation. The repair answers the missing call with a synthetic result that says it was
    never completed, and drops a ``tool`` row whose call is not in the history at all (its
    assistant row was skipped as an error, so the pair can never be completed).
    """
    if not messages:
        return messages
    known: set[str] = set()
    for message in messages:
        if message['role'] != 'assistant':
            continue
        for block in message.get('blocks') or ():
            if block.get('type') == 'tool_use' and block.get('id'):
                known.add(str(block['id']))
    answered: set[str] = set()
    kept: list = []
    for message in messages:
        if message['role'] != 'tool':
            kept.append(message)
            continue
        call_id = str(message.get('tool_call_id') or '')
        # An orphan (no assistant call in this window) or a second answer to one call would both
        # be refused by the provider; the first real answer is the one that counts.
        if call_id not in known or call_id in answered:
            continue
        answered.add(call_id)
        kept.append(message)
    repaired: list = []
    for message in kept:
        repaired.append(message)
        if message['role'] != 'assistant':
            continue
        for block in message.get('blocks') or ():
            if block.get('type') != 'tool_use' or not block.get('id'):
                continue
            call_id = str(block['id'])
            if call_id in answered:
                continue
            answered.add(call_id)
            repaired.append(
                {
                    'role': 'tool',
                    'content': json.dumps({'ok': False, 'error': t('ai.toolUnanswered')}, ensure_ascii=False),
                    'tool_call_id': call_id,
                    'is_error': True,
                    'meta': {'tool_call_id': call_id, 'name': str(block.get('name') or ''), 'is_error': True},
                }
            )
    return repaired


def _turn_user(conversation_id: str, turn_id: str) -> dict | None:
    for message in store.list_messages(conversation_id, limit=400):
        if message['id'] == turn_id and message['role'] == 'user':
            return message
    return None


def _abandon_pending(conversation_id: str) -> None:
    """A new user message takes the transcript back, so the old question cannot be answered.

    Its approval request must go with it: otherwise a grant nobody chose would survive in memory.
    """
    approvals.revoke(conversation_id)
    pending = store.pending_questions(conversation_id)
    if not pending:
        return
    for question in pending:
        store.answer_question(question['id'], {'answers': [], 'cancelled': True})
        assistant = store.get_message(question.get('message_id') or '')
        if assistant is None:
            continue
        store.update_message(
            assistant['id'], status='done', meta={**(assistant.get('meta') or {}), 'cancelled_question': question['id']}
        )
        store.append_message(
            conversation_id,
            'tool',
            json.dumps(
                {
                    'cancelled': True,
                    'tool': 'ask_user_question',
                    'questions': question.get('questions') or [],
                    'reason': t('ai.questionUnanswered'),
                },
                ensure_ascii=False,
            ),
            status='done',
            meta={
                'turn_id': (assistant.get('meta') or {}).get('turn_id') or assistant['id'],
                'tool_call_id': question.get('tool_use_id') or '',
                'is_error': True,
            },
        )
