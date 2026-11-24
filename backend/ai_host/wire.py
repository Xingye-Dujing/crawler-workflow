"""Host-side wire translation: attachment extraction and the panel's event names.

This is not the engine and it is not the UI: the framework receives text/images, the browser receives
the names it already knows. Keeping both here leaves ``api/ai_workspace.py`` as route wiring.
"""

from __future__ import annotations

import base64

from agent_workspace import AIError as AgentError


def attachments(raw, workspace=None, account: str = '') -> list[dict]:
    """Host-side extraction: the browser sends bytes, the framework only ever sees text/images.

    ``[{'name': 'a.pdf', 'data': '<base64>'}]`` is extracted here with ``ai.file_text``; an entry with
    ``text`` or ``image`` is passed through unchanged; a bare file id is resolved from the stored file
    row (the panel uploads first, then names the ids). Every failure becomes a named refusal, never
    an empty document.
    """
    from ai import file_text
    from ai.errors import AIError as LegacyError

    found = []
    for item in raw or []:
        if isinstance(item, str) and item:
            if workspace is None:
                raise AgentError('attachment.unknownFile', kind='not_found', key='attachment.unknownFile', reason=item)
            row = workspace.store.get_file(item)
            if not row or row.get('account') != account:
                raise AgentError('attachment.unknownFile', kind='not_found', key='attachment.unknownFile', reason=item)
            meta = row.get('meta') or {}
            found.append(
                {
                    'name': str(row.get('name') or ''),
                    'text': str(meta.get('text') or ''),
                    'image': str(meta.get('image') or ''),
                    'file_id': str(row.get('id') or ''),
                }
            )
            continue
        if not isinstance(item, dict):
            raise AgentError('attachment.badShape', kind='bad_request', key='attachment.badShape')
        entry = {'name': str(item.get('name') or '')}
        if item.get('file_id'):
            entry['file_id'] = str(item['file_id'])
        if item.get('text'):
            entry['text'] = str(item['text'])
        elif item.get('data'):
            try:
                data = base64.b64decode(str(item['data']), validate=False)
            except Exception as exc:
                raise AgentError(
                    'attachment.badData',
                    kind='bad_request',
                    key='attachment.badData',
                    reason=str(item.get('name') or ''),
                ) from exc
            try:
                extracted = file_text.extract(str(item.get('name') or ''), data)
            except LegacyError as exc:
                raise AgentError(str(exc), kind='bad_request', key=str(exc.key or 'ai.attachExtract')) from exc
            entry['text'] = str(extracted.get('text') or '')
        if item.get('image'):
            entry['image'] = str(item['image'])
        found.append(entry)
    return found


def legacy_events(events):
    """The frontend's wire names, mapped once at the host edge (the engine stays canonical)."""
    for event in events:
        kind = event.get('type')
        if kind == 'text_delta':
            yield {**event, 'type': 'text'}
        elif kind == 'thinking_delta':
            yield {**event, 'type': 'thinking'}
        elif kind == 'tool_start':
            yield {
                **event,
                'type': 'tool_start',
                'id': event.get('call_id') or '',
                'name': event.get('tool') or '',
                'arguments': event.get('arguments') or {},
            }
        elif kind == 'tool_result':
            ok = not event.get('is_error')
            payload = {**event, 'type': 'tool_result', 'id': event.get('call_id') or '', 'ok': ok}
            if ok:
                payload['result'] = event.get('content')
            else:
                payload['error'] = event.get('content')
            yield payload
        elif kind == 'error':
            yield {**event, 'error': event.get('message') or event.get('error') or ''}
        elif kind == 'citation':
            yield {**event, 'type': 'citation', 'citation': event.get('payload') or {}}
        elif kind == 'server_tool':
            yield {**event, 'type': 'server_tool', 'block': event.get('payload') or {}}
        else:
            yield event
