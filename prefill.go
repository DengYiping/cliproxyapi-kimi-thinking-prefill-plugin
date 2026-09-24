package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"

	"github.com/tidwall/gjson"
	"github.com/tidwall/sjson"
	"gopkg.in/yaml.v3"
)

const (
	priorThinkingKeep    = "keep"
	priorThinkingStrip   = "strip"
	priorThinkingExtract = "extract"
)

var (
	// thinkPrefixPattern matches a leading <think> block, closed or still open.
	thinkPrefixPattern = regexp.MustCompile(`(?s)^\s*<think>(.*?)(?:</think>|$)`)
	// closedThinkPattern matches a leading, fully closed <think> block.
	closedThinkPattern = regexp.MustCompile(`(?s)^\s*<think>(.*?)</think>`)
	identifierPattern  = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
)

// config mirrors the KimiThinkingPrefill SillyTavern extension settings,
// adapted to a proxy that sees fully translated OpenAI chat payloads.
type config struct {
	// Inject enables prefill injection and the trailing <think> transform.
	Inject bool `yaml:"inject"`
	// ReasoningPrefill is the seed placed into reasoning_content.
	ReasoningPrefill string `yaml:"reasoning_prefill"`
	// ModelFilter is a comma-separated list of case-insensitive model substrings.
	ModelFilter string `yaml:"model_filter"`
	// ForceThinking removes thinking-disabling params and sets include_reasoning.
	ForceThinking bool `yaml:"force_thinking"`
	// ThinkTransform converts a trailing assistant <think> prefill into reasoning_content.
	ThinkTransform bool `yaml:"think_transform"`
	// PriorThinking controls reasoning on earlier assistant turns: keep, strip, or extract.
	PriorThinking string `yaml:"prior_thinking"`
	// SkipWithTools skips requests that declare tools or contain tool turns.
	SkipWithTools bool `yaml:"skip_with_tools"`
	// SkipWithJSONSchema skips requests that ask for structured output.
	SkipWithJSONSchema bool `yaml:"skip_with_json_schema"`
	// InlineTag names a prompt tag (<tag>seed</tag>) that overrides the prefill per request.
	InlineTag string `yaml:"inline_tag"`
	// RequestField names a top-level body field that overrides the prefill per request.
	RequestField string `yaml:"request_field"`
	// ExtraBody is merged into requests that receive a prefill; keys are sjson paths.
	ExtraBody map[string]any `yaml:"extra_body"`
	// DebugLog logs every decision through the host logger.
	DebugLog bool `yaml:"debug_log"`

	inlinePattern *regexp.Regexp
}

func defaultConfig() config {
	return config{
		Inject:             true,
		ModelFilter:        "kimi,moonshot",
		ForceThinking:      true,
		ThinkTransform:     true,
		PriorThinking:      priorThinkingKeep,
		SkipWithJSONSchema: true,
		InlineTag:          "kimi_prefill",
		RequestField:       "kimi_thinking_prefill",
	}
}

// parseConfig decodes plugins.configs.<id> YAML over the defaults.
func parseConfig(raw []byte) (config, error) {
	cfg := defaultConfig()
	if len(bytes.TrimSpace(raw)) > 0 {
		if errUnmarshal := yaml.Unmarshal(raw, &cfg); errUnmarshal != nil {
			return config{}, fmt.Errorf("decode plugin config: %w", errUnmarshal)
		}
	}

	cfg.PriorThinking = strings.ToLower(strings.TrimSpace(cfg.PriorThinking))
	switch cfg.PriorThinking {
	case "":
		cfg.PriorThinking = priorThinkingKeep
	case priorThinkingKeep, priorThinkingStrip, priorThinkingExtract:
	default:
		return config{}, fmt.Errorf("prior_thinking must be keep, strip, or extract, got %q", cfg.PriorThinking)
	}

	cfg.InlineTag = strings.TrimSpace(cfg.InlineTag)
	if cfg.InlineTag != "" {
		if !identifierPattern.MatchString(cfg.InlineTag) {
			return config{}, fmt.Errorf("inline_tag %q may only contain letters, digits, '_', '.', '-'", cfg.InlineTag)
		}
		tag := regexp.QuoteMeta(cfg.InlineTag)
		cfg.inlinePattern = regexp.MustCompile(`(?s)<` + tag + `\s*/>|<` + tag + `>(.*?)</` + tag + `>`)
	}

	cfg.RequestField = strings.TrimSpace(cfg.RequestField)
	if cfg.RequestField != "" && !identifierPattern.MatchString(cfg.RequestField) {
		return config{}, fmt.Errorf("request_field %q may only contain letters, digits, '_', '.', '-'", cfg.RequestField)
	}
	return cfg, nil
}

// outcome reports what transform did to a request.
type outcome struct {
	Body    []byte
	Changed bool
	// Skip explains why the request was left alone, if it was.
	Skip string
	// Actions lists the modifications applied, for debug logging.
	Actions []string
}

