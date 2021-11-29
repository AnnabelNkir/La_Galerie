# -*- coding: utf-8 -*-
from logging import getLogger


_LOG = getLogger(__name__)


class IterableWrapper():
    """ Wrap iterator to catch the StopIteration exception and mark the current
    call as done (makes it possible to calculate the total time of a request).
    """

    def __init__(self, iterable, end_cb):
        """
        :param iterable: The response body that should be wrapped.
        :type iterable: iterable
        :param end_cb: Function to call when the body was processed. The
            function gets called with the requests WSGI environment, the start
            time stamp and the request URL (without any query string).
        :type end_cb: function ({}, int, str)
        """
        self._end_cb = end_cb
        self._iter = iter(iterable)

    def __iter__(self):
        return self

    def __next__(self):
        """ For iterating over the wrapped iterable, adding stuff to be done at
        the end of the iteration.
        """
        if self._iter is None:
            raise StopIteration()
        try:
            return next(self._iter)
        except StopIteration:
            # Build the request URL and call the end call back function.
            if self._end_cb is not None:
                try:
                    self._end_cb()
                except Exception:
                    # Just log and ignore.
                    _LOG.exception("End callback crashed.")
            # Prevent memory leaks, clean out stuff which isn't needed anymore.
            self._end_cb = None
            self._iter = None
            raise  # continue with end of iteration

    def next(self):  # Python 2
        return self.__next__()
