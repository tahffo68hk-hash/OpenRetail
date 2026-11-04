# Home Assistant read-only/notification link

1. Install Home Assistant from official installation docs; configure an account and long-lived access token.
2. Set `HA_ENABLED=true`, `HA_URL`, `HA_TOKEN` in the **local** `.env`.
3. `GET /api/admin/overview` checks `/api/` reachability. OpenRetail's `HomeAssistantAdapter.publish_event()` supports optional notifications to `/api/events/{event_type}`. No event is sent automatically in V1: hook it into an explicit server-side notification policy after access controls and privacy review.
4. ESPHome sample `../esphome/door_contact_READ_ONLY.example.yaml` is only a **sensor**, not a commercial access controller.
5. `LIVE_DOOR_ENABLED=true` is deliberately rejected at application startup. Do not remove this safety gate merely to make the demo actuate a physical door. Actual operation requires an appropriately certified controller, qualified door/egress installation, identity/rate-limit implementation, and hardware fail-safe checks.

Official API: https://developers.home-assistant.io/docs/api/rest/
