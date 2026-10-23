"""Package exactly one task directory, excluding author caches."""
import argparse
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=ROOT.parent.parent / "incremental-cohort-board.zip")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Archive must be outside the task directory")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if "__pycache__" in relative.parts or path.suffix == ".pyc":
                continue
            archive.write(path, Path("collinear-candidate") / ROOT.name / relative)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        task_roots = {"/".join(name.split("/")[:2]) for name in names}
        if task_roots != {f"collinear-candidate/{ROOT.name}"}:
            raise RuntimeError("Archive contains other task directories")
        if archive.testzip() is not None:
            raise RuntimeError("Archive integrity failure")
    print(output)
    print(f"{len(names)} files, {output.stat().st_size} bytes")
    print(f"SHA256 {hashlib.sha256(output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
