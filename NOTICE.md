# Attribution

## Tiny11 Builder by ntdev

Slim11 Builder is inspired by and modelled on
[Tiny11 Builder](https://github.com/ntdevlabs/tiny11builder) by
[ntdev](https://github.com/ntdevlabs), and in particular its native
[WinUI app](https://github.com/ntdevlabs/tiny11builder/releases/tag/winui-v0.1.2).

What Slim11 takes from Tiny11 Builder is the concept and the design: a guided
wizard that turns an official Windows 11 ISO into a leaner one, the
"Tiny11-style" preset next to a Custom mode, and the choice of which bundled
apps, Edge/OneDrive files and privacy/ads/Copilot/hardware-check settings to
target. Provisioned-app names and registry policy names are public Windows
identifiers.

Slim11 does **not** include, translate or redistribute Tiny11 Builder's C#,
XAML or PowerShell source, its images or its answer file. Slim11's code was
written independently for Python so it can run on Linux and macOS. At the time
of writing, the Tiny11 Builder repository does not carry a license file, so
none of its material is reused here.

Please support ntdev:
[GitHub Sponsors](https://github.com/sponsors/ntdevlabs) ·
[Patreon](https://www.patreon.com/ntdev) ·
[PayPal](https://paypal.me/ntdev2) ·
[Ko-fi](https://ko-fi.com/ntdev)

## Design

The interface follows the look of Microsoft's
[WinUI](https://learn.microsoft.com/windows/apps/winui/) and Fluent design
system (navigation rail, layered surfaces, accent color). No WinUI code or
assets are included.

## Third-party software

- [wimlib](https://wimlib.net) by Eric Biggers. Used as an external program;
  not bundled; see wimlib's own license terms.
- [pycdlib](https://github.com/clalancette/pycdlib) by Chris Lalancette.
  Installed from PyPI; LGPL-2.1.

## Trademarks

Windows is a trademark of the Microsoft group of companies. Tiny11 is
associated with ntdev. Slim11 is not affiliated with or endorsed by either.
