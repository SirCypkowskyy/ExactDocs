"""Confidence intervals and paired tests for the benchmarks' numbers (#489).

Every benchmark scores each golden case on its own, so each of its numbers is a mean over cases (a
rate is the mean of a 0/1 outcome). This module gives such a mean a confidence interval, and two
runs on the same cases a paired test. It is pure: the same values, seed and number of resamples
always give the same numbers.

- **Interval**: a percentile bootstrap over cases. ``resamples`` times, draw as many cases as there
  are, with replacement, from ``random.Random(seed)``, and take the mean; the interval runs from
  the 2.5th to the 97.5th percentile of those means (95%). The draws depend only on the seed and
  the number of cases, so every configuration that answered the same cases (in the same order) is
  resampled with the same draws: the bootstrap is paired.
- **Hit-or-miss outcomes** (recall@k, agent accuracy): McNemar's test, mid-p version. Only the cases
  the two runs disagree on count; under no difference, each is as likely to favour either run.
- **Graded outcomes** (MRR, nDCG@10): a paired sign-flip permutation test on the per-case
  differences. Under no difference, each difference is as likely to have either sign.
- Both tests also give the paired bootstrap interval of the difference.

Definitions: docs/benchmark/method.md#intervals-and-significance.
"""

import math
import random
from array import array
from collections.abc import Callable, Sequence
from functools import lru_cache
from itertools import compress
from statistics import fmean
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

SEED: Final[int] = 489
"""The bootstrap's and the permutation test's seed."""
RESAMPLES: Final[int] = 10_000
"""Bootstrap resamples, and the permutation test's random sign flips."""
CONFIDENCE: Final[float] = 0.95
"""The intervals' confidence level."""
ALPHA: Final[float] = 0.05
"""A paired test is significant when its p-value is below this."""
_DIGITS: Final[int] = 4
"""Interval bounds and differences are rounded to this many decimals by default."""
_P_DIGITS: Final[int] = 4
"""p-values keep this many significant digits."""
_TOLERANCE: Final[float] = 1e-9
"""Float noise tolerated when a permuted statistic is compared with the observed one."""
_TWO_BYTES: Final[int] = 0xFFFF
"""The largest case index a resample keeps in two bytes (the golden set has a few hundred)."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class StatsMethod(_Model):
    """How a report's intervals and paired tests were computed, so that they can be reproduced."""

    seed: int = SEED
    """The seed of ``random.Random`` for the bootstrap and the permutation test."""
    resamples: int = RESAMPLES
    """Bootstrap resamples, and random sign flips of the permutation test."""
    confidence: float = CONFIDENCE
    """The intervals' confidence level."""
    alpha: float = ALPHA
    """The significance level of the paired tests."""
    interval: str = "percentile bootstrap over cases, paired"
    """How an interval is computed."""
    binary_test: str = "McNemar, mid-p"
    """The paired test of a hit-or-miss outcome."""
    graded_test: str = "paired sign-flip permutation"
    """The paired test of a graded outcome."""


DEFAULT: Final[StatsMethod] = StatsMethod()
"""The settings the benchmarks use."""


class Interval(_Model):
    """A confidence interval."""

    low: float
    """Its lower bound."""
    high: float
    """Its upper bound."""


class PairedTest(_Model):
    """One metric of run B against run A, on the cases both answered."""

    test: Literal["mcnemar-mid-p", "permutation"]
    """McNemar's mid-p test (hit-or-miss outcomes) or a sign-flip permutation test (graded)."""
    cases: int
    """The cases compared."""
    difference: float
    """B minus A, in the metric's unit (a share for a rate)."""
    interval: Interval
    """The paired bootstrap interval of the difference."""
    p_value: float
    """Two-sided."""
    significant: bool
    """``p_value`` is below the significance level."""
    gained: int | None = None
    """McNemar only: the cases B gets right and A does not."""
    lost: int | None = None
    """McNemar only: the cases A gets right and B does not."""


@lru_cache(maxsize=64)
def _draws(cases: int, seed: int, resamples: int) -> tuple[array[int], ...]:
    """Draw the bootstrap's resamples of case indices.

    Args:
        cases: How many cases there are.
        seed: The seed.
        resamples: How many resamples.

    Returns:
        ``resamples`` arrays of ``cases`` indices, drawn with replacement.
    """
    rng = random.Random(seed)
    population = range(cases)
    code = "H" if cases <= _TWO_BYTES else "I"
    return tuple(array(code, rng.choices(population, k=cases)) for _ in range(resamples))


def _quantile(ordered: Sequence[float], q: float) -> float:
    """A quantile, linearly interpolated between order statistics.

    Args:
        ordered: The values, ascending.
        q: The quantile, in [0, 1].

    Returns:
        The value at ``q``.
    """
    position = q * (len(ordered) - 1)
    below = math.floor(position)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (position - below)


