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


# keyword (lowercase substring)  ->  category name (must exist in the DB)
# Longer, more specific keywords are matched first (see _SORTED_KEYWORDS),
# so e.g. "uber eats" (Dining Out) wins over "uber" (Public Transport).
KEYWORD_TO_CATEGORY: Dict[str, str] = {
    # Groceries
    "tesco": "Groceries", "sainsbury": "Groceries", "asda": "Groceries",
    "aldi": "Groceries", "lidl": "Groceries", "morrison": "Groceries",
    "waitrose": "Groceries", "m&s food": "Groceries", "marks & spencer": "Groceries",
    "co-op": "Groceries", "iceland": "Groceries", "ocado": "Groceries",
    # Coffee/Snacks
    "costa": "Coffee/Snacks", "pret": "Coffee/Snacks", "greggs": "Coffee/Snacks",
    "starbucks": "Coffee/Snacks", "caffe nero": "Coffee/Snacks",
    # Dining Out
    "uber eats": "Dining Out", "just eat": "Dining Out", "deliveroo": "Dining Out",
    "nando": "Dining Out", "wagamama": "Dining Out", "mcdonald": "Dining Out",
    "kfc": "Dining Out", "domino": "Dining Out", "pizza express": "Dining Out",
    "franco manca": "Dining Out", "five guys": "Dining Out", "burger king": "Dining Out",
    # Public Transport
    "tfl": "Public Transport", "trainline": "Public Transport",
    "national rail": "Public Transport", "uber": "Public Transport",
    "bolt": "Public Transport", "citymapper": "Public Transport",
    # Fuel
    "shell": "Fuel", "esso": "Fuel", "texaco": "Fuel", "gulf oil": "Fuel",
    # Streaming
    "netflix": "Streaming", "spotify": "Streaming", "disney+": "Streaming",
    "disney plus": "Streaming", "now tv": "Streaming", "apple tv": "Streaming",
    "youtube premium": "Streaming",
    # Games / Books
    "steam": "Games", "playstation": "Games", "nintendo": "Games", "xbox": "Games",
    "waterstones": "Books", "audible": "Books",
    # Fitness / Supplements
    "puregym": "Fitness", "the gym group": "Fitness", "myprotein": "Supplements",
    "bulk.com": "Supplements", "holland & barrett": "Supplements",
    # Pharmacy
    "boots": "Pharmacy", "superdrug": "Pharmacy",
    # Utilities / Phone
    "british gas": "Utilities", "octopus energy": "Utilities", "thames water": "Utilities",
    "vodafone": "Phone/Mobile", "giffgaff": "Phone/Mobile", "sky mobile": "Phone/Mobile",
    # Household / Clothing / Shopping
    "ikea": "Household", "b&q": "Household", "dunelm": "Household", "argos": "Household",
    "primark": "Clothing", "asos": "Clothing", "uniqlo": "Clothing", "jd sports": "Clothing",
    "zara": "Clothing", "h&m": "Clothing",
    "amazon": "Shopping",
    # Travel
    "ryanair": "Travel/Holidays", "easyjet": "Travel/Holidays",
    "british airways": "Travel/Holidays", "booking.com": "Travel/Holidays",
    "airbnb": "Travel/Holidays", "expedia": "Travel/Holidays",
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
