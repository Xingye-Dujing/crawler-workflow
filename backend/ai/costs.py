"""What one conversation has spent, in the provider's own prices.

Token counts are FACTS the store recorded; money is a provider's list price, so each transport
answers ``cost()`` and a provider with no published price answers ``None`` — the panel then shows
tokens and the cache rate, and says the money is unknown instead of inventing a number. A cache hit
is not a discount we compute: it is the split DeepSeek itself reports (hit vs miss prompt tokens).
"""

from __future__ import annotations

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