def interval(
    values: Sequence[float], method: StatsMethod = DEFAULT, *, digits: int = _DIGITS
) -> Interval | None:
    """The percentile bootstrap interval of a mean over cases.

    Args:
        values: One value per case (1 or 0 for a hit or a miss), in a fixed case order.
        method: The seed, resamples and confidence.
        digits: Decimals the bounds are rounded to.

    Returns:
        The interval; ``None`` for no case. Equal values give an interval of no width.
    """
    if not values:
        return None
    values = list(values)
    if min(values) == max(values):
        return Interval(low=round(values[0], digits), high=round(values[0], digits))
    count = len(values)
    get: Callable[[int], float] = values.__getitem__
    means = sorted(
        sum(map(get, draw)) / count for draw in _draws(count, method.seed, method.resamples)
    )
    tail = (1 - method.confidence) / 2
    return Interval(
        low=round(_quantile(means, tail), digits), high=round(_quantile(means, 1 - tail), digits)
    )


def mcnemar_mid_p(gained: int, lost: int) -> float:
    """McNemar's test, mid-p version, from the discordant cases.

    With *n* discordant cases and *k* the smaller count, the exact test's two-sided p-value is
    2 P(X <= k) for X ~ Binomial(n, 1/2); the mid-p version counts P(X = k) half, which keeps the
    test close to its nominal level instead of the exact test's conservative one.

    Args:
        gained: The cases B gets right and A does not.
        lost: The cases A gets right and B does not.

    Returns:
        The two-sided mid-p value; 1 when the runs never disagree.
    """
    discordant = gained + lost
    if not discordant:
        return 1.0
    smaller = min(gained, lost)
    below = sum(math.comb(discordant, i) for i in range(smaller))
    return min(1.0, (2 * below + math.comb(discordant, smaller)) / 2**discordant)


def permutation_p(differences: Sequence[float], method: StatsMethod = DEFAULT) -> float:
    """A paired sign-flip permutation test of a mean difference.

    Each permutation gives every per-case difference a random sign and sums them; the p-value is
    the share of permutations whose sum is at least as far from 0 as the observed one, counting
    the observed one too. A zero difference is the same either sign, so it is left out.

    Args:
        differences: B minus A, per case.
        method: The seed and the number of permutations.

    Returns:
        The two-sided p-value; 1 when every difference is 0.
    """
    moved = [d for d in differences if d]
    if not moved:
        return 1.0
    total = sum(moved)
    observed = abs(total) - _TOLERANCE
    rng, width = random.Random(method.seed), f"0{len(moved)}b"
    extreme = 0
    for _ in range(method.resamples):
        flipped = sum(compress(moved, map(int, format(rng.getrandbits(len(moved)), width))))
        extreme += abs(total - 2 * flipped) >= observed
    return (extreme + 1) / (method.resamples + 1)


def _significant_digits(p: float) -> float:
    return float(f"{p:.{_P_DIGITS}g}")


def _differences(a: Sequence[float], b: Sequence[float]) -> list[float]:
    """Pair two runs' values case by case.

    Args:
        a: Run A's values.
        b: Run B's values, for the same cases in the same order.

    Returns:
        B minus A, per case.

    Raises:
        ValueError: The runs have a different number of cases.
    """
    if len(a) != len(b):
        message = f"paired runs need the same cases: {len(a)} against {len(b)}"
        raise ValueError(message)
    return [float(y) - float(x) for x, y in zip(a, b, strict=True)]


def paired_binary(
    a: Sequence[bool], b: Sequence[bool], method: StatsMethod = DEFAULT
) -> PairedTest | None:
    """Compare two runs' hit-or-miss outcomes on the same cases (McNemar, mid-p).

    Args:
        a: Run A's outcome per case.
        b: Run B's outcome per case, in the same order.
        method: The seed, resamples, confidence and significance level.

    Returns:
        The test; ``None`` for no case.
    """
    differences = _differences(a, b)
    spread = interval(differences, method)
    if spread is None:
        return None
    gained = sum(1 for d in differences if d > 0)
    lost = sum(1 for d in differences if d < 0)
    p = mcnemar_mid_p(gained, lost)
    return PairedTest(
        test="mcnemar-mid-p",
        cases=len(differences),
        difference=round(fmean(differences), _DIGITS),
        interval=spread,
        p_value=_significant_digits(p),
        significant=p < method.alpha,
        gained=gained,
        lost=lost,
    )


def paired_mean(
    a: Sequence[float], b: Sequence[float], method: StatsMethod = DEFAULT
) -> PairedTest | None:
    """Compare two runs' graded outcomes on the same cases (sign-flip permutation).

    Args:
        a: Run A's value per case.
        b: Run B's value per case, in the same order.
        method: The seed, resamples, confidence and significance level.

    Returns:
        The test; ``None`` for no case.
    """
    differences = _differences(a, b)
    spread = interval(differences, method)
    if spread is None:
        return None
    p = permutation_p(differences, method)
    return PairedTest(
        test="permutation",
        cases=len(differences),
        difference=round(fmean(differences), _DIGITS),
        interval=spread,
        p_value=_significant_digits(p),
        significant=p < method.alpha,
    )
