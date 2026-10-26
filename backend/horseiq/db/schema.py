"""Database schema (SQLAlchemy Core). Works on SQLite (local dev) and PostgreSQL / Supabase.

Conventions on every source-backed table:
  source_system   - 'TJK_API', 'TJK_HTML', 'ACCURACE', 'DEMO', 'HORSEIQ' ...
  source_id       - id of the record in that source (if the source has one)
  data_status     - REAL / ESTIMATED / DEMO
  created_at / updated_at
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)

metadata = MetaData()


def _audit() -> list[Column]:
    return [
        Column("source_system", String(32), nullable=False),
        Column("source_id", String(128)),
        Column("data_status", String(16), nullable=False),
        Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
        Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False),
    ]


racetracks = Table(
    "racetracks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", String(32), nullable=False, unique=True),  # folded name, e.g. ISTANBUL
    Column("name", String(128), nullable=False),
    Column("home_straight_m", Float),  # geometry used by the simulator (nullable = generic)
    Column("turn_radius_m", Float),
    *_audit(),
)

horses = Table(
    "horses",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(128), nullable=False),
    Column("name_key", String(128), nullable=False),  # fold(name)
    Column("birth_year", Integer),
    Column("sex", String(16)),
    Column("sire", String(128)),
    Column("dam", String(128)),
    *_audit(),
    Index("ix_horses_name_key", "name_key"),
)

# A horse can carry several identities (TJK id, Accurace id, ...). Matching never relies on
# the name alone when a source id exists; name-only matches are recorded with method='NAME'.
horse_source_ids = Table(
    "horse_source_ids",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("horse_id", Integer, ForeignKey("horses.id", ondelete="CASCADE"), nullable=False),
    Column("source_system", String(32), nullable=False),
    Column("source_horse_id", String(128), nullable=False),
    Column("match_method", String(16), nullable=False),  # SOURCE_ID / NAME / MANUAL
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    UniqueConstraint("source_system", "source_horse_id", name="uq_horse_source"),
)

jockeys = Table(
    "jockeys",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(128), nullable=False),
    Column("name_key", String(128), nullable=False),
    Column("apprentice", Boolean),
    *_audit(),
    UniqueConstraint("source_system", "source_id", name="uq_jockey_source"),
    Index("ix_jockeys_name_key", "name_key"),
)

races = Table(
    "races",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("racetrack_id", Integer, ForeignKey("racetracks.id"), nullable=False),
    Column("race_date", Date, nullable=False),
    Column("race_no", Integer, nullable=False),
    Column("post_time", String(8)),
    Column("distance_m", Integer),
    Column("surface", String(16)),
    Column("going", String(64)),
    Column("race_class", String(128)),
    Column("conditions", Text),
    Column("has_results", Boolean, nullable=False, default=False),
    Column("cancelled", Boolean, nullable=False, default=False),
    *_audit(),
    UniqueConstraint("racetrack_id", "race_date", "race_no", name="uq_race"),
    Index("ix_races_date", "race_date"),
)

race_entries = Table(
    "race_entries",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_id", Integer, ForeignKey("races.id", ondelete="CASCADE"), nullable=False),
    Column("horse_id", Integer, ForeignKey("horses.id"), nullable=False),
    Column("jockey_id", Integer, ForeignKey("jockeys.id")),
    Column("program_no", Integer),
    Column("gate", Integer),
    Column("weight_kg", Float),
    Column("age_text", String(32)),
    Column("scratched", Boolean, nullable=False, default=False),
    Column("jockey_changed", Boolean, nullable=False, default=False),
    *_audit(),
    UniqueConstraint("race_id", "horse_id", name="uq_entry"),
)

race_results = Table(
    "race_results",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_id", Integer, ForeignKey("races.id", ondelete="CASCADE"), nullable=False),
    Column("horse_id", Integer, ForeignKey("horses.id"), nullable=False),
    Column("finish_pos", Integer),
    Column("finish_time_s", Float),
    Column("margin_text", String(64)),
    Column("status", String(16), nullable=False),  # FINISHED / DNF / DISQUALIFIED / SCRATCHED
    *_audit(),
    UniqueConstraint("race_id", "horse_id", name="uq_result"),
    Index("ix_results_horse", "horse_id"),
)

# Per-run derived metrics (cache); ESTIMATED when derived from finishing time only,
# REAL when computed from measured tracking data.
horse_performances = Table(
    "horse_performances",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_id", Integer, ForeignKey("races.id", ondelete="CASCADE"), nullable=False),
    Column("horse_id", Integer, ForeignKey("horses.id"), nullable=False),
    Column("avg_speed_mps", Float),
    Column("max_speed_mps", Float),
    Column("total_distance_m", Float),  # actual ground covered (tracking)
    Column("early_speed_mps", Float),
    Column("late_speed_mps", Float),
    Column("extra", JSON),
    *_audit(),
    UniqueConstraint("race_id", "horse_id", "source_system", name="uq_perf"),
)

sectional_times = Table(
    "sectional_times",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_id", Integer, ForeignKey("races.id", ondelete="CASCADE"), nullable=False),
    Column("horse_id", Integer, ForeignKey("horses.id"), nullable=False),
    Column("from_m", Float, nullable=False),
    Column("to_m", Float, nullable=False),
    Column("time_s", Float, nullable=False),
    Column("speed_mps", Float),
    Column("position", Integer),
    *_audit(),
    UniqueConstraint("race_id", "horse_id", "from_m", "to_m", "source_system", name="uq_sectional"),
)

horse_tracking_points = Table(
    "horse_tracking_points",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_id", Integer, ForeignKey("races.id", ondelete="CASCADE"), nullable=False),
    Column("horse_id", Integer, ForeignKey("horses.id"), nullable=False),
    Column("t_ms", Integer, nullable=False),  # ms since start
    Column("distance_m", Float),
    Column("lat", Float),
    Column("lon", Float),
    Column("speed_mps", Float),
    Column("rail_distance_m", Float),  # bariyere uzaklık
    Column("position", Integer),
    Column("source_system", String(32), nullable=False),
    UniqueConstraint("race_id", "horse_id", "t_ms", "source_system", name="uq_tracking_point"),
)

simulation_runs = Table(
    "simulation_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_id", Integer, ForeignKey("races.id", ondelete="CASCADE"), nullable=False),
    Column("seed", Integer, nullable=False),
    Column("engine_version", String(16), nullable=False),
    Column("form_settings", JSON, nullable=False),
    Column("intervention", JSON),
    Column("kind", String(16), nullable=False),  # SINGLE / MONTE_CARLO / BACKTEST
    Column("data_status", String(16), nullable=False),  # weakest status among inputs
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

simulation_results = Table(
    "simulation_results",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False),
    Column("horse_id", Integer, ForeignKey("horses.id"), nullable=False),
    Column("sim_pos", Integer),
    Column("sim_time_s", Float),
    Column("win_prob", Float),
    Column("top3_prob", Float),
    Column("form_score", Float),
    UniqueConstraint("run_id", "horse_id", name="uq_sim_result"),
)

import_logs = Table(
    "import_logs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source_system", String(32), nullable=False),
    Column("source_ref", String(256)),  # file name / API call
    Column("started_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("races_inserted", Integer, default=0),
    Column("races_updated", Integer, default=0),
    Column("entries_upserted", Integer, default=0),
    Column("results_upserted", Integer, default=0),
    Column("issues", JSON),  # list of {level, message, ref}
)
