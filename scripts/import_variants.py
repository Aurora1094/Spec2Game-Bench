"""Import the supplied specifications; final DOCX text is authoritative.

Run explicitly with --archive. This is a build-time data conversion tool, never
part of generation/evaluation. The archive and intermediate reports stay outside
the repository. Checkpoint edits are maintained in variant_rules.py.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import difflib
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import yaml

from checkpoint_corrections import correction_metadata, load_corrections
from variant_rules import apply_rule

ROOT = Path(__file__).resolve().parents[1]
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def docx_text(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as doc:
        body = ET.fromstring(doc.read("word/document.xml")).find(W + "body")
    def paragraph(node):
        return "".join(n.text or "" if n.tag == W + "t" else "\t" if n.tag == W + "tab" else "\n" if n.tag in {W + "br", W + "cr"} else "" for n in node.iter())
    blocks = []
    for node in body:
        if node.tag == W + "p":
            blocks.append(paragraph(node))
        elif node.tag == W + "tbl":
            rows = [["<br>".join(paragraph(p) for p in c.findall(W + "p")) for c in r.findall(W + "tc")] for r in node.findall(W + "tr")]
            for i, row in enumerate(rows):
                blocks.append("| " + " | ".join(row) + " |")
                if i == 0:
                    blocks.append("| " + " | ".join("---" for _ in row) + " |")
    return "\n".join(blocks).strip() + "\n"


def frontmatter(path: Path):
    parts = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(parts[1]), parts[2].lstrip()


def blocks(text: str):
    """Keep exact source paragraphs, including fenced maps, in a change ledger."""
    return [x for x in text.splitlines() if x.strip()]


def canonical_findings():
    """Verify and record the resolved terminal-priority corrections."""
    corrections = load_corrections()
    findings = []
    for correction in corrections["corrections"]:
        if correction["kind"] != "terminal_priority":
            continue
        checkpoint_id = correction["checkpoint_id"]
        family = checkpoint_id.split(".D2.", 1)[0]
        rows = [
            json.loads(line)
            for line in (ROOT / f"benchmark/games/{family}/checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        checkpoint = next(row for row in rows if row["id"] == checkpoint_id)
        stale_fields = [
            field
            for field, expected in correction["after"].items()
            if checkpoint.get(field) != expected
        ]
        if stale_fields:
            raise ValueError(f"{checkpoint_id}: corrected fields are stale: {', '.join(stale_fields)}")
        findings.append({
            "checkpoint_id": checkpoint_id,
            "previous_assertion": correction["before"]["expected_transition"],
            "current_assertion": checkpoint["expected_transition"],
            "specification_rule": correction["after"]["expected_transition"],
            "source_spec": correction["source_spec"],
            "source_section": correction["source_section"],
            "correction_revision": corrections["revision"],
            "disposition": "corrected to the final specification",
        })
    return findings


def import_specs(archive: Path, report: Path | None = None):
    catalog = yaml.safe_load((ROOT / "benchmark/catalog.yaml").read_text(encoding="utf-8"))
    corrections = load_corrections()
    audit = {
        "source_archive_sha256": digest(archive.read_bytes()),
        "authority": "final_docx",
        "checkpoint_corrections": correction_metadata(),
        "variant_exceptions": corrections["variant_exceptions"],
        "instances": [],
        "canonical_review_findings": canonical_findings(),
    }
    with zipfile.ZipFile(archive) as z:
        audit["difference_spreadsheets"] = [
            {"source_path": name, "sha256": digest(z.read(name)), "role": "draft differences; final DOCX controls gameplay"}
            for name in z.namelist() if name.lower().endswith(".xlsx")
        ]
        docs = [n for n in z.namelist() if n.lower().endswith(".docx")]
        if len(docs) != 150:
            raise ValueError(f"Expected 150 specifications, found {len(docs)}")
        for number, family in enumerate(catalog["games"], 1):
            slug = family["slug"]
            names = [n for n in docs if n.split("/")[-2].startswith(f"{number}_")]
            if len(names) != 10:
                raise ValueError(f"{slug}: expected ten source documents")
            base_name = next(n for n in names if not re.search(r"_V\d+\.docx$", n, re.I))
            base_doc = docx_text(z.read(base_name))
            meta, base_body = frontmatter(ROOT / family["path"].replace("games/", "benchmark/games/") / "spec.md")
            if re.sub(r"\s+", "", base_doc) != re.sub(r"\s+", "", base_body):
                raise ValueError(f"{slug}: canonical DOCX differs from checked-in specification")
            for source_version in range(2, 11):
                name = next(n for n in names if re.search(fr"_V{source_version}\.docx$", n, re.I))
                raw = z.read(name)
                text = docx_text(raw)
                corrections = []
                if slug == "maze_runner" and source_version in {2, 3, 7}:
                    pattern = r"(?m)^#{15}\r?\n(?:[^\n]*\n){13}#{15}$"
                    canonical_map = re.search(pattern, base_doc).group()
                    text, count = re.subn(pattern, lambda _: canonical_map, text)
                    if count != 1:
                        raise ValueError(f"{name}: cannot locate fixed map")
                    corrections.append("Restored unchanged canonical maze spacing; this variant changes no map cells.")
                if slug == "mini_zelda" and source_version == 10:
                    text = text.replace("# 3.8 Game State", "## 3.8 Game State")
                    corrections.append("Corrected the Game State subsection heading level.")
                if slug == "tetris" and source_version == 6:
                    corrections.append("Final DOCX removes the Next preview; draft spreadsheet bullet design is superseded.")
                if slug in {"pipe_connection", "mini_zelda"}:
                    corrections.append("Final DOCX takes precedence over spreadsheet draft differences.")
                if slug == "whack_a_mole":
                    corrections.append("Mapped the Whack-a-Hole source folder to whack_a_mole.")
                variant_id = f"var{source_version - 1:02d}"
                instance_id = f"{slug}_{variant_id}"
                target = ROOT / "benchmark/games" / instance_id
                target.mkdir(parents=True, exist_ok=True)
                instance_meta = json.loads(json.dumps(meta).replace(slug + ".D2.", instance_id + ".D2."))
                instance_meta.update(family_slug=slug, variant_id=variant_id, instance_id=instance_id)
                (target / "spec.md").write_text("---\n" + json.dumps(instance_meta, ensure_ascii=False, indent=2) + "\n---\n\n" + text, encoding="utf-8")
                changes = []
                old, new = blocks(base_doc), blocks(text)
                for tag, i, j, k, end in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
                    if tag != "equal":
                        changes.append({"id": f"change{len(changes)+1:02d}", "before": old[i:j], "after": new[k:end]})
                record = {"instance_id": instance_id, "family_slug": slug, "variant_id": variant_id,
                          "source_path": name, "source_docx_sha256": digest(raw), "spec_sha256": digest((target / "spec.md").read_bytes()),
                          "corrections": corrections, "changes": changes}
                audit["instances"].append(record)
    write_json(ROOT / "benchmark/variant_source_audit.json", audit)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        write_json(report, audit)
    return catalog, audit


def rebuild_existing():
    """Re-materialize variants from checked-in specs, audit records, and rules."""
    catalog_path = ROOT / "benchmark/catalog.yaml"
    audit_path = ROOT / "benchmark/variant_source_audit.json"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if len(audit.get("instances", [])) != 135:
        raise ValueError("existing source audit must contain all 135 variant instances")

    corrections = load_corrections()
    audit.update(
        authority="final_docx",
        checkpoint_corrections=correction_metadata(),
        variant_exceptions=corrections["variant_exceptions"],
        canonical_review_findings=canonical_findings(),
    )
    write_json(audit_path, audit)
    materialize(catalog, audit)
    return catalog, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path)
    source.add_argument("--rebuild-existing", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.archive:
        catalog, audit = import_specs(args.archive, args.report)
        materialize(catalog, audit)
        status = "specifications_imported"
    else:
        if args.report:
            raise ValueError("--report is only valid with --archive")
        catalog, audit = rebuild_existing()
        status = "specifications_rebuilt"
    print(json.dumps({status: len(audit["instances"]), "full_checkpoint_count": catalog["full_checkpoint_count"]}))


def materialize(catalog, audit):
    """Emit complete, immutable runtime datasets from the maintained rule edits."""
    human_path = ROOT / "benchmark/human_review.json"
    human = json.loads(human_path.read_text(encoding="utf-8"))
    full_counts = Counter(catalog["dimensions"])
    entries = []
    for family in catalog["games"]:
        slug = family["slug"]
        source = ROOT / "benchmark" / family["path"]
        base_path = source / "checkpoints.jsonl"
        base_rows = [json.loads(line) for line in base_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        base_meta = yaml.safe_load((source / "game.yaml").read_text(encoding="utf-8"))
        family.update(family_slug=slug, variant_id="base", variants=[f"{slug}_var{n:02d}" for n in range(1, 10)])
        base_meta.update(family_slug=slug, variant_id="base", variants=family["variants"])
        write_json(source / "game.yaml", base_meta)
        for n, instance_id in enumerate(family["variants"], 1):
            record = next(row for row in audit["instances"] if row["instance_id"] == instance_id)
            target = ROOT / "benchmark/games" / instance_id
            rows, changed, types = apply_rule(base_rows, slug, n)
            if not changed:
                raise ValueError(f"{instance_id}: no assertion tests the changed requirements")
            for order, row in enumerate(rows, 1):
                row.update(id=row["id"].replace(slug + ".", instance_id + ".", 1), game_slug=instance_id,
                           family_slug=slug, variant_id=f"var{n:02d}", source_order=order)
            counts = Counter(row["dimension"] for row in rows)
            full_counts.update(counts)
            checkpoint_path = target / "checkpoints.jsonl"
            checkpoint_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
            entry = {**deepcopy(family), "slug": instance_id, "variant_id": f"var{n:02d}",
                     "path": f"games/{instance_id}", "variants": [], "checkpoint_count": len(rows),
                     "dimension_counts": dict(counts), "variation_types": types}
            entries.append(entry)
            write_json(target / "game.yaml", {**deepcopy(base_meta), "slug": instance_id,
                       "variant_id": entry["variant_id"], "variants": [], "variation_types": types,
                       "source_audit": {"docx_sha256": record["source_docx_sha256"],
                           "base_checkpoints_sha256": digest(base_path.read_bytes()), "checkpoint_count": len(rows)}})
            changed_ids = [cp.replace(slug + ".", instance_id + ".", 1) for cp in changed]
            write_json(target / "variation.json", {
                "instance_id": instance_id, "family_slug": slug, "variant_id": entry["variant_id"],
                "variation_types": types, "source_path": record["source_path"],
                "corrections": record["corrections"], "source_changes": record["changes"],
                "changed_checkpoint_ids": changed_ids,
                "added_checkpoint_ids": [row["id"] for row in rows if row["base_checkpoint_id"] is None],
                "base_checkpoints_sha256": digest(base_path.read_bytes()),
                "checkpoints_sha256": digest(checkpoint_path.read_bytes()),
            })
            human["games"][instance_id] = json.loads(json.dumps(human["games"][slug]).replace(slug + ".D2.", instance_id + ".D2."))
    catalog.update(variant_instances=entries, instance_count=150,
                   full_checkpoint_count=sum(full_counts.values()), full_dimensions=dict(full_counts))
    write_json(ROOT / "benchmark/catalog.yaml", catalog)
    write_json(human_path, human)


if __name__ == "__main__":
    main()
