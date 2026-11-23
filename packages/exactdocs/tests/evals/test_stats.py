"""The benchmarks' intervals and paired tests (#489), on synthetic runs with known answers."""

import math

import pytest

from retrieval_eval.stats import (
    DEFAULT,
    StatsMethod,
    interval,
    mcnemar_mid_p,
    paired_binary,
    paired_mean,
    permutation_p,
)

# ---------------------------------------------------------------- intervals


def test_an_interval_holds_the_mean_and_matches_the_binomial_bootstrap() -> None:
    hits = [1.0] * 50 + [0.0] * 50

    found = interval(hits)

    assert found is not None
    assert found.low < 0.5 < found.high
    # resampling 100 hits or misses of rate 1/2 draws Binomial(100, 1/2) hits: its 2.5th and
    # 97.5th percentiles are 40 and 60
    assert found.low == pytest.approx(0.40, abs=0.011)
    assert found.high == pytest.approx(0.60, abs=0.011)


def test_an_interval_is_reproducible_from_its_seed() -> None:
    values = [i % 7 / 7 for i in range(80)]

    assert interval(values) == interval(values)
    # another seed draws other resamples (seen with few of them and unrounded bounds)
    seeded = {interval(values, StatsMethod(seed=s, resamples=50), digits=12) for s in range(5)}
    assert len(seeded) > 1


def test_an_interval_narrows_with_more_cases() -> None:
    small = interval([1.0] * 40 + [0.0] * 10)
    large = interval([1.0] * 400 + [0.0] * 100)

    assert small is not None
    assert large is not None
    assert large.high - large.low < small.high - small.low


def test_equal_values_give_an_interval_of_no_width_and_no_case_none() -> None:
    assert interval([0.0] * 30) == interval([0.0])
    found = interval([1.0] * 30)
    assert found is not None
    assert (found.low, found.high) == (1.0, 1.0)
    assert interval([]) is None


def test_a_wider_confidence_gives_a_wider_interval() -> None:
    values = [1.0] * 30 + [0.0] * 20
    ninety = interval(values, StatsMethod(confidence=0.90))
    ninety_nine = interval(values, StatsMethod(confidence=0.99))

    assert ninety is not None
    assert ninety_nine is not None
    assert ninety_nine.low < ninety.low
    assert ninety.high < ninety_nine.high


# ---------------------------------------------------------------- McNemar, mid-p


@pytest.mark.parametrize(
    ("gained", "lost", "p"),
    [
        (0, 0, 1.0),  # the runs never disagree
        (5, 5, 1.0),  # as many either way
        (10, 0, 1 / 1024),  # 2 (P(X < 0) + P(X = 0) / 2), X ~ Binomial(10, 1/2)
        (3, 1, 0.375),  # (2 * 1 + 4) / 16
        (1, 3, 0.375),  # two-sided: the direction does not matter
        # (2 * (1 + 16 + 120 + 560) + 1820) / 2**16: significant, where the exact test's
        # 2 (697 + 1820) / 2**16 = 0.077 is not
        (12, 4, 3214 / 65536),
    ],
)
def test_mcnemar_mid_p_matches_the_binomial(gained: int, lost: int, p: float) -> None:
    assert mcnemar_mid_p(gained, lost) == pytest.approx(p)


def test_identical_hit_or_miss_runs_are_not_significant() -> None:
    a = [i % 3 != 0 for i in range(90)]

    test = paired_binary(a, a)

    assert test is not None
    assert (test.difference, test.p_value, test.significant) == (0, 1, False)
    assert (test.gained, test.lost, test.cases) == (0, 0, 90)
    assert (test.interval.low, test.interval.high) == (0, 0)


def test_a_clear_hit_or_miss_gap_is_significant() -> None:
    a = [i < 50 for i in range(100)]  # 50 hits
    b = [i < 70 for i in range(100)]  # the same 50 and 20 more

    test = paired_binary(a, b)

    assert test is not None
    assert test.significant
    assert test.p_value == pytest.approx(2**-20, rel=1e-3)  # kept to 4 significant digits
    assert (test.gained, test.lost, test.difference) == (20, 0, 0.2)
    assert 0 < test.interval.low < 0.2 < test.interval.high


def test_a_gap_on_few_disagreements_is_not_significant() -> None:
    # 10 points more, but from two cases out of twenty
    a = [i < 10 for i in range(20)]
    b = [i < 12 for i in range(20)]

    test = paired_binary(a, b)

    assert test is not None
    assert test.difference == pytest.approx(0.1)
    assert test.p_value == pytest.approx(0.25)
    assert not test.significant
    assert test.interval.low <= 0 < test.interval.high


def test_paired_runs_need_the_same_cases() -> None:
    with pytest.raises(ValueError, match="same cases"):
        paired_binary([True], [True, False])
    assert paired_binary([], []) is None
    assert paired_mean([], []) is None


# ---------------------------------------------------------------- permutation test


def test_identical_graded_runs_are_not_significant() -> None:
    a = [1 / (1 + i % 10) for i in range(80)]

    test = paired_mean(a, a)

    assert test is not None
    assert (test.difference, test.p_value, test.significant) == (0, 1, False)
    assert permutation_p([0.0] * 10) == 1


def test_a_clear_graded_gap_is_significant() -> None:
    a = [0.5] * 60
    b = [0.5 + 0.2 * (i % 2) for i in range(60)]  # better on half the cases, never worse

    test = paired_mean(a, b)

    assert test is not None
    assert test.significant
    assert test.p_value == pytest.approx(1 / (DEFAULT.resamples + 1))
    assert test.difference == pytest.approx(0.1)
    assert 0 < test.interval.low < 0.1 < test.interval.high


def test_differences_that_cancel_out_are_not_significant() -> None:
    assert permutation_p([0.25, -0.25] * 20) == 1


def test_the_permutation_p_value_estimates_the_exact_one() -> None:
    # three differences of +1: of the 8 sign patterns, 2 sum to 3 or -3
    assert permutation_p([1.0, 1.0, 1.0]) == pytest.approx(0.25, abs=0.015)
    # five: 2 of 32
    assert permutation_p([0.5] * 5) == pytest.approx(2 / 32, abs=0.01)


def test_the_tests_record_their_level() -> None:
    a = [i < 10 for i in range(20)]
    b = [i < 13 for i in range(20)]  # three cases gained: p = 1/8 = 0.125

    strict = paired_binary(a, b, StatsMethod(alpha=0.05))
    lenient = paired_binary(a, b, StatsMethod(alpha=0.2))

    assert strict is not None
    assert lenient is not None
    assert strict.p_value == lenient.p_value == pytest.approx(0.125)
    assert (strict.significant, lenient.significant) == (False, True)
    assert math.isclose(strict.difference, 0.15)
