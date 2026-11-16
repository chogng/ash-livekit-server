import json
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import build_release as build
import producer


class ReleaseTests(unittest.TestCase):
    def test_distribution_revision_allows_a_new_release_without_an_upstream_bump(self):
        lock = {"version": "1.13.7"}
        with patch.object(build, "read", return_value={"releaseRevision": 2}):
            self.assertEqual(build.release_tag(lock), "livekit-v1.13.7-ash.2")
        for revision in (0, -1, True, "2"):
            with (
                self.subTest(revision=revision),
                patch.object(build, "read", return_value={"releaseRevision": revision}),
            ):
                with self.assertRaisesRegex(ValueError, "distribution revision"):
                    build.release_tag(lock)

    def test_archives_are_reproducible_and_aggregation_rejects_tampering(self):
        lock = build.read(build.ROOT / "upstream-lock.json")
        targets = ["aarch64-apple-darwin", "x86_64-apple-darwin", *lock["artifacts"]]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "livekit-server"
            binary.write_bytes(b"native server fixture")
            notices = [build.ROOT / "LIVEKIT-LICENSE", build.ROOT / "LIVEKIT-NOTICE"]
            output = root / "dist"
            archives = [
                build.package(
                    binary, notices, t, lock, output, "chogng/ash-livekit-server"
                )
                for t in targets
            ]
            original = archives[0].read_bytes()
            binary.touch()
            build.package(
                binary, notices, targets[0], lock, output, "chogng/ash-livekit-server"
            )
            self.assertEqual(archives[0].read_bytes(), original)
            build.aggregate(output, lock)
            self.assertEqual(
                set(build.read(output / "runtime-lock.json")["artifacts"]), set(targets)
            )
            provenance_path = output / f"{targets[0]}.provenance.json"
            provenance = provenance_path.read_bytes()
            changed = build.read(provenance_path)
            changed["goVersion"] = "0.0.0"
            provenance_path.write_text(build.json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "Mixed build inputs"):
                build.aggregate(output, lock)
            provenance_path.write_bytes(provenance)
            archives[0].write_bytes(original + b"tampered")
            with self.assertRaisesRegex(ValueError, "evidence"):
                build.aggregate(output, lock)

    def test_incomplete_native_matrix_cannot_publish_a_consumer_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                build.aggregate(
                    Path(directory), build.read(build.ROOT / "upstream-lock.json")
                )
            self.assertFalse((Path(directory) / "runtime-lock.json").exists())

    def test_a_mixed_producer_recipe_cannot_publish(self):
        lock = build.read(build.ROOT / "upstream-lock.json")
        targets = ["aarch64-apple-darwin", "x86_64-apple-darwin", *lock["artifacts"]]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary = directory / "server"
            binary.write_bytes(b"native fixture")
            for target in targets:
                build.package(
                    binary,
                    [],
                    target,
                    lock,
                    directory / "dist",
                    "chogng/ash-livekit-server",
                )
            with patch.object(build, "recipe", return_value={"different": "recipe"}):
                with self.assertRaisesRegex(ValueError, "Mixed build inputs"):
                    build.aggregate(directory / "dist", lock)
            self.assertFalse((directory / "dist/runtime-lock.json").exists())

    def test_official_binary_is_prepared_in_an_isolated_directory_and_repairs_tampering(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b"verified server bytes"
            archive = root / "input.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("livekit-server.exe", payload)
            lock = {
                "version": "1.13.7",
                "artifacts": {
                    "x86_64-pc-windows-msvc": {
                        "url": "https://example.invalid/server.zip",
                        "archive": "input.zip",
                        "sha256": build.digest(archive),
                    }
                },
            }
            (root / "upstream-lock.json").write_text(json.dumps(lock), encoding="utf-8")
            cache = root / ".cache/livekit/1.13.7"
            cache.mkdir(parents=True)
            (cache / archive.name).write_bytes(archive.read_bytes())
            with patch.object(
                producer,
                "download_and_verify",
                side_effect=AssertionError("no network expected"),
            ):
                binary = producer.resolve_livekit("x86_64-pc-windows-msvc", root=root)
                self.assertEqual(binary.read_bytes(), payload)
                binary.write_bytes(b"tampered")
                self.assertEqual(
                    producer.resolve_livekit(
                        "x86_64-pc-windows-msvc", root=root
                    ).read_bytes(),
                    payload,
                )
            self.assertFalse((root / "build-source").exists())

    def test_macos_build_requires_the_exact_local_go_toolchain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = {
                "version": "1.13.7",
                "artifacts": {},
                "source": {
                    "url": "https://example.invalid/source.tar.gz",
                    "sha256": "a" * 64,
                },
            }
            (root / "upstream-lock.json").write_text(json.dumps(lock), encoding="utf-8")
            (root / "build-inputs.json").write_text(
                json.dumps({"goVersion": "1.26.11"}), encoding="utf-8"
            )
            with (
                patch.object(producer.sys, "platform", "darwin"),
                patch.object(producer.shutil, "which", return_value="go"),
                patch.object(
                    producer.subprocess, "check_output", return_value="go1.26.10\n"
                ) as version,
                patch.object(producer, "download_and_verify") as download,
            ):
                with self.assertRaisesRegex(ValueError, "Go toolchain"):
                    producer.resolve_livekit("aarch64-apple-darwin", root=root)
                self.assertEqual(
                    version.call_args.kwargs["env"]["GOTOOLCHAIN"], "local"
                )
                download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
