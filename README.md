# VU Dials - VU Server

> **Upstream is unmaintained.** The original [SasaKaranovic/VU-Server](https://github.com/SasaKaranovic/VU-Server) has received no commits since May 2024. This fork is the actively maintained continuation — see [Relationship to upstream](#relationship-to-upstream).

![VU1 Dial](assets/vu1_hello_world.png?raw=true "VU1 Dial")

VU Server is the server application for [VU1 dials](https://vudials.com). It talks to the VU1 hardware hub over serial/USB and exposes a simple HTTP API, so any third-party application, script, or service can control the dials without needing to know anything about the underlying hardware protocol.

For example, updating a dial is a single HTTP request:

```bash
curl "http://localhost:5340/api/v0/dial/<dial_uid>/set?value=50&key=<api_key>"
```

See the full [API documentation](https://docs.vudials.com/api_messaging/) for everything the server exposes.

## Quick start

**Windows** users can grab `VUServer.zip` from this fork's [latest release](https://github.com/erinlkolp/VU-Server/releases/latest). Note that the download on vudials.com is built from upstream and does not include any of the [fixes listed below](#relationship-to-upstream).

**Linux / macOS** users run from source:

```bash
git clone https://github.com/erinlkolp/VU-Server.git
cd VU-Server
pip3 install -r requirements.txt
python3 server.py
```

Then open `http://localhost:5340` in your browser for the server's web GUI (create API keys, name dials, etc).

For a more detailed walkthrough (including fixing the common `/dev/ttyUSBx` permission error on Linux) see [Running from source on Linux](Running_from_source_on_linux.md).

## Configuration

Server settings live in `config.yaml`:

```yaml
server:
  hostname: localhost
  port: 5340
  communication_timeout: 10
  dial_update_period: 200
  master_key: <your-master-key>

hardware:
  port:
```

- `hostname` is the address the server binds to. `localhost` (the default) only accepts connections from the same machine. To reach the server from other devices on your network, set it to a specific interface address or leave it empty (`hostname:`) to bind all interfaces -- and change `master_key` first.
- `master_key` is the admin key used to create/manage other API keys. Change it from the default before exposing the server beyond your own machine.
- `hardware.port` can be left blank; the server will auto-detect the VU1 hub on the USB bus. Set it explicitly if you need to pin a specific serial port.

## Development

Install dev dependencies (adds `pytest` on top of the runtime requirements):

```bash
pip3 install -r requirements-dev.txt
```

Run the test suite:

```bash
pytest tests/
```

## Why a server instead of standalone apps?

VU dials can display almost anything — CPU load, weather, stock prices, temperatures — and everyone already has their own favorite app for tracking that data. Rather than fragment the community with yet another dedicated app per use case, VU Server exposes a small HTTP API so *any* existing application, script, or service can drive the dials with a single request. That keeps you using the tools you already like, while letting them integrate with VU dials as a plugin/extension rather than a replacement.

## Demo application

The [VU1 demo application](https://github.com/SasaKaranovic/VU-Demo-App) ([download](https://vudials.com/download/demo_app)) shows dials driving resource-usage monitoring on Windows, built entirely on top of the VU Server API.

See [community_applications.md](community_applications.md) for other scripts and integrations built by the community.

## Relationship to upstream

VU Server was originally written by [Sasa Karanovic](https://github.com/SasaKaranovic) as the official server for VU1 dials. Full credit for the original design and hardware protocol work goes to him.

Upstream development stopped in May 2024. This fork picks it up from that last commit and has since added 60+ commits, including:

- **Security fixes** — SQL injection in `database.py` (every query is now parameterized), and API-key enforcement on device-status and image endpoints that previously served data unauthenticated.
- **Stability fixes** — server hangs on shutdown, crashes on partial easing/backlight requests, phantom offline dials, false timeouts on dial writes, and a batch of serial-protocol bugs (response bleed-through, blocking I/O on the event loop, stale-buffer spin).
- **Maintenance** — Python 3.12–3.14 support, pinned dependencies, Dependabot, and CI that actually runs the test suite and PyLint on every push.
- **New features** — per-dial and bus-wide software reset, exposed via both the API and the web UI.

Run `git log 62a4059..HEAD` for the complete list.

**Where to file things:** open issues and pull requests against [this repository](https://github.com/erinlkolp/VU-Server/issues). Issues filed upstream are unlikely to get a response.

**On licensing:** upstream never published a license file, so this fork inherits that ambiguity. Treat the code as all-rights-reserved by the original author unless and until that changes.

## Contributing

If you build (or want to build) an integration, extension, or plugin that talks to VU dials, start with the [VU Dials API documentation](https://docs.vudials.com/api_messaging/). Non-developers can help by asking maintainers of their favorite apps to add VU dials support.

Contributions to the server itself are welcome — see [Relationship to upstream](#relationship-to-upstream) for where to file them.

---

[VU Dials Home page](https://vudials.com)
