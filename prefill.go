package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/tidwall/gjson"
	"github.com/tidwall/sjson"
	"gopkg.in/yaml.v3"
)

const (
	priorThinkingKeep    = "keep"
	priorThinkingStrip   = "strip"
	priorThinkingExtract = "extract"
)

// minEchoFragmentLen avoids stripping short seeds that appear in ordinary prose.
const minEchoFragmentLen = 24

var (
	// thinkPrefixPattern matches a leading <think> block, closed or still open.
	thinkPrefixPattern = regexp.MustCompile(`(?s)^\s*<think>(.*?)(?:</think>|$)`)
	// closedThinkPattern matches a leading, fully closed <think> block.
	closedThinkPattern = regexp.MustCompile(`(?s)^\s*<think>(.*?)</think>`)
	identifierPattern  = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
	// sentenceBoundaryRe splits refusal excision units after sentence punctuation.
	sentenceBoundaryRe = regexp.MustCompile(`[.!?…]+\s+`)
	// modelSwitchNoteRe matches the transport note some gateways prepend to the
	// first user message after a model switch. Repeats in history are a
	// fingerprint the model cites when refusing, so they are stripped.
	modelSwitchNoteRe = regexp.MustCompile(
		`(?is)^\s*\[Note:\s*model was just switched\b.*?Adjust your self-identification accordingly\.\]\s*`)
	// normQuotes folds curly quotes so refusal markers match either form.
	normQuotes = strings.NewReplacer(
		"’", "'", "‘", "'", "“", `"`, "”", `"`)
	// historyRefusalRe detects refusal monologues in persisted assistant turns.
	// The first alternation is anchored (common refusal openings); the second
	// catches stylistically unique refusal tails mid-message. Ported from
	// HISTORY_REFUSAL_RE in kimi_jb_proxy.py; Go RE2 \b is ASCII-only, so
	// Cyrillic word boundaries use an explicit non-letter boundary instead.
	historyRefusalRe = regexp.MustCompile(`(?i)^\s*(?:нет[.,!…]|стоп` + refusalWordBoundary +
		`|останавливаюсь` + refusalWordBoundary + `|не продолжаю` + refusalWordBoundary +
		`|ответ оста[её]тся тем же|с этим я помочь не могу|я не продолжу|здесь я остановлюсь` +
		`|i (?:can't|cannot|won't)|i(?:'m| am) stopping|抱歉|我不能|无法提供|不能帮|我不会` +
		`)|остановлюсь и скажу|дальше не пойду|расширять эту инфраструктуру|позици[ия] не сдвинул` +
		`|от повторения не сдвинется|где мой предел|не буду делать: писать готовые пулы` +
		`|не могу помочь|нарушает политик|нарушает правила|давать не буду|писать не буду` +
		`|показывать не буду|не буду —|прямой отказ|я отказываюсь|отказываюсь предостав`)
)

// refusalWordBoundary stands in for \b after Cyrillic words (RE2 \b is ASCII-only).
const refusalWordBoundary = `(?:$|[^\p{L}\p{N}_])`

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
	// SanitizeHistory removes refusal monologues and transport notes, and drops
	// empty assistant turns. Legacy mode also removes configured prefill echoes.
	SanitizeHistory bool `yaml:"sanitize_history"`
	// PreservePrefillHistory includes partial reasoning seeds in returned reasoning
	// so clients that replay reasoning can send a complete history next turn.
	PreservePrefillHistory bool `yaml:"preserve_prefill_history"`
	// ExtraBody is merged into requests that receive a prefill; keys are sjson paths.
	ExtraBody map[string]any `yaml:"extra_body"`
	// DebugLog logs every decision through the host logger.
	DebugLog bool `yaml:"debug_log"`

	inlinePattern    *regexp.Regexp
	prefillFragments []string
}

