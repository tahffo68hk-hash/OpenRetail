# Frigate local NVR + MQTT bridge (optional)

This repository does **not** redistribute Frigate source/images or pretend its camera pipeline ran.

1. Install and configure Frigate per https://docs.frigate.video/configuration/ and https://docs.frigate.video/integrations/mqtt/ .
2. Use a dedicated local MQTT broker with authentication and network segmentation. Example Frigate MQTT settings:

```yaml
mqtt:
  enabled: true
  host: <your-broker-LAN-IP>
  user: <MQTT_USER>
  password: <MQTT_PASSWORD>
```

3. Configure actual PoE/RTSP cameras in Frigate. Do not commit RTSP credentials. `frigate/events` reports object events, NOT retail theft.
4. `pip install 'paho-mqtt>=2,<3'` inside a dedicated worker environment; set FRIGATE_MQTT_HOST, PORT, USER, PASSWORD, INTERNAL_API_URL, INTEGRATION_KEY in a private `.env`.
5. Run `python workers/frigate_mqtt.py` from the project root. The worker forwards Frigate MQTT `new` and `end` person events to `POST /api/integrations/frigate-event`; identical event IDs/types are deduplicated.
6. OpenRetail receives **only person event metadata**. No direct camera credentials, customer faces, video files, or shoplifting labels are sent to the retail database.

CPU-only Frigate object detection may be slow; validate actual server headroom before deciding whether one N100 hosts both POS and NVR.
