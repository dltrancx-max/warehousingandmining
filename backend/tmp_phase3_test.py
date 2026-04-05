from app import app

with app.test_client() as client:
    paths = [
        '/api/phase3/status',
        '/api/phase3/create-dimensions',
        '/api/phase3/compare'
    ]
    for path in paths:
        if path == '/api/phase3/create-dimensions':
            resp = client.post(path)
        else:
            resp = client.get(path)
        print(path, resp.status_code)
        print(resp.get_data(as_text=True)[:800])
