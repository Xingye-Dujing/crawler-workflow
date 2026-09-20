import io
import re

import pandas as pd


def extract_number(text: str) -> int:
    """Extract first integer from text, supporting thousands separators."""
    if not text:
        return 0
    m = re.search(r'(\d+(?:,\d+)*)', text.replace(',', ''))
    return int(m.group(1)) if m else 0


def sanitize_filename(name: str) -> str:
    """Remove illegal characters from filename."""
    return re.sub(r'[\\/*?:"<>|]', '_', name)


def df_to_csv_string(df: pd.DataFrame) -> str:
    """Convert DataFrame to CSV string."""
    output = io.StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')
    return output.getvalue()


def merge_results(results: list, _key: str = 'platform') -> pd.DataFrame:
    """Merge multiple result lists into a single DataFrame."""
    all_items = []
    for r in results:
        if isinstance(r, list):
            all_items.extend(r)
        elif isinstance(r, dict):
            all_items.append(r)
    return pd.DataFrame(all_items)
