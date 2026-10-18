import io
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from slim11 import catalog, iso, setup_files
from slim11.engine import BuildConfig, build, inspect_iso
from slim11.tools import Cancelled, CancelToken, ToolError, find_wimlib, run
from slim11.wim import editions_from_header, parse_info

WIM_XML = """<WIM><IMAGE INDEX="1"><NAME>Windows 11 Home</NAME><TOTALBYTES>100</TOTALBYTES>
<WINDOWS><ARCH>9</ARCH><VERSION><BUILD>26100</BUILD></VERSION><LANGUAGES><DEFAULT>en-US</DEFAULT></LANGUAGES></WINDOWS>
</IMAGE><IMAGE INDEX="2"><NAME>Windows 11 Pro</NAME><DISPLAYNAME>Windows 11 Pro</DISPLAYNAME>
<WINDOWS><ARCH>12</ARCH></WINDOWS></IMAGE></WIM>"""


def fake_wim_header(xml: str) -> bytes:
    data = ("﻿" + xml).encode("utf-16-le")
    header = bytearray(208)
    header[:8] = b"MSWIM\0\0\0"
    struct.pack_into("<QQQ", header, 72, len(data), 208, len(data))
    return bytes(header) + data


def make_media(root: Path) -> None:
    (root / "boot").mkdir(parents=True)
    (root / "efi/microsoft/boot").mkdir(parents=True)
    (root / "sources").mkdir()
    (root / "boot/etfsboot.com").write_bytes(b"\0" * 2048)
    (root / "efi/microsoft/boot/efisys.bin").write_bytes(b"\1" * 1474560)
    (root / "setup.exe").write_bytes(b"setup")
    (root / "sources/empty.txt").write_bytes(b"")


class CatalogTests(unittest.TestCase):
    def test_presets_are_valid(self):
        for preset_id, _title, _desc in catalog.PRESETS:
            catalog.preset(preset_id).validate()

    def test_unknown_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            catalog.Selection(apps=["nope"]).validate()

    def test_slim_keeps_risky_items_off(self):
        self.assertNotIn("webview2", catalog.preset("slim").files)

    def test_extra_packages_are_deduplicated(self):
        sel = catalog.Selection(apps=["ai"], extra_packages=["Microsoft.Copilot", " Contoso.App "])
        self.assertEqual(sel.packages().count("Microsoft.Copilot"), 1)
        self.assertIn("Contoso.App", sel.packages())


class SetupFileTests(unittest.TestCase):
    def test_autounattend_is_valid_xml(self):
        xml = setup_files.autounattend(catalog.preset("slim"), "x86_64")
        root = ET.fromstring(xml)
        ns = "{urn:schemas-microsoft-com:unattend}"
        passes = [s.get("pass") for s in root.findall(f"{ns}settings")]
        self.assertEqual(passes, ["windowsPE", "specialize", "oobeSystem"])
        self.assertIn("BypassTPMCheck", xml)
        self.assertIn('processorArchitecture="amd64"', xml)
        self.assertIn("HideOnlineAccountScreens", xml)

    def test_autounattend_without_tweaks(self):
        xml = setup_files.autounattend(catalog.Selection(), "arm64")
        self.assertNotIn("LabConfig", xml)
        self.assertNotIn("HideOnlineAccountScreens", xml)
        self.assertIn('processorArchitecture="arm64"', xml)

    def test_specialize_script(self):
        script = setup_files.specialize_script(catalog.preset("slim"))
        self.assertIn("'Microsoft.BingNews'", script)
        self.assertIn(r'reg.exe add "HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection"', script)
        self.assertIn(r"HKU\Slim11Default", script)
        self.assertIn("schtasks.exe /Change", script)
        self.assertTrue(script.endswith("\r\n"))

    def test_empty_selection_script_has_no_actions(self):
        script = setup_files.specialize_script(catalog.Selection())
        self.assertNotIn("Remove-AppxProvisionedPackage", script)
        self.assertNotIn("reg.exe", script)

    def test_single_quotes_are_escaped(self):
        script = setup_files.specialize_script(catalog.Selection(extra_packages=["O'Brien.App"]))
        self.assertIn("'O''Brien.App'", script)


class WimTests(unittest.TestCase):
    def test_parse_wimlib_info(self):
        text = ("WIM Information:\n----\nImage Count: 2\n\n"
                "Index:                  1\nName:                   Windows 11 Home\nArchitecture:  x86_64\n"
                "Build:  26100\nTotal Bytes:  123\n\n"
                "Index:                  2\nName:                   Windows 11 Pro\nDisplay Name:  Pro!\n")
        eds = parse_info(text)
        self.assertEqual([e.index for e in eds], [1, 2])
        self.assertEqual(eds[0].architecture, "x86_64")
        self.assertEqual(eds[0].size_bytes, 123)
        self.assertEqual(eds[1].display_name, "Pro!")

    def test_editions_from_header(self):
        eds = editions_from_header(io.BytesIO(fake_wim_header(WIM_XML)))
        self.assertEqual([(e.index, e.name, e.architecture) for e in eds],
                         [(1, "Windows 11 Home", "x86_64"), (2, "Windows 11 Pro", "arm64")])
        self.assertEqual(eds[0].build, "26100")
        self.assertEqual(eds[0].language, "en-US")


