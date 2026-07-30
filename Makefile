PYTHON ?= python3
FONT ?= vendor/IBMPlexSansTC-Regular.ttf
BUILD ?= build
GLYPHS ?= config/glyphsets/smoke.txt
CONFIG ?= config/regular.toml
OVERRIDES ?= config/overrides.yaml
SOURCE ?= vendor/ibm-plex-sans-tc/sources/masters/IBM Plex Sans TC.glyphs
DERIVED_SOURCE ?= $(BUILD)/source/Kumamaru Sans.glyphs
SOURCE_REPORT ?= $(BUILD)/source/rounding-report.json
SMOKE_DERIVED_SOURCE ?= $(BUILD)/source/Kumamaru Sans Smoke.glyphs
SMOKE_SOURCE_REPORT ?= $(BUILD)/source/smoke-rounding-report.json
VARIABLE_FONT ?= $(BUILD)/source/variable-ttf/KumamaruSans[wght].ttf
SOURCE_FONTBAKERY_REPORT ?= $(BUILD)/source/fontbakery.json
INSTANCE ?=

.PHONY: lint test smoke full validate validate-full fontbakery proof source-inspect source-round source-round-smoke source-build-masters source-build-instance source-build-instances source-build-variable source-fontbakery

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

source-inspect:
	@if [ ! -f "$(SOURCE)" ]; then \
		echo "skip: missing official upstream Glyphs source: $(SOURCE)"; \
	else \
		mkdir -p "$(BUILD)/source"; \
		$(PYTHON) -m kumamaru.cli source-inspect --input "$(SOURCE)" --glyphs "$(GLYPHS)" --expect-ibm-plex-sans-tc --output "$(BUILD)/source/manifest.json"; \
	fi

source-round:
	@if [ ! -f "$(SOURCE)" ]; then \
		echo "skip: missing official upstream Glyphs source: $(SOURCE)"; \
	else \
		mkdir -p "$(BUILD)/source"; \
		$(PYTHON) -m kumamaru.cli source-round --input "$(SOURCE)" --output "$(DERIVED_SOURCE)" --all-glyphs --report "$(SOURCE_REPORT)" --reference-master Regular --radius Thin=28 --radius Regular=48 --radius Bold=68 --inner-radius Thin=18 --inner-radius Regular=32 --inner-radius Bold=46 --normalize-ibm-plex-sans-tc; \
	fi

source-round-smoke:
	@if [ ! -f "$(SOURCE)" ]; then \
		echo "skip: missing official upstream Glyphs source: $(SOURCE)"; \
	else \
		mkdir -p "$(BUILD)/source"; \
		$(PYTHON) -m kumamaru.cli source-round --input "$(SOURCE)" --output "$(SMOKE_DERIVED_SOURCE)" --glyphs "$(GLYPHS)" --report "$(SMOKE_SOURCE_REPORT)" --reference-master Regular --radius Thin=28 --radius Regular=48 --radius Bold=68 --inner-radius Thin=18 --inner-radius Regular=32 --inner-radius Bold=46 --normalize-ibm-plex-sans-tc; \
	fi

source-build-masters:
	@if [ ! -f "$(DERIVED_SOURCE)" ]; then \
		echo "skip: missing derived Glyphs source: $(DERIVED_SOURCE)"; \
	else \
		mkdir -p "$(BUILD)/source/master-ttf" && \
		$(PYTHON) -m fontmake "$(DERIVED_SOURCE)" -o ttf --output-dir "$(BUILD)/source/master-ttf" --master-dir "$(BUILD)/source/master-build-ufo" --designspace-path "$(BUILD)/source/masters.designspace" --no-production-names --verbose ERROR && \
		$(PYTHON) -m kumamaru.source_metadata --config "$(CONFIG)" "$(BUILD)/source/master-ttf"; \
	fi

source-build-instances:
	@if [ ! -f "$(DERIVED_SOURCE)" ]; then \
		echo "skip: missing derived Glyphs source: $(DERIVED_SOURCE)"; \
	else \
		mkdir -p "$(BUILD)/source/instance-ttf" && \
		$(PYTHON) -m fontmake "$(DERIVED_SOURCE)" -o ttf -i --output-dir "$(BUILD)/source/instance-ttf" --master-dir "$(BUILD)/source/instance-build-ufo" --designspace-path "$(BUILD)/source/instances.designspace" --no-production-names --verbose ERROR && \
		$(PYTHON) -m kumamaru.source_metadata --config "$(CONFIG)" "$(BUILD)/source/instance-ttf"; \
	fi

source-build-instance:
	@if [ -z "$(INSTANCE)" ]; then \
		echo "error: INSTANCE is required"; \
		exit 2; \
	elif [ ! -f "$(DERIVED_SOURCE)" ]; then \
		echo "skip: missing derived Glyphs source: $(DERIVED_SOURCE)"; \
	else \
		mkdir -p "$(BUILD)/source/instance-ttf" && \
		$(PYTHON) -m fontmake "$(DERIVED_SOURCE)" -o ttf -i ".* $(INSTANCE)$$" --output-dir "$(BUILD)/source/instance-ttf" --master-dir "$(BUILD)/source/instance-build-ufo" --designspace-path "$(BUILD)/source/instances.designspace" --no-production-names --verbose ERROR && \
		$(PYTHON) -m kumamaru.source_metadata --config "$(CONFIG)" "$(BUILD)/source/instance-ttf"; \
	fi

source-build-variable:
	@if [ ! -f "$(DERIVED_SOURCE)" ]; then \
		echo "skip: missing derived Glyphs source: $(DERIVED_SOURCE)"; \
	else \
		mkdir -p "$(dir $(VARIABLE_FONT))" && \
		$(PYTHON) -m fontmake "$(DERIVED_SOURCE)" -o variable --output-path "$(VARIABLE_FONT)" --master-dir "$(BUILD)/source/variable-build-ufo" --designspace-path "$(BUILD)/source/variable.designspace" --no-production-names --filter='...' --filter='kumamaru.filters.variable_compatibility::VariableCompatibilityFilter' --verbose ERROR && \
		$(PYTHON) -m kumamaru.source_metadata --config "$(CONFIG)" "$(VARIABLE_FONT)"; \
	fi

source-fontbakery:
	@mkdir -p "$(dir $(SOURCE_FONTBAKERY_REPORT))"
	$(PYTHON) -m fontbakery check-universal \
		--skip-network --no-progress --error-code-on FAIL \
		--json "$(SOURCE_FONTBAKERY_REPORT)" \
		-c opentype/family/consistent_family_name \
		-c opentype/fvar/axis_ranges_correct \
		-c opentype/fvar/regular_coords_correct \
		-c opentype/varfont/STAT_axis_record_for_each_axis \
		-c opentype/weight_class_fvar \
		-c fvar_name_entries \
		-c inconsistencies_between_fvar_STAT \
		-c STAT_strings \
		-c typographic_family_name \
		"$(BUILD)"/source/instance-ttf/*.ttf "$(VARIABLE_FONT)"
