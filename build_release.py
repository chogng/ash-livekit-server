"""Build immutable LiveKit inputs using the pinned upstream and build harness."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def release_tag(lock):
    version = lock["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid upstream version")
    return f"livekit-v{version}-ash.1"


def package(binary, notices, target, lock, output, repository):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid distribution repository")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"livekit_{lock['version']}_{target}.tar.gz"
    name = "livekit-server.exe" if "windows" in target else "livekit-server"
    with (
        archive.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped,
        tarfile.open(fileobj=zipped, mode="w|") as tar,
    ):
        for member_name, data, mode in [
            (name, binary.read_bytes(), 0o755),
            *[(p.name, p.read_bytes(), 0o644) for p in notices],
        ]:
            info = tarfile.TarInfo(member_name)
            info.size = len(data)
            info.mode = mode
            info.mtime = info.uid = info.gid = 0
            tar.addfile(info, io.BytesIO(data))
    entry = {
        "url": f"https://github.com/{repository}/releases/download/{release_tag(lock)}/{archive.name}",
        "archive": archive.name,
        "sha256": digest(archive),
        "size": archive.stat().st_size,
    }
    (output / f"{target}.json").write_text(
        json.dumps(entry, indent=2) + "\n", encoding="utf-8"
    )
    provenance = {
        "target": target,
        "upstream": lock["source"],
        "buildHarness": read(ROOT / "build-inputs.json")["buildHarness"],
        "binarySha256": digest(binary),
    }
    (output / f"{target}.provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    return archive


def aggregate(directory, lock):
    targets = ["aarch64-apple-darwin", "x86_64-apple-darwin", *lock["artifacts"]]
    entries = {}
    for target in targets:
        entry = read(directory / f"{target}.json")
        archive = directory / entry["archive"]
        if Path(entry["archive"]).name != entry["archive"] or not archive.is_file():
            raise ValueError("Invalid archive identity")
        if (
            digest(archive) != entry["sha256"]
            or archive.stat().st_size != entry["size"]
        ):
            raise ValueError("Archive does not match native job evidence")
        provenance = read(directory / f"{target}.provenance.json")
        if (
            provenance["target"] != target
            or provenance["upstream"] != lock["source"]
            or provenance["buildHarness"]
            != read(ROOT / "build-inputs.json")["buildHarness"]
        ):
            raise ValueError("Mixed build inputs")
        with tarfile.open(archive) as tar:
            member = tar.getmember(
                "livekit-server.exe" if "windows" in target else "livekit-server"
            )
            if (
                not member.isfile()
                or hashlib.sha256(tar.extractfile(member).read()).hexdigest()
                != provenance["binarySha256"]
            ):
                raise ValueError("Invalid binary provenance")
        entries[target] = entry
    result = {**lock, "artifacts": entries}
    (directory / "runtime-lock.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "SHA256SUMS").write_text(
        "".join(
            f"{digest(p)}  {p.name}\n"
            for p in sorted(directory.iterdir())
            if p.is_file() and p.name != "SHA256SUMS"
        ),
        encoding="ascii",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "aggregate"])
    parser.add_argument("--target")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lock = read(ROOT / "upstream-lock.json")
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and os.environ[
        "GITHUB_REF_NAME"
    ] != release_tag(lock):
        parser.error("Release tag does not match the locked upstream version")
    if args.command == "aggregate":
        aggregate(args.output, lock)
        return
    if (
        not args.source
        or not args.target
        or args.target
        not in {"aarch64-apple-darwin", "x86_64-apple-darwin", *lock["artifacts"]}
    ):
        parser.error("A source checkout and supported target are required")
    source = args.source.resolve()
    if read(source / "third_party/livekit/runtime-lock.json") != lock:
        raise ValueError("Pinned build harness has different upstream inputs")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    if revision != read(ROOT / "build-inputs.json")["buildHarness"]["revision"]:
        raise ValueError("Build harness revision does not match the pin")
    resolved = subprocess.check_output(
        [sys.executable, "-B", str(source / "build/lib/livekit.py"), args.target],
        cwd=source,
        text=True,
    )
    binary = Path(json.loads(resolved)["executable"])
    version = subprocess.check_output([str(binary), "--version"], text=True).strip()
    if version != "livekit-server version " + lock["version"]:
        raise ValueError("Built server has an unexpected version")
    package(
        binary,
        [ROOT / "LIVEKIT-LICENSE", ROOT / "LIVEKIT-NOTICE"],
        args.target,
        lock,
        args.output,
        os.environ["GITHUB_REPOSITORY"],
    )


if __name__ == "__main__":
    main()
