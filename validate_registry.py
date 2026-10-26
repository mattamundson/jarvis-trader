import json, os, sys

schema_path = 'docs/research/strategy-registry/schema.json'
entries_dir = 'docs/research/strategy-registry/entries'

with open(schema_path) as f:
    schema = json.load(f)

# Check schema walk_forward shape
wf_schema = schema['properties']['windows']['properties']['walk_forward']
print('Schema walk_forward:', json.dumps(wf_schema, indent=2)[:300])
print()

errors = []
for fname in sorted(os.listdir(entries_dir)):
    if not fname.endswith('.json'):
        continue
    path = os.path.join(entries_dir, fname)
    with open(path) as f:
        entry = json.load(f)
    required = schema['required']
    for field in required:
        if field not in entry:
            errors.append(f'{fname}: missing required field {field}')
    if 'windows' in entry:
        wf = entry['windows'].get('walk_forward')
        if wf is not None:
            if not isinstance(wf, dict):
                errors.append(f'{fname}: walk_forward is not an object: {type(wf)}')
            else:
                for k in ['start', 'end']:
                    if k not in wf:
                        errors.append(f'{fname}: walk_forward missing {k}')
                if 'config' not in wf:
                    errors.append(f'{fname}: walk_forward missing config')
                extra = set(wf.keys()) - {'start', 'end', 'config'}
                if extra:
                    errors.append(f'{fname}: walk_forward has extra fields: {extra}')

if errors:
    print('VALIDATION FAILURES:')
    for e in errors:
        print(' ', e)
    sys.exit(1)
else:
    n = len([f for f in os.listdir(entries_dir) if f.endswith('.json')])
    print(f'All {n} entries pass schema checks.')
    for fname in sorted(os.listdir(entries_dir)):
        if not fname.endswith('.json'):
            continue
        with open(os.path.join(entries_dir, fname)) as f:
            e = json.load(f)
        wf = e['windows'].get('walk_forward')
        if wf:
            cfg = wf.get('config', 'N/A')
            print(f'  {e["strategy_id"]:40} {e["promotion_state"]:20} walk_forward: {wf["start"]} -> {wf["end"]} config={cfg[:60]}')
        else:
            print(f'  {e["strategy_id"]:40} {e["promotion_state"]:20} walk_forward: none')
