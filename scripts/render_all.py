#!/usr/bin/env python3
"""Render every service file of this repository exactly as Argo CD will, and validate it.

For each workloads/<env>/<app>/<service>.yaml (not _env.yaml):
  1. read chart.path and chart.revision from the file;
  2. fetch that chart at that git tag from the charts repository;
  3. helm template with the same layering as the workloads ApplicationSet:
       values/<service>.yaml (chart)  <  _env.yaml  <  <service>.yaml  <  activeApp=<service>
     -- the chart's values.schema.json validates every layer;
  4. kubeconform -strict on the result.

For each infra/<cluster>/<component>.yaml the chart repo/name/version come from the infra
ApplicationSet of the root repository (path given as an argument).

Usage: render_all.py <values-repo-dir> <root-repo-dir>
Requires: helm, git, kubeconform, PyYAML.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

# Overridable for local runs against an unpushed tag: CHARTS_REPO=/path/to/clone render_all.py ...
CHARTS_REPO = os.environ.get("CHARTS_REPO", "https://github.com/ailves2009/poc-aws-eks-karpenter.git")


def run(*cmd: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def validate(name: str, rendered: str) -> bool:
    check = run("kubeconform", "-strict", "-summary", "-", input=rendered)
    ok = check.returncode == 0
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {check.stdout.strip() or check.stderr.strip()}")
    return ok


def checkout(revision: str, cache: dict, workdir: Path) -> Path:
    if revision not in cache:
        target = workdir / revision
        clone = run("git", "clone", "--quiet", "--depth", "1", "--branch", revision, CHARTS_REPO, str(target))
        if clone.returncode != 0:
            raise SystemExit(f"cannot fetch {CHARTS_REPO} at {revision}: {clone.stderr.strip()}")
        cache[revision] = target
    return cache[revision]


def workloads(values: Path, workdir: Path) -> bool:
    ok, cache = True, {}
    for service_file in sorted(values.glob("workloads/*/*/*.yaml")):
        if service_file.name == "_env.yaml":
            continue
        service = service_file.stem
        name = str(service_file.relative_to(values))
        chart_ref = (yaml.safe_load(service_file.read_text()) or {}).get("chart") or {}
        if not chart_ref.get("path") or not chart_ref.get("revision"):
            print(f"FAIL {name}: chart.path and chart.revision are required")
            ok = False
            continue
        chart = checkout(chart_ref["revision"], cache, workdir) / chart_ref["path"]
        build = run("helm", "dependency", "build", str(chart))
        if build.returncode != 0:
            print(f"FAIL {name}: helm dependency build: {build.stderr.strip()}")
            ok = False
            continue
        render = run("helm", "template", service, str(chart),
                     "--namespace", f"{service_file.parent.name}-{service_file.parent.parent.name}",
                     "--set", f"activeApp={service}",
                     "-f", str(chart / "values" / f"{service}.yaml"),
                     "-f", str(service_file.parent / "_env.yaml"),
                     "-f", str(service_file))
        if render.returncode != 0:
            print(f"FAIL {name}: {render.stderr.strip()}")
            ok = False
            continue
        ok &= validate(name, render.stdout)
    return ok


def infra(values: Path, root: Path) -> bool:
    ok = True
    for appset_file in sorted(root.glob("clusters/*/*.yaml")):
        doc = yaml.safe_load(appset_file.read_text())
        if doc.get("kind") != "ApplicationSet":
            continue
        cluster = appset_file.parent.name
        for generator in doc["spec"]["generators"]:
            for element in (generator.get("list") or {}).get("elements", []):
                values_file = values / "infra" / cluster / f"{element['name']}.yaml"
                name = str(values_file.relative_to(values))
                render = run("helm", "template", element.get("releaseName", element["name"]), element["chart"],
                             "--repo", element["repoURL"], "--version", str(element["version"]),
                             "--namespace", element["namespace"], "-f", str(values_file))
                if render.returncode != 0:
                    print(f"FAIL {name}: {render.stderr.strip()}")
                    ok = False
                    continue
                ok &= validate(name, render.stdout)
    return ok


def main(values: Path, root: Path) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ok = workloads(values, Path(tmp))
    ok &= infra(values, root)
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
