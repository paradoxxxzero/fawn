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

fawn = Fawn(app, connection_factory)

@app.route('/')
def index():
    import uwsgi
    message = 'This is a notification from worker %d' % uwsgi.worker_id()
    db.session.execute(fawn.notify('ws', message))
    db.session.execute(fawn.notify('ws2', message + ' [2]'))
    db.session.commit()

    return """
    <script>
        var s = new WebSocket("ws://" + location.host + "/ws/");
        s.onopen = e => document.body.innerHTML += 'Socket opened' + '<br>'
        s.onmessage = e => document.body.innerHTML += e.data + '<br>'
        s.onerror = e => document.body.innerHTML += 'Error <br>'
        s.onclose = e => document.body.innerHTML += 'connection closed' + '<br>'
        var s = new WebSocket("ws://" + location.host + "/ws/2");
        s.onopen = e => document.body.innerHTML += 'Socket 2 opened' + '<br>'
        s.onmessage = e => document.body.innerHTML += e.data + ' (2)<br>'
        s.onerror = e => document.body.innerHTML += ' Error (2)<br>'
        s.onclose = e => document.body.innerHTML += 'connection closed' + ' (2)<br>'
    </script>
    Page rendered on worker %d <br>
    """ % uwsgi.worker_id()


@fawn.route('/ws/')
class ws(fawn.WebSocket):
    def open(self):
        pass

    def message(self, message):
        pass

    def notify(self, payload):
        import uwsgi
        self.send('Notification "%s" received in worker %d in ws' % (
            payload, uwsgi.worker_id()))

    def close(self, reason):
        pass

@fawn.route('/ws/2')
class ws2(fawn.WebSocket):
    def open(self):
        pass

    def message(self, message):
        pass

    def notify(self, payload):
        import uwsgi
        self.send('Notification "%s" received in worker %d in ws2' % (
            payload, uwsgi.worker_id()))

    def close(self, reason):
        pass
