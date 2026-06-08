#!/usr/bin/env python3
"""Live skill inventory for the Erich front-door skill."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_CODEX_SKILLS = Path("/Users/erichroepke/.codex/skills")
DEFAULT_ESTACK_MANIFEST = Path(
    "/Volumes/MASTER 140 TB 1/2026/05-2026 SKILLS/E-STACK/codex-skills/manifests/e-stack-skills.json"
)


@dataclass
class Skill:
    name: str
    path: str
    description: str
    installed: bool = True
    in_estack_manifest: bool = False


def parse_frontmatter(text: str) -> Dict[str, str]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data: Dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        data[key.strip()] = value
    return data


def read_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter = parse_frontmatter(text)
    name = frontmatter.get("name") or path.parent.name
    description = frontmatter.get("description", "")
    if description in ("|", ">"):
        description = first_nonempty_body_line(text)
    return Skill(name=name, path=str(path.parent), description=description)


def first_nonempty_body_line(text: str) -> str:
    body = text.split("---", 2)[-1] if text.startswith("---") else text
    for line in body.splitlines():
        stripped = re.sub(r"^[#\\s-]+", "", line).strip()
        if stripped:
            return stripped[:200]
    return ""


def load_estack_manifest(path: Path) -> List[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(data.get("skills", []))


def build_inventory(codex_root: Path, estack_manifest: Path) -> Dict[str, object]:
    skills: List[Skill] = []
    for skill_md in sorted(codex_root.glob("*/SKILL.md")):
        try:
            skills.append(read_skill(skill_md))
        except OSError:
            continue

    manifest_names = set(load_estack_manifest(estack_manifest))
    installed_names = {skill.name for skill in skills}

    for skill in skills:
        skill.in_estack_manifest = skill.name in manifest_names or Path(skill.path).name in manifest_names

    missing_from_manifest = sorted(manifest_names - installed_names - {Path(skill.path).name for skill in skills})
    extras = sorted(
        skill.name for skill in skills
        if skill.name not in manifest_names and Path(skill.path).name not in manifest_names
    )

    return {
        "codex_root": str(codex_root),
        "estack_manifest": str(estack_manifest),
        "installed_count": len(skills),
        "estack_manifest_count": len(manifest_names),
        "missing_from_estack_manifest": missing_from_manifest,
        "extra_installed": extras,
        "skills": [asdict(skill) for skill in skills],
    }


def write_markdown(path: Path, inventory: Dict[str, object]) -> None:
    lines = ["# Erich Skill Inventory", ""]
    lines.append(f"- Codex skill root: `{inventory['codex_root']}`")
    lines.append(f"- Installed skills: `{inventory['installed_count']}`")
    lines.append(f"- E-STACK manifest skills: `{inventory['estack_manifest_count']}`")
    lines.append("")
    lines.append("## Missing From E-STACK Manifest")
    lines.append("")
    missing = inventory["missing_from_estack_manifest"]
    if missing:
        for name in missing:
            lines.append(f"- `{name}`")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Extra Installed")
    lines.append("")
    extras = inventory["extra_installed"]
    if extras:
        for name in extras:
            lines.append(f"- `{name}`")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Skills")
    lines.append("")
    for skill in inventory["skills"]:
        marker = "E-STACK" if skill["in_estack_manifest"] else "extra"
        lines.append(f"- `{skill['name']}` ({marker}) — {skill['description']} [{skill['path']}]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inventory installed Codex skills for routing.")
    parser.add_argument("--codex-root", default=str(DEFAULT_CODEX_SKILLS))
    parser.add_argument("--estack-manifest", default=str(DEFAULT_ESTACK_MANIFEST))
    parser.add_argument("--out", default="/tmp/erich-skill-inventory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory(Path(args.codex_root), Path(args.estack_manifest))
    json_path = out / "skills.json"
    md_path = out / "skills.md"
    json_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    write_markdown(md_path, inventory)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
