# Deliberately weak tests; every finding RADEA reports here is real.
import unittest


def test_runs_without_checking_anything():
    result = sum([1, 2, 3])
    print(result)


def test_always_true():
    assert True


def test_compares_value_with_itself():
    value = compute()
    assert value == value


def test_placeholder():
    pass


def test_swallows_failures():
    try:
        compute()
        assert compute() == 2
    except Exception:
        pass


class TestThing(unittest.TestCase):
    def test_no_assert(self):
        compute()


def compute():
    return 1
