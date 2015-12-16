from flask import Flask
from fawn import Fawn

from sqlalchemy import create_engine
engine = create_engine('postgresql+psycopg2://user@localhost/db', echo=True)


def connection_factory():
    connection = engine.connect()
    connection.detach()
    return connection.connection.connection  # ...

app = Flask(__name__)
app.debug = True
fawn = Fawn(app, connection_factory)


@app.route('/')
def index():
    fawn.notify(ws, 'From the class')
    fawn.notify('ws', 'From the endpoint')
    return """
    <script>
        var s = new WebSocket("ws://" + location.host + "/ws/");
        s.onopen = e => document.write('opened')
        s.onmessage = e => document.write(e.data)
        s.onerror = e => document.write(e)
        s.onclose = e => document.write('connection closed')
    </script>
    """


@fawn.route('/ws/')
class ws(fawn.WebSocket):
    def open(self):
        print('Opened')

    def message(self, message):
        print('Message ', message)

    def notify(self, payload):
        self.send('Got payload %s' % payload)

    def close(self, reason):
        print('Closed (%r)' % reason)
