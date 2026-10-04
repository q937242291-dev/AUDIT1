"""Pure context and surface-form interventions on boundary-checked snapshots."""
from __future__ import annotations

from copy import deepcopy
import json
import keyword
import re
from .contracts import digest, reject_outcomes, require, runtime_snapshot

TRACKS = ('entity_tree', 'symbol', 'import_call', 'api_implementation',
          'config_registry_dispatch', 'detour', 'graph')
PROGRESSIVE = {
    'C0_issue_only': (),
    'C1_executable_failure': ('executable_failure',),
    'C2_structural_localization': ('executable_failure', 'structural_localization'),
    'C3_requirement_design': ('executable_failure', 'structural_localization', 'requirement_design'),
    'C4_evidence_bundle': ('executable_failure', 'structural_localization', 'requirement_design', 'evidence_bundle'),
}
MATCHED = {
    'c0_issue_only': (), 'c1_entity_tree': TRACKS[:1], 'c2_symbol_evidence': TRACKS[:2],
    'c3_dependency_api': TRACKS[:4], 'c4_structural_bundle': TRACKS,
    'c5_checkpoint_history': TRACKS + ('checkpoint_history',),
    'c6_bounded_full_context': TRACKS + ('checkpoint_history', 'bounded_extra'),
}
PROJECTIONS = ('O_original_future_info', 'C_future_scrubbed', 'P_equal_length_legal_history',
               'L_location_only', 'D_diff_only')


def project_context(snapshot: dict, condition: str, sources: dict, *, max_chars: int,
                    legal_history_chars: int | None = None) -> tuple[dict, dict]:
    original = runtime_snapshot(snapshot)
    reject_outcomes(sources, 'context_sources')
    require(type(max_chars) is int and max_chars > 0, 'A positive context construction bound is required')
    projected = deepcopy(original)
    if condition in PROGRESSIVE:
        selected = PROGRESSIVE[condition]
    elif condition in MATCHED:
        selected = MATCHED[condition]
    elif condition in PROJECTIONS:
        selected = ('legal_history',) if condition == 'P_equal_length_legal_history' else ()
        if condition in {'L_location_only', 'D_diff_only'}:
            projected['issue'] = ''
    else:
        raise ValueError(f'Unknown context projection: {condition}')
    for name in selected:
        require(name in sources, f'Registered context source missing: {name}')
        require(isinstance(sources[name], dict) and set(sources[name]) <= {'content', 'evidence_ids'},
                f'Invalid context source: {name}')
        require(isinstance(sources[name].get('content'), str), f'Context source needs text: {name}')
        require(isinstance(sources[name].get('evidence_ids', []), list), 'evidence_ids must be an array')
    chunks, evidence_ids, remaining = [], set(), max_chars
    for name in selected:
        content = sources[name]['content']
        if name == 'legal_history':
            require(type(legal_history_chars) is int and 0 <= legal_history_chars <= max_chars,
                    'Equal-length projection requires an explicit legal-history character budget')
            require(len(content) >= legal_history_chars, 'Insufficient legal history; do not pad evidence')
            content = content[:legal_history_chars]
        kept = content[:remaining]
        remaining -= len(kept)
        chunks.append({'source': name, 'content': kept})
        if kept:
            evidence_ids.update(sources[name].get('evidence_ids', []))
    # Provider-facing prompts cannot inherit candidates or a repository tree from excluded arms.
    projected['context'] = json.dumps(chunks, ensure_ascii=False, separators=(',', ':')) if chunks else ''
    projected['candidates'] = []
    projected['repository_files'] = None
    projected['evidence'] = [e for e in original.get('evidence', []) if e['id'] in evidence_ids]
    projected['history'] = deepcopy(original.get('history', [])) if 'checkpoint_history' in selected else []
    runtime_snapshot(projected)
    visibility = {'condition_id': condition, 'issue_visible': bool(projected.get('issue')),
                  'future_payload_visible': False, 'location_payload_visible': False,
                  'diff_payload_visible': False, 'selected_sources': list(selected),
                  'content_chars': sum(len(c['content']) for c in chunks),
                  'max_context_chars': max_chars, 'snapshot_sha256': digest(projected)}
    return projected, visibility


def identifier_mapping(identifiers: list[str], *, salt: str = 'identifier-map-v1') -> dict[str, str]:
    require(isinstance(identifiers, list) and all(isinstance(x, str) and x.isidentifier()
            and not keyword.iskeyword(x) for x in identifiers), 'Vocabulary must contain legal non-keyword identifiers')
    mapping = {token: 'id_' + digest([salt, token])[:20] for token in sorted(set(identifiers))}
    require(len(set(mapping.values())) == len(mapping), 'Identifier mapping collision')
    require(not set(mapping.values()) & set(mapping), 'Identifier target collides with an original token')
    return mapping


def map_identifiers(value, mapping: dict[str, str]):
    """Substitute whole identifier tokens consistently in strings and mapping keys."""
    if isinstance(value, str):
        if not mapping:
            return value
        pattern = r'(?<!\w)(?:' + '|'.join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)) + r')(?!\w)'
        return re.sub(pattern, lambda m: mapping[m.group(0)], value)
    if isinstance(value, list):
        return [map_identifiers(v, mapping) for v in value]
    if isinstance(value, dict):
        keys = [map_identifiers(k, mapping) for k in value]
        require(len(set(keys)) == len(keys), 'Identifier mapping collapsed object keys')
        return {key: map_identifiers(v, mapping) for key, v in zip(keys, value.values())}
    return deepcopy(value)


def mutate_snapshot(snapshot: dict, mapping: dict[str, str]) -> dict:
    original = runtime_snapshot(snapshot)
    # Preserve the schema, task/trial join keys, categorical enums and model identity.
    result = deepcopy(original)
    for key in ('issue', 'context', 'repository_files'):
        if key in result:
            result[key] = map_identifiers(result[key], mapping)
    fields = {
        'candidates': ('path', 'rationale'),
        'evidence': ('path', 'content', 'owner', 'claim'),
        'history': ('context', 'object', 'candidate'),
    }
    for section, text_fields in fields.items():
        for record in result.get(section, []):
            for field in text_fields:
                if field in record:
                    record[field] = map_identifiers(record[field], mapping)
            if section == 'history' and record.get('verifier'):
                record['verifier']['detail'] = map_identifiers(record['verifier'].get('detail', ''), mapping)
    return runtime_snapshot(result)