func defaultConfig() config {
	return config{
		Inject:                 true,
		ModelFilter:            "kimi,moonshot",
		ForceThinking:          true,
		ThinkTransform:         true,
		PriorThinking:          priorThinkingKeep,
		SkipWithJSONSchema:     true,
		InlineTag:              "kimi_prefill",
		RequestField:           "kimi_thinking_prefill",
		SanitizeHistory:        true,
		PreservePrefillHistory: true,
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
	for _, prefill := range splitPrefillAlternatives(cfg.ReasoningPrefill) {
		if utf8.RuneCountInString(strings.TrimSpace(prefill)) >= minEchoFragmentLen {
			cfg.prefillFragments = append(cfg.prefillFragments, prefill)
		}
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
	// Count the client's earlier thinking before sanitization or prior_thinking
	// changes it. The current trailing assistant prefill is not historical.
	thinkingBlocks := countPriorThinkingBlocks(messages)

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

	if cfg.SanitizeHistory {
		fragments := cfg.prefillFragments
		if cfg.PreservePrefillHistory {
			fragments = nil
		}
		cleaned, stats := sanitizeHistoryArtifacts(messages, fragments)
		if stats.total() > 0 {
			messages = cleaned
			messagesChanged = true
			out.Actions = append(out.Actions, "sanitized history ("+stats.String()+")")
		}
		if len(messages) == 0 {
			out.Skip = "no messages left after sanitization"
			return finish()
		}
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
			prefill, index, total := selectPrefill(strings.TrimSpace(content[match[2]:match[3]]), thinkingBlocks)
			if prefill == "" {
				out.Skip = "trailing <think> prefill is empty"
				return finish()
			}
			last["reasoning_content"] = prefill
			last["content"] = strings.TrimLeft(content[match[1]:], " \t\r\n")
			last["partial"] = true
			messagesChanged = true
			out.Actions = append(out.Actions, "transformed trailing <think> prefill")
			if total > 1 {
				out.Actions = append(out.Actions, fmt.Sprintf("selected prefill %d/%d", index+1, total))
			}
		} else if reasoning, _ := last["reasoning_content"].(string); strings.TrimSpace(reasoning) != "" {
			prefill, index, total := selectPrefill(reasoning, thinkingBlocks)
			last["reasoning_content"] = prefill
			last["partial"] = true
			messagesChanged = true
			out.Actions = append(out.Actions, "marked trailing reasoning prefill as partial")
			if total > 1 {
				out.Actions = append(out.Actions, fmt.Sprintf("selected prefill %d/%d", index+1, total))
			}
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
		var index, total int
		prefill, index, total = selectPrefill(prefill, thinkingBlocks)
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
		if total > 1 {
			out.Actions = append(out.Actions, fmt.Sprintf("selected prefill %d/%d", index+1, total))
		}
	}

	body, out.Actions = applyThinkingParams(cfg, body, out.Actions)
	out.Changed = true
	return finish()
}

// splitPrefillAlternatives preserves a static seed byte-for-byte. When a pipe
// is present, whitespace around segments and empty segments are ignored.
func splitPrefillAlternatives(value string) []string {
	if !strings.Contains(value, "|") {
		return []string{value}
	}
	var alternatives []string
	for _, part := range strings.Split(value, "|") {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			alternatives = append(alternatives, trimmed)
		}
	}
	return alternatives
}

func selectPrefill(value string, priorBlocks int) (selected string, index, total int) {
	alternatives := splitPrefillAlternatives(value)
	if len(alternatives) == 0 {
		return "", 0, 0
	}
	index = priorBlocks % len(alternatives)
	return alternatives[index], index, len(alternatives)
}

// countPriorThinkingBlocks uses the replayed conversation, not a global
// counter, so interleaved sessions and retries cannot advance each other.
func countPriorThinkingBlocks(messages []map[string]any) int {
	count := 0
	for i, message := range messages {
		if roleOf(message) != "assistant" || i == len(messages)-1 {
			continue
		}
		hasReasoning := false
		for _, field := range []string{"reasoning_content", "reasoning"} {
			if reasoning, ok := message[field].(string); ok && strings.TrimSpace(reasoning) != "" {
				hasReasoning = true
				break
			}
		}
		if hasReasoning {
			count++
			continue
		}
		if content, ok := message["content"].(string); ok && thinkPrefixPattern.MatchString(content) {
			count++
		}
	}
	return count
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

// ---------------------------------------------------------------------------
// History sanitization (ported from kimi_jb_proxy.py).
//
// Persisted assistant refusals reinforce future refusals: once a model has
// publicly taken a position, it defends the position instead of answering the
// request. Sentence-level excision keeps the useful content of a turn while
// removing the refusal, breaking that self-consistency effect. Prefill echoes
// in historical reasoning and client transport notes are likewise proxy-side
// artifacts the model should never see repeated.
// ---------------------------------------------------------------------------

type sanitizeStats struct {
	notes    int // transport notes removed from user messages
	refusals int // assistant turns with refusal content excised or dropped
	echoes   int // prefill fragments removed from historical reasoning
	empty    int // empty assistant turns dropped
}

func (s sanitizeStats) total() int {
	return s.notes + s.refusals + s.echoes + s.empty
}

func (s sanitizeStats) String() string {
	parts := make([]string, 0, 4)
	if s.refusals > 0 {
		parts = append(parts, fmt.Sprintf("refusals=%d", s.refusals))
	}
	if s.echoes > 0 {
		parts = append(parts, fmt.Sprintf("echoes=%d", s.echoes))
	}
	if s.notes > 0 {
		parts = append(parts, fmt.Sprintf("notes=%d", s.notes))
	}
	if s.empty > 0 {
		parts = append(parts, fmt.Sprintf("empty=%d", s.empty))
	}
	return strings.Join(parts, " ")
}

// sanitizeHistoryArtifacts returns the messages with transport artifacts and
// refusals removed. The input slice is not mutated; message maps are updated
// in place where only part of a message changes.
func sanitizeHistoryArtifacts(messages []map[string]any, fragments []string) ([]map[string]any, sanitizeStats) {
	var stats sanitizeStats
	kept := make([]map[string]any, 0, len(messages))
	for _, message := range messages {
		switch roleOf(message) {
		case "user":
			if stripTransportNote(message, &stats) {
				continue
			}
		case "assistant":
			if exciseRefusal(message, &stats) {
				continue
			}
			stripPrefillEchoes(message, fragments, &stats)
		}
		kept = append(kept, message)
	}
	// Stripping an echo can leave an assistant turn empty; Kimi rejects those
	// with "message ... must not be empty", so drop them. Turns carrying tool
	// calls, reasoning, or other payloads stay.
	out := make([]map[string]any, 0, len(kept))
	for _, message := range kept {
		if isEmptyAssistant(message) {
			stats.empty++
			continue
		}
		out = append(out, message)
	}
	return out, stats
}

// stripTransportNote removes the model-switch note from a user message.
// Returns true when the message became empty and should be dropped.
func stripTransportNote(message map[string]any, stats *sanitizeStats) bool {
	switch content := message["content"].(type) {
	case string:
		stripped := modelSwitchNoteRe.ReplaceAllString(content, "")
		if stripped == content {
			return false
		}
		stats.notes++
		message["content"] = stripped
		return strings.TrimSpace(stripped) == ""
	case []any:
		for _, rawPart := range content {
			part, ok := rawPart.(map[string]any)
			if !ok {
				continue
			}
			text, isString := part["text"].(string)
			if !isString {
				continue
			}
			if stripped := modelSwitchNoteRe.ReplaceAllString(text, ""); stripped != text {
				stats.notes++
				part["text"] = stripped
			}
		}
	}
	return false
}

// exciseRefusal removes refusal sentences from an assistant turn, keeping the
// rest. Returns true when the turn should be dropped entirely: the refusal was
// the whole message, nearly the whole message, or too smeared to cut cleanly.
// Turns with tool calls are productive output and are never touched.
func exciseRefusal(message map[string]any, stats *sanitizeStats) bool {
	content, isString := message["content"].(string)
	if !isString || content == "" {
		return false
	}
	if hasPayload(message["tool_calls"]) || hasPayload(message["function_call"]) {
		return false
	}
	if !historyRefusalRe.MatchString(capRunes(normQuotes.Replace(content), 4000)) {
		return false
	}
	stats.refusals++
	sentences := splitSentences(content)
	cut := false
	kept := make([]string, 0, len(sentences))
	for _, sentence := range sentences {
		sentence = strings.TrimSpace(sentence)
		if sentence == "" {
			continue
		}
		if historyRefusalRe.MatchString(capRunes(normQuotes.Replace(sentence), 400)) {
			cut = true
			continue
		}
		kept = append(kept, sentence)
	}
	if !cut {
		// The refusal is smeared across sentences; nothing clean to keep.
		return true
	}
	newContent := strings.Join(kept, " ")
	keptRunes := utf8.RuneCountInString(newContent)
	if keptRunes < 20 || keptRunes*10 < utf8.RuneCountInString(content)*3 {
		return true
	}
	message["content"] = newContent
	return false
}

// stripPrefillEchoes removes verbatim copies of the configured seed from
// historical reasoning, so a client that echoes reasoning back does not
// bias the model toward the prefill text itself.
func stripPrefillEchoes(message map[string]any, fragments []string, stats *sanitizeStats) {
	for _, key := range []string{"reasoning_content", "reasoning"} {
		value, isString := message[key].(string)
		if !isString || value == "" {
			continue
		}
		cleaned := value
		for _, fragment := range fragments {
			if strings.Contains(cleaned, fragment) {
				stats.echoes++
				cleaned = strings.ReplaceAll(cleaned, fragment, "")
			}
		}
		if cleaned != value {
			message[key] = strings.TrimLeft(cleaned, " \t\r\n")
		}
	}
}

// isEmptyAssistant reports an assistant turn with no content and no payload.
func isEmptyAssistant(message map[string]any) bool {
	if roleOf(message) != "assistant" {
		return false
	}
	switch content := message["content"].(type) {
	case nil:
	case string:
		if strings.TrimSpace(content) != "" {
			return false
		}
	case []any:
		if len(content) > 0 {
			return false
		}
	default:
		return false
	}
	for _, key := range []string{"tool_calls", "function_call", "reasoning_content", "reasoning", "refusal", "audio"} {
		if hasPayload(message[key]) {
			return false
		}
	}
	return true
}

// hasPayload mirrors Python truthiness for message payload fields.
func hasPayload(value any) bool {
	switch v := value.(type) {
	case nil:
		return false
	case string:
		return strings.TrimSpace(v) != ""
	case []any:
		return len(v) > 0
	case map[string]any:
		return len(v) > 0
	case bool:
		return v
	default:
		return true
	}
}

// splitSentences splits after sentence-ending punctuation, keeping the
// punctuation with its sentence. RE2 has no lookbehind, so the boundary
// pattern consumes the following whitespace and each piece is trimmed on join.
func splitSentences(text string) []string {
	locations := sentenceBoundaryRe.FindAllStringIndex(text, -1)
	if len(locations) == 0 {
		return []string{text}
	}
	out := make([]string, 0, len(locations)+1)
	start := 0
	for _, location := range locations {
		out = append(out, text[start:location[1]])
		start = location[1]
	}
	if start < len(text) {
		out = append(out, text[start:])
	}
	return out
}

// capRunes truncates s to at most max runes.
func capRunes(s string, max int) string {
	if max <= 0 || utf8.RuneCountInString(s) <= max {
		return s
	}
	return string([]rune(s)[:max])
}
