# -*- coding: utf-8 -*-
from calendar import timegm
from datetime import datetime, timedelta
from logging import getLogger
try:
    from queue import Queue, Full
except ImportError:
    from Queue import Queue, Full  # Python 2
from socket import gethostname
from threading import Thread
from time import time
try:
    from urllib.parse import quote  # @UnusedImport
except ImportError:
    from urllib import quote  # Python 2 @UnresolvedImport @Reimport

from pytz import UTC

from .response_wrapper import IterableWrapper


_LOG = getLogger(__name__)

_CALLS_BUFFER_LIMIT = 1000

_SEND_LIMIT = 5

_MAX_SEND_INTERVALL = timedelta(seconds=5)


def _build_event(host, service, endpoint, env, start, end, status):
    """ Build keyword arguments for the Riemann event call.

    See Riemann documentation for possible arguments.

    This is an example implementation which sends end point and status as tags
    and transmits the metric (the request length) as milliseconds.

    :param host: As passed to the Owl constructor.
    :type host: str
    :param service: As passed to the Owl constructor.
    :type service: str
    :param endpoint: The API end point (method and URL) to which the request
        was made.
    :type endpoint: str
    :param env: The WSGI environment for the request.
    :type env: {}
    :param start: Start time of the request, in epoch seconds.
    :type start: float
    :param end: End time of the request, in epoch seconds.
    :type end: float
    :param status: HTML response status code
    :type status: str
    """
    return {
        "time": timegm(datetime.utcnow().replace(tzinfo=UTC).timetuple()),
        "host": host,
        "service": service,
        "metric_sint64": int(round((end - start) * 1000)),
        "tags": [endpoint, status]
    }


def _reconstruct_endpoint(env):
    """ Using the original WSGI environment of the request reconstruct the end
    point, consisting of the request method and the path, leaving out the host
    and query information.

    Example:
    GET /users

    :type env: {}
    :rtype: str
    """
    return (
        env.get("REQUEST_METHOD", "--") + " " +
        quote(env.get("SCRIPT_NAME", "")) +
        quote(env.get("PATH_INFO", "")))


class Owl(object):
    """ Mixin class for Falcon API, treats each request as an event to send to
    Riemann.
    """

    def __init__(self, *args, **kwds):
        """ Set up the background event message queue for sending request call
        events to Riemann.

        Removes relevant parameters from kwds and passes the rest to the parent
        __init__.

        :param get_riemann_client: The Riemann client builder function. Called
            each time when a batch of events should be send to Riemann.
        :type get_riemann_client:
            function () -> riemann_client.client.QueuedClient
        :param owl_service: The default for the service parameter of an Riemann
            event.
        :type owl_service: str
        :param owl_host: The default for the host parameter of an Riemann
            event. Defaults to the result of socket.gethostname.
        :type owl_host: str
        :param event_builder: Function that build the keyword arguments for a
            Riemann event using the provided request information and
            measurements. See _build_event for an example implementation. That
            function is also the default for this parameter.
        :type event_builder: function (str, str, {}, float, float, str) -> {}
        :param endpoint_builder: Looking at the request WSGI environment this
            function should build a end point identifier, something like the
            request method and the request URL perhaps. Look at
            _reconstruct_endpoint for the default implementation.
        :type endpoint_builder: function({}) -> str
        """
        _LOG.debug("Owl in place.")
        self._get_riemann_client = kwds.pop("get_riemann_client")
        self._events_service = kwds.pop("owl_service")
        self._events_host = kwds.pop("owl_host", gethostname())
        self._event_builder = kwds.pop("event_builder", _build_event)
        self._endpoint_builder = kwds.pop(
            "endpoint_builder", _reconstruct_endpoint)
        self._call_events = Queue(1000)
        super(Owl, self).__init__(*args, **kwds)  # initialize API
        # Create and start background thread that sends events to Riemann.
        event_worker = Thread(target=self._process_call_metrics)
        event_worker.daemon = True
        event_worker.start()

    def _process_call_metrics(self):
        """ Listens for events on the _call_events queue and sends them to
        Riemann.

        Meant to be run in the background in a daemon thread.
        """
        _LOG.debug("Owl airborne.")
        try:
            last_send = (
                datetime.now() - _MAX_SEND_INTERVALL)  # first is immediate
            events = []  # buffer for events that should get send
            while True:  # daemon thread, terminates automatically on exit
                events.append(self._call_events.get())  # wait for new event
                # Don't spam Riemann, send blocks of events or wait for some
                # time.
                if (len(events) >= _SEND_LIMIT or
                        last_send < datetime.now() - _MAX_SEND_INTERVALL):
                    with self._get_riemann_client() as client:
                        # Prepare events for sending.
                        for event in events:
                            try:
                                client.event(**event)
                            except Exception:
                                # Just log, drop event, no connection
                                _LOG.warning(
                                    "Add event failed.", exc_info=True)
                        # Send and clear buffer.
                        try:
                            client.flush()
                            _LOG.debug("Monitor: sent")
                        except Exception:
                            # Just log, ignore, events lost.
                            _LOG.warning("Flush events failed.", exc_info=True)
                        del events[:]
        except Exception:
            _LOG.critical("Owl crashed.")
            raise

    def _monitor_end_call(self, env, start, status):
        """ Called when a request ended.

        Builds an event and places it in the _call_events queue. If the queue
        is full, events get discarded.

        :type env: {}
        :type start: flaot
        :type status: str
        """
        end = time()
        try:
            endpoint = self._endpoint_builder(env)
        except:
            _LOG.warning("End point builder failed.", exc_info=True)
        else:
            try:
                event = self._event_builder(
                    self._events_host, self._events_service, endpoint, env,
                    start, end, status)
            except Exception:
                _LOG.warning("Event builder failed.", exc_info=True)
            else:
                try:
                    self._call_events.put_nowait(event)
                except Full:
                    pass  # silently drop event

    def __call__(self, env, start_response):
        """ Overwrite Falcons WSGI API call function to add a wrapper to the
        result in order to catch the actual request end.

        Captures the start end end time of a request and places a corresponding
        event in the queue to be send to Riemann by the background thread.
        """
        # Wrap the status code in a list, such that the sart_response function
        # replacement can report what the response status is and so that the
        # event builder function can then use this information.
        status_recorder = ["000"]
        start = time()

        # Replacement for the start_response function, captures the status
        # code.
        def _start_response(status, headers, status_recorder=status_recorder):
            start_response(status, headers)
            status_recorder[0] = status

        # Wrapper for the request-did-end function, injecting the WSG
        # environment, the start time and the response status code.
        def call_back(env=env, start=start, status_recorder=status_recorder):
            self._monitor_end_call(env, start, (status_recorder[0] or "")[:3])

        # Wrap the result of the request, so that when all the data was
        # consumed by the WSGI server the request "ends" and the end time gets
        # taken then and not before.
        try:
            response = super(Owl, self).__call__(env, _start_response)
            return IterableWrapper(response, call_back)
        except Exception:
            # Server error, make sure callback is called.
            if not str(status_recorder[0] or "").startswith("5"):
                status_recorder[0] = "500"
            try:
                call_back()
            except Exception:
                # Just log and ignore.
                _LOG.exception("End callback crashed.")
            raise
