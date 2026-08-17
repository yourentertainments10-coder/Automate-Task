"""Load industry task templates from structured JSON or CSV.

    python manage.py load_directory                      # bundled starter pack
    python manage.py load_directory mypack.json
    python manage.py load_directory mypack.csv
    python manage.py load_directory pack.json --replace  # wipe first

JSON shape:
[
  {"industry": "E-commerce", "icon": "🛒", "description": "...",
   "templates": [
     {"category": "Orders", "name": "Daily order processing",
      "description": "...", "priority": "high", "frequency": "daily",
      "tags": ["ops"],
      "steps": [{"title": "...", "description": "...", "offset_days": 0}]}
   ]}
]

CSV columns: industry, icon, category, template, description, priority,
frequency, tags (|-separated), step_title, step_description, offset_days
-- one row per STEP; rows are grouped into templates automatically.
"""
import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from directory.models import DirectoryTemplate, Industry

DEFAULT_SEED = Path(__file__).resolve().parent.parent.parent / "seeds" / "starter_pack.json"
VALID_PRIORITY = {"low", "normal", "high", "urgent"}
VALID_FREQUENCY = {"one_time", "daily", "weekly", "monthly"}


class Command(BaseCommand):
    help = "Load/refresh the industry template directory from JSON or CSV (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default=str(DEFAULT_SEED))
        parser.add_argument("--replace", action="store_true",
                            help="Delete existing directory content first.")

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        data = self._read_csv(path) if path.suffix.lower() == ".csv" else self._read_json(path)

        if opts["replace"]:
            DirectoryTemplate.objects.all().delete()
            Industry.objects.all().delete()
            self.stdout.write(self.style.WARNING("Existing directory content removed."))

        industries = templates = skipped = 0
        for order, block in enumerate(data):
            name = str(block.get("industry", "")).strip()
            if not name:
                skipped += 1
                continue
            industry, made = Industry.objects.update_or_create(
                slug=slugify(name)[:80],
                defaults={"name": name, "icon": block.get("icon", "")[:8],
                          "description": str(block.get("description", ""))[:300],
                          "order": order, "active": True},
            )
            industries += 1 if made else 0
            for tpl in block.get("templates", []):
                tname = str(tpl.get("name", "")).strip()
                steps = [s for s in tpl.get("steps", []) if str(s.get("title", "")).strip()]
                if not tname or not steps:
                    skipped += 1
                    continue
                priority = tpl.get("priority", "normal")
                frequency = tpl.get("frequency", "one_time")
                DirectoryTemplate.objects.update_or_create(
                    industry=industry, name=tname[:160],
                    defaults={
                        "category": str(tpl.get("category", "General"))[:80],
                        "description": str(tpl.get("description", "")),
                        "priority": priority if priority in VALID_PRIORITY else "normal",
                        "frequency": frequency if frequency in VALID_FREQUENCY else "one_time",
                        "tags": [str(t)[:40] for t in (tpl.get("tags") or [])][:10],
                        "steps": [{
                            "title": str(s["title"])[:200],
                            "description": str(s.get("description", ""))[:1000],
                            "offset_days": int(s.get("offset_days") or 0),
                        } for s in steps][:50],
                        "active": True,
                    },
                )
                templates += 1

        self.stdout.write(self.style.SUCCESS(
            f"Directory loaded: {Industry.objects.count()} industries "
            f"({industries} new), {templates} templates upserted"
            + (f", {skipped} row(s) skipped as invalid" if skipped else "")))

    # ---- readers ---------------------------------------------------------
    def _read_json(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON: {exc}")
        if not isinstance(data, list):
            raise CommandError("JSON root must be a list of industry blocks.")
        return data

    def _read_csv(self, path):
        blocks, index = [], {}
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                ind = (row.get("industry") or "").strip()
                tpl = (row.get("template") or "").strip()
                step = (row.get("step_title") or "").strip()
                if not ind or not tpl or not step:
                    continue
                if ind not in index:
                    index[ind] = {"industry": ind, "icon": (row.get("icon") or "").strip(),
                                  "templates": {}}
                    blocks.append(index[ind])
                tpls = index[ind]["templates"]
                if tpl not in tpls:
                    tpls[tpl] = {
                        "name": tpl, "category": (row.get("category") or "General").strip(),
                        "description": (row.get("description") or "").strip(),
                        "priority": (row.get("priority") or "normal").strip(),
                        "frequency": (row.get("frequency") or "one_time").strip(),
                        "tags": [t for t in (row.get("tags") or "").split("|") if t.strip()],
                        "steps": [],
                    }
                tpls[tpl]["steps"].append({
                    "title": step,
                    "description": (row.get("step_description") or "").strip(),
                    "offset_days": int(row.get("offset_days") or 0),
                })
        for block in blocks:
            block["templates"] = list(block["templates"].values())
        return blocks
