# waterer

Code for my Raspberry Pi Zero-W single sprinkler controller.

The hardware includes:

* 24 Volt 2 Amp power adapter with 5.5mm x 2.5mm barrel tip
* chassis mount socket for that
* 5 Volt 2 Amp buck convertor (to power the Pi and the relay)
* miniature 5V relay
* resistor, transistor, and diode for that
* MCP3008 ADC chip
* moisture sensor
* 0.96 inch OLED monochrome screen with yellow and blue filters
* momentary pushbutton
* wire, and 3D PLA prints for the device housing and for the sensor

This software implements a control loop based on the `config.json` file, and logs events to the `log.json` file. The button enables immediate override to either start a watering event (press for 4 seconds) or to end a watering event that is in progress (press for 2 seconds). It also implements a JSON-based REST API to GET `/status`, GET or POST the `/config`, GET or DELETE the `/log`, or to initiate or terminate a `/watwr` event with POST. To invoke the latter, use:

```
curl -sS -X POST -d 'action=water' localhost/water
curl -sS -X POST -d 'action=stop' localhost/water
```

(to start or stop the watering, respectively).

To modify the config, you can use something similar to this:

```
curl -sS -X POST -d 'sensor=false&dry=20000&cooldown_min=120&timer=true&when=6%3A30AM&duration_sec=120&days=odd' localhost/config
```

Hopefully the other APIs are pretty self-explanatory. :-) 

