# WiFi Setup

Applies to the WiFi variant (`jxd-r6-e1eth-lcd-wifi.yaml`). The Ethernet variant needs
none of this.

The firmware ships no network credentials. When it cannot reach a known network it
raises its own access point and serves a captive portal, and you hand it the real
network from there.

## Initial setup

1. **Flash the firmware** over USB using the WiFi configuration.

2. **Wait for the access point.** It comes up 90 seconds after the device fails to reach
   a known network, using the `wifi_ap_ssid` and `wifi_ap_password` values from your
   `secrets.yaml` (see [`secrets.yaml.example`](../secrets.yaml.example)).

3. **Join it** from a phone or laptop.

4. **Configure the network.** The captive portal usually opens on its own; otherwise
   browse to `http://192.168.4.1`. Pick your network from the list, enter its password
   and save.

5. **The device reconnects** to your network, shows its IP on the display, and becomes
   reachable over the API and web interface.

## Access point details

- **SSID** — value of `wifi_ap_ssid`
- **Password** — value of `wifi_ap_password`; WPA2, 8 to 64 characters, or an empty
  string for an open AP
- **Timeout** — 90 seconds without a WiFi connection (ESPHome's default)
- **Address** — `192.168.4.1` while in AP mode

## Changing the network later

**From the display menu.** **Settings → Reset WiFi creds → Confirm** clears the stored
credentials and reboots into AP mode; reconfigure through the captive portal as above.

**By factory reset.** **Settings → Factory reset → Confirm** clears all stored data,
credentials included, and reboots into AP mode.

**By baking credentials into the firmware.** `packages/features/wifi.yaml` configures
only the fallback AP; add `ssid` and `password` to its `wifi:` block — through `!secret`,
so they stay out of the repository — then recompile and upload:

```bash
esphome run jxd-r6-e1eth-lcd-wifi.yaml --device <IP_ADDRESS>
```
