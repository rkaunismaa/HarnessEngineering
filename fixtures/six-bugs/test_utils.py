from utils import chunk, clamp, mean, median, parse_kv, slugify


def test_mean():
    assert mean([1, 2, 3, 4]) == 2.5


def test_median_odd():
    assert median([3, 1, 2]) == 2


def test_median_even():
    assert median([4, 1, 3, 2]) == 2.5


def test_clamp():
    assert clamp(5, 0, 3) == 3
    assert clamp(-1, 0, 3) == 0
    assert clamp(2, 0, 3) == 2


def test_slugify():
    assert slugify("Hello World Again") == "hello-world-again"


def test_parse_kv():
    assert parse_kv("a=1, b=2") == {"a": "1", "b": "2"}


def test_chunk_even():
    assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_chunk_remainder():
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
