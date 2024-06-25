
### TODO List:
- Implement Home Assistant Auto Discovery
- Accept settings via command line and/or web UI
  - Currently the `default.json` file needs to be manually updated to include the following object:
    ``` JSON
    "mqttrelay": {
        "name": "My MQTT Broker",
        "host": "hostname or IP",
        "port": 1883,
        "username": "myusername",
        "password": "xxxxxxx",
        "use_ssl": false,
        "use_ha": true,
        "__type__": "MqttRelay"
    },
    ```
- Send commands/queries to Ankerctl from local MQTT and send back response
  - Especially Gcode commands like pause, resume, stop, set temps, move extruder, etc.
- Create Home Assistant services, buttons, switches, etc. to communicate back to Ankerctl (via local MQTT)
- Make new `mqtt relay` CLI arguments instead of using existing `monitor`
- Allow relay and webserver to run simultaneously
- Expose PPPP info/commnads via MQTT

### Maybe:
- Video feed to Home Assistant
