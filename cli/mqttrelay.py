import click
import logging as log
import ssl
import json
import base64
import enum
import requests

# import paho.mqtt
import paho.mqtt.client
from paho.mqtt.properties import Properties as MqttProperties
from paho.mqtt.packettypes import PacketTypes as MqttPacketTypes 

import cli.util

from libflagship import ROOT_DIR
from libflagship.mqttapi import AnkerMQTTBaseClient

from datetime import datetime, timedelta


class MqttPrinterStatus(enum.IntEnum):
    Idle               = 0
    Printing           = 1
    Complete           = 4
    AutoLeveling       = 5 # ?
    Preheating         = 8 # ?
    ManualPreheat      = 9 # ?

class MqttRelay:

    def __init__(self, env, anker_client, printer_index):

        log.debug("Loading MqttRelay config...")
        with env.config.open() as cfg:
            self.config = cfg
        self.printer = self.config.printers[printer_index]

        self.last_heartbeat = None
        self.heartbeat_fequency = 30 # seconds
        self.heartbeat_expiration = 45 # seconds

        self.mqtt_msg_count = 0
        self.last_msg_received = None
        self.max_time_since_last_msg = 30 # seconds

        self.last_image_url = ""
        
        self.use_ha_availability = True

        self.anker_client = anker_client
        self.client = self.create_client()

    def create_client(self):
        log.debug("Creating local MQTT client...")
        client = paho.mqtt.client.Client()
        # client.on_log = self.on_log
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        return client

    def connect(self):
        try:
            log.info(f"Opening connection to [{self.config.mqttrelay.name}]")
            self.client.enable_logger()
            self.client.username_pw_set(self.config.mqttrelay.username, self.config.mqttrelay.password)
            self.client.connect(self.config.mqttrelay.host, port=self.config.mqttrelay.port, keepalive=60)
            self.client.loop_start()
        except Exception as err:
            print(f"Unexpected {err=}, {type(err)=}")

    # def on_log(self, client, userdata, level, buf):
    #     log.debug(f"MQTT relay client: {buf}")

    def on_connect(self, client, userdata, flags, reason_code):
        # try:
            print(f"MQTT relay connected with result code {reason_code}")

            client.reconnect_delay_set(min_delay=1, max_delay=600)

            if self.config.mqttrelay.use_ha:
                self.publish_ha_discovery_topics()

            # Publish printer information
            topic = "ankerctl/" + self.printer.sn + "/info"
            payload = {
                "name": self.printer.name,
                "model": self.printer.model,
                "sn": self.printer.sn,
                "duid": self.printer.p2p_duid,
                "wifi_mac": self.printer.wifi_mac,
                "ip_addr": self.printer.ip_addr
            }
            self.publish([{"topic":topic, "payload":payload, "expiry_interval": 300}])

        # except Exception as err:
        #     print(f"Unexpected {err=}, {type(err)=}")

    def on_disconnect(self, client, userdata, reason_code, properties):
        try:
            print(f"MQTT relay disconnected with result code {reason_code}")
        except Exception as err:
            print(f"Unexpected {err=}, {type(err)=}")

    def on_message(self, client, userdata, msg):
        try:
            print(f"MQTT relay received message: {msg}")
        except Exception as err:
            print(f"Unexpected {err=}, {type(err)=}")

    def heaertbeat_expired(self):
        return (self.last_heartbeat is None) or (self.last_heartbeat + timedelta(seconds=self.heartbeat_fequency) <= datetime.now())

    def heartbeat(self, force_send=False):
        msg = {
            "topic": "ankerctl/" + self.printer.sn + "/availability",
            "payload": {
                "ankerctl": 'online',
                "mqtt": 'online' if self.anker_client._connected else 'offline',
                "printer": 'online' if (self.last_msg_received is not None) and (self.last_msg_received + timedelta(seconds=self.max_time_since_last_msg) > datetime.now()) else 'offline'
            },
            "expiry_interval": self.heartbeat_expiration
        }
        if force_send: 
            self.last_heartbeat = datetime.now()
            self.publish([msg])
        else:
            return msg

    def process_incoming_msg(self, msg_data, name=None):
        try :
            self.last_msg_received = datetime.now()            
            if self.mqtt_msg_count == 0:
                self.heartbeat(True)
            self.mqtt_msg_count += 1

            # Naming overrides
            if msg_data['commandType'] == 1085:
                name = 'error_notify'
            if name == None:
                name = f"undefined_msg_type_{msg_data['commandType']}"

            # Value overrides
            if (name == "event_notify") and (msg_data['subType'] == 1):
                if msg_data['value'] in [item.value for item in MqttPrinterStatus]:
                    msg_data['printer_status'] = MqttPrinterStatus(msg_data['value']).name
                else:
                    msg_data['printer_status'] = msg_data['value']

            log.debug(f"Received incoming message [{name}]:   {msg_data}")

            topic = "ankerctl/" + self.printer.sn + "/" + name
            payload = msg_data
            self.publish([{"topic": topic, "payload": payload}])

            # Preview Image
            if (msg_data['commandType'] == 1001) and ('img' in msg_data) and (msg_data['img'].strip() != ""):
                image_url = msg_data['img']
                if self.last_image_url != image_url:
                    self.publishPreviewImageData(image_url)
                    self.last_image_url = image_url

        except Exception as err:
            print(f"Unexpected {err=}, {type(err)=}")

    def publish(self, msg_list: list):
        try:
            default_qos = 0
            properties = MqttProperties(MqttPacketTypes.PUBLISH)

            if self.heaertbeat_expired():
                msg_list.append(self.heartbeat())
                self.last_heartbeat = datetime.now()

            for m in msg_list:
                if "retain" not in m:
                    m["retain"] = False
                if ("expiry_interval" in m) and m["expiry_interval"] > 0:
                    m["retain"]=True
                    properties.MessageExpiryInterval = m["expiry_interval"]
                else:
                    m["expiry_interval"] = 0
                if "qos" not in m:
                    m["qos"] = default_qos
                if isinstance(m["payload"], dict):
                    m["payload"] = json.dumps(m["payload"])

                log.info(f"Publishing to topic [{m["topic"]}] (Retain: {m["retain"]}{' - Expires: ' + str(m["expiry_interval"]) + 's' if m["expiry_interval"] > 0 else ''}):   {m["payload"]}")

                self.client.publish(m["topic"], m["payload"], m["qos"], m["qos"], properties)

            # self.client.publish.multiple(msg_list)
        except Exception as err:
            print(f"Unexpected {err=}, {type(err)=}")
        

    def publishPreviewImageData(self, image_url):
        print(f"Downloading image [{image_url}]")
        img_data = base64.b64encode(requests.get(image_url, timeout=30).content).decode('utf-8')
        topic = "ankerctl/" + self.printer.sn + "/preview_image"
        self.publish([{"topic": topic, "payload": img_data}])




    def publish_ha_discovery_topics(self):
        # https://www.home-assistant.io/integrations/sensor.mqtt/
        # https://www.home-assistant.io/integrations/homeassistant/#device-class
        # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
        # try:

            entities = [
                {
                    "name": "Status",
                    "domain": "sensor",
                    "icon": "mdi:printer-3d",
                    "state_topic": "event_notify",
                    "value_template": "value_json.printer_status"
                    # "json_attributes_topic": "printer_status",
                    # "json_attributes_template", ""
                },
                {
                    "name": "Printer Connection",
                    "domain": "binary_sensor",
                    "device_class": "connectivity",
                    "entity_category": "diagnostic",
                    "state_topic": "availability",
                    "value_template": "value_json.printer",
                    "payload_on": "online",
                    "payload_off": "offline"
                },
                {
                    "name": "MQTT Connection",
                    "domain": "binary_sensor",
                    "device_class": "connectivity",
                    "entity_category": "diagnostic",
                    "state_topic": "availability",
                    "value_template": "value_json.mqtt",
                    "payload_on": "online",
                    "payload_off": "offline"
                },
                {
                    "name": "Last Error",
                    "domain": "sensor",
                    "icon": "mdi:alert-octagram",
                    "entity_category": "diagnostic",
                    "state_topic": "event_error",
                    "value_template": "'[' + value_json.errorLevel + '] ' + value_json.errorCode + ' (' + value_json.ext + ')'"
                },
                {
                    "name": "IP Address",
                    "domain": "sensor",
                    "icon": "mdi:ip-outline",
                    "entity_category": "diagnostic",
                    "state_topic": "info",
                    "value_template": "value_json.ip_addr"
                },

                {
                    "name": "DUID",
                    "domain": "sensor",
                    "icon": "mdi:identifier",
                    "entity_category": "diagnostic",
                    "state_topic": "info",
                    "value_template": "value_json.duid"
                },

                {
                    "name": "Task ID",
                    "domain": "sensor",
                    "icon": "mdi:information-slab-box-outline",
                    "state_topic": "print_schedule",
                    "value_template": "value_json.task_id"
                },

                {
                    "name": "Model Name",
                    "domain": "sensor",
                    "icon": "mdi:file-code-outline",
                    "state_topic": "print_schedule",
                    "value_template": "value_json.name"
                },

               {
                    "name": "Preview Image",
                    "domain": "image",
                    "icon": "mdi:image-outline",
                    "content_type": "image/png",
                    "image_encoding": "b64",
                    "image_topic": "preview_image"
                },

                {
                    "name": "Print Progress",
                    "domain": "sensor",
                    "unit_of_measurement": "%",
                    "icon": "mdi:timelapse",
                    "state_topic": "print_schedule",
                    "value_template": "value_json.progress / 100"
                },

                {
                    "name": "Time Elapsed",
                    "domain": "sensor",
                    "device_class": "duration",
                    "unit_of_measurement": "s",
                    "icon": "mdi:clock-start",
                    "state_topic": "print_schedule",
                    "value_template": "value_json.totalTime"
                },
                {
                    "name": "Time Remaining",
                    "domain": "sensor",
                    "device_class": "duration",
                    "unit_of_measurement": "s",
                    "icon": "mdi:clock-end",
                    "state_topic": "print_schedule",
                    "value_template": "value_json.time"
                },

                {
                    "name": "Print Speed",
                    "domain": "sensor",
                    "device_class": "speed",
                    "unit_of_measurement": "mm/s",
                    "icon": "mdi:speedometer",
                    "state_topic": "print_schedule",
                    "value_template": "value_json.realSpeed"
                },

                {
                    "name": "Print Speed Setting",
                    "domain": "sensor",
                    "device_class": "speed",
                    "unit_of_measurement": "mm/s",
                    "icon": "mdi:speedometer",
                    "state_topic": "print_speed",
                    "value_template": "value_json.value"
                },

                {
                    "name": "Model Filament Length",
                    "domain": "sensor",
                    "device_class": "distance",
                    "unit_of_measurement": "m",
                    "icon": "mdi:ruler",
                    "state_topic": "print_schedule",
                    "value_template": "value_json.filamentUsed / 1000"
                },

                {
                    "name": "Fan Speed",
                    "domain": "sensor",
                    "unit_of_measurement": "%",
                    "icon": "mdi:fan",
                    "state_topic": "fan_speed",
                    "value_template": "value_json.value"
                },

                {
                    "name": "Model Layer",
                    "domain": "sensor",
                    "icon": "mdi:layers-outline",
                    "state_topic": "model_layer",
                    "value_template": "value_json.real_print_layer"
                },

                {
                    "name": "Model Layers Total",
                    "domain": "sensor",
                    "icon": "mdi:layers-triple",
                    "state_topic": "model_layer",
                    "value_template": "value_json.total_layer"
                },

                {
                    "name": "Nozzle Temperature",
                    "domain": "sensor",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                    "icon": "mdi:printer-3d-nozzle-heat",
                    "state_topic": "nozzle_temp",
                    "value_template": "value_json.currentTemp / 100"
                },
                {
                    "name": "Bed Temperature",
                    "domain": "sensor",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                    "icon": "mdi:heat-wave",
                    "state_topic": "hotbed_temp",
                    "value_template": "value_json.currentTemp / 100"
                },

                {
                    "name": "Nozzle Temperature Target",
                    "domain": "sensor",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                    "icon": "mdi:thermometer-high",
                    "state_topic": "nozzle_temp",
                    "value_template": "value_json.targetTemp / 100"
                },
                {
                    "name": "Bed Temperature Target",
                    "domain": "sensor",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                    "icon": "mdi:thermometer-high",
                    "state_topic": "hotbed_temp",
                    "value_template": "value_json.targetTemp / 100"
                },

                {
                    "name": "Motor Lock",
                    "domain": "sensor",
                    "device_class": "enum",
                    "icon": "mdi:axis-arrow-lock",
                    "state_topic": "motor_lock",
                    "value_template": "iif(value_json.value == 1, 'Locked', 'Unlocked')"
                },
            ]

            msg_list =[]
            for e in entities:
                topic_name = e['name'].lower().strip().replace(" ","_")
                msg = {
                    "topic": f"homeassistant/{e['domain']}/ankerctl_{self.printer.sn}/{topic_name}/config",
                    "payload": self.generate_ha_autodiscovery_payload(e),
                    "expiry_interval": 300
                }
                msg_list.append(msg)
            self.publish(msg_list)
            
        # except Exception as err:
        #     print(f"Unexpected {err=}, {type(err)=}")

    def generate_ha_autodiscovery_payload(self, entity):
            unique_id = f"ankerctl_{self.printer.sn}_{entity['name'].lower().strip().replace(" ","_")}"
            
            payload = {
                "device": {
                    "identifiers": [
                        "ankerctl_" + self.printer.sn
                    ],
                    "manufacturer": "Ankermake",
                    "model": self.printer.model,
                    "name": self.printer.name,
                    "serial_number": self.printer.sn,
                    # "hw_version": "0.0",
                    # "sw_version": "0.0",
                    "configuration_url": "https://www.ankermake.com",
                    "connections": [
                        ["mac", ':'.join(self.printer.wifi_mac[i:i+2] for i in range(0,12,2))],
                        ["ip", self.printer.ip_addr]
                    ]
                },
                "object_id": unique_id,
                "origin": {
                    "name": "Ankerctl MQTT Relay"
                },
                "unique_id": unique_id
            }

            if self.use_ha_availability:
                availability_data = {
                    "availability": [
                        {
                            "topic": "ankerctl/" + self.printer.sn + "/availability",
                            "value_template": "{{ value_json.ankerctl }}"
                        }
                    ]
                    #,"availability_mode": "all"
                }
                payload.update(availability_data)

            for x in ['state_topic', 'json_attributes_topic', 'url_topic', 'image_topic']:
                if x in entity:
                    entity[x] = f"ankerctl/{self.printer.sn}/{entity[x]}"

            for x in ['value_template', 'json_attributes_template', 'url_template']:
                if (x in entity) and ('{' not in entity[x]):
                    entity[x] =  "{{" + entity[x] + "}}"

            payload.update(entity)
            # print(f"Autodiscovery Data:\n{json.dumps(payload, indent=4)}")
            return payload
