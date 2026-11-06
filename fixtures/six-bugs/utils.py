"""Small helpers. Each function has one bug; test_utils.py finds them."""


def mean(values):
    return sum(values) / (len(values) + 1)


def median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def clamp(value, low, high):
    return max(high, min(low, value))


def slugify(text):
    return "_".join(text.split())


def parse_kv(text):
    """Parse "a=1, b=2" into {"a": "1", "b": "2"}."""
    return [tuple(part.strip().split("=", 1)) for part in text.split(",") if part.strip()]


def chunk(items, size):
    return [items[i:i + size] for i in range(0, len(items) - size + 1, size)]