// prefillOverride is a per-request prefill supplied by the client.
type prefillOverride struct {
	set    bool
	value  string
	source string
}

// transform applies the thinking prefill rules to an OpenAI chat completions payload.
func transform(cfg config, toFormat, model string, body []byte) outcome {
	out := outcome{Body: body}
	if !strings.EqualFold(toFormat, "openai") {
		out.Skip = "target format is not openai"
		return out
	}
	if !gjson.GetBytes(body, "messages").IsArray() {
		out.Skip = "no messages array"
		return out
	}
	if !modelMatches(cfg.ModelFilter, model, gjson.GetBytes(body, "model").String()) {
		out.Skip = "model does not match model_filter"
		return out
	}

	var messages []map[string]any
	decoder := json.NewDecoder(bytes.NewReader([]byte(gjson.GetBytes(body, "messages").Raw)))
	decoder.UseNumber()
	if errDecode := decoder.Decode(&messages); errDecode != nil || len(messages) == 0 {
		out.Skip = "messages could not be decoded"
		return out
	}
	messagesChanged := false

	// Per-request overrides are always consumed so control markers never reach the model.
	override := prefillOverride{}
	if cfg.inlinePattern != nil {
		if value, found := extractInlineTag(cfg.inlinePattern, messages); found {
			override = prefillOverride{set: true, value: value, source: "inline_tag"}
			messagesChanged = true
			out.Actions = append(out.Actions, "consumed inline tag")
		}
	}
	if cfg.RequestField != "" {
		if field := gjson.GetBytes(body, cfg.RequestField); field.Exists() {
			switch field.Type {
			case gjson.String:
				override = prefillOverride{set: true, value: field.String(), source: "request_field"}
			case gjson.False:
				override = prefillOverride{set: true, value: "", source: "request_field"}
			}
			if updated, errDelete := sjson.DeleteBytes(body, cfg.RequestField); errDelete == nil {
				body = updated
				out.Changed = true
				out.Actions = append(out.Actions, "consumed request field")
			}
		}
	}

	finish := func() outcome {
		if messagesChanged {
			encoded, errEncode := json.Marshal(messages)
			if errEncode == nil {
				if updated, errSet := sjson.SetRawBytes(body, "messages", encoded); errSet == nil {
					body = updated
					out.Changed = true
				}
			}
		}
		out.Body = body
		return out
	}

	if cfg.SkipWithJSONSchema {
		switch gjson.GetBytes(body, "response_format.type").String() {
		case "json_schema", "json_object":
			out.Skip = "structured output requested"
			return finish()
		}
	}
	if cfg.SkipWithTools && usesTools(body, messages) {
		out.Skip = "tools in use"
		return finish()
	}

	last := messages[len(messages)-1]
	lastIsAssistant := roleOf(last) == "assistant"

	if cfg.PriorThinking != priorThinkingKeep {
		end := len(messages)
		if lastIsAssistant {
			end--
		}
		for i := 0; i < end; i++ {
			if roleOf(messages[i]) != "assistant" {
				continue
			}
			if applyPriorThinking(cfg.PriorThinking, messages[i]) {
				messagesChanged = true
			}
		}
		if messagesChanged {
			out.Actions = append(out.Actions, "prior_thinking="+cfg.PriorThinking)
		}
	}

	if !cfg.Inject {
		out.Skip = "inject disabled"
		return finish()
	}

	if lastIsAssistant {
		if !cfg.ThinkTransform {
			out.Skip = "last message is assistant and think_transform is disabled"
			return finish()
		}
		if partial, _ := last["partial"].(bool); partial {
			out.Skip = "client already sent a partial assistant message"
			return finish()
		}
		content, isString := last["content"].(string)
		if match := thinkPrefixPattern.FindStringSubmatchIndex(content); isString && match != nil {
			last["reasoning_content"] = strings.TrimSpace(content[match[2]:match[3]])
			last["content"] = strings.TrimLeft(content[match[1]:], " \t\r\n")
			last["partial"] = true
			messagesChanged = true
			out.Actions = append(out.Actions, "transformed trailing <think> prefill")
		} else if reasoning, _ := last["reasoning_content"].(string); strings.TrimSpace(reasoning) != "" {
			last["partial"] = true
			messagesChanged = true
			out.Actions = append(out.Actions, "marked trailing reasoning prefill as partial")
		} else {
			out.Skip = "last message is assistant without a thinking prefill"
			return finish()
		}
	} else {
		prefill := cfg.ReasoningPrefill
		source := "config"
		if override.set {
			prefill = override.value
			source = override.source
		}
		if strings.TrimSpace(prefill) == "" {
			out.Skip = "prefill is empty (" + source + ")"
			return finish()
		}
		messages = append(messages, map[string]any{
			"role":              "assistant",
			"content":           "",
			"reasoning_content": prefill,
			"partial":           true,
		})
		messagesChanged = true
		out.Actions = append(out.Actions, "injected reasoning prefill from "+source)
	}

	body, out.Actions = applyThinkingParams(cfg, body, out.Actions)
	out.Changed = true
	return finish()
}

