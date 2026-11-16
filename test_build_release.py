import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import build_release as build


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


if __name__ == "__main__":
    unittest.main()
