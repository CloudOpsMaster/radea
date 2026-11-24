import pytest


def compute():
    return 3


def test_checks_the_result():
    assert compute() == 3


def test_expected_failure():
    with pytest.raises(ZeroDivisionError):
        1 / 0


def test_helper_assertion():
    check_total(compute())


def test_smoke():  # radea: allow-no-assert
    compute()


@pytest.mark.skip(reason="needs a cluster")
def test_skipped():
    pass


def check_total(value):
    assert value == 3
