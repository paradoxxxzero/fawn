# Run with uwsgi --ini little_flask_example.ini

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import uwsgi

from fawn import Fawn

app = Flask(__name__)
app.debug = True

app.config[
    'SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://user@localhost/db'
db = SQLAlchemy(app)


def connection_factory():
    connection = db.engine.connect()
    connection.detach()
    return connection.connection.connection

fawn = Fawn(app, connection_factory)


@app.route('/')
def index():
    return """
    <script>
        var sockets = [];
        function handle_socket(i) {
            var s = new WebSocket("ws://" + location.host + "/ws/" + i);
            s.onopen = e => document.body.innerHTML += i + ' opened '
            s.onmessage = e => document.body.innerHTML += e.data + ' (' + i + ') '
            s.onerror = e => document.body.innerHTML += 'Error (' + i + ')<br>'
            s.onclose = e => document.body.innerHTML += 'Socket closed (' + i + ')<br>'
            return i;
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
            '"%s" recv (w%d)' % (
                payload, uwsgi.worker_id()))
    dct = {
        'notify': notify_
    }
    ws = type('s%d' % i, (fawn.WebSocket, ), dct)
    fawn.route('/ws/%d' % i)(ws)
