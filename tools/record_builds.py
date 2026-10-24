"""Record local build evidence without inventing device measurements."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rows = {}
for mode in ("baseline", "headvoice"):
    build = ROOT / ".work" / mode / "apps/build"
    log = ROOT / "artifacts" / f"{mode}-build.log"
    text = log.read_text(encoding="utf-8", errors="replace")
    if "Project build complete." not in text:
        raise RuntimeError(f"No successful build result: {mode}")
    files = {}
    for relative in ("vb701n.bin", "bootloader/bootloader.bin",
                     "partition_table/partition-table.bin",
                     "espdl_models/coco_pose.espdl", "flash_args"):
        data = (build / relative).read_bytes()
        files[relative] = dict(bytes=len(data),
                               sha256=hashlib.sha256(data).hexdigest())
    flash = (build / "flash_args").read_text()
    if "0x810000" not in flash or "coco_pose.espdl" not in flash:
        raise RuntimeError(f"Model missing from full flash manifest: {mode}")
    description = json.loads((build / "project_description.json").read_text())
    options = {}
    for line in (build / "CMakeCache.txt").read_text().splitlines():
        if line.startswith("HEADVOICE_") and "=" in line:
            name, value = line.split("=", 1)
            options[name.split(":", 1)[0]] = value
    rows[mode] = dict(version=description.get("project_version"),
                      target=description.get("target"), files=files,
                      headvoice_options=options,
                      hardware_verified=False)
report = dict(sdk_commit="89020f5e04bf777ae1672b8f3d320bc6e0ef3e0c",
              builds=rows, device_metrics=None,
              note="Successful local cross-compilation; no board connected")
path = ROOT / "artifacts/build-summary.json"
path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(path)
