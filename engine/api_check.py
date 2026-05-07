import json

import requests

h = {'X-API-Key': 'xPRdYjkyUP20r29jrhAlgefneE1oYGSvFn3ri5C1OGc'}
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
