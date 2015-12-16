# Copyright (c) 2016 Florian Mounier <paradoxxx.zero@gmail.com>

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import uwsgi
import psycopg2
from werkzeug.exceptions import HTTPException
from werkzeug.routing import Map, Rule


class WebSocket(object):
    def open(self):
        pass

    def send(self, message):
        uwsgi.websocket_send(message)

    def message(self, message):
        pass

    def notify(self, payload):
        pass

    def close(self, reason):
        pass


class FawnLoop(object):
    def __init__(self, db, handler, channel):
        self.websocket_fd = uwsgi.connection_fd()
        self.db = db
        self.handler = handler
        curs = self.db.cursor()
        curs.execute("LISTEN %s;COMMIT;" % channel)
        self.db_fd = self.db.fileno()
        self.handler.open()

    def wait(self):
        uwsgi.wait_fd_read(self.websocket_fd, 3)
        uwsgi.wait_fd_read(self.db_fd)
        uwsgi.suspend()
        fd = uwsgi.ready_fd()
        if fd == self.websocket_fd:
            return 'websocket'
        if fd == self.db_fd:
            return 'db'
        # Try ping / ponging the websocket in case of error
        return 'websocket'

    def _loop(self):
        if self.wait() == 'websocket':
            return self.websocket_read()
        return self.db_read()

    def websocket_read(self):
        try:
            msg = uwsgi.websocket_recv_nb()
        except Exception as e:
            self.handler.close(e)
            return False
        if msg:
            self.handler.message(msg)
        return True

    def db_read(self):
        if self.db.poll() != psycopg2.extensions.POLL_OK:
            return True  # Should crash ?

        if not self.db.notifies:
            return True

        self.handler.notify(self.db.notifies.pop())
        return True

    def loop(self):
        while self._loop():
            pass


class FawnMiddleware(object):
    """
    Middleware handling websocket routes
    """

    def __init__(self, wsgi_app, fawn):
        self.wsgi_app = wsgi_app
        self.fawn = fawn

    def __call__(self, environ, start_response):
        urls = self.fawn.url_map.bind_to_environ(environ)
        try:
            endpoint, args = urls.match()
            handler = self.fawn.view_functions[endpoint]()
        except HTTPException:
            handler = None

        if not handler or 'HTTP_SEC_WEBSOCKET_KEY' not in environ:
            return self.wsgi_app(environ, start_response)

        uwsgi.websocket_handshake(
            environ['HTTP_SEC_WEBSOCKET_KEY'],
            environ.get('HTTP_ORIGIN', ''))
        db = self.fawn.connection_factory()
        FawnLoop(db, handler, endpoint).loop()
        return []


class Fawn(object):
    def __init__(self, app, connection_factory):
        app.wsgi_app = FawnMiddleware(app.wsgi_app, self)
        self.app = app
        self.connection_factory = connection_factory
        self.url_map = Map()
        self.routes = {}
        self.view_functions = {}
        self.WebSocket = WebSocket

    def notify(self, endpoint_or_route, payload=''):
        if hasattr(endpoint_or_route, '__name__'):
            endpoint_or_route = endpoint_or_route.__name__
        notify = 'NOTIFY %s' % endpoint_or_route
        if payload:
            payload = payload.replace("'", '"')
            notify += ", '%s'" % payload
        notify += ';COMMIT;'

        cursor = self.connection_factory().cursor()
        cursor.execute(notify)
        cursor.close()

    def route(self, rule, **options):
        def decorator(f):
            endpoint = options.pop('endpoint', None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f
        return decorator

    def add_url_rule(self, rule, endpoint=None, view_func=None, **options):
        assert view_func is not None, 'view_func is mandatory'
        if endpoint is None:
            endpoint = view_func.__name__
        options['endpoint'] = endpoint
        options['methods'] = 'GET',
        provide_automatic_options = False
        rule = Rule(rule, **options)
        rule.provide_automatic_options = provide_automatic_options
        self.url_map.add(rule)
        if view_func is not None:
            old_func = self.view_functions.get(endpoint)
            if old_func is not None and old_func != view_func:
                raise AssertionError(
                    'View function mapping is overwriting an '
                    'existing endpoint function: %s' % endpoint)
            self.view_functions[endpoint] = view_func
