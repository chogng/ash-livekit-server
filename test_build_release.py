import tempfile
import unittest
from pathlib import Path
import build_release as build


class ReleaseTests(unittest.TestCase):
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
