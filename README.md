# oma-warp

An Omarchy bar widget for Cloudflare WARP and verified client maintenance on
x86_64 Omarchy. The widget opens the **Panel**, which shows WARP status and
provides the controls for turning WARP on or off and maintaining the client.

## Install and update

On x86_64 Omarchy, install and enable the plugin with:

```sh
omarchy plugin add https://github.com/spitefulFr0g/oma-warp --enable
```

Update the plugin and its Panel and backend together with:

```sh
omarchy plugin update
```

An AUR helper may notice the package name `cloudflare-warp-bin` and offer to
swap it for the AUR package. oma-warp obtains and installs the client from
Cloudflare's verified repository instead.

## The Panel

Click the cloud icon in the Omarchy bar to open the Panel. Its **Status** view
shows the WARP switch, the current Problem or running Job, and the exit IP when
available. It offers the relevant fix, Update or Restart action when one is
needed. A full cloud means Cloudflare's trace endpoint confirmed traffic is
**Through Cloudflare**. An outlined cloud means WARP is connected but that
confirmation is not available yet. A crossed-out cloud indicates a Problem;
the small dot indicates an available update or a needed restart.

Open **Diagnostics** with the ⓘ control to see package, service, daemon,
registration, connection, Through Cloudflare, location, DNS and latest-release
details. A Problem's fix appears beside the related detail. Diagnostics also
provides the automatic check setting and a manual check action.

Install, Update, Restart, Start service and Register run as **Jobs** in a
floating terminal. This lets sudo and Cloudflare's registration terms prompt
work normally. The Panel shows the active Job while it runs; its result and any
follow-up prompt appear in the terminal.

## Verification and trust

Before oma-warp offers or installs a release, it checks Cloudflare's signed
repository metadata against a pinned signing-key fingerprint, verifies the
package index checksum, and verifies the package checksum. Redirects are
refused. The pinned fingerprint is a reviewed constant in this project; it is
not independently certified. A signing-key rotation fails closed and requires
a reviewed source change.

Cloudflare's signed metadata does not provide `Valid-Until`. To defend against
replayed older metadata, Update compares the verified release with the
installed version and refuses a downgrade. If the repository release is equal
or older, the installed client is kept.

## Remove the plugin

To remove oma-warp and the WARP client, run this from the plugin directory in
a terminal:

```sh
./oma-warp uninstall
```

The command confirms once, then removes the WARP connection and registration,
stops and disables its service, removes the client and its state, clears
oma-warp's cache and runtime files, and removes the plugin. Privileged steps
use sudo in that terminal. It stops at the first failure; run the same command
again to resume cleanup.

Disabling the plugin leaves the client, service, registration and plugin files
in place. Disable is reversible; use the uninstall command above for removal.

## Development

Run the full development gate before contributing:

```sh
./dev/check
```

The gate runs pytest, Qt 6 `qmllint`, Qt 6 `qmltestrunner` when QML tests are
present, Omarchy plugin manifest validation, and the privacy scrub. Install
pytest, the Qt 6 QML tools, and Omarchy's shell imports when setting up a
development environment. The gate fails when a required tool is missing or a
check fails. Backend tests fake system effects; they do not change the host's
WARP configuration.

## License

MIT. See [LICENSE](LICENSE).
