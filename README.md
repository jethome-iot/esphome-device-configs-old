# ESPHome Device Configurations made by JetHome

![ESPHome](https://img.shields.io/badge/ESPHome-2026.8.2-blue)

This repository contains ESPHome configurations for various automation devices. Everything is built from upstream ESPHome components — no forked or custom components are required. These are **open-source firmware configurations** that you can customize and build yourself.

## Supported Devices

### JXD-R6-E1ETH-LCD
JetHome DIN-rail automation controller with display. For a proprietary firmware version with additional features and support, visit [JetHome official website](https://jethome.com/).

**Configurations**:
- `jxd-r6-e1eth-lcd-eth.yaml` - Ethernet variant
- `jxd-r6-e1eth-lcd-wifi.yaml` - WiFi variant

## JXD-R6-E1ETH-LCD Features

The JXD-R6-E1ETH-LCD is a powerful DIN-rail automation controller with the following capabilities:

### Hardware
- **ESP32** microcontroller with 16MB flash and PSRAM
- **6 Relay outputs** via PCA9554 I/O expander
- **6 Digital inputs** via PCA9554 I/O expander
- **OLED Display**: SSD1306/SH1106 128x64 pixels with interactive menu
- **RTC**: PCF8563 hardware real-time clock with battery backup
- **Temperature monitoring**: Onboard TMP102 sensor + Dallas DS18B20 over a DS2484 I²C-to-1-Wire bridge
- **Connectivity**: LAN8720 Ethernet or WiFi (ESP32 built-in)
- **Voltage monitoring**: Input voltage measurement
- **RS485/Modbus**: 2x UART interfaces for Modbus RTU communication

### Software Features

- **RTC Time Synchronization**: Hardware RTC with NTP sync and battery backup
- **Modbus RTU Server**: Acts as Modbus slave, mapping relays to coils and digital inputs to discrete inputs
- **Home Assistant Integration**: Native ESPHome API with automatic entity discovery and OTA updates
- **Display Control**: Interactive OLED menu with status, time, relay control, input monitoring, and settings
- **Dallas Temperature Sensors**: OneWire support for multiple DS18B20 sensors ([setup guide](doc/ONEWIRE_WORKFLOW.md))

## Repository Layout

Device configurations live in the repository root (`jxd-r6-e1eth-lcd-eth.yaml`,
`jxd-r6-e1eth-lcd-wifi.yaml`) and are thin: they set substitutions and list the packages
that make up the device. Everything else lives under `packages/`, split by role:

| Directory | Contents |
|---|---|
| `packages/boards/` | Platform and the chips sitting on each board — `jxd-cpu-e1eth.yaml` (ESP32, api/ota/logger/web_server, TMP102, LED, FN button) and `jxd-d6-r6-rev1.2.yaml` (PCA9554 expander, 6 relays, 6 inputs, DS2484 1-Wire bridge) |
| `packages/features/` | SoC buses (`i2c.yaml`, `uarts.yaml`) and functionality — `temperature`, `rtc-time`, `vin-measure`, `modbus-server`, `display-off`, `ethernet`, `wifi` |
| `packages/display/` | Display, pages, menu and buttons — `display.yaml`, `menu.yaml`, `buttons.yaml`, `menu-items-eth.yaml`, `menu-items-wifi.yaml` |

Relays, digital inputs and temperature sensors are published as globals holding entity
pointers (`relays`, `inputs`, `temperatures`), filled at boot. The status page iterates
those vectors, so adding a sensor is a one-line change.

Note that `!include` paths are relative to the file containing them, while asset paths
(`font: file:`) are resolved against the directory of the device config — which is why
`packages/display/display.yaml` refers to `fonts/` and not `../fonts/`.

### Generated configs (`dist/`)

`dashboard_import` gives the ESPHome Builder a single YAML file, so neither the package
tree nor the local `fonts/` reach the importing user. `scripts/build-dist.py` flattens
each device config into `dist/<device>.yaml` with fonts pointed at raw URLs, taking the
repository, ref and output path from that config's own `package_import_url`.

Regenerate and commit `dist/` after changing anything a device config pulls in — the
pre-commit hook and CI both check it:

```bash
python scripts/build-dist.py           # regenerate
python scripts/build-dist.py --check   # fail if stale
```

The generator refuses values the Builder would corrupt on import, such as a quoted
`'Yes'` that comes back as a boolean, and names them.

## Quick Start

### Requirements

- **Python 3.12, 3.13 or 3.14** (ESPHome 2026.8.2 requires `>=3.12,<3.15`)
- **ESPHome 2026.8.2** (pinned version for compatibility)
- USB cable or serial adapter for initial flashing
- Network connection for OTA updates

### Installation

1. **Clone this repository**:
```bash
git clone <repository-url>
cd esphome-device-configs
```

2. **Set up Python environment**:

**Linux/macOS**:
```bash
./scripts/setup.sh
source .venv/bin/activate
```

**Windows**:
```cmd
scripts\setup.bat
.venv\Scripts\activate
```

3. **Create your secrets file**:
```bash
cp secrets.yaml.example secrets.yaml
```

`secrets.yaml` is gitignored and never leaves your machine; `secrets.yaml.example`
is the tracked template listing every key the configs expect. Only the WiFi variant
reads secrets — it needs the fallback access point's SSID and password. A missing
file stops the build at `Error reading file secrets.yaml: [Errno 2] No such file or
directory`; a file that is present but missing a key, at `Secret 'wifi_ap_ssid' not
defined`. The Ethernet variant builds without a `secrets.yaml` at all.

### Configuration Variants

The repository provides two configuration variants:

#### Ethernet Version
```bash
esphome run jxd-r6-e1eth-lcd-eth.yaml
```
- Uses LAN8720 Ethernet controller
- Static or DHCP IP configuration
- Best for industrial/stable installations

#### WiFi Version
```bash
esphome run jxd-r6-e1eth-lcd-wifi.yaml
```
- Uses ESP32 built-in WiFi
- Captive portal for easy setup
- WiFi credentials stored in device
- Access Point mode for configuration

### Timezone

The timezone is compiled into the firmware and is never changed at runtime — Home
Assistant does not override it.

By default the build uses the timezone of the machine doing the build, so pin it
explicitly for reproducible builds:

```bash
esphome -s timezone UTC run jxd-r6-e1eth-lcd-eth.yaml
```

or per device in the device config:

```yaml
substitutions:
  timezone: Europe/Berlin
```

Both IANA names (`Europe/Berlin`) and POSIX TZ strings (`CET-1CEST,M3.5.0,M10.5.0/3`)
are accepted. POSIX strings per zone: [posix_tz_db](https://github.com/nayarsystems/posix_tz_db/blob/master/zones.csv).

### First Flash

For the first flash, connect via USB:
```bash
esphome run jxd-r6-e1eth-lcd-eth.yaml
# or
esphome run jxd-r6-e1eth-lcd-wifi.yaml
```

Subsequent updates can be done over-the-air (OTA):
```bash
esphome run jxd-r6-e1eth-lcd-eth.yaml --device <IP_ADDRESS>
```

### WiFi Setup (WiFi Version Only)

The WiFi version supports easy configuration through a captive portal:

#### Initial Setup

1. **Flash the firmware** via USB using the WiFi configuration
2. **Device creates Access Point**:
   - SSID: the `wifi_ap_ssid` value from your `secrets.yaml`
   - Password: the `wifi_ap_password` value from your `secrets.yaml`
   - The AP comes up 90 seconds after the device fails to reach a known network

3. **Connect to the AP**:
   - Use your phone or laptop to connect to the device's WiFi network
   
4. **Configure WiFi**:
   - Your device will show a captive portal notification suggesting to open WiFi settings
   - Tap the notification or manually navigate to `http://192.168.4.1`
   - The captive portal will display a list of available WiFi networks
   - Select your WiFi network from the list
   - Enter your WiFi password
   - Click "Save"

5. **Device connects**:
   - Device will disconnect from AP mode
   - Connects to your WiFi network
   - IP address displayed on device screen
   - Device now accessible via Home Assistant and web interface

#### Changing WiFi Settings

You can change WiFi configuration in two ways:

**Method 1: Via Display Menu (WiFi version)**
1. Press the Menu button to open the display menu
2. Navigate to: **Settings → Reset WiFi creds → Yes**
3. Device clears stored WiFi credentials and reboots in AP mode
4. Reconfigure WiFi using the captive portal (see Initial Setup above)

**Method 2: Via Configuration File**
1. Edit `packages/features/wifi.yaml` to set default credentials
2. Recompile and upload firmware:
```bash
esphome run jxd-r6-e1eth-lcd-wifi.yaml --device <IP_ADDRESS>
```

**Method 3: Factory Reset**
1. Open display menu: **Settings → Factory reset → Yes**
2. This clears all stored data including WiFi credentials
3. Device reboots and creates AP for reconfiguration

#### WiFi AP Details

The Access Point is configured from `secrets.yaml`, not derived from the device MAC:
- **SSID**: value of `wifi_ap_ssid`
- **Password**: value of `wifi_ap_password` — WPA2, 8 to 64 characters, or an empty string for an open AP
- **Timeout**: AP activates after 90 seconds without a WiFi connection (ESPHome's default)
- **IP Address**: Device accessible at `192.168.4.1` when in AP mode

## Display UI Overview

The device features an interactive OLED display with multiple pages accessible via the menu button:

### Main Page
<img src="images/jxd-r6-main-page-ui.svg" width="400" alt="Main Page">

Shows device name, uptime, input voltage, and IP address.

### Status Page
<img src="images/jxd-r6-status-page-ui.svg" width="400" alt="Status Page">

Shows relay states, digital input states and temperature readings at a glance, and lets
you switch the relays: LEFT and RIGHT move the highlight (the inverted relay number) along
the relay row, CENTER toggles the highlighted relay.

### Time Page
<img src="images/jxd-r6-time-page-ui.svg" width="400" alt="Time Page">

Displays current date and time from the hardware RTC.

### Menu Navigation
<img src="images/jxd-r6-menu-ui.svg" width="400" alt="Menu">

Interactive menu for relays, inputs, temperatures, device info and settings:
- **Relays** - toggle each of the 6 relays
- **Inputs** - live state of the 6 digital inputs
- **Temperatures** - temperature sensor readings
- **Info** - network information (IP, MAC address)
- **Settings** - display auto-off timer, WiFi credential reset (WiFi version only), factory reset, reboot

Buttons: LEFT and RIGHT open the status and time pages from the main page, CENTER opens
the menu, BACK steps out of a submenu and then closes the menu, HOME returns to the main
page. On the status page LEFT and RIGHT select a relay and CENTER toggles it.

## Documentation

- **[OneWire Workflow Guide](doc/ONEWIRE_WORKFLOW.md)**: Step-by-step guide for adding Dallas DS18B20 temperature sensors

## Modbus RTU Server

The device can act as a Modbus RTU server (slave) for integration with PLCs, SCADA systems, and other industrial automation equipment:

- **Slave Address**: 0x01 (configurable)
- **Baud Rate**: Configurable via UART settings (`packages/features/uarts.yaml`, `jxm_uart2`)
- **Coils** `0x0000`-`0x0005` (FC 0x01/0x05/0x0F): read/write relay 1-6
- **Discrete Inputs** `0x0010`-`0x0015` (FC 0x02): read digital input 1-6
- **Holding/input registers**: none mapped; a courtesy response answers `0` instead of an exception

Upstream `modbus_server` keeps coils and discrete inputs in a single bit address space, so
the two blocks are placed at different offsets rather than both starting at zero.

**RS-485 Connector (JXM2)**:
- Pin 1: B
- Pin 2: A
- Pin 3: B
- Pin 4: A

The map is defined in `packages/features/modbus-server.yaml`. `scripts/modbus_probe.py` walks the
whole map over RS485 for a quick check:

```bash
.venv/bin/python scripts/modbus_probe.py --port /dev/ttyUSB2 probe
```

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This project is open-source.

## Related Links

- [ESPHome Official Documentation](https://esphome.io/)
- [JetHome Official Website](https://jethome.com/) - Proprietary firmware version with additional features
- [JetHome AliExpress Store](https://aliexpress.ru/store/1105052969)

## Support

For issues related to:
- **Open-source firmware**: Use GitHub issues in this repository
- **Hardware or proprietary firmware**: Contact [JetHome support](mailto:sales@jethome.com)

