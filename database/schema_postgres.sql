-- HorseIQ schema for PostgreSQL / Supabase.
-- Generated from backend/horseiq/db/schema.py (source of truth). Regenerate after schema changes.

CREATE TABLE horses (
	id SERIAL NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	name_key VARCHAR(128) NOT NULL, 
	birth_year INTEGER, 
	sex VARCHAR(16), 
	sire VARCHAR(128), 
	dam VARCHAR(128), 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(128), 
	data_status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_horses_name_key ON horses (name_key);

CREATE TABLE import_logs (
	id SERIAL NOT NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_ref VARCHAR(256), 
	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	races_inserted INTEGER, 
	races_updated INTEGER, 
	entries_upserted INTEGER, 
	results_upserted INTEGER, 
	issues JSON, 
	PRIMARY KEY (id)
);

CREATE TABLE jockeys (
	id SERIAL NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	name_key VARCHAR(128) NOT NULL, 
	apprentice BOOLEAN, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(128), 
	data_status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_jockey_source UNIQUE (source_system, source_id)
);
CREATE INDEX ix_jockeys_name_key ON jockeys (name_key);

CREATE TABLE racetracks (
	id SERIAL NOT NULL, 
	code VARCHAR(32) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	home_straight_m FLOAT, 
	turn_radius_m FLOAT, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(128), 
	data_status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE TABLE horse_source_ids (
	id SERIAL NOT NULL, 
	horse_id INTEGER NOT NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_horse_id VARCHAR(128) NOT NULL, 
	match_method VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_horse_source UNIQUE (source_system, source_horse_id), 
	FOREIGN KEY(horse_id) REFERENCES horses (id) ON DELETE CASCADE
);

CREATE TABLE races (
	id SERIAL NOT NULL, 
	racetrack_id INTEGER NOT NULL, 
	race_date DATE NOT NULL, 
	race_no INTEGER NOT NULL, 
	post_time VARCHAR(8), 
	distance_m INTEGER, 
	surface VARCHAR(16), 
	going VARCHAR(64), 
	race_class VARCHAR(128), 
	conditions TEXT, 
	has_results BOOLEAN NOT NULL, 
	cancelled BOOLEAN NOT NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(128), 
	data_status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_race UNIQUE (racetrack_id, race_date, race_no), 
	FOREIGN KEY(racetrack_id) REFERENCES racetracks (id)
);
CREATE INDEX ix_races_date ON races (race_date);

CREATE TABLE horse_performances (
	id SERIAL NOT NULL, 
	race_id INTEGER NOT NULL, 
	horse_id INTEGER NOT NULL, 
	avg_speed_mps FLOAT, 
	max_speed_mps FLOAT, 
	total_distance_m FLOAT, 
	early_speed_mps FLOAT, 
	late_speed_mps FLOAT, 
	extra JSON, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(128), 
	data_status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_perf UNIQUE (race_id, horse_id, source_system), 
	FOREIGN KEY(race_id) REFERENCES races (id) ON DELETE CASCADE, 
	FOREIGN KEY(horse_id) REFERENCES horses (id)
);

CREATE TABLE horse_tracking_points (
	id SERIAL NOT NULL, 
	race_id INTEGER NOT NULL, 
	horse_id INTEGER NOT NULL, 
	t_ms INTEGER NOT NULL, 
	distance_m FLOAT, 
	lat FLOAT, 
	lon FLOAT, 
	speed_mps FLOAT, 
	rail_distance_m FLOAT, 
	position INTEGER, 
	source_system VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tracking_point UNIQUE (race_id, horse_id, t_ms, source_system), 
	FOREIGN KEY(race_id) REFERENCES races (id) ON DELETE CASCADE, 
	FOREIGN KEY(horse_id) REFERENCES horses (id)
);

CREATE TABLE race_entries (
	id SERIAL NOT NULL, 
	race_id INTEGER NOT NULL, 
	horse_id INTEGER NOT NULL, 
	jockey_id INTEGER, 
	program_no INTEGER, 
	gate INTEGER, 
	weight_kg FLOAT, 
	age_text VARCHAR(32), 
	scratched BOOLEAN NOT NULL, 
	jockey_changed BOOLEAN NOT NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(128), 
	data_status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_entry UNIQUE (race_id, horse_id), 
	FOREIGN KEY(race_id) REFERENCES races (id) ON DELETE CASCADE, 
	FOREIGN KEY(horse_id) REFERENCES horses (id), 
	FOREIGN KEY(jockey_id) REFERENCES jockeys (id)
);

CREATE TABLE race_results (
	id SERIAL NOT NULL, 
	race_id INTEGER NOT NULL, 
	horse_id INTEGER NOT NULL, 
	finish_pos INTEGER, 
	finish_time_s FLOAT, 
	margin_text VARCHAR(64), 
	status VARCHAR(16) NOT NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(128), 
	data_status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_result UNIQUE (race_id, horse_id), 
	FOREIGN KEY(race_id) REFERENCES races (id) ON DELETE CASCADE, 
	FOREIGN KEY(horse_id) REFERENCES horses (id)
);
CREATE INDEX ix_results_horse ON race_results (horse_id);

CREATE TABLE sectional_times (
	id SERIAL NOT NULL, 
	race_id INTEGER NOT NULL, 
	horse_id INTEGER NOT NULL, 
	from_m FLOAT NOT NULL, 
	to_m FLOAT NOT NULL, 
	time_s FLOAT NOT NULL, 
	speed_mps FLOAT, 
	position INTEGER, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(128), 
	data_status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_sectional UNIQUE (race_id, horse_id, from_m, to_m, source_system), 
	FOREIGN KEY(race_id) REFERENCES races (id) ON DELETE CASCADE, 
	FOREIGN KEY(horse_id) REFERENCES horses (id)
);

CREATE TABLE simulation_runs (
	id SERIAL NOT NULL, 
	race_id INTEGER NOT NULL, 
	seed INTEGER NOT NULL, 
	engine_version VARCHAR(16) NOT NULL, 
	form_settings JSON NOT NULL, 
	intervention JSON, 
	kind VARCHAR(16) NOT NULL, 
	data_status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(race_id) REFERENCES races (id) ON DELETE CASCADE
);

CREATE TABLE simulation_results (
	id SERIAL NOT NULL, 
	run_id INTEGER NOT NULL, 
	horse_id INTEGER NOT NULL, 
	sim_pos INTEGER, 
	sim_time_s FLOAT, 
	win_prob FLOAT, 
	top3_prob FLOAT, 
	form_score FLOAT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_sim_result UNIQUE (run_id, horse_id), 
	FOREIGN KEY(run_id) REFERENCES simulation_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(horse_id) REFERENCES horses (id)
);
