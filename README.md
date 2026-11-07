# oma-warp

An Omarchy bar widget for Cloudflare WARP and verified client maintenance on Arch.

**Work in progress, not yet installable.** The manifest reserves the Panel entry
point; the Panel and its bar icon are implemented in later tickets.

The backend foundation provides read-only client facts:

```sh
./oma-warp status --json
# Equivalent isolated invocation used by the Panel:
/usr/bin/python3 -I -B ./oma-warp status --json
```

Status always prints a schema-1 document with every key present. Unknown facts
are `null`; a partial document still exits successfully. A connected client
with no probe result is Unconfirmed. Probe, update and Job results are not yet
implemented, and the Problem list is empty in this slice.

The stdlib-only `oma_warp` package runs local fact commands concurrently with
1.5 second timeouts. Commands, HTTPS, time, and runtime/cache directory locations
are supplied by one injectable system boundary. Status does not change the
service, registration, packages or network settings.

## Development

Run `dev/check` before merging. It runs pytest (a development dependency),
`qmllint` for all QML files, qmltestrunner when QML tests exist,
`omarchy plugin validate` on the repository root, and `dev/scrub`. Missing tools
and failed checks make the gate fail; all steps still run. QML steps with no
inputs pass. The gate enables local-file XHR for shared QML Fixtures.

The tests also run without pytest using
`/usr/bin/python3 -B -m unittest discover -s tests`. Backend scenarios fake only
the system boundary and reproduce the shared `tests/fixtures/` documents.

The scrub check scans tracked and non-ignored files for personal machine facts,
trace locations and IPs outside the documentation ranges. It discovers local
identity values at runtime. Only the required public plugin id and repository
URL are exempt from username matching. Examples use `~`, `colo=XXX`, `loc=XX`,
203.0.113.0/24, 198.51.100.0/24 or 2001:db8::/32.

## License

MIT. See [LICENSE](LICENSE).
