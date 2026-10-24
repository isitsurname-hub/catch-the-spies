PYTHON ?= python3
INPUT_DIR ?= /home/gotm/Загрузки/03_processed-20261023T151344Z-1-001/03_processed
OUTPUT_DIR ?= results

PRIMARY_THRESHOLD ?= 8
SECONDARY_MIN_SCORE ?= 5
SECONDARY_MIN_TYPES ?= 2
MAX_ROUNDS ?= 3
HOST ?= 127.0.0.1
PORT ?= 8765

DB := $(OUTPUT_DIR)/index.sqlite
INPUT_FILES := $(INPUT_DIR)/dim_person.csv $(INPUT_DIR)/fact_tickets.csv $(INPUT_DIR)/fact_flights.csv
PRIMARY_FILES := $(addprefix $(OUTPUT_DIR)/,01_passport_collision.csv 02_profile_conflict.csv 03_joint_travel.csv 04_near_passports_with_travel.csv 05_schedule_conflict.csv)
SECONDARY_FILES := $(addprefix $(OUTPUT_DIR)/,06_near_passport.csv 07_shared_pnr.csv 08_parallel_arrivals.csv 09_convergence.csv)

.DEFAULT_GOAL := help
.PHONY: help prepare primary-signals score primary secondary-signals secondary expand all test status web

help:
	@printf '%s\n' \
	  'Команды (запускать из директории spy_detection):' \
	  '  make primary     индекс + 5 первичных признаков + баллы' \
	  '  make expand      первичный этап при необходимости + 4 вторичных признака + цепочки' \
	  '  make all         полный прогон (то же, что make expand с нуля)' \
	  '  make prepare     только индекс и связи билетов с людьми' \
	  '  make score       пересчитать первичные баллы' \
	  '  make secondary  только таблицы вторичных признаков' \
	  '  make status     число строк в основных итоговых CSV' \
	  '  make web        локальный сайт на http://127.0.0.1:8765' \
	  '  make test       тесты на небольшом искусственном наборе' \
	  '' \
	  'По умолчанию входные CSV: $(INPUT_DIR)' \
	  'Результаты: $(OUTPUT_DIR)' \
	  'Повторный запуск использует готовые файлы; make -B all пересчитает всё.'

$(DB): $(INPUT_FILES) pipeline.py
	$(PYTHON) pipeline.py prepare --input-dir "$(INPUT_DIR)" --output-dir "$(OUTPUT_DIR)"

prepare: $(DB)

$(OUTPUT_DIR)/01_passport_collision.csv: $(DB) pipeline.py
	$(PYTHON) pipeline.py passport_collision --output-dir "$(OUTPUT_DIR)"

$(OUTPUT_DIR)/02_profile_conflict.csv: $(DB) pipeline.py
	$(PYTHON) pipeline.py profile_conflict --output-dir "$(OUTPUT_DIR)"

$(OUTPUT_DIR)/03_joint_travel.csv: $(DB) pipeline.py
	$(PYTHON) pipeline.py joint_travel --output-dir "$(OUTPUT_DIR)"

$(OUTPUT_DIR)/04_near_passports_with_travel.csv: $(DB) pipeline.py
	$(PYTHON) pipeline.py near_passports_with_travel --output-dir "$(OUTPUT_DIR)"

$(OUTPUT_DIR)/05_schedule_conflict.csv: $(DB) pipeline.py
	$(PYTHON) pipeline.py schedule_conflict --output-dir "$(OUTPUT_DIR)"

primary-signals: $(PRIMARY_FILES)

score: $(PRIMARY_FILES)
	$(PYTHON) pipeline.py score --output-dir "$(OUTPUT_DIR)" --threshold $(PRIMARY_THRESHOLD)

primary: score

$(OUTPUT_DIR)/06_near_passport.csv: $(DB) pipeline.py
	$(PYTHON) pipeline.py near_passport --output-dir "$(OUTPUT_DIR)"

$(OUTPUT_DIR)/07_shared_pnr.csv: $(DB) pipeline.py
	$(PYTHON) pipeline.py shared_pnr --output-dir "$(OUTPUT_DIR)"

$(OUTPUT_DIR)/08_parallel_arrivals.csv: $(DB) pipeline.py
	$(PYTHON) pipeline.py parallel_arrivals --output-dir "$(OUTPUT_DIR)"

$(OUTPUT_DIR)/09_convergence.csv: $(DB) pipeline.py
	$(PYTHON) pipeline.py convergence --output-dir "$(OUTPUT_DIR)"

secondary-signals: $(SECONDARY_FILES)
secondary: secondary-signals

expand: score secondary-signals
	$(PYTHON) pipeline.py expand --output-dir "$(OUTPUT_DIR)" \
	  --min-score $(SECONDARY_MIN_SCORE) \
	  --min-types $(SECONDARY_MIN_TYPES) \
	  --max-rounds $(MAX_ROUNDS)

all: expand

test:
	$(PYTHON) -m unittest discover -s . -p 'test_*.py' -v

status:
	@$(PYTHON) -c 'import csv,pathlib; p=pathlib.Path("$(OUTPUT_DIR)"); names=("primary_candidates.csv","secondary_candidates.csv","primary_candidates_final.csv","chain_edges.csv"); [(print(name+": "+str(sum(1 for _ in csv.DictReader((p/name).open(encoding="utf-8-sig"))))) if (p/name).exists() else print(name+": ещё не создан")) for name in names]'

web:
	$(PYTHON) web/server.py --input-dir "$(INPUT_DIR)" --results-dir "$(OUTPUT_DIR)" --host "$(HOST)" --port "$(PORT)"
