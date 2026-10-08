"""Lossless presentation of already filtered observations; no game access."""
from .policy import canonical

VIEWS = ('compact', 'full')
PROTOCOL = 'columns-v1'


def columns(value):
    if isinstance(value, dict):
        return {key: columns(child) for key, child in value.items()}
    if not isinstance(value, list):
        return value
    items = [columns(child) for child in value]
    if len(items) < 3 or not all(isinstance(item, dict) for item in items):
        return items
    keys = list(items[0])
    # Missing fields remain missing, including the deliberately small back-card
    # whitelist. Never fill a heterogeneous record with null or invented data.
    if not keys or any(set(item) != set(keys) for item in items):
        return items
    table = {'$columns': keys, '$rows': [[item[key] for key in keys] for item in items]}
    return table if len(canonical(table)) < len(canonical(items)) else items


def expand(value):
    """Decode our representation for offline consumers, not untrusted input."""
    if isinstance(value, list):
        return [expand(child) for child in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {'$columns', '$rows'}:
        keys, rows = value['$columns'], value['$rows']
        if (not isinstance(keys, list) or not all(isinstance(key, str) for key in keys)
                or len(set(keys)) != len(keys) or not isinstance(rows, list)
                or any(not isinstance(row, list) or len(row) != len(keys) for row in rows)):
            raise ValueError('invalid_columns')
        return [{key: expand(child) for key, child in zip(keys, row, strict=True)} for row in rows]
    return {key: expand(child) for key, child in value.items()}


def present(result, view='full'):
    if view not in VIEWS:
        raise ValueError('invalid_view')
    if view == 'full':
        return result
    formatted = dict(result)
    changed = False
    for key in ('observation', 'last_observation'):
        if key in result:
            compressed = columns(result[key])
            if compressed != result[key]:
                formatted[key] = compressed
                changed = True
    if changed:
        candidate = {**formatted, 'observation_encoding': PROTOCOL}
        # Include the protocol marker in the size comparison too.
        if len(canonical(candidate)) < len(canonical(result)):
            return candidate
    return result
