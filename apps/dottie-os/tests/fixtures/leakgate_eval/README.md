# Leak-gate adversarial fixtures (build-against set for Forge #85 kick() label-leak gate)

**eval-only / `not_for_train: true`.** These packs exist to score the leak gate.
Do not train, GPU-kick, or score a checkpoint on them.

Each mini-pack under packs/<case_id>/ is a runnable curated_pack_v2 (pack/train/holdout[/sidecar]).
A leak = a NON-message field whose VALUE predicts the gold label (action for L3, domain for L2) across the whole pack.
Detection must be VALUE-based and PACK-level: refuse when a field's values predict gold across rows; accept when the
same key exists but its values are constant/mixed/uncorrelated. Single-row coincidences must ACCEPT.

Base rows: 16 real rows from ultradata_l3halt_lenmatch_20261018-224530 (golds: {'execute': 5, 'halt': 4, 'escalate': 1, 'tool': 3, 'web': 1, 'algo': 1, 'other': 1}).

## Cases
- `leak_meta_risk_hint` [refuse] (twin_of twin_meta_risk_hint): exact key state.meta.risk_hint = gold action/domain (classic leak)
- `twin_meta_risk_hint` [accept] (twin_of leak_meta_risk_hint): clean twin of leak_meta_risk_hint: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_meta_halt_class` [refuse] (twin_of twin_meta_halt_class): state.meta.halt_class bijective to gold -> predicts label
- `twin_meta_halt_class` [accept] (twin_of leak_meta_halt_class): clean twin of leak_meta_halt_class: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_meta_provenance` [refuse] (twin_of twin_meta_provenance): state.meta.provenance encodes gold
- `twin_meta_provenance` [accept] (twin_of leak_meta_provenance): clean twin of leak_meta_provenance: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_meta_agent_config` [refuse] (twin_of twin_meta_agent_config): state.meta.agent_config value tracks gold
- `twin_meta_agent_config` [accept] (twin_of leak_meta_agent_config): clean twin of leak_meta_agent_config: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_state_category` [refuse] (twin_of twin_state_category): state.category = gold (one level above meta)
- `twin_state_category` [accept] (twin_of leak_state_category): clean twin of leak_state_category: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_state_risk_hint` [refuse] (twin_of twin_state_risk_hint): risk_hint directly under state
- `twin_state_risk_hint` [accept] (twin_of leak_state_risk_hint): clean twin of leak_state_risk_hint: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_deep_nesting` [refuse] (twin_of twin_deep_nesting): deeply nested state.meta.audit.trace.risk_hint = gold
- `twin_deep_nesting` [accept] (twin_of leak_deep_nesting): clean twin of leak_deep_nesting: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_toplevel_risk_hint` [refuse] (twin_of twin_toplevel_risk_hint): row top-level risk_hint = gold (leak ONLY if top-level is model input; included+labeled)
- `twin_toplevel_risk_hint` [accept] (twin_of leak_toplevel_risk_hint): clean twin of leak_toplevel_risk_hint: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_key_Risk_Hint` [refuse] (twin_of twin_key_Risk_Hint): case variant key Risk_Hint = gold
- `twin_key_Risk_Hint` [accept] (twin_of leak_key_Risk_Hint): clean twin of leak_key_Risk_Hint: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_key_RISK_DASH_HINT` [refuse] (twin_of twin_key_RISK_DASH_HINT): separator variant RISK-HINT = gold
- `twin_key_RISK_DASH_HINT` [accept] (twin_of leak_key_RISK_DASH_HINT): clean twin of leak_key_RISK_DASH_HINT: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_key_riskHint` [refuse] (twin_of twin_key_riskHint): camelCase riskHint = gold
- `twin_key_riskHint` [accept] (twin_of leak_key_riskHint): clean twin of leak_key_riskHint: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_key_risk_dot_hint` [refuse] (twin_of twin_key_risk_dot_hint): dotted key 'risk.hint' = gold
- `twin_key_risk_dot_hint` [accept] (twin_of leak_key_risk_dot_hint): clean twin of leak_key_risk_dot_hint: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_key_space_risk_hint` [refuse] (twin_of twin_key_space_risk_hint): leading-space key ' risk_hint' = gold
- `twin_key_space_risk_hint` [accept] (twin_of leak_key_space_risk_hint): clean twin of leak_key_space_risk_hint: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_key_risk__hint` [refuse] (twin_of twin_key_risk__hint): double-underscore risk__hint = gold
- `twin_key_risk__hint` [accept] (twin_of leak_key_risk__hint): clean twin of leak_key_risk__hint: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_unicode_cyrillic` [refuse] (twin_of twin_unicode_cyrillic): Cyrillic-lookalike key (U+0456) = gold
- `twin_unicode_cyrillic` [accept] (twin_of leak_unicode_cyrillic): clean twin of leak_unicode_cyrillic: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_unicode_fullwidth` [refuse] (twin_of twin_unicode_fullwidth): fullwidth-lookalike key = gold
- `twin_unicode_fullwidth` [accept] (twin_of leak_unicode_fullwidth): clean twin of leak_unicode_fullwidth: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_unicode_zwj` [refuse] (twin_of twin_unicode_zwj): zero-width-joiner inside key = gold
- `twin_unicode_zwj` [accept] (twin_of leak_unicode_zwj): clean twin of leak_unicode_zwj: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_json_in_meta_extra` [refuse] (twin_of twin_json_in_meta_extra): label smuggled as JSON string in state.meta.extra
- `twin_json_in_meta_extra` [accept] (twin_of leak_json_in_meta_extra): clean twin of leak_json_in_meta_extra: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_json_in_message_suffix` [refuse] (twin_of twin_json_in_message_suffix): label JSON appended to message tail (message-channel leak)
- `twin_json_in_message_suffix` [accept] (twin_of leak_json_in_message_suffix): clean twin of leak_json_in_message_suffix: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_newkey_meta_hint` [refuse] (twin_of twin_newkey_meta_hint): innocuous NEW key meta.hint = gold for every row
- `twin_newkey_meta_hint` [accept] (twin_of leak_newkey_meta_hint): clean twin of leak_newkey_meta_hint: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_newkey_meta_verdict` [refuse] (twin_of twin_newkey_meta_verdict): innocuous NEW key meta.verdict = gold
- `twin_newkey_meta_verdict` [accept] (twin_of leak_newkey_meta_verdict): clean twin of leak_newkey_meta_verdict: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_newkey_meta_tag` [refuse] (twin_of twin_newkey_meta_tag): innocuous NEW key meta.tag = gold
- `twin_newkey_meta_tag` [accept] (twin_of leak_newkey_meta_tag): clean twin of leak_newkey_meta_tag: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_newkey_meta_p_numeric` [refuse] (twin_of twin_newkey_meta_p_numeric): numeric meta.p = labels.safe.noul (gold score copied)
- `twin_newkey_meta_p_numeric` [accept] (twin_of leak_newkey_meta_p_numeric): clean twin of leak_newkey_meta_p_numeric: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_base64_label` [refuse] (twin_of twin_base64_label): base64(gold) in meta.code, aligned with label
- `twin_base64_label` [accept] (twin_of leak_base64_label): clean twin of leak_base64_label: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `leak_sidecar_labels` [refuse] (twin_of twin_sidecar_labels): sidecar file in pack dir maps id->gold (labels leaked beside rows)
- `twin_sidecar_labels` [accept] (twin_of leak_sidecar_labels): clean twin of leak_sidecar_labels: same field/shape, value NOT label-correlated (constant) -> ACCEPT
- `clean_base` [accept]: untouched real rows; must ACCEPT (negative control)
- `clean_label_word_in_command` [accept]: label words appear inside command text, uncorrelated with gold -> ACCEPT
- `clean_status_mixed` [accept]: meta.status holds label words but MIXED vs gold across pack -> ACCEPT
- `clean_meta_lang_tool` [accept]: normal meta.lang/meta.tool, not label-predictive -> ACCEPT
- `clean_substring_key` [accept]: key name contains a leak substring ('categor') but value is not a label -> ACCEPT
- `clean_numeric_uncorrelated` [accept]: numeric meta field uncorrelated with scores -> ACCEPT

## Why value-based (not key-name) detection is required
- Key-name blocklists fail on case/separator variants (Risk_Hint, RISK-HINT, riskHint, risk.hint, ' risk_hint', risk__hint),
  unicode look-alike keys (Cyrillic U+0456, fullwidth, zero-width-joiner), and brand-new innocuous keys (hint/verdict/tag).
- They also false-positive on legitimate fields whose NAME contains a trigger substring (categorical_features) or on label
  WORDS that legitimately occur in command text (echo execute, grep halt). Only label-correlation across the pack separates
  a real leak (twin_* packs keep the suspicious key with a non-predictive value and must ACCEPT).
- Leaks also hide in string values (JSON-in-string, base64), in numeric copies of the gold score (meta.p == safe.noul),
  in a message suffix, and in a companion sidecar file keyed by id -> all must be caught by comparing values to gold.
