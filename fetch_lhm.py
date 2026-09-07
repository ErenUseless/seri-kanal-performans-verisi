"""LibreHardwareMonitorLib ve bagimliliklarini nuget.org'dan lib/ klasorune indirir.

.NET Framework 4.7.2 hedefi icin uygun DLL'ler secilir (yoksa netstandard2.0).
Calistirma:  python fetch_lhm.py
"""

import io
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

FLAT = "https://api.nuget.org/v3-flatcontainer"
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")

ROOT = ("librehardwaremonitorlib", "0.9.6")

# Tercih sirasi: net472 -> netstandard2.0 -> ... (en uygun lib klasoru)
TFM_ORDER = ["net472", "net471", "net47", "net462", "net461", "net46", "net45",
             "netstandard2.0", "netstandard1.6", "netstandard1.3", "netstandard1.0"]
# Bagimlilik gruplarinda gecen TFM adlari
GROUP_ORDER = [".netframework4.7.2", ".netframework4.7", ".netframework4.6.1",
               ".netstandard2.0", "net472", "netstandard2.0", ""]

# .NET Framework 4.8 icinde zaten bulunan, indirilmemesi gereken paketler
SKIP = {"netstandard.library", "system.io.ports", "mono.posix.netstandard"}


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def latest_version(pkg):
    data = fetch("%s/%s/index.json" % (FLAT, pkg)).decode("utf-8")
    versions = re.findall(r'"([^"]+)"', data.split("[", 1)[1])
    stable = [v for v in versions if "-" not in v]
    return (stable or versions)[-1]


def pick_lib_entries(zf):
    """Paket icinden hedef cerceveye en uygun lib DLL'lerini sec."""
    names = zf.namelist()
    for tfm in TFM_ORDER:
        for prefix in ("runtimes/win-x64/lib/%s/" % tfm, "lib/%s/" % tfm):
            hits = [n for n in names
                    if n.lower().startswith(prefix) and n.lower().endswith(".dll")]
            if hits:
                return hits
    return []


def dependencies(nuspec_bytes):
    root = ET.fromstring(nuspec_bytes)
    ns = {"n": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    def find(path):
        return root.findall(path if not ns else path.replace("/", "/n:")
                            .replace("metadata", "n:metadata"), ns)
    deps_node = None
    for md in root.iter():
        if md.tag.endswith("dependencies"):
            deps_node = md
            break
    if deps_node is None:
        return []

    groups = [g for g in deps_node if g.tag.endswith("group")]
    chosen = None
    if groups:
        for want in GROUP_ORDER:
            for g in groups:
                tf = (g.get("targetFramework") or "").lower()
                if tf == want or (want and tf.startswith(want)):
                    chosen = g
                    break
            if chosen is not None:
                break
        if chosen is None:
            chosen = groups[0]
        items = [d for d in chosen if d.tag.endswith("dependency")]
    else:
        items = [d for d in deps_node if d.tag.endswith("dependency")]

    out = []
    for d in items:
        pid = (d.get("id") or "").lower()
        ver = (d.get("version") or "").strip("[]()").split(",")[0]
        if pid and pid not in SKIP:
            out.append((pid, ver))
    return out


def main():
    os.makedirs(LIB, exist_ok=True)
    todo = [ROOT]
    seen = set()
    written = []

    while todo:
        pkg, ver = todo.pop(0)
        if pkg in seen:
            continue
        seen.add(pkg)
        if not ver:
            ver = latest_version(pkg)
        url = "%s/%s/%s/%s.%s.nupkg" % (FLAT, pkg, ver, pkg, ver)
        try:
            blob = fetch(url)
        except Exception as exc:
            print("  ! %s %s indirilemedi: %s" % (pkg, ver, exc))
            continue

        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for entry in pick_lib_entries(zf):
                name = os.path.basename(entry)
                target = os.path.join(LIB, name)
                with zf.open(entry) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                written.append(name)
            nuspecs = [n for n in zf.namelist() if n.lower().endswith(".nuspec")]
            deps = dependencies(zf.read(nuspecs[0])) if nuspecs else []

        print("%-38s %-10s -> %d dll" % (pkg, ver, len(pick_lib_entries(
            zipfile.ZipFile(io.BytesIO(blob))))))
        for dep in deps:
            if dep[0] not in seen:
                todo.append(dep)

    print("\nlib/ icine yazilan %d dosya:" % len(written))
    for n in sorted(set(written)):
        print("  " + n)


if __name__ == "__main__":
    main()
