#!/usr/bin/env python3
"""Sync Git-backed Codex skills into Erich's runtime skill mirrors."""

from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILLS = ROOT / "skills"

RUNTIME_SKILLS = Path("/Users/erichroepke/.codex/skills")
ESTACK_SKILLS = Path(
    "/Volumes/MASTER 140 TB 1/2026/05-2026 SKILLS/E-STACK/codex-skills/skills"
)
ESTACK_RUNTIME_MIRROR = Path(
    "/Volumes/MASTER 140 TB 1/2026/05-2026 SKILLS/E-STACK/codex-skills/runtime-mirror/skills"
)
STANDALONE_ERICH = Path("/Volumes/MASTER 140 TB 1/2026/05-2026 SKILLS/ERICH")


SKILL_DESTINATIONS = (RUNTIME_SKILLS, ESTACK_SKILLS, ESTACK_RUNTIME_MIRROR)


def copy_tree(src: Path, dest: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"DRY-RUN copy {src} -> {dest}")
        return
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def copy_contents(src: Path, dest: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"DRY-RUN mirror contents {src} -> {dest}")
        return
    dest.mkdir(parents=True, exist_ok=True)
    for child in dest.iterdir():
        if child.name == ".DS_Store":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in src.iterdir():
        if child.name == ".DS_Store":
            continue
        target = dest / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def dircmp_equal(left: Path, right: Path) -> bool:
    if not left.exists() or not right.exists():
        return False
    cmp = filecmp.dircmp(left, right, ignore=[".DS_Store", "__pycache__"])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    return all(dircmp_equal(left / name, right / name) for name in cmp.common_dirs)


def sync(dry_run: bool) -> int:
    if not SOURCE_SKILLS.exists():
        raise SystemExit(f"Missing source skills directory: {SOURCE_SKILLS}")

    skills = sorted(path for path in SOURCE_SKILLS.iterdir() if (path / "SKILL.md").exists())
    if not skills:
        raise SystemExit(f"No skills found in {SOURCE_SKILLS}")

    for skill in skills:
        for dest_root in SKILL_DESTINATIONS:
            copy_tree(skill, dest_root / skill.name, dry_run)

    erich_src = SOURCE_SKILLS / "erich"
    if erich_src.exists():
        copy_contents(erich_src, STANDALONE_ERICH, dry_run)

    print("Synced skills:", ", ".join(skill.name for skill in skills))
    return 0


def check() -> int:
    missing = []
    for skill in sorted(path for path in SOURCE_SKILLS.iterdir() if (path / "SKILL.md").exists()):
        for dest_root in SKILL_DESTINATIONS:
            target = dest_root / skill.name
            if not dircmp_equal(skill, target):
                missing.append(f"{skill.name}: {target}")

    erich_src = SOURCE_SKILLS / "erich"
    if erich_src.exists() and not dircmp_equal(erich_src, STANDALONE_ERICH):
        missing.append(f"erich standalone: {STANDALONE_ERICH}")

    if missing:
        print("Out of sync:")
        for item in missing:
            print(f"- {item}")
        return 1

    print("All configured skill mirrors are in sync.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="show planned copies without writing")
    parser.add_argument("--check", action="store_true", help="verify mirrors without writing")
    args = parser.parse_args()

    if args.check:
        return check()
    return sync(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