class RunTests(unittest.TestCase):
    def test_progress_and_errors(self):
        seen, logged = [], []
        code = "import sys; print('Step (40%)'); print('hello'); sys.exit(3)"
        with self.assertRaises(ToolError):
            run([sys.executable, "-c", code], log=logged.append, progress=seen.append)
        self.assertEqual(seen, [0.4])
        self.assertIn("hello", logged)

    def test_cancel_stops_process(self):
        token = CancelToken()
        threading.Timer(0.3, token.cancel).start()
        start = time.monotonic()
        with self.assertRaises(Cancelled):
            run([sys.executable, "-c", "import time; time.sleep(30)"], log=lambda _m: None, cancel=token)
        self.assertLess(time.monotonic() - start, 10)


class IsoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="slim11-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip_and_boot_catalog(self):
        media = self.tmp / "media"
        make_media(media)
        (media / "sources/install.wim").write_bytes(fake_wim_header(WIM_XML))
        out = self.tmp / "out.iso"
        iso.build(str(media), str(out), label="slim11 x64", log=lambda _m: None)

        import pycdlib
        disc = pycdlib.PyCdlib()
        disc.open(str(out))
        try:
            catalog_ = disc.eltorito_boot_catalog
            self.assertEqual(catalog_.initial_entry.sector_count, 8)
            self.assertEqual([s.platform_id for s in catalog_.sections], [0xEF])
        finally:
            disc.close()

        back = self.tmp / "back"
        iso.extract(str(out), str(back), log=lambda _m: None)
        for rel in ("setup.exe", "boot/etfsboot.com", "efi/microsoft/boot/efisys.bin", "sources/empty.txt"):
            self.assertEqual((back / rel).read_bytes(), (media / rel).read_bytes(), rel)

        eds = inspect_iso(str(out))
        self.assertEqual(len(eds), 2)

    def test_missing_boot_files_fail(self):
        (self.tmp / "m").mkdir()
        with self.assertRaises(RuntimeError):
            iso.build(str(self.tmp / "m"), str(self.tmp / "x.iso"), label="x", log=lambda _m: None)


@unittest.skipUnless(find_wimlib(), "wimlib-imagex not installed")
class EndToEndTests(unittest.TestCase):
    def test_full_build(self):
        wimlib = find_wimlib()
        tmp = Path(tempfile.mkdtemp(prefix="slim11-e2e-"))
        try:
            os_root = tmp / "os"
            (os_root / "Program Files (x86)/Microsoft/Edge").mkdir(parents=True)
            (os_root / "Program Files (x86)/Microsoft/Edge/msedge.exe").write_bytes(os.urandom(4096))
            (os_root / "Windows/System32").mkdir(parents=True)
            (os_root / "Windows/System32/OneDriveSetup.exe").write_bytes(b"x")
            (os_root / "Windows/System32/notepad.exe").write_bytes(b"y")
            media = tmp / "media"
            make_media(media)
            wim = media / "sources/install.wim"
            for name in ("Windows 11 Home", "Windows 11 Pro"):
                verb = "append" if wim.exists() else "capture"
                subprocess.run([wimlib, verb, str(os_root), str(wim), name], check=True, capture_output=True)
            subprocess.run([wimlib, "info", str(wim), "2", "--image-property", "WINDOWS/ARCH=9"],
                           check=True, capture_output=True)
            src = tmp / "src.iso"
            iso.build(str(media), str(src), label="src", log=lambda _m: None)

            out = tmp / "out" / "slim.iso"
            stages = []
            build(BuildConfig(str(src), 2, str(out), catalog.preset("slim")), log=lambda _m: None,
                  progress=lambda s, _v: stages.append(s))
            self.assertEqual(stages[-1], "done")
            self.assertFalse(any(p.name.startswith(".slim11-work") for p in out.parent.iterdir()))

            back = tmp / "back"
            iso.extract(str(out), str(back), log=lambda _m: None)
            self.assertTrue((back / "autounattend.xml").is_file())
            listing = subprocess.run([wimlib, "dir", str(back / "sources/install.esd"), "1"],
                                     check=True, capture_output=True, text=True).stdout
            self.assertIn("/Windows/Setup/Scripts/Slim11/Specialize.ps1", listing)
            self.assertIn("/Windows/System32/notepad.exe", listing)
            self.assertNotIn("OneDriveSetup.exe", listing)
            self.assertNotIn("msedge.exe", listing)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
