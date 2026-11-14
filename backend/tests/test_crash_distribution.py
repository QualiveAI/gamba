"""Pure deterministic checks for the server-authoritative Crash distribution."""

import math

from app.games.crash import MAX_MULT, SESSION_RTP, crash_point_from_roll


def test_crash_point_boundaries_and_cap():
    assert crash_point_from_roll(0.0) == 1.0
    assert crash_point_from_roll(1.0) == MAX_MULT
    assert 1.0 <= crash_point_from_roll(0.03) <= MAX_MULT
    assert crash_point_from_roll(0.5) == round(SESSION_RTP / 0.5, 2)
    assert crash_point_from_roll(0.999999999) <= MAX_MULT


def test_crash_point_is_monotonic_and_finite():
    rolls = [i / 10_000 for i in range(10_000)]
    points = [crash_point_from_roll(roll) for roll in rolls]
    assert points == sorted(points)
    assert all(math.isfinite(point) and 1 <= point <= MAX_MULT for point in points)


def test_crash_distribution_has_frequent_small_and_rare_large_outcomes():
    points = [crash_point_from_roll(i / 20_000) for i in range(20_000)]
    small = sum(point < 2 for point in points) / len(points)
    medium = sum(point >= 3 for point in points) / len(points)
    large = sum(point >= 10 for point in points) / len(points)
    very_large = sum(point >= 100 for point in points) / len(points)
    assert 0.48 <= small <= 0.55
    assert 0.30 <= medium <= 0.35
    assert 0.085 <= large <= 0.11
    assert 0.007 <= very_large <= 0.012


def test_crash_distribution_does_not_depend_on_player_context():
    rolls = [0.001, 0.031, 0.25, 0.5, 0.9, 0.999]
    assert [crash_point_from_roll(value) for value in rolls] == [
        crash_point_from_roll(value) for value in rolls
    ]