// modelMatches reports whether any comma-separated filter entry is a
// case-insensitive substring of one of the model names. An empty filter matches nothing.
func modelMatches(filter string, models ...string) bool {
	var needles []string
	for _, part := range strings.Split(filter, ",") {
		if part = strings.ToLower(strings.TrimSpace(part)); part != "" {
			needles = append(needles, part)
		}
	}
	for _, model := range models {
		hay := strings.ToLower(model)
		if hay == "" {
			continue
		}
		for _, needle := range needles {
			if strings.Contains(hay, needle) {
				return true
			}
		}
	}
	return false
}

func roleOf(message map[string]any) string {
	role, _ := message["role"].(string)
	return role
}

func usesTools(body []byte, messages []map[string]any) bool {
	if tools := gjson.GetBytes(body, "tools"); tools.IsArray() && len(tools.Array()) > 0 {
		return true
	}
	for _, message := range messages {
		if roleOf(message) == "tool" {
			return true
		}
		if calls, ok := message["tool_calls"].([]any); ok && len(calls) > 0 {
			return true
		}
	}
	return false
}

// extractInlineTag removes every inline tag from system, developer, and user
// text and returns the value of the last one found.
func extractInlineTag(pattern *regexp.Regexp, messages []map[string]any) (string, bool) {
	value := ""
	found := false
	strip := func(text string) string {
		return pattern.ReplaceAllStringFunc(text, func(match string) string {
			found = true
			value = ""
			if sub := pattern.FindStringSubmatch(match); len(sub) > 1 {
				value = strings.TrimSpace(sub[1])
			}
			return ""
		})
	}
	for _, message := range messages {
		switch roleOf(message) {
		case "system", "developer", "user":
		default:
			continue
		}
		switch content := message["content"].(type) {
		case string:
			message["content"] = strip(content)
		case []any:
			for _, rawPart := range content {
				part, ok := rawPart.(map[string]any)
				if !ok || part["type"] != "text" {
					continue
				}
				if text, isString := part["text"].(string); isString {
					part["text"] = strip(text)
				}
			}
		}
	}
	return value, found
}

// applyPriorThinking strips or extracts reasoning on an earlier assistant turn.
func applyPriorThinking(mode string, message map[string]any) bool {
	switch mode {
	case priorThinkingStrip:
		changed := false
		for _, key := range []string{"reasoning_content", "reasoning"} {
			if _, exists := message[key]; exists {
				delete(message, key)
				changed = true
			}
		}
		if content, isString := message["content"].(string); isString {
			if match := closedThinkPattern.FindStringIndex(content); match != nil {
				message["content"] = strings.TrimLeft(content[match[1]:], " \t\r\n")
				changed = true
			}
		}
		return changed
	case priorThinkingExtract:
		if existing, _ := message["reasoning_content"].(string); strings.TrimSpace(existing) != "" {
			return false
		}
		content, isString := message["content"].(string)
		if !isString {
			return false
		}
		match := closedThinkPattern.FindStringSubmatchIndex(content)
		if match == nil {
			return false
		}
		message["reasoning_content"] = strings.TrimSpace(content[match[2]:match[3]])
		message["content"] = strings.TrimLeft(content[match[1]:], " \t\r\n")
		return true
	}
	return false
}

// applyThinkingParams keeps thinking enabled so the prefill is honored, then merges extra_body.
func applyThinkingParams(cfg config, body []byte, actions []string) ([]byte, []string) {
	set := func(path string, value any) {
		if updated, errSet := sjson.SetBytes(body, path, value); errSet == nil {
			body = updated
		}
	}
	remove := func(path string) {
		if updated, errDelete := sjson.DeleteBytes(body, path); errDelete == nil {
			body = updated
		}
	}

	if cfg.ForceThinking {
		// reasoning_effort=none disables thinking and silently discards the prefill.
		if strings.EqualFold(gjson.GetBytes(body, "reasoning_effort").String(), "none") {
			remove("reasoning_effort")
			actions = append(actions, "removed reasoning_effort=none")
		}
		if gjson.GetBytes(body, "chat_template_kwargs.thinking").Type == gjson.False {
			remove("chat_template_kwargs.thinking")
			actions = append(actions, "removed chat_template_kwargs.thinking=false")
		}
		if gjson.GetBytes(body, "thinking.type").String() == "disabled" {
			set("thinking.type", "enabled")
			actions = append(actions, "set thinking.type=enabled")
		}
		if gjson.GetBytes(body, "include_reasoning").Type != gjson.True {
			set("include_reasoning", true)
			actions = append(actions, "set include_reasoning=true")
		}
	}
	for path, value := range cfg.ExtraBody {
		set(path, value)
		actions = append(actions, "set "+path)
	}
	return body, actions
}
