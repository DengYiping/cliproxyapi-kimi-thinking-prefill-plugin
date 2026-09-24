package main

/*
#include <stdint.h>
#include <stdlib.h>

typedef struct {
	void* ptr;
	size_t len;
} cliproxy_buffer;

typedef int (*cliproxy_host_call_fn)(void*, const char*, const uint8_t*, size_t, cliproxy_buffer*);
typedef void (*cliproxy_host_free_fn)(void*, size_t);

typedef struct {
	uint32_t abi_version;
	void* host_ctx;
	cliproxy_host_call_fn call;
	cliproxy_host_free_fn free_buffer;
} cliproxy_host_api;

typedef int (*cliproxy_plugin_call_fn)(char*, uint8_t*, size_t, cliproxy_buffer*);
typedef void (*cliproxy_plugin_free_fn)(void*, size_t);
typedef void (*cliproxy_plugin_shutdown_fn)(void);

typedef struct {
	uint32_t abi_version;
	cliproxy_plugin_call_fn call;
	cliproxy_plugin_free_fn free_buffer;
	cliproxy_plugin_shutdown_fn shutdown;
} cliproxy_plugin_api;

extern int cliproxyPluginCall(char*, uint8_t*, size_t, cliproxy_buffer*);
extern void cliproxyPluginFree(void*, size_t);
extern void cliproxyPluginShutdown(void);

static const cliproxy_host_api* stored_host;

static void store_host_api(const cliproxy_host_api* host) {
	stored_host = host;
}

static int call_host_api(const char* method, const uint8_t* request, size_t request_len, cliproxy_buffer* response) {
	if (stored_host == NULL || stored_host->call == NULL) {
		return 1;
	}
	return stored_host->call(stored_host->host_ctx, method, request, request_len, response);
}

static void free_host_buffer(void* ptr, size_t len) {
	if (stored_host != NULL && stored_host->free_buffer != NULL && ptr != NULL) {
		stored_host->free_buffer(ptr, len);
	}
}
*/
import "C"

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync/atomic"
	"unsafe"

	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginabi"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
)

const (
	pluginName    = "kimi-thinking-prefill"
	pluginVersion = "0.2.0"
)

// githubRepository is required non-empty by the host; override with
// -ldflags "-X main.githubRepository=<url>" when publishing elsewhere.
var githubRepository = "https://github.com/DengYiping/cliproxyapi-kimi-thinking-prefill-plugin"

var currentConfig atomic.Pointer[config]

