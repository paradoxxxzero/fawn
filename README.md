FAWN
====

FAWN aka Flask Async uWSGI WebSocket postgresql Notify is a Flask Extension allowing websocket uwsgi broadcasting from postgresql notify channels.


Requirements
------------

 - A postgresql database and the psycopg2 driver.
 - A uwsgi server with async support (uwsgi --async 1000)


Usage
-----

```python

    from flask import Flask
    from fawn import Fawn

    # If your are using SQLAlchemy:
    from sqlalchemy import create_engine
    engine = create_engine('postgresql+psycopg2://user@localhost/db', echo=True)

    def connection_factory():
        connection = engine.connect()  # or db.engine.connect()
        connection.detach()
        return connection.connection.connection

    # If your are using directly psycopg2
    # def connection_factory():
    #     return psycopg2.connect('dbname=db user=user')

    app = Flask(__name__)
    fawn = Fawn(app, connection_factory)

    # You can now declare a websocket route:
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

    # And declare a very simple route
    @app.route('/')
    def index():
        # All connected websockets to the ws endpoint can be notified with:
        fawn.notify(ws, 'From the class')
        fawn.notify('ws', 'From the endpoint')

        # A little js to show it on the page
        return """
        <script>
            var s = new WebSocket("ws://" + location.host + "/ws/");
            s.onopen = e => document.write('opened')
            s.onmessage = e => document.write(e.data)
            s.onerror = e => document.write(e)
            s.onclose = e => document.write('connection closed')
        </script>
        """
```

This example can be run with:

```sh
  uwsgi --master --http localhost:1231 --http-websockets --callable=app --wsgi-file little_flask_example.py --async 100 --ugreen --process 5
```

Author
------

Florian Mounier
Kozea


License
-------

```
The MIT License (MIT)
Copyright (c) 2016 Florian Mounier <paradoxxx.zero@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```