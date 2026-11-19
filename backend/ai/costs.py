"""What one conversation has spent, in the provider's own prices.

Token counts are FACTS the store recorded; money is a provider's list price, so each transport
answers ``cost()`` and a provider with no published price answers ``None`` — the panel then shows
tokens and the cache rate, and says the money is unknown instead of inventing a number. A cache hit
is not a discount we compute: it is the split DeepSeek itself reports (hit vs miss prompt tokens).
"""

from __future__ import annotations

from datetime import UTC, datetime, time

from runtime.settings import get_setting

from ai import store
from ai.errors import AIError
from ai.providers import get_provider


def conversation_cost(conversation_id: str) -> dict:
    """Totals, a per-model breakdown, the cache hit rate and the estimated money for one chat."""
    rows = store.conversation_usage(conversation_id)
    lines = []
    prompt = completion = cached = reasoning = calls = 0
    amount = 0.0
    currency = ''
    priced = True
    for row in rows:
        model = str(row.get('model') or '')
        provider_id = str(row.get('provider') or '')
        row_prompt = int(row.get('prompt_tokens') or 0)
        row_completion = int(row.get('completion_tokens') or 0)
        row_cached = int(row.get('cached_tokens') or 0)
        prompt += row_prompt
        completion += row_completion
        cached += row_cached
        reasoning += int(row.get('reasoning_tokens') or 0)
        calls += int(row.get('calls') or 0)
        price = None
        try:
            price = get_provider(provider_id).cost(model, row_prompt, row_completion, row_cached)
        except AIError:
            # A provider that was uninstalled since still has rows in this conversation's history.
            price = None
        if price and price.get('amount') is not None:
            amount += float(price['amount'])
            currency = currency or str(price.get('currency') or '')
        else:
            priced = False
        lines.append(
            {
                'provider': provider_id,
                'model': model,
                'prompt_tokens': row_prompt,
                'completion_tokens': row_completion,
                'cached_tokens': row_cached,
                'calls': int(row.get('calls') or 0),
                'cost': price.get('amount') if price else None,
                'currency': str((price or {}).get('currency') or ''),
            }
        )
    hit_rate = round(cached / prompt, 4) if prompt else 0.0
    return {
        'prompt_tokens': prompt,
        'completion_tokens': completion,
        'cached_tokens': cached,
        'reasoning_tokens': reasoning,
        'total_tokens': prompt + completion,
        'cache_hit_rate': hit_rate,
        'calls': calls,
        'cost': round(amount, 6) if (lines and priced) else None,
        'currency': currency,
        # True when every model in this conversation had a published price, so the money is whole.
        'cost_complete': bool(lines) and priced,
        'models': lines,
    }


def _local_day_start_utc() -> str:
    """Midnight of the server's LOCAL day, in UTC for the ISO ``created_at`` column.

    A budget's "day" is the operator's day, not UTC's: asking the machine for its timezone (instead
    of hardcoding one) also keeps CI's UTC box and an Asia/Shanghai desktop honest.
    """
    local = datetime.now().astimezone()
    midnight = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
    return midnight.astimezone(UTC).isoformat()


def spend_state(conversation_id: str) -> dict:
    """The token caps and what is already spent — checked BEFORE another provider round.

    Money is deliberately absent here: a list price is in the provider's own currency, and adding
    currencies would invent a number. Tokens are the one meter every transport actually reports.
    A cap of 0 means off; a reached cap is a soft stop (the agent asks), not a failed turn.
    """
    conv_cap = max(0, int(get_setting('ai_budget_conversation_tokens') or 0))
    day_cap = max(0, int(get_setting('ai_budget_daily_tokens') or 0))
    conv_tokens = int((store.token_usage(conversation_id=conversation_id) or {}).get('tokens') or 0)
    day_tokens = int((store.token_usage(since=_local_day_start_utc()) or {}).get('tokens') or 0)
    scope = ''
    limit = 0
    spent = 0
    if conv_cap and conv_tokens >= conv_cap:
        scope, limit, spent = 'conversation', conv_cap, conv_tokens
    elif day_cap and day_tokens >= day_cap:
        scope, limit, spent = 'day', day_cap, day_tokens
    return {
        'conversation_tokens': conv_tokens,
        'conversation_limit': conv_cap,
        'daily_tokens': day_tokens,
        'daily_limit': day_cap,
        'exceeded': bool(scope),
        'scope': scope,
        'limit': limit,
        'spent': spent,
    }
