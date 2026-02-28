# AgentStream — build targets for macOS app
#
# Usage:
#   make app          Build AgentStream.app (requires macOS + py2app)
#   make app-dev      Alias build for fast iteration (symlinks, not copied)
#   make dmg          Build a distributable DMG installer
#   make icon         Generate the app icon (requires Pillow)
#   make install      Copy AgentStream.app to /Applications
#   make uninstall    Remove from /Applications
#   make clean        Remove all build artifacts
#   make test         Run the test suite
#   make help         Show this help

.DEFAULT_GOAL := help
SHELL := /bin/bash

APP_NAME     := AgentStream
APP_BUNDLE   := dist/$(APP_NAME).app
DMG_NAME     := $(APP_NAME).dmg
DMG_PATH     := dist/$(DMG_NAME)
ICON_PATH    := assets/$(APP_NAME).icns
INSTALL_DIR  := /Applications

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

.PHONY: app app-dev icon

icon: ## Generate app icon (requires: pip install Pillow)
	python macos/create_icon.py

app: _check-macos _ensure-deps icon ## Build AgentStream.app
	python setup_mac.py py2app
	@echo ""
	@echo "  ✓ Built $(APP_BUNDLE)"
	@echo "  → Drag to $(INSTALL_DIR) or run:  make install"
	@echo ""

app-dev: _check-macos _ensure-deps ## Alias build (fast, for development)
	python setup_mac.py py2app -A
	@echo ""
	@echo "  ✓ Built $(APP_BUNDLE) (alias/dev mode)"
	@echo ""

# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

.PHONY: dmg

dmg: app ## Build distributable DMG
	@rm -f "$(DMG_PATH)"
	@echo "Creating DMG..."
	hdiutil create \
		-volname "$(APP_NAME)" \
		-srcfolder "$(APP_BUNDLE)" \
		-ov -format UDZO \
		"$(DMG_PATH)"
	@echo ""
	@echo "  ✓ Created $(DMG_PATH)"
	@echo ""

# ---------------------------------------------------------------------------
# Install / Uninstall
# ---------------------------------------------------------------------------

.PHONY: install uninstall

install: app ## Install to /Applications
	@echo "Installing $(APP_NAME).app..."
	@rm -rf "$(INSTALL_DIR)/$(APP_NAME).app"
	cp -R "$(APP_BUNDLE)" "$(INSTALL_DIR)/$(APP_NAME).app"
	@echo "  ✓ Installed to $(INSTALL_DIR)/$(APP_NAME).app"
	@echo ""
	@echo "  Tip: Add to Login Items in System Settings to auto-start."

uninstall: ## Remove from /Applications
	@echo "Removing $(APP_NAME).app..."
	rm -rf "$(INSTALL_DIR)/$(APP_NAME).app"
	@echo "  ✓ Removed"

# ---------------------------------------------------------------------------
# Test / Lint
# ---------------------------------------------------------------------------

.PHONY: test

test: ## Run test suite
	python -m pytest tests/ -v

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

.PHONY: clean

clean: ## Remove all build artifacts
	rm -rf build/ dist/ .eggs/
	rm -rf assets/$(APP_NAME).iconset assets/$(APP_NAME).icns
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "  ✓ Cleaned"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

.PHONY: _check-macos _ensure-deps help

_check-macos:
	@if [ "$$(uname)" != "Darwin" ]; then \
		echo "Error: macOS is required to build $(APP_NAME).app"; \
		exit 1; \
	fi

_ensure-deps:
	@python -c "import rumps" 2>/dev/null || \
		(echo "Installing toolbar dependencies..." && pip install -q ".[toolbar]")
	@python -c "import py2app" 2>/dev/null || \
		(echo "Installing py2app..." && pip install -q py2app)
	@python -c "import PIL" 2>/dev/null || \
		(echo "Installing Pillow for icon generation..." && pip install -q Pillow)

help: ## Show this help
	@echo "AgentStream — macOS App Build Targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Quick start:"
	@echo "  make app          Build the .app bundle"
	@echo "  make install      Copy to /Applications"
	@echo "  make dmg          Create a distributable DMG"
