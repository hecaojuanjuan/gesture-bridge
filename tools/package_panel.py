"""Package only built H5 assets, never SDK source, credentials or local logs."""
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'panel/dist'
for required in ('index.html', 'app.json'):
    if not (source / required).is_file():
        raise SystemExit('Build panel first: npm --prefix panel run build')
output = ROOT / 'artifacts/headvoice-panel.zip'
with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
    for file in sorted(source.rglob('*')):
        if file.is_file():
            archive.write(file, file.relative_to(source).as_posix())
summary = {'artifact': output.name, 'bytes': output.stat().st_size,
           'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
           'protocol': json.loads((ROOT/'panel/protocol.json').read_text()),
           'hardware_verified': False}
(ROOT/'artifacts/panel-build-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(output)
print(json.dumps(summary,indent=2))
