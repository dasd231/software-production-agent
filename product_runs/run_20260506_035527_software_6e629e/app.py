from flask import Flask
app = Flask(__name__)
@app.get('/hello')
def hello():
    return 'ok'
if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':
        c = app.test_client()
        r = c.get('/hello')
        print(r.status_code, r.get_data(as_text=True))
        sys.exit(0 if r.status_code == 200 else 1)
    app.run(host='127.0.0.1', port=5055, debug=False)
