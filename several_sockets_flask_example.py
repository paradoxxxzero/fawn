# Run with uwsgi --ini little_flask_example.ini
import uwsgi
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from fawn import Fawn

db = SQLAlchemy()


def connection_factory():
    connection = db.engine.connect()
    connection.detach()
    return connection.connection.connection

fawn = Fawn(connection_factory)

app = Flask(__name__)
app.debug = True

app.config[
    'SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://user@localhost/db'

db.app = app
db.init_app(app)


@app.route('/')
def index():
    return """
    <script>
        var sockets = [];
        function handle_socket(i) {
            var s = new WebSocket("ws://" + location.host + "/ws/" + i);
            s.onopen = e => document.body.innerHTML += i + ' opened  <br>'
            s.onmessage = e => document.body.innerHTML += e.data + ' (' + i + ') <br>'
            s.onerror = e => document.body.innerHTML += 'Error (' + i + ')<br>'
            s.onclose = e => document.body.innerHTML += 'Socket closed (' + i + ')<br>'
            return s;
        }
        document.addEventListener('DOMContentLoaded', function () {
            for (var i = 0; i < 10; i++) {
                sockets.push(handle_socket(i))
            }
        });
    </script>
    Page rendered on worker %d <br>
    """ % uwsgi.worker_id()


@app.route('/iframes/<int:n>')
def iframes(n):
    return """
        <style>
           body {
                display: flex;
                flex-wrap: wrap;
           }
           iframe {
                flex: 1;
           }
       </style>
    """ + ' '.join(['<iframe src="/" ></iframe>'] * n)


@app.route('/notify')
def notify():
    message = '%%d (w%d)' % uwsgi.worker_id()
    for i in range(10):
        db.session.execute(fawn.notify('s%d' % i, message % i))
    db.session.commit()
    return 'OK'

for i in range(10):

    def notify_(self, payload):
        self.send(
            '"%s" recv (w%d) %s' % (
                payload, uwsgi.worker_id(), request.path))
    dct = {
        'notify': notify_
    }
    ws = type('s%d' % i, (fawn.WebSocket, ), dct)
    app.route('/ws/%d' % i)(fawn.websocket(ws))
