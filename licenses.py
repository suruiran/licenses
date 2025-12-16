import json
import os
import subprocess
import typing


def parse_pkgs_go_mod(
    fp: str, ignores: list[str] | None = None
) -> list[tuple[str, str, str]]:
    pkgs = []

    def append_pkg(line: str):
        indirect = line.endswith("// indirect")

        parts = [x for x in line.split(" ") if x]
        if len(parts) < 2:
            return

        pkg = parts[0]
        if ignores and pkg in ignores:
            return

        pkgs.append((pkg, parts[1], "indirect" if indirect else "direct"))

    in_require = False

    with open(fp, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("//"):
                continue

            if not in_require:
                if line.startswith("require"):
                    in_require = True
                continue

            if line == ")":
                in_require = False
                continue

            append_pkg(line)

    return pkgs


def _go_lower_case(txt: str) -> str:
    tmp: list[str] = []
    for c in txt:
        if c.isupper():
            tmp.append("!")
            tmp.append(c.lower())
        else:
            tmp.append(c)
    return "".join(tmp)


result = subprocess.run(
    "go env GOMODCACHE",
    shell=True,
    check=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
gomodcache = result.stdout.decode().strip()
if not gomodcache:
    os._exit(1)
if not os.path.isdir(gomodcache):
    os._exit(1)


def find_go_pkg_license_via_fs(pkg: str, ver: str) -> str | None:
    fspath = gomodcache
    parts = pkg.split("/")

    for part in parts:
        fspath = f"{fspath}/{_go_lower_case(part)}"

    license = f"{fspath}@{ver}/LICENSE"
    if os.path.isfile(license):
        return license

    for ext in [".txt", ".md"]:
        license = f"{fspath}@{ver}/LICENSE{ext}"
        if os.path.isfile(license):
            return license
    return None


def fetch_go_pkg_license_via_network(pkg: str, ver: str) -> str | None:
    raise NotImplementedError


def parse_npm_package_json(
    fp: str, ignores: list[str] | None = None
) -> list[tuple[str, str]]:
    with open(fp, "r") as f:
        info = json.load(f)
        deps = info.get("dependencies", [])
        dev_deps = info.get("devDependencies", [])

        pkgs = []
        for name in deps.keys():
            if ignores and name in ignores:
                continue
            pkgs.append((name, "deps"))

        for name in dev_deps.keys():
            if ignores and name in ignores:
                continue
            pkgs.append((name, "dev-deps"))

        return pkgs


def find_npm_pkg_license_via_fs(pkgjsonfp: str, pkg: str) -> str | None:
    root = os.path.dirname(pkgjsonfp)

    license = f"{root}/node_modules/{pkg}/LICENSE"
    if os.path.isfile(license):
        return license

    for ext in [".txt", ".md"]:
        license = f"{root}/node_modules/{pkg}/LICENSE{ext}"
        if os.path.isfile(license):
            return license

    pkgjson = f"{root}/node_modules/{pkg}/package.json"
    if os.path.isfile(pkgjson):
        with open(pkgjson, "r") as f:
            info = json.load(f)
            license = info.get("license")
            if license:
                if license.lower() == "mit":
                    return os.path.join(os.path.dirname(__file__), "mit.license")
                elif license.lower() == "apache-2.0":
                    return os.path.join(os.path.dirname(__file__), "apache.2.0.license")

                print(f"license name: {license}")
                return license
    return None


def find_npm_pkg_license_via_network(pkg: str) -> str | None:
    raise NotImplementedError


LINCESE_SEQ = 1
ALL_LICENSES = {}


def read_license(fp: str) -> int:
    content = ""
    if os.path.isfile(fp):
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read().strip()
    else:
        content = fp

    lid = ALL_LICENSES.get(content)
    if not lid:
        global LINCESE_SEQ
        LINCESE_SEQ += 1
        ALL_LICENSES[content] = LINCESE_SEQ
        lid = LINCESE_SEQ

    return lid


def main(
    files: list[str],
    output: typing.Optional[str] = None,
    ignore_go_pkgs: list[str] | None = None,
    ignore_npm_pkgs: list[str] | None = None,
):
    go_pkgs = []
    npm_pkgs = []

    for fp in files:
        if not os.path.isfile(fp):
            print(f"file not found: {fp}")
            continue

        if fp.endswith("go.mod"):
            for pkg, ver, tag in parse_pkgs_go_mod(fp, ignores=ignore_go_pkgs):
                lic = find_go_pkg_license_via_fs(pkg, ver)
                if not lic:
                    lic = fetch_go_pkg_license_via_network(pkg, ver)
                    if not lic:
                        print(f"go pkg license not found: {pkg}@{ver}")
                        continue

                go_pkgs.append((pkg, read_license(lic), tag))

        elif fp.endswith("package.json"):
            for pkg, tag in parse_npm_package_json(fp, ignores=ignore_npm_pkgs):
                lic = find_npm_pkg_license_via_fs(fp, pkg)
                if not lic:
                    lic = find_npm_pkg_license_via_network(pkg)
                    if not lic:
                        print(f"npm pkg license not found: {pkg}")
                        continue

                npm_pkgs.append((pkg, read_license(lic), tag))

    lics = {}

    for lic, lic_id in ALL_LICENSES.items():
        lics[lic_id] = lic

    if not output:
        output = "./licenses"

    os.makedirs(output, exist_ok=True)

    with open(f"{output}/licenses.json", "w", encoding="utf-8") as f:
        json.dump(lics, f, ensure_ascii=False, indent=2)

    pidx = 1
    with open(f"{output}/opensource.deps.html", "w", encoding="utf-8") as f:
        f.write("<h2>Go Modules</h2>\n")
        f.write("<ul>\n")
        for pkg, lic_id, tag in go_pkgs:
            f.write(
                f'''<li data-lic="{lic_id}" data-tag="{tag}" data-kind="go">
    <span>{pkg}</span>
    <span class="btn">show license</span>
    <span class="btn">web page</span>
</li>
'''
            )
            pidx += 1
        f.write("</ul>\n")

        f.write("<h2>NPM Modules</h2>\n")
        f.write("<ul>\n")
        for pkg, lic_id, tag in npm_pkgs:
            f.write(
                f'''<li data-lic="{lic_id}" data-tag="{tag}" data-kind="npm">
    <span>{pkg}</span>
    <span class="btn">show license</span>
    <span class="btn">web page</span>
</li>
'''
            )
            pidx += 1
        f.write("</ul>\n")


if __name__ == "__main__":
    import typer

    typer.run(main)
