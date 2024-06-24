import logging as log

from ..lib.service import Service
from .. import app

from libflagship.util import enhex

import cli.mqtt


class MqttQueue(Service):

    def worker_start(self):
        self.client = cli.mqtt.mqtt_open(
            app.config["config"],
            app.config["printer_index"],
            app.config["insecure"]
        )

    def worker_run(self, timeout):
        for msg, body in self.client.fetch(timeout=timeout):
            log.info(f"TOPIC [{msg.topic}]")
            log.debug(enhex(msg.payload[:]))

            for obj in body:
                self.notify(obj)

    def worker_stop(self):
        del self.client
