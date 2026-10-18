import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from slim11 import ai, iso, jobs, settings
from slim11.cli import main as cli_main
from slim11.mcp_server import Server, serve

from test_slim11 import WIM_XML, fake_wim_header, make_media


class SettingsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="slim11-ai-"))
        self.env = mock.patch.dict(os.environ, {"SLIM11_CONFIG": str(self.tmp / "settings.json")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_iso(self) -> Path:
        media = self.tmp / "media"
        make_media(media)
        (media / "sources/install.wim").write_bytes(fake_wim_header(WIM_XML))
        out = self.tmp / "src.iso"
        iso.build(str(media), str(out), label="t", log=lambda _m: None)
        return out


class SettingsTests(SettingsTestCase):
    def test_ai_off_by_default_and_toggles(self):
        self.assertFalse(settings.ai_enabled())
        ai.set_enabled(True)
        self.assertTrue(settings.ai_enabled())
        self.assertTrue(json.loads((self.tmp / "settings.json").read_text())["ai_features"])
        ai.set_enabled(False)
        self.assertFalse(settings.ai_enabled())

    def test_unknown_setting_rejected(self):
        with self.assertRaises(ValueError):
            settings.save(nope=1)

    def test_snippets_use_this_python(self):
        import sys
        for text in ai.config_snippets().values():
            self.assertIn("mcp", text)
        self.assertEqual(ai.server_command()[0], sys.executable)


class McpTests(SettingsTestCase):
    def rpc(self, server, method, params=None, id_=1):
        return server.handle({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})

    def call(self, server, name, **arguments):
        result = self.rpc(server, "tools/call", {"name": name, "arguments": arguments})["result"]
        text = result["content"][0]["text"]
        return result["isError"], (text if result["isError"] else json.loads(text))

    def test_refuses_when_ai_off(self):
        out = io.StringIO()
        self.assertEqual(serve(stdin=io.StringIO(""), stdout=out), 1)
        self.assertEqual(out.getvalue(), "")

    def test_stdio_session(self):
        ai.set_enabled(True)
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "nope"},
        ]
        out = io.StringIO()
        stdin = io.StringIO("\n".join(json.dumps(l) for l in lines) + "\nnot json\n")
        self.assertEqual(serve(stdin=stdin, stdout=out), 0)
        replies = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual([r.get("id") for r in replies], [1, 2, 3, None])
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        names = {t["name"] for t in replies[1]["result"]["tools"]}
        self.assertTrue({"list_editions", "preview_build", "start_build", "build_status"} <= names)
        self.assertEqual(replies[2]["error"]["code"], -32601)
        self.assertEqual(replies[3]["error"]["code"], -32700)

    def test_tools(self):
        server = Server()
        src = self.make_iso()
        err, isos = self.call(server, "find_isos", folder=str(self.tmp))
        self.assertFalse(err)
        self.assertEqual([Path(i["path"]).name for i in isos], ["src.iso"])
        err, eds = self.call(server, "list_editions", iso=str(src))
        self.assertEqual([e["index"] for e in eds], [1, 2])
        profile = {"source": str(src), "edition": 1, "output": str(self.tmp / "out.iso"), "preset": "light"}
        err, preview = self.call(server, "preview_build", profile=profile)
        self.assertFalse(err, preview)
        self.assertIn("Microsoft.Copilot", preview["apps_removed_during_setup"])
        self.assertIn("<unattend", preview["autounattend_xml"])
        err, msg = self.call(server, "preview_build", profile={**profile, "edition": 9})
        self.assertTrue(err)
        self.assertIn("Edition 9", msg)
        err, msg = self.call(server, "preview_build", profile={**profile, "selection": {"apps": ["bogus"]}})
        self.assertTrue(err)
        err, saved = self.call(server, "save_profile", path=str(self.tmp / "p.json"), profile=profile)
        self.assertFalse(err)
        err, loaded = self.call(server, "load_profile", path=str(self.tmp / "p.json"))
        self.assertEqual(loaded, profile)
        err, status = self.call(server, "build_status")
        self.assertEqual(status["state"], "idle")


class ProfileTests(SettingsTestCase):
    def test_round_trip_and_validation(self):
        profile = {"source": "a.iso", "edition": 2, "output": "b.iso", "preset": "slim", "format": "wim"}
        config = jobs.config_from_profile(profile)
        self.assertEqual(config.format, "wim")
        again = jobs.config_from_profile(jobs.profile_from_config(config))
        self.assertEqual(again.selection.__dict__, config.selection.__dict__)
        for bad in ({**profile, "output": "b.img"}, {**profile, "format": "zip"}, {**profile, "colour": 1},
                    {k: v for k, v in profile.items() if k != "edition"}):
            with self.assertRaises(ValueError):
                jobs.config_from_profile(bad)

    def test_add_and_remove_adjust_a_preset(self):
        config = jobs.config_from_profile({"source": "a.iso", "edition": 1, "output": "b.iso", "preset": "light",
                                           "add": {"files": ["onedrive"], "extra_packages": ["X.Y"]},
                                           "remove": {"tweaks": ["search"]}})
        self.assertIn("onedrive", config.selection.files)
        self.assertIn("X.Y", config.selection.packages())
        self.assertNotIn("search", config.selection.tweaks)
        with self.assertRaises(ValueError):
            jobs.config_from_profile({"source": "a.iso", "edition": 1, "output": "b.iso", "add": {"files": ["nope"]}})

    def test_cli_save_profile_with_overrides(self):
        path = self.tmp / "p.json"
        rc = cli_main(["build", "x.iso", "-e", "6", "-o", "y.iso", "--preset", "light",
                       "--add-files", "onedrive", "--package", "Contoso.App", "--save-profile", str(path)])
        self.assertEqual(rc, 0)
        data = json.loads(path.read_text())
        self.assertIn("onedrive", data["selection"]["files"])
        self.assertEqual(data["selection"]["extra_packages"], ["Contoso.App"])
        rc = cli_main(["build", "--profile", str(path), "--skip-tweaks", "search", "--save-profile", str(path)])
        self.assertEqual(rc, 0)
        self.assertNotIn("search", json.loads(path.read_text())["selection"]["tweaks"])


if __name__ == "__main__":
    unittest.main()
