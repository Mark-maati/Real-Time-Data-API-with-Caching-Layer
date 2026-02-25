import pytest
from app.cache import build_key


def test_build_key_deterministic():
    k1 = build_key("records", "posts", 1, 50)
    k2 = build_key("records", "posts", 1, 50)
    assert k1 == k2


def test_build_key_prefix():
    k = build_key("test")
    assert k.startswith("agg:v2:")


def test_build_key_different_inputs():
    k1 = build_key("records", "posts")
    k2 = build_key("records", "users")
    assert k1 != k2
