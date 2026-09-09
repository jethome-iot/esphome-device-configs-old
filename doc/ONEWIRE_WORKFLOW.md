# OneWire Temperature Sensors Workflow

Guide for adding Dallas DS18B20 temperature sensors to your device.

The 1-Wire bus is driven by a DS2484 I²C-to-1-Wire bridge at address `0x18`
(`boards/jxd-d6-r6-rev1.2.yaml`), so sensors are found on that bus rather than
on a bit-banged GPIO.

## Step 1: Find Sensor Address

Connect DS18B20 sensor(s) to the onewire connector, then check logs:

```
[15:45:33.923][C][ds2484:021]: DS2484 1-wire bus:
[15:45:33.934][C][ds2484:084]:   Found devices:
[15:45:33.940][C][ds2484:086]:     0xeb01227905460228 (DS18B20)
```

Copy the address: `0xeb01227905460228`

## Step 2: Add the Sensor

Edit `features/temperature.yaml`:

```yaml
sensor:
  - platform: dallas_temp
    name: "Temperature"
    id: temperature_sensor
    update_interval: 20s

  - platform: dallas_temp
    address: 0xeb01227905460228
    name: "Temperature 2"
    id: temperature_sensor_2
    update_interval: 20s
```

With more than one sensor on the bus, give every sensor an explicit `address`
(or `index`) — otherwise the assignment depends on discovery order.

## Step 3: Add to the `temperatures` global

The status page iterates a global vector of sensor pointers instead of a group.
Add the new sensor to it in the same file:

```yaml
globals:
  - id: temperatures
    type: std::vector<sensor::Sensor *>

esphome:
  on_boot:
    - priority: 800
      then:
        - lambda: 'id(temperatures) = {id(temperature_sensor), id(temperature_sensor_2)};'
```

## Step 4: Add to the Display Menu

Edit `display/menu.yaml`, in the `Temperatures` submenu:

```yaml
    - type: menu
      text: "Temperatures"
      items:
        - type: label
          text: !lambda |-
            return str_sprintf("%s: %2.1f°C", id(temperature_sensor).get_name().c_str(),
                               id(temperature_sensor).state);

        - type: label
          text: !lambda |-
            return str_sprintf("%s: %2.1f°C", id(temperature_sensor_2).get_name().c_str(),
                               id(temperature_sensor_2).state);
```

## Step 5: Upload Firmware

```bash
esphome run jxd-r6-e1eth-lcd-eth.yaml
```

The sensor will now appear in Home Assistant and on the device display.

## Hardware Connection

Connect DS18B20 sensors to the onewire connector on the device. Multiple sensors
can be connected in parallel on the same bus.
