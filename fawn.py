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

import os
import logging
import psycopg2

from contextlib import contextmanager
from flask import url_for
from flask.globals import _request_ctx_stack, _app_ctx_stack
from werkzeug.exceptions import HTTPException
from werkzeug.routing import Map, Rule

log = logging.getLogger('fawn')

try:
    import uwsgi
except ImportError:
    log.warning("Can't import uwsgi. Fawn will not work")
    uwsgi = None

if 'FAWN_DEBUG' in os.environ:
    try:
        from log_colorizer import basicConfig
    except ImportError:
        from logging import basicConfig
    log.setLevel(int(os.getenv('FAWN_DEBUG')))
    basicConfig()
else:
    log.setLevel(logging.WARNING)


@contextmanager
def swap(base, property, new_property):
    old_property = getattr(base, property)
    setattr(base, property, new_property)
    try:
        yield
    finally:
        setattr(base, property, old_property)


class WebSocket(object):
    def __init__(self, app, environ):
        self.app = app
        self.environ = environ

    @property
    def _request_context(self):
        return self.app.request_context(self.environ)

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
    connection = None
    last_notifications = []

    def __init__(self,  handler, channel):
        self.websocket_fd = uwsgi.connection_fd()
        self.handler = handler
        self.db_fd = os.dup(self.connection.fileno())
        self.channel = channel
        with self.handler._request_context:
            self.handler.open()

    def wait(self):
        uwsgi.wait_fd_read(self.websocket_fd, 3)
        uwsgi.wait_fd_read(self.db_fd, 5)
        uwsgi.suspend()
        fd = uwsgi.ready_fd()
        if fd == self.websocket_fd:
            return 'websocket'
        if fd == self.db_fd:
            return 'db'
        # Try ping / ponging the websocket in case of error
        return 'timeout'

    def _loop(self):
        wait = self.wait()
        if wait == 'websocket' or wait == 'timeout':
            return self.websocket_read()
        if wait == 'db' or wait == 'timeout':
            return self.db_read()

    def websocket_read(self):
        try:
            msg = uwsgi.websocket_recv_nb()
        except Exception as e:
            log.warning('Error in websocket recv', exc_info=True)
            with self.handler._request_context:
                self.handler.close(e)
            return False
        if msg:
            with self.handler._request_context:
                self.handler.message(msg)
        return True

    def db_read(self):
        if self.connection is None:
            # Db connection was broken
            return False

        try:
            poll = self.connection.poll()
        except Exception:
            log.warning('Error in db poll', exc_info=True)
            FawnLoop.connection = None
            return False

        if poll == psycopg2.extensions.POLL_ERROR:
            return False

        if poll != psycopg2.extensions.POLL_OK:
            return True

        if not self.connection.notifies:
            for notification in FawnLoop.last_notifications:
                if notification.channel == self.channel:
                    with self.handler._request_context:
                        self.handler.notify(notification.payload)
            return True

        FawnLoop.last_notifications = []
        while self.connection.notifies:
            notification = self.connection.notifies.pop(0)
            FawnLoop.last_notifications.append(notification)
            if notification.channel == self.channel:
                with self.handler._request_context:
                    self.handler.notify(notification.payload)
        return True

    def loop(self):
        try:
            while self._loop():
                pass
        finally:
            try:
                os.close(self.db_fd)
            except Exception:
                pass
            try:
                os.close(self.websocket_fd)
            except Exception:
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
            handler = self.fawn.view_functions[endpoint](self.fawn.app, environ)
        except HTTPException:
            handler = None

        if not handler or 'HTTP_SEC_WEBSOCKET_KEY' not in environ:
            return self.wsgi_app(environ, start_response)

        if uwsgi is None:
            criticality = log.info if self.fawn.app.debug else log.error
            criticality('The server is not run with uwsgi. '
                        'Websocket will not work.')

            return self.wsgi_app(environ, start_response)

        uwsgi.websocket_handshake(
            environ['HTTP_SEC_WEBSOCKET_KEY'],
            environ.get('HTTP_ORIGIN', ''))

        # One connection per loop (per process)
        if FawnLoop.connection is None:
            try:
                self.get_db_connection()
            except Exception:
                log.warning('Error getting db connection', exc_info=True)
                return []

        FawnLoop(handler, endpoint).loop()
        return []

    def get_db_connection(self):
        FawnLoop.connection = self.fawn.connection_factory()

        # Ensure autocommit
        FawnLoop.connection.set_isolation_level(
            psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = FawnLoop.connection.cursor()

        for channel in self.fawn.view_functions.keys():
            cursor.execute('LISTEN %s;' % channel)


class Fawn(object):
    def __init__(self, connection_factory, app=None, custom_url_for=None):
        self.url_map = Map()
        self.routes = {}
        self.view_functions = {}
        self.WebSocket = WebSocket
        self.connection_factory = connection_factory
        if app is not None:
            self.init_app(app)
        if custom_url_for is not None:
            self.flask_url_for = custom_url_for
        else:
            self.flask_url_for = url_for

    def init_app(self, app):
        app.wsgi_app = FawnMiddleware(app.wsgi_app, self)
        self.app = app

    def notify(self, endpoint_or_route, payload=''):
        if hasattr(endpoint_or_route, '__name__'):
            endpoint_or_route = endpoint_or_route.__name__
        if payload:
            payload = payload.replace("'", '"')
            payload = ", '%s'" % payload
        else:
            payload = ''

        return 'NOTIFY %s%s;' % (endpoint_or_route, payload)

    def url_for(self, ep, **values):
        if self.app.config.get('PREFERRED_URL_SCHEME') == 'https':
            scheme = 'wss'
        else:
            scheme = 'ws'
        values['_external'] = True
        values['_scheme'] = scheme

        appctx = _app_ctx_stack.top
        reqctx = _request_ctx_stack.top

        if reqctx is not None:
            url_adapter = self.url_map.bind_to_environ(
                reqctx.request.environ,
                server_name=self.app.config['SERVER_NAME'])

            with swap(reqctx, 'url_adapter', url_adapter):
                return self.flask_url_for(ep, **values)

        url_adapter = self.url_map.bind(
            self.app.config['SERVER_NAME'],
            script_name=self.app.config['APPLICATION_ROOT'] or '/',
            url_scheme=self.app.config['PREFERRED_URL_SCHEME'])

        with swap(appctx, 'url_adapter', url_adapter):
            return self.flask_url_for(ep, **values)

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
