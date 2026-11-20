# Regenerate the Fava extension screenshots in docs/fava/images: all of them, or
# only the named ones, e.g. `make screenshots NAMES=year-in-review`. Set
# PLAYWRIGHT to pin the version matching an installed browser, e.g.
# PLAYWRIGHT=playwright==1.63.0.
PLAYWRIGHT ?= playwright

screenshots:
	uv run --with $(PLAYWRIGHT) python docs/fava/screenshots.py $(NAMES)

.PHONY: screenshots
