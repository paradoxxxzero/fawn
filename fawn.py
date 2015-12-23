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

from flask import (
    current_app, url_for, request, abort, Response, _request_ctx_stack)

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


class WebSocket(object):
    def open(self, *args, **kwargs):
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

    @classmethod
    def handle_connection(cls, connection_factory, channels):
        # One connection per loop (per process)
        if cls.connection is None:
            try:
                cls.connection = connection_factory()

                # Ensure autocommit
                cls.connection.set_isolation_level(
                    psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                cursor = cls.connection.cursor()

                for channel in channels:
                    cursor.execute('LISTEN %s;' % channel)
            except Exception:
                log.warning('Error getting db connection', exc_info=True)
                return []

    @classmethod
    def get_notifications(cls):
        if cls.connection.notifies:
            cls.pop_and_save_notifications()

        return cls.last_notifications

    @classmethod
    def pop_and_save_notifications(cls):
        cls.last_notifications = []
        while cls.connection.notifies:
            notification = cls.connection.notifies.pop(0)
            cls.last_notifications.append(notification)

    def __init__(self,  ws, channel, fawn):
        self.websocket_fd = uwsgi.connection_fd()
        self.fawn = fawn
        self.ws = ws
        self.handle_connection(fawn.connection_factory, fawn.channels)
        self.db_fd = os.dup(self.connection.fileno())
        self.channel = channel

    def wait(self):
        # Remove context as we are switching between green thread
        # (and therefore websocket request)
        self.ws.request_context.pop()
        uwsgi.wait_fd_read(self.websocket_fd, 3)
        uwsgi.wait_fd_read(self.db_fd, 5)
        uwsgi.suspend()
        # Restoring request context for all other operations
        self.ws.request_context.push()
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
            log.info('Websocket closed')
            self.ws.close(e)
            return False
        if msg:
            self.ws.message(msg)
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

        for notification in self.get_notifications():
            if notification.channel == self.channel:
                self.ws.notify(notification.payload)

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


class VoidResponse(Response):
    """Empty response since it has already been sent during handshake"""

    def __call__(self, environ, start_response):
        """Don't call start_response and send nothing"""
        return iter([])


class Fawn(object):
    def __init__(self, connection_factory):
        self.channels = set()
        self.WebSocket = WebSocket
        self.connection_factory = connection_factory
        self._url_for = url_for

    def override_url_for(self, url_for):
        self._url_for = url_for

    def websocket(self, cls):
        assert issubclass(cls, WebSocket), (
            "Your websocket class should inherit from fawn.WebSocket")

        channel = cls.__name__
        self.channels.add(channel)

        def route_fun(*args, **kwargs):
            ws = cls()
            loop = FawnLoop(ws, channel, self)

            if not request.headers.get('Sec-Websocket-Key'):
                log.error('Not a websocket request')
                abort(500)

            if uwsgi is None:
                log.erorr('The server is not run with uwsgi. '
                          'Websocket will not work.')
                abort(426)

            uwsgi.websocket_handshake(
                request.headers['Sec-Websocket-Key'],
                request.headers.get('Origin', ''))

            ws.request_context = _request_ctx_stack.top
            ws.open(*args, **kwargs)
            loop.loop()

            # Don't respond here (already done during handshake)
            return VoidResponse('')

        route_fun.__name__ = cls.__name__
        route_fun.__qualname__ = cls.__qualname__
        route_fun.__doc__ = cls.__doc__
        route_fun.__module__ = cls.__module__
        route_fun.__wrapped__ = cls
        return route_fun

    def notify(self, endpoint_or_route, payload=''):
        if hasattr(endpoint_or_route, '__name__'):
            endpoint_or_route = endpoint_or_route.__name__
        if payload:
            payload = payload.replace("'", '"')
            payload = ", '%s'" % payload
        else:
            payload = ''

        return 'NOTIFY %s%s;' % (endpoint_or_route, payload)

    def url_for(self, endpoint, **values):
        if current_app.config.get('PREFERRED_URL_SCHEME') == 'https':
            scheme = 'wss'
        else:
            scheme = 'ws'
        values['_external'] = True
        values['_scheme'] = scheme

        return self._url_for(endpoint, **values)
