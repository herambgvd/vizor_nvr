# TURN Server Deployment Guide — GVD NVR

WebRTC direct (ICE) connections work in most LAN deployments. This guide covers deploying a TURN server for operators who are behind double-NAT or symmetric NAT.

---

## When is TURN Needed?

| Network topology | ICE direct works? | TURN needed? |
|---|---|---|
| Camera and viewer on same LAN | ✅ Yes | No |
| Viewer on corporate VPN, NVR on LAN | Usually ✅ | Rarely |
| NVR behind single NAT (port-forwarded) | ✅ Yes | No |
| NVR behind double-NAT (ISP CGNAT) | ❌ No | **Yes** |
| Viewer behind symmetric NAT (strict firewall) | ❌ No | **Yes** |
| Mobile viewer on 4G/5G, NVR on public IP | Usually ✅ | Sometimes |

A quick way to test: if WebRTC live view fails with `ICE failed` in the browser console and the NVR is reachable via HTTPS, a TURN server will likely fix it.

---

## Recommended TURN Server: coturn

[coturn](https://github.com/coturn/coturn) is a production-quality, open-source TURN/STUN server that runs on any Linux host.

### Install

```bash
# Ubuntu / Debian
sudo apt-get install -y coturn

# Enable the service
sudo systemctl enable coturn
```

### Minimal Configuration

Edit `/etc/turnserver.conf`:

```ini
# /etc/turnserver.conf — minimal config for GVD NVR
listening-port=3478
tls-listening-port=5349

# Replace with the public IP of your TURN server
external-ip=<TURN_SERVER_PUBLIC_IP>

# Shared secret for time-limited credentials (recommended over static passwords)
use-auth-secret
static-auth-secret=<GENERATE_WITH: openssl rand -hex 32>

# Realm (any string, often your domain)
realm=nvr.example.com

# Log to syslog
syslog

# Only allow TURN relaying (not STUN-only bypass)
no-stun

# Optional: limit relay to RFC1918 blocks for security
# denied-peer-ip=0.0.0.0-0.255.255.255
# denied-peer-ip=10.0.0.0-10.255.255.255  # remove if cameras are on 10.x

# Optional: TLS cert for encrypted TURN (port 5349)
# cert=/etc/letsencrypt/live/turn.example.com/fullchain.pem
# pkey=/etc/letsencrypt/live/turn.example.com/privkey.pem
```

```bash
# Start coturn
sudo systemctl start coturn
sudo systemctl status coturn

# Open firewall ports
sudo ufw allow 3478/udp
sudo ufw allow 3478/tcp
sudo ufw allow 5349/udp
sudo ufw allow 5349/tcp
sudo ufw allow 49152:65535/udp   # TURN relay port range
```

---

## Pointing go2rtc at the TURN Server

Edit `go2rtc.yaml` (or `go2rtc.yaml.template` and regenerate):

```yaml
webrtc:
  ice_servers:
    - urls:
        - stun:stun.l.google.com:19302          # public STUN fallback
        - turn:<TURN_SERVER_PUBLIC_IP>:3478      # your coturn server
        - turns:<TURN_SERVER_PUBLIC_IP>:5349     # TLS variant (optional)
      username: ""        # leave empty; go2rtc generates time-limited tokens
      credential: ""      # leave empty; go2rtc generates time-limited tokens
  # tell go2rtc to use coturn shared-secret for token generation
  ice_servers_auth:
    type: turn_credentials
    secret: <SAME_STATIC_AUTH_SECRET_AS_TURNSERVER_CONF>
    ttl: 86400
```

> For the full go2rtc WebRTC configuration reference, see:  
> https://github.com/AlexxIT/go2rtc/blob/master/README.md#webrtc

After editing, apply the change:

```bash
docker compose restart go2rtc
```

---

## Pointing the NVR Backend at the TURN Server

Update `.env` (or use the Network settings UI at `Settings → Network`):

```dotenv
GO2RTC_CANDIDATES=<TURN_SERVER_PUBLIC_IP>:8555,127.0.0.1:8555
```

Or via the API:

```bash
curl -X PUT https://localhost/api/system/network \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"go2rtc_candidates": "<TURN_SERVER_PUBLIC_IP>:8555,127.0.0.1:8555"}' -k
```

---

## Verifying TURN Connectivity

Use the WebRTC ICE trickle test from the operator's browser (the browser that has the NAT problem):

1. Open: https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/
2. Remove default STUN entries.
3. Add your TURN server:
   - **STUN or TURN URI**: `turn:<TURN_SERVER_PUBLIC_IP>:3478`
   - **Username**: generate a time-limited credential (or use a static test user if `lt-cred-mech` is enabled)
   - **Credential**: the corresponding password
4. Click **Gather Candidates**.
5. Confirm you see a candidate of type **relay** in the results list.

A `relay` candidate confirms that TURN is working. If you only see `host` or `srflx` candidates, check coturn logs:

```bash
sudo journalctl -u coturn -f
```

---

## Security Notes

- Use `use-auth-secret` (time-limited shared-secret credentials) rather than static username/password.
- Rotate `static-auth-secret` periodically and update `go2rtc.yaml` accordingly.
- Restrict the TURN relay port range (`min-port` / `max-port` in `turnserver.conf`) to reduce attack surface.
- Do **not** expose the TURN server admin port (default: 8080) publicly.
- Consider running coturn on a dedicated small VM separate from the NVR host.

---

## Quick Reference

| Item | Value |
|---|---|
| Default TURN port (UDP/TCP) | 3478 |
| Default TURNS port (TLS) | 5349 |
| TURN relay port range | 49152–65535 (UDP) |
| Config file | `/etc/turnserver.conf` |
| Service name | `coturn` |
| Log location | syslog (`journalctl -u coturn`) |
| Test tool | https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/ |
