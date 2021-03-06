# Run with uwsgi --ini little_flask_example.ini

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from fawn import Fawn

app = Flask(__name__)
app.debug = True
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://user@localhost/db'
db = SQLAlchemy(app)


def connection_factory():
    connection = db.engine.connect()
    connection.detach()
    return connection.connection.connection

fawn = Fawn(connection_factory)


@app.route('/')
def index():
    import uwsgi
    message = 'This is a notification from worker %d' % uwsgi.worker_id()
    db.session.execute(fawn.notify('ws', message))
    db.session.commit()

    return """
    <script>
        var s = new WebSocket("ws://" + location.host + "/ws/" + (Math.random() * 1000 << 1));
        s.onopen = e => document.body.innerHTML += 'Socket opened' + '<br>'
        s.onmessage = e => document.body.innerHTML += e.data + '<br>'
        s.onerror = e => document.body.innerHTML += 'Error <br>'
        s.onclose = e => document.body.innerHTML += 'connection closed' + '<br>'
    </script>
    Page rendered on worker %d <br>
    """ % uwsgi.worker_id()


@app.route('/ws/<int:rand>')
@fawn.websocket
class ws(fawn.WebSocket):
    def open(self, rand):
        self.rand = rand

    def message(self, message):
        pass

    def notify(self, payload):
        import uwsgi
        self.send('Notification "%s" received in worker %d in ws %s' % (
            payload, uwsgi.worker_id(), self.rand))

    def close(self, reason):
        pass
