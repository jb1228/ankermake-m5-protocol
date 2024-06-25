import click
import logging as log
import ssl
import json
import uuid

import paho.mqtt
import paho.mqtt.client as mqtt_local

import cli.mqtt as mqtt_anker

import cli.util

from libflagship import ROOT_DIR
from libflagship.mqttapi import AnkerMQTTBaseClient

from datetime import datetime, timedelta


class MqttRelay:
    def __init__(self, env, printer_index):
        with env.config.open() as cfg:
            self.config = cfg

        self.local_client = mqtt_local.Client()
        
        log.info("Loading existing MqttRelay values..")
        # exiting_config  = open(env.config.config_path('default'))
        # existing_data = json.load(exiting_config)
        relay_config = self.config.mqttrelay

        self.printer = self.config.printers[printer_index]

        log.info(f"Printer: {self.printer.name} [{self.printer.sn}]")

        log.info(f"Opening connection to [{relay_config.name}]")
        self.local_client.enable_logger()
        self.local_client.username_pw_set(relay_config.username, relay_config.password)
        self.local_client.connect(relay_config.host, port=relay_config.port, keepalive=60)
        self.local_client.loop_start()

        topic = "ankerctl/" + self.printer.sn + "/info"
        payload = {
            "name": self.printer.name
        }
        self.local_client.publish(topic, json.dumps(payload, indent=4))

    def process_incoming_msg(self, msg_data, name):
        try :
            log.info(f"Received incoming message [{name}]:   {msg_data}")
            
            topic = "ankerctl/" + self.printer.sn + "/" + name
            payload = json.dumps(msg_data, indent=4)

            log.info(f"Publishing to topic [{topic}]:   {payload}")
            self.local_client.publish(topic, payload)

        except Exception as err:
            print(f"Unexpected {err=}, {type(err)=}")

        
    def publish_autodiscovery_data(self, xx):
        # ad_template = {
        #     "device_class": temperature
        #     "state_topic": "homeassistant/sensor/xxxxxxxxx/state"
        #     "unit_of_measurement" "°C"
        #     "value_template": "{{ value_json.currentTemp}}"
        #     "unique_id": "xxxxxxxx"
        #     "device": {
        #         "identifiers": [
        #             "xxxxxdevicexxxxx"
        #         ]
        #         "name": "Nozzle Temperature"
        #     }
        # }
