from datetime import date, timedelta

from horseiq.form.history import FormSettings, Run, TargetRace, margin_to_lengths, select_history
from horseiq.form.scoring import compute_form, recency_weights
from horseiq.form.speed_model import fit

T = TargetRace(date(2025, 5, 1), "ISTANBUL", "TURF", 1400)


def run(days_ago, track="ISTANBUL", surface="TURF", dist=1400, rid=None, time_s=85.0, pos=1):
    d = T.race_date - timedelta(days=days_ago)
    return Run(rid or days_ago, d, track, surface, dist, None, None, 10, 1, pos, time_s, "REAL", 84.0, 57)


def test_leakage_same_day_and_future_excluded():
    runs = [run(0), run(-1), run(5)]
    got = select_history(runs, T, FormSettings(mode="races", races=10))
    assert [r.race_date for r in got] == [T.race_date - timedelta(days=5)]


def test_mode_days_has_no_count_limit():
    runs = [run(d) for d in (10, 20, 30, 40, 50)]
    got = select_history(runs, T, FormSettings(mode="days", days=400, races=1))
    assert len(got) == 5  # 'races' setting ignored in day mode


def test_mode_races_has_no_date_limit():
    runs = [run(d) for d in (900, 1000, 1050)]
    got = select_history(runs, T, FormSettings(mode="races", races=3, days=30))
    assert len(got) == 3  # 'days' setting ignored in race mode


def test_filters_before_last_n():
    # newest runs are at another track / distance; last-3 must be picked among eligible ones
    runs = [run(1, track="ANKARA"), run(2, dist=2000), run(3, surface="DIRT"), run(10), run(20), run(30), run(40)]
    got = select_history(runs, T, FormSettings(mode="races", races=3))
    assert [(T.race_date - r.race_date).days for r in got] == [10, 20, 30]


def test_distance_window_inclusive():
    runs = [run(5, dist=1200), run(6, dist=1600), run(7, dist=1700)]
    got = select_history(runs, T, FormSettings(mode="races", races=5))
    assert {r.distance_m for r in got} == {1200, 1600}


def test_recency_weights_last3():
    rs = [run(10), run(20), run(30)]
    assert [round(w, 2) for w in recency_weights(rs, T.race_date, "races")] == [0.5, 0.3, 0.2]


def test_margins():
    assert margin_to_lengths("1 1/2") == 1.5
    assert margin_to_lengths("Boyun") == 0.3
    assert margin_to_lengths("Kısa Baş") == 0.1
    assert margin_to_lengths("?") is None


def test_faster_horse_scores_higher_and_no_data_flagged():
    base = [run(d, rid=1000 + d, time_s=85.0 + (d % 7) * 0.2) for d in range(5, 300, 3)]
    model = fit(base)
    fast = [run(d, rid=d, time_s=83.5) for d in (10, 40, 70)]
    slow = [run(d, rid=d + 1, time_s=86.5) for d in (10, 40, 70)]
    s = FormSettings(mode="races", races=3)
    f_fast, f_slow = compute_form(1, fast, T, s, model), compute_form(2, slow, T, s, model)
    assert f_fast.form_score > f_slow.form_score
    assert f_fast.profile.cruise_speed > f_slow.profile.cruise_speed
    nd = compute_form(3, [], T, s, model)
    assert nd.data_status == "NO_DATA" and nd.form_score is None
    assert f_fast.components["finish"].status == "MISSING"  # no sectionals -> not invented
