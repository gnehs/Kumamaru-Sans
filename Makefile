PYTHON ?= python3
FONT ?= vendor/IBMPlexSansTC-Regular.ttf
BUILD ?= build
GLYPHS ?= config/glyphsets/smoke.txt
CONFIG ?= config/regular.toml
OVERRIDES ?= config/overrides.yaml

.PHONY: lint test smoke full validate validate-full fontbakery proof

lint:
	$(PYTHON) -m ruff format --check src tests
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m mypy src/kumamaru

test:
	$(PYTHON) -m pytest

smoke:
	@if [ ! -f "$(FONT)" ]; then \
		echo "skip: missing official upstream font: $(FONT)"; \
	else \
		mkdir -p "$(BUILD)"; \
		$(PYTHON) -m kumamaru.cli inspect --input "$(FONT)" --output "$(BUILD)/inspection.json"; \
		$(PYTHON) -m kumamaru.cli analyze --input "$(FONT)" --glyphs "$(GLYPHS)" --config "$(CONFIG)" --output "$(BUILD)/analysis.json"; \
		$(PYTHON) -m kumamaru.cli build --input "$(FONT)" --output "$(BUILD)/KumamaruSans-Regular.ttf" --glyphs "$(GLYPHS)" --config "$(CONFIG)" --overrides "$(OVERRIDES)" --report "$(BUILD)/build-report.json"; \
	fi

full:
	@if [ ! -f "$(FONT)" ]; then \
		echo "skip: missing official upstream font: $(FONT)"; \
	else \
		mkdir -p "$(BUILD)"; \
		$(PYTHON) -m kumamaru.cli inspect --input "$(FONT)" --output "$(BUILD)/inspection.json"; \
		$(PYTHON) -m kumamaru.cli analyze --input "$(FONT)" --glyphs "$(GLYPHS)" --config "$(CONFIG)" --output "$(BUILD)/analysis.json"; \
		$(PYTHON) -m kumamaru.cli build --input "$(FONT)" --output "$(BUILD)/KumamaruSans-Regular.ttf" --all-encoded-glyphs --config "$(CONFIG)" --overrides "$(OVERRIDES)" --report "$(BUILD)/build-report.json"; \
	fi

proof:
	@if [ ! -f "$(FONT)" ]; then \
		echo "skip: missing official upstream font: $(FONT)"; \
	else \
		$(PYTHON) -m kumamaru.cli proof --before "$(FONT)" --after "$(BUILD)/KumamaruSans-Regular.ttf" --glyphs "$(GLYPHS)" --analysis "$(BUILD)/analysis.json" --build-report "$(BUILD)/build-report.json" --output "$(BUILD)/proof"; \
	fi

validate:
	@if [ ! -f "$(FONT)" ]; then \
		echo "skip: missing official upstream font: $(FONT)"; \
	else \
		$(PYTHON) -m kumamaru.cli validate --before "$(FONT)" --after "$(BUILD)/KumamaruSans-Regular.ttf" --glyphs "$(GLYPHS)" --output "$(BUILD)/validation.json"; \
	fi

validate-full:
	@if [ ! -f "$(FONT)" ]; then \
		echo "skip: missing official upstream font: $(FONT)"; \
	else \
		$(PYTHON) -m kumamaru.cli validate --before "$(FONT)" --after "$(BUILD)/KumamaruSans-Regular.ttf" --all-encoded-glyphs --output "$(BUILD)/validation.json"; \
	fi

fontbakery:
	@if [ ! -f "$(BUILD)/KumamaruSans-Regular.ttf" ]; then \
		echo "skip: missing built font: $(BUILD)/KumamaruSans-Regular.ttf"; \
	else \
		mkdir -p "$(BUILD)"; \
		$(PYTHON) -m fontbakery check-universal --no-progress --json "$(BUILD)/fontbakery.json" "$(BUILD)/KumamaruSans-Regular.ttf"; \
	fi
