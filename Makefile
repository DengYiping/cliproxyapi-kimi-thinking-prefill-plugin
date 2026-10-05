PLUGIN_ID  := kimi-thinking-prefill
PLUGIN_VERSION := $(shell awk -F '"' '/pluginVersion =/ {print $$2; exit}' main.go)
# Directory configured as plugins.dir in the CLIProxyAPI config.
PLUGINS_DIR ?= $(HOME)/.cli-proxy-api/plugins
GOOS       := $(shell go env GOOS)
GOARCH     := $(shell go env GOARCH)
EXT        := $(if $(filter darwin,$(GOOS)),dylib,$(if $(filter windows,$(GOOS)),dll,so))
OUT_DIR    := bin/$(GOOS)/$(GOARCH)
ARTIFACT   := $(OUT_DIR)/$(PLUGIN_ID).$(EXT)
INSTALLED_ARTIFACT := $(PLUGINS_DIR)/$(GOOS)/$(GOARCH)/$(PLUGIN_ID)-v$(PLUGIN_VERSION).$(EXT)

.PHONY: build test install install-hot-reload clean

build:
	@mkdir -p $(OUT_DIR)
	CGO_ENABLED=1 go build -trimpath -buildmode=c-shared -o $(ARTIFACT) .
	@rm -f $(OUT_DIR)/$(PLUGIN_ID).h
	@echo "built $(ARTIFACT)"

test:
	go test .

install: install-hot-reload

install-hot-reload: build
	@mkdir -p $(PLUGINS_DIR)/$(GOOS)/$(GOARCH)
	@if test -f '$(INSTALLED_ARTIFACT)' && ! cmp -s '$(ARTIFACT)' '$(INSTALLED_ARTIFACT)'; then \
		echo "refusing to overwrite existing $(notdir $(INSTALLED_ARTIFACT)); bump pluginVersion in main.go first" >&2; \
		exit 1; \
	fi
	@cmp -s '$(ARTIFACT)' '$(INSTALLED_ARTIFACT)' || cp $(ARTIFACT) $(INSTALLED_ARTIFACT)
	@echo "installed $(INSTALLED_ARTIFACT); let CLIProxyAPI hot-reload it without a restart"

clean:
	rm -rf bin
