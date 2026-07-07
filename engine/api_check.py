
import os

import requests

# Engine API key comes from the environment (same API_KEY the engine validates).
# Never hardcode the credential in source -- it ends up in git history.
h = {'X-API-Key': os.environ.get('API_KEY', '')}
base = 'http://localhost:8010'

for label, method, url, body in [
    ('MACRO', 'GET', '/macro/snapshot', None),
    ('SESSION', 'GET', '/market/session', None),
    ('SENTIMENT', 'GET', '/sentiment/recent', None),
    ('MCL', 'POST', '/analyze/technical', {'symbol':'MCL','interval':'1h'}),
    ('MNQ', 'POST', '/analyze/technical', {'symbol':'MNQ','interval':'1h'}),
]:
    try:
        if method == 'GET':
            r = requests.get(base+url, headers=h, timeout=20)
        else:
            r = requests.post(base+url, headers=h, json=body, timeout=30)
        print(f'=={label}== status={r.status_code}')
        print(r.text[:2000])
    except Exception as e:
        print(f'=={label}== ERROR: {e}')
    print()
