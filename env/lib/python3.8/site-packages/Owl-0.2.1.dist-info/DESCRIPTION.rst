Owl
===

.. image:: https://api.travis-ci.org/merry-bits/Owl.svg?branch=master
    :target: https://travis-ci.org/merry-bits/Owl?branch=master

Measure how long your `Falcon <http://falconframework.org/>`_ requests take and
send each measurement as an event to `Riemann <http://riemann.io/>`_.


Example
-------

Owl is designed to be a mix-in class for API. To use Owl you create your own
API class providing configuration parameters for Owl.

In Python 3 this could look something like this:

.. code-block:: python

    from falcon.api import API
    from riemann_client.client import QueuedClient
    from owl import Owl

    class MonitoredAPI(Owl, API):

        def __init__(self, *args, **kwds):
            kwds["get_riemann_client"] = lambda: QueuedClient()
            kwds["owl_service"] = "MyAPI"  # service name for Riemann
            super().__init__(*args, **kwds)

    api = MonitoredAPI()
    # api.add_route(...)
    # ...

In Riemann you get the end point and the request result status code as tags. To
convert them into their own `InfluxDB <https://influxdata.com/>`_ tags (
``endpoint` and ``status-code``) for later use (for example in
`Grafana <http://grafana.org/>`_) you could do something like this in your
Riemann InfluxDB configuration:

.. code-block:: clojure

    (defn- parse-api-event
     [event]
     (if (contains? event :tags)
       (let [[endpoint status-code & other] (:tags event)]
         (assoc event
           :endpoint endpoint
           :status-code status-code))
       event))

    (let [index (index)]
     (streams index
       ; Write API monitoring to database
       (where (service "MyAPI")
         #(info (parse-api-event %))
         (comp api-db parse-api-event))))

Check out the ``event_builder`` parameter if you want to customize the event
parameters (change what service means or add a description for example).


Installation
============

.. code-block:: bash

    $ pip install owl


Changelog
=========

0.2.0
-----

 - generate a message with status 500 when a request throws an exception


