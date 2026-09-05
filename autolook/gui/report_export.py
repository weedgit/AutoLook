"""Export incident reports to CSV and HTML."""

import base64
import csv
import html
import shutil
from pathlib import Path


COLUMNS = [
    "id", "timestamp", "end_timestamp", "name", "host", "user", "source",
    "detection_type", "alert_level", "confidence", "description",
    "url", "app_name", "screenshot_path", "thumbnail_path",
]


def _with_names(incidents: list[dict], host_aliases: dict[str, str] | None = None) -> list[dict]:
    from autolook.utils.host_names import resolve_display_name
    aliases = host_aliases or {}
    result = []
    for inc in incidents:
        row = dict(inc)
        row["name"] = resolve_display_name(inc.get("host", "") or "", aliases)
        result.append(row)
    return result


def export_csv(incidents: list[dict], output_path: str | Path, host_aliases: dict[str, str] | None = None):
    """Export incidents to CSV file (includes image paths)."""
    rows = _with_names(incidents, host_aliases)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for inc in rows:
            writer.writerow(inc)


def _image_data_uri(path: str | None, max_width: int = 480) -> str | None:
    """Build a small JPEG data-URI for HTML embed, or None."""
    if not path:
        return None
    src = Path(path)
    if not src.exists() or not src.is_file():
        return None
    try:
        from PIL import Image
        import io

        img = Image.open(src)
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, max(1, int(img.height * ratio))), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        try:
            raw = src.read_bytes()
            if len(raw) > 400_000:
                return None
            mime = "image/jpeg"
            suf = src.suffix.lower()
            if suf == ".png":
                mime = "image/png"
            elif suf == ".webp":
                mime = "image/webp"
            b64 = base64.b64encode(raw).decode("ascii")
            return f"data:{mime};base64,{b64}"
        except Exception:
            return None


def export_html(incidents: list[dict], output_path: str | Path, host_aliases: dict[str, str] | None = None):
    """Export incidents to HTML report with embedded screen thumbnails."""
    from autolook.detection.alert_scorer import kind_label

    output_path = Path(output_path)
    incidents = _with_names(incidents, host_aliases)
    kind_colors = {
        "nsfw": "#d32f2f",
        "korea": "#1565c0",
        "nsfw+korea": "#8e24aa",
    }

    # Also copy full-size screens next to the HTML for offline viewing
    images_dir = output_path.with_name(output_path.stem + "_images")
    if any((inc.get("screenshot_path") or inc.get("thumbnail_path")) for inc in incidents):
        images_dir.mkdir(parents=True, exist_ok=True)

    rows_html = []
    for inc in incidents:
        kind = (inc.get("alert_level") or "").lower()
        color = kind_colors.get(kind, "#757575")
        cols = []
        for c in COLUMNS:
            val = html.escape(str(inc.get(c, "") or ""))
            if c == "alert_level":
                label = html.escape(kind_label(kind))
                val = (
                    f'<span style="background:{color};color:#fff;'
                    f'padding:2px 6px;border-radius:3px">{label}</span>'
                )
            cols.append(f"<td>{val}</td>")

        # Screen preview column
        screen = inc.get("screenshot_path") or ""
        thumb = inc.get("thumbnail_path") or ""
        preview_src = thumb or screen
        img_html = ""
        data_uri = _image_data_uri(preview_src)
        file_link = ""
        if screen and Path(screen).exists():
            try:
                dest = images_dir / f"inc_{inc.get('id', 'x')}_{Path(screen).name}"
                if not dest.exists():
                    shutil.copy2(screen, dest)
                rel = dest.name
                file_link = (
                    f'<div><a href="{html.escape(images_dir.name + "/" + rel)}" '
                    f'target="_blank">Open full screen</a></div>'
                )
            except Exception:
                file_link = ""
        if data_uri:
            img_html = (
                f'<img src="{data_uri}" alt="screen" '
                f'style="max-width:240px;max-height:140px;border:1px solid #ccc;" />'
                f"{file_link}"
            )
        elif file_link:
            img_html = file_link
        else:
            img_html = "<span style='color:#999'>—</span>"
        cols.append(f"<td>{img_html}</td>")
        rows_html.append(f"<tr>{''.join(cols)}</tr>")

    headers = "".join(f"<th>{html.escape(c)}</th>" for c in COLUMNS)
    headers += "<th>Screen</th>"

    content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>AutoLook Report</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; }}
  h1 {{ color: #333; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th {{ background: #333; color: #fff; padding: 8px; text-align: left; }}
  td {{ border-bottom: 1px solid #ddd; padding: 6px 8px; vertical-align: top; }}
  tr:hover {{ background: #f5f5f5; }}
</style>
</head>
<body>
<h1>AutoLook Incident Report</h1>
<p>Total incidents: {len(incidents)}</p>
<table>
<tr>{headers}</tr>
{''.join(rows_html)}
</table>
</body>
</html>"""

    output_path.write_text(content, encoding="utf-8")
