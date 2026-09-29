"""Evaluator-only scoring, deliberately separate from model-facing modules."""
from __future__ import annotations
import math

def _binary(value):
    if type(value) not in (bool, int) or value not in (0, 1):
        raise ValueError('An observed binary outcome is required; missing is not failure')
    return int(value)

def localization(ranking: list[str], gold_files: list[str], *, evidence_record_complete: bool | None = None) -> dict:
    if not isinstance(ranking, list) or not isinstance(gold_files, list) or not gold_files:
        raise ValueError('Ranking and nonempty evaluator-only gold_files are required')
    if any(not isinstance(x, str) or not x for x in ranking + gold_files):
        raise ValueError('File paths must be nonempty strings')
    if len(ranking) != len(set(ranking)):
        raise ValueError('Duplicate ranked candidates')
    if evidence_record_complete is not None and type(evidence_record_complete) is not bool:
        raise ValueError('evidence_record_complete must be bool or null')
    return {'candidate_nonempty': bool(ranking),
            **{f'file_hit_{k}': bool(set(ranking[:k]) & set(gold_files)) for k in (1, 3, 5)},
            'evidence_record_complete': evidence_record_complete}

def repair_outcome(record: dict, endpoint: str) -> int | None:
    if endpoint not in {'bounded_test_success', 'official_resolution'}:
        raise ValueError('Repair endpoints must be selected explicitly')
    if record.get('status') != 'completed':
        return None
    if endpoint not in record or record[endpoint] is None:
        return None
    return _binary(record[endpoint])

def necessity(full: list[dict], removed: list[dict], *, outcome: str, key_fields=('task_id', 'trial_id')) -> dict:
    """Equation 2: mean(Y_full - Y_removed) over complete same-key pairs.

    gain/loss are improvements/regressions from retaining the behavior. Rows
    must be prefiltered to one pair of conditions and one outcome level.
    """
    def index(rows):
        result = {}
        for row in rows:
            key = tuple(row[name] for name in key_fields)
            if key in result:
                raise ValueError(f'Duplicate matched key: {key}')
            result[key] = row
        return result
    a, b = index(full), index(removed)
    completed = []
    for key in sorted(a.keys() & b.keys()):
        left, right = a[key], b[key]
        if left.get('status') != 'completed' or right.get('status') != 'completed':
            continue
        if left.get(outcome) is None or right.get(outcome) is None:
            continue
        completed.append((_binary(left[outcome]), _binary(right[outcome])))
    if not completed:
        raise ValueError('No complete same-task outcome pairs')
    gains = sum(x == 1 and y == 0 for x, y in completed)
    losses = sum(x == 0 and y == 1 for x, y in completed)
    discordant = gains + losses
    p = min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(gains, losses) + 1)) / 2 ** discordant) if discordant else 1.0
    return {'outcome': outcome, 'paired_n': len(completed), 'gains': gains, 'losses': losses,
            'ties': len(completed) - discordant, 'necessity': (gains - losses) / len(completed),
            'exact_mcnemar_p': p, 'unpaired_full': len(a.keys() - b.keys()),
            'unpaired_removed': len(b.keys() - a.keys()),
            'shared_incomplete': len(a.keys() & b.keys()) - len(completed)}