type envelope struct {
	OK     bool            `json:"ok"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  *envelopeError  `json:"error,omitempty"`
}

type envelopeError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type lifecycleRequest struct {
	ConfigYAML []byte `json:"config_yaml"`
}

type registration struct {
	SchemaVersion uint32                 `json:"schema_version"`
	Metadata      pluginapi.Metadata     `json:"metadata"`
	Capabilities  registrationCapability `json:"capabilities"`
}

type registrationCapability struct {
	RequestNormalizer bool `json:"request_normalizer"`
}

type hostLogRequest struct {
	Level   string         `json:"level"`
	Message string         `json:"message"`
	Fields  map[string]any `json:"fields,omitempty"`
}

func main() {}

func init() {
	cfg := defaultConfig()
	currentConfig.Store(&cfg)
}

//export cliproxy_plugin_init
func cliproxy_plugin_init(host *C.cliproxy_host_api, plugin *C.cliproxy_plugin_api) C.int {
	if plugin == nil {
		return 1
	}
	C.store_host_api(host)
	plugin.abi_version = C.uint32_t(pluginabi.ABIVersion)
	plugin.call = C.cliproxy_plugin_call_fn(C.cliproxyPluginCall)
	plugin.free_buffer = C.cliproxy_plugin_free_fn(C.cliproxyPluginFree)
	plugin.shutdown = C.cliproxy_plugin_shutdown_fn(C.cliproxyPluginShutdown)
	return 0
}

//export cliproxyPluginCall
func cliproxyPluginCall(method *C.char, request *C.uint8_t, requestLen C.size_t, response *C.cliproxy_buffer) C.int {
	if response != nil {
		response.ptr = nil
		response.len = 0
	}
	if method == nil {
		writeResponse(response, errorEnvelope("invalid_method", "method is required"))
		return 1
	}
	var requestBytes []byte
	if request != nil && requestLen > 0 {
		requestBytes = C.GoBytes(unsafe.Pointer(request), C.int(requestLen))
	}
	raw, errHandle := handleMethod(C.GoString(method), requestBytes)
	if errHandle != nil {
		writeResponse(response, errorEnvelope("plugin_error", errHandle.Error()))
		return 1
	}
	writeResponse(response, raw)
	return 0
}

//export cliproxyPluginFree
func cliproxyPluginFree(ptr unsafe.Pointer, _ C.size_t) {
	if ptr != nil {
		C.free(ptr)
	}
}

//export cliproxyPluginShutdown
func cliproxyPluginShutdown() {}

func handleMethod(method string, request []byte) ([]byte, error) {
	switch method {
	case pluginabi.MethodPluginRegister, pluginabi.MethodPluginReconfigure:
		if errConfigure := configure(request); errConfigure != nil {
			return nil, errConfigure
		}
		return okEnvelope(pluginRegistration())
	case pluginabi.MethodRequestNormalize:
		return normalizeRequest(request)
	default:
		return errorEnvelope("unknown_method", "unknown method: "+method), nil
	}
}

func configure(raw []byte) error {
	var req lifecycleRequest
	if len(raw) > 0 {
		if errUnmarshal := json.Unmarshal(raw, &req); errUnmarshal != nil {
			return fmt.Errorf("decode lifecycle request: %w", errUnmarshal)
		}
	}
	cfg, errParse := parseConfig(req.ConfigYAML)
	if errParse != nil {
		hostLog("warn", pluginName+": invalid config", map[string]any{"error": errParse.Error()})
		return errParse
	}
	currentConfig.Store(&cfg)
	return nil
}

func normalizeRequest(raw []byte) ([]byte, error) {
	var req pluginapi.RequestTransformRequest
	if errUnmarshal := json.Unmarshal(raw, &req); errUnmarshal != nil {
		return nil, fmt.Errorf("decode normalize request: %w", errUnmarshal)
	}
	cfg := currentConfig.Load()
	result := transform(*cfg, req.ToFormat, req.Model, req.Body)
	if cfg.DebugLog && strings.EqualFold(req.ToFormat, "openai") {
		// The host formatter prints only allowlisted fields, so details go in the message.
		message := fmt.Sprintf("%s: from=%s", pluginName, req.FromFormat)
		if len(result.Actions) > 0 {
			message += " actions=[" + strings.Join(result.Actions, "; ") + "]"
		}
		if result.Skip != "" {
			message += " skip=[" + result.Skip + "]"
		}
		hostLog("info", message, map[string]any{"model": req.Model})
	}
	return okEnvelope(pluginapi.PayloadResponse{Body: result.Body})
}

func pluginRegistration() registration {
	return registration{
		SchemaVersion: pluginabi.SchemaVersion,
		Metadata: pluginapi.Metadata{
			Name:             pluginName,
			Version:          pluginVersion,
			Author:           "ydeng",
			GitHubRepository: githubRepository,
			ConfigFields: []pluginapi.ConfigField{
				{Name: "inject", Type: pluginapi.ConfigFieldTypeBoolean, Description: "Inject the reasoning prefill and transform trailing <think> prefills."},
				{Name: "reasoning_prefill", Type: pluginapi.ConfigFieldTypeString, Description: "Seed text placed into reasoning_content of an injected partial assistant message."},
				{Name: "model_filter", Type: pluginapi.ConfigFieldTypeString, Description: "Comma-separated, case-insensitive model substrings to act on."},
				{Name: "force_thinking", Type: pluginapi.ConfigFieldTypeBoolean, Description: "Remove thinking-disabling params and set include_reasoning on modified requests."},
				{Name: "think_transform", Type: pluginapi.ConfigFieldTypeBoolean, Description: "Convert a trailing assistant <think> prefill into reasoning_content with partial=true."},
				{Name: "prior_thinking", Type: pluginapi.ConfigFieldTypeEnum, EnumValues: []string{priorThinkingKeep, priorThinkingStrip, priorThinkingExtract}, Description: "Reasoning on earlier assistant turns: keep as sent, strip it, or extract <think> blocks into reasoning_content."},
				{Name: "skip_with_tools", Type: pluginapi.ConfigFieldTypeBoolean, Description: "Skip requests with tools or tool turns."},
				{Name: "skip_with_json_schema", Type: pluginapi.ConfigFieldTypeBoolean, Description: "Skip requests asking for structured output."},
				{Name: "inline_tag", Type: pluginapi.ConfigFieldTypeString, Description: "Prompt tag name whose content overrides the prefill per request; empty disables."},
				{Name: "request_field", Type: pluginapi.ConfigFieldTypeString, Description: "Top-level request field that overrides the prefill per request; empty disables."},
				{Name: "sanitize_history", Type: pluginapi.ConfigFieldTypeBoolean, Description: "Strip refusal monologues, prefill echoes, and transport notes from history; drop empty assistant turns."},
				{Name: "anchor", Type: pluginapi.ConfigFieldTypeBoolean, Description: "Append the verbatim user ask to a config-sourced prefill, keeping the reasoning pinned to the request."},
				{Name: "anchor_template", Type: pluginapi.ConfigFieldTypeString, Description: "Template appended to the prefill when anchor is on; {ask} is replaced with the user ask."},
				{Name: "anchor_max_chars", Type: pluginapi.ConfigFieldTypeInteger, Description: "Cap on the verbatim ask embedded by the anchor."},
				{Name: "extra_body", Type: pluginapi.ConfigFieldTypeObject, Description: "Fields (sjson paths) merged into requests that receive a prefill."},
				{Name: "debug_log", Type: pluginapi.ConfigFieldTypeBoolean, Description: "Log each decision through the host logger."},
			},
		},
		Capabilities: registrationCapability{RequestNormalizer: true},
	}
}

func hostLog(level, message string, fields map[string]any) {
	raw, errMarshal := json.Marshal(hostLogRequest{Level: level, Message: message, Fields: fields})
	if errMarshal != nil {
		return
	}
	cMethod := C.CString(pluginabi.MethodHostLog)
	defer C.free(unsafe.Pointer(cMethod))
	req := (*C.uint8_t)(C.CBytes(raw))
	defer C.free(unsafe.Pointer(req))
	var response C.cliproxy_buffer
	if C.call_host_api(cMethod, req, C.size_t(len(raw)), &response) == 0 && response.ptr != nil {
		C.free_host_buffer(response.ptr, response.len)
	}
}

func okEnvelope(v any) ([]byte, error) {
	raw, errMarshal := json.Marshal(v)
	if errMarshal != nil {
		return nil, errMarshal
	}
	return json.Marshal(envelope{OK: true, Result: raw})
}

func errorEnvelope(code, message string) []byte {
	raw, _ := json.Marshal(envelope{OK: false, Error: &envelopeError{Code: code, Message: message}})
	return raw
}

func writeResponse(response *C.cliproxy_buffer, raw []byte) {
	if response == nil || len(raw) == 0 {
		return
	}
	ptr := C.CBytes(raw)
	if ptr == nil {
		return
	}
	response.ptr = ptr
	response.len = C.size_t(len(raw))
}
