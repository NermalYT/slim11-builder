# Slim11 Builder

Build a smaller Windows 11 ISO on **Linux, macOS or Windows**. Start from an
official Windows 11 ISO, choose what to remove, and get a new bootable ISO.

> **Slim11 is a cross-platform take on [ntdev's Tiny11 Builder](https://github.com/ntdevlabs/tiny11builder)
> and its [WinUI app](https://github.com/ntdevlabs/tiny11builder/releases/tag/winui-v0.1.2).**
> The idea, the build modes, the step-by-step wizard and the list of what a lean
> Windows should drop all come from ntdev's work. Tiny11 Builder only runs on
> Windows because it relies on DISM, so Slim11 was written from scratch to run
> on Linux and macOS as well. It contains no Tiny11 Builder code. See
> [Credits](#credits).

## What it does

| Preset | Removes / changes | Keeps |
| --- | --- | --- |
| **Slim** | Bundled consumer apps, Copilot, Xbox apps, communication apps, media apps, inbox utilities, Edge, the OneDrive installer; skips hardware checks, allows a local account, turns off ads, Copilot, widgets, web search and most telemetry | Windows Update, Defender, Store, WinRE/recovery |
| **Light** | Promo apps and Copilot, hardware-check bypass, local account, ads, web search | Edge, OneDrive, utilities, everything above |
| **Custom** | Nothing until you choose each item | Everything you don't select |

The output ISO holds a single edition, compressed as ESD (smallest) or WIM
(faster to build).

## Install

You need **Python 3.10+** and **wimlib**.

| OS | wimlib |
| --- | --- |
| Debian / Ubuntu | `sudo apt install wimtools` |
| Fedora | `sudo dnf install wimlib-utils` |
| Arch | `sudo pacman -S wimlib` |
| macOS | `brew install wimlib` |
| Windows | Download the Windows build from [wimlib.net](https://wimlib.net/downloads/) and extract it into a `tools` folder next to this README (or set `SLIM11_WIMLIB` to `wimlib-imagex.exe`) |

Then, from a clone of this repository:

```bash
./slim11.sh
```

On Windows, run `slim11.cmd`. The launcher creates a virtual environment, installs
the one Python dependency ([pycdlib](https://github.com/clalancette/pycdlib)),
starts the builder and opens it in your browser. No administrator or root rights
are needed.

You can also install it with pip: `pip install .` and run `slim11`.

## Use

1. Download a Windows 11 ISO from [Microsoft](https://www.microsoft.com/software-download/windows11).
2. Run Slim11 and pick **Slim**, **Light** or **Custom**.
3. Choose the ISO and an edition, review the components, choose where to save.
4. Build. You need about three times the ISO size in free space.
5. **Test the result in a virtual machine first.**

### Command line

```bash
slim11 inspect Win11_24H2_English_x64.iso
slim11 build Win11_24H2_English_x64.iso -e 6 -o Win11-slim.iso
slim11 build Win11.iso -e 6 -o Win11-light.iso --preset light --add-files onedrive
slim11 catalog    # every app group, file removal and tweak id, as JSON
```

## How it works

Tiny11 Builder mounts the image with DISM and edits it in place, which only
works on Windows. Slim11 splits the job differently so the same code runs
everywhere:

1. **Offline, on your machine** (via wimlib, no mounting): export the chosen
   edition, delete Edge / OneDrive / WebView2 files, and add a setup script.
2. **During Windows Setup** (via `autounattend.xml`): the TPM / Secure Boot / RAM
   check bypass is set inside Setup, and the script runs in the *specialize*
   pass as SYSTEM, before the first user exists. It removes the selected
   provisioned apps with `Remove-AppxProvisionedPackage`, applies the
   machine and default-user registry settings, and disables telemetry tasks.
   It logs to `C:\Windows\Setup\Scripts\Slim11\Specialize.log`.
3. **ISO writing** in pure Python: UDF for all files plus BIOS and UEFI El
   Torito boot entries, like Microsoft's own media.

### Differences from Tiny11 Builder

- **No Tiny11 Core equivalent.** Core resets the component store and deletes
  WinSxS content; doing that safely needs DISM, so it is not offered.
- **Apps are removed during Setup, not in the ISO.** The app files stay in the
  image until Setup runs, so the ISO is not much smaller than the original, but
  the installed system is. This avoids editing the AppX state database offline.
- **No Microsoft download inside the app.** Get the ISO from Microsoft's site.
- **Setup always runs from the new answer file.** Editions are reduced to the
  one you choose; Setup may ask for a product key or offer "I don't have a
  product key".

## Status

0.1.0 is an early release. The build pipeline is covered by automated tests on
Linux, macOS and Windows using synthetic images. Installing a real Windows 11
build from a Slim11 ISO has not been verified yet; please test in a VM and
open an issue with the build number and `Specialize.log` if something fails.

## Credits

- **[ntdev](https://github.com/ntdevlabs) and [Tiny11 Builder](https://github.com/ntdevlabs/tiny11builder)**,
  including the [Tiny11 Builder WinUI app](https://github.com/ntdevlabs/tiny11builder/releases/tag/winui-v0.1.2).
  Slim11's whole premise, its Tiny11-style / Custom modes, the six-step wizard
  flow, the warnings about testing in a VM, and the selection of apps, files and
  policies worth removing are modelled on ntdev's work. If Slim11 helps you,
  please support the original author:
  [GitHub Sponsors](https://github.com/sponsors/ntdevlabs) ·
  [Patreon](https://www.patreon.com/ntdev) ·
  [PayPal](https://paypal.me/ntdev2) ·
  [Ko-fi](https://ko-fi.com/ntdev)
- **Microsoft's [WinUI](https://learn.microsoft.com/windows/apps/winui/) / Fluent design**
  for the look of the interface.
- **[wimlib](https://wimlib.net)** by Eric Biggers for reading and writing WIM/ESD images.
- **[pycdlib](https://github.com/clalancette/pycdlib)** by Chris Lalancette for ISO reading and writing.

See [NOTICE.md](NOTICE.md) for details.

## Disclaimer

Slim11 is not affiliated with or endorsed by Microsoft or ntdev. Windows is a
trademark of Microsoft. Windows media, use and activation remain subject to
Microsoft's license terms. Removing components can break features; you use
this tool at your own risk.

## License

[MIT](LICENSE) for this project's code.
