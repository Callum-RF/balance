"""
Guess a spending category from a transaction description / merchant string.

Used by the statement importer (to categorise each row instead of dumping
everything into one blanket category) and available to the manual entry form
for a merchant-based default. Two signals, in priority order:

  1. History  -- if the person has categorised this exact merchant before,
                 reuse the category they used most often for it.
  2. Keywords -- a curated map of common (mostly UK) merchants, so a fresh
                 database with no history still gets useful suggestions.

Everything here only *suggests*; the caller keeps the value editable.
"""
from typing import Dict, Iterable, Optional


# keyword (lowercase substring)  ->  category name (must exist in the DB).
# Names track the lean flat taxonomy in database.DEFAULT_CATEGORIES.
# Longer, more specific keywords are matched first (see _SORTED_KEYWORDS),
# so e.g. "uber eats" (Eating Out) wins over "uber" (Transport).
KEYWORD_TO_CATEGORY: Dict[str, str] = {
    # Groceries
    "tesco": "Groceries", "sainsbury": "Groceries", "asda": "Groceries",
    "aldi": "Groceries", "lidl": "Groceries", "morrison": "Groceries",
    "waitrose": "Groceries", "m&s food": "Groceries", "marks & spencer": "Groceries",
    "co-op": "Groceries", "iceland": "Groceries", "ocado": "Groceries",
    # Eating Out (cafes, takeaways, restaurants)
    "costa": "Eating Out", "pret": "Eating Out", "greggs": "Eating Out",
    "starbucks": "Eating Out", "caffe nero": "Eating Out",
    "uber eats": "Eating Out", "just eat": "Eating Out", "deliveroo": "Eating Out",
    "nando": "Eating Out", "wagamama": "Eating Out", "mcdonald": "Eating Out",
    "kfc": "Eating Out", "domino": "Eating Out", "pizza express": "Eating Out",
    "franco manca": "Eating Out", "five guys": "Eating Out", "burger king": "Eating Out",
    # Transport (public transport + fuel)
    "tfl": "Transport", "trainline": "Transport",
    "national rail": "Transport", "uber": "Transport",
    "bolt": "Transport", "citymapper": "Transport",
    "shell": "Transport", "esso": "Transport", "texaco": "Transport", "gulf oil": "Transport",
    # Entertainment (streaming, games, books, hobbies)
    "netflix": "Entertainment", "spotify": "Entertainment", "disney+": "Entertainment",
    "disney plus": "Entertainment", "now tv": "Entertainment", "apple tv": "Entertainment",
    "youtube premium": "Entertainment",
    "steam": "Entertainment", "playstation": "Entertainment", "nintendo": "Entertainment",
    "xbox": "Entertainment", "waterstones": "Entertainment", "audible": "Entertainment",
    # Health & Fitness (gym, supplements, pharmacy, medical)
    "puregym": "Health & Fitness", "the gym group": "Health & Fitness",
    "myprotein": "Health & Fitness", "bulk.com": "Health & Fitness",
    "holland & barrett": "Health & Fitness",
    "boots": "Health & Fitness", "superdrug": "Health & Fitness",
    # Bills & Utilities (energy, water, phone/mobile)
    "british gas": "Bills & Utilities", "octopus energy": "Bills & Utilities",
    "thames water": "Bills & Utilities",
    "vodafone": "Bills & Utilities", "giffgaff": "Bills & Utilities", "sky mobile": "Bills & Utilities",
    # Shopping (household, clothing, general)
    "ikea": "Shopping", "b&q": "Shopping", "dunelm": "Shopping", "argos": "Shopping",
    "primark": "Shopping", "asos": "Shopping", "uniqlo": "Shopping", "jd sports": "Shopping",
    "zara": "Shopping", "h&m": "Shopping",
    "amazon": "Shopping",
    # Travel
    "ryanair": "Travel", "easyjet": "Travel",
    "british airways": "Travel", "booking.com": "Travel",
    "airbnb": "Travel", "expedia": "Travel",
}

# Longest keywords first so specific merchants beat generic ones.
_SORTED_KEYWORDS = sorted(KEYWORD_TO_CATEGORY, key=len, reverse=True)


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def build_history_map(transactions: Iterable) -> Dict[str, int]:
    """{normalised merchant -> most-used category_id} from past transactions."""
    counts: Dict[str, Dict[int, int]] = {}
    for t in transactions:
        merchant = getattr(t, "merchant", None)
        category_id = getattr(t, "category_id", None)
        if not merchant or not category_id:
            continue
        m = _norm(merchant)
        counts.setdefault(m, {})
        counts[m][category_id] = counts[m].get(category_id, 0) + 1
    return {m: max(cc, key=cc.get) for m, cc in counts.items()}


def guess_category_id(
    description: Optional[str],
    name_to_id: Dict[str, int],
    history_map: Optional[Dict[str, int]] = None,
) -> Optional[int]:
    """Best category_id guess for a description, or None if nothing matches."""
    if not description:
        return None
    d = _norm(description)

    if history_map and d in history_map:
        return history_map[d]

    for kw in _SORTED_KEYWORDS:
        if kw in d:
            cid = name_to_id.get(KEYWORD_TO_CATEGORY[kw])
            if cid:
                return cid
    return None
