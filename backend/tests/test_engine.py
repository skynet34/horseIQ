from horseiq.form.scoring import SimProfile
from horseiq.sim.engine import BAND_M, LENGTH_M, Intervention, Runner, lengths_text, simulate


def P(c=16.5, e=0.5, k=0.5, sd=0.0):
    return SimProfile(c, e, k, 0.5, 1.0, sd, {})


def field():
    styles = [(0.85, 0.2), (0.8, 0.3), (0.75, 0.3), (0.5, 0.5), (0.3, 0.7), (0.2, 0.85), (0.4, 0.6), (0.5, 0.5)]
    return [Runner(i, i, f"H{i}", i, P(16.5 + 0.04 * (i % 3), e, k, 0.12)) for i, (e, k) in enumerate(styles, 1)]


def test_solo_time_matches_profile():
    for d in (1200, 1600, 2400):
        r = simulate([Runner(1, 1, "S", 1, P())], d, seed=3)
        assert abs(r.order[0]["time_s"] - d / 16.5) / (d / 16.5) < 0.01


def test_everyone_finishes_and_deterministic():
    a = simulate(field(), 1400, seed=11)
    b = simulate(field(), 1400, seed=11)
    assert all(o["time_s"] for o in a.order)
    assert [o["horse_id"] for o in a.order] == [o["horse_id"] for o in b.order]
    assert [o["time_s"] for o in a.order] == [o["time_s"] for o in b.order]


def test_no_running_through_each_other():
    r = simulate(field(), 1400, seed=5)
    for fr in r.frames[5:-1]:
        h = fr["h"]
        for i in range(len(h)):
            for j in range(len(h)):
                if i != j and h[i][0] < 1400 and h[j][0] < 1400 and abs(h[i][1] - h[j][1]) < BAND_M * 0.9:
                    assert abs(h[i][0] - h[j][0]) >= LENGTH_M - 0.6


def test_interventions_cost_the_horse_and_move_others():
    others_changed = 0
    for seed in range(21, 26):
        base = simulate(field(), 1600, seed=seed)
        t0 = {o["horse_id"]: o["time_s"] for o in base.order}
        for kind in ("start", "blocked", "late", "traffic"):
            iv = simulate(field(), 1600, seed=seed, intervention=Intervention(4, kind))
            t1 = {o["horse_id"]: o["time_s"] for o in iv.order}
            assert t1[4] > t0[4], (seed, kind)
            assert any(e.get("intervention") for e in iv.events)
            others_changed += any(abs(t1[h] - t0[h]) > 1e-6 for h in t0 if h != 4)
    # the whole race is recomputed: in a good share of scenarios other runners are affected too
    assert others_changed >= 5


def test_pace_duel_helps_closers_on_average():
    """Three front-runners duelling should, on average, finish worse than identical horses that don't."""
    def avg_rank(early_three):
        ranks = []
        for seed in range(12):
            runners = [Runner(i, i, f"H{i}", i, P(16.5, early_three if i <= 3 else 0.3, 0.5, 0.1)) for i in range(1, 9)]
            r = simulate(runners, 1600, seed=seed)
            pos = {o["horse_id"]: o["pos"] for o in r.order}
            ranks += [pos[i] for i in (1, 2, 3)]
        return sum(ranks) / len(ranks)

    assert avg_rank(0.95) > avg_rank(0.3)


def test_lengths_text():
    assert lengths_text(0.05) == "Burun" and lengths_text(0.3) == "Boyun"
    assert lengths_text(1.0) == "1 boy" and lengths_text(2.5) == "2 1/2 boy" and lengths_text(20) == "Uzak"
