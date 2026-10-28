"""Data-only Lorcana Price Watch coverage audit.

Does not identify purchase opportunities, compare unlike pack counts,
send Discord messages, or edit scanner state. Uses only already-normalized
eligible, fresh in-stock price-history candidates.
"""
from collections import Counter


def summarize_lorcana_coverage(candidates):
    """Produce bounded metrics; do not infer market pricing from these rows."""
    rows = [
        row for row in candidates
        if isinstance(row, dict) and str(row.get("game") or "").upper() == "LORCANA"
    ]
    source_counts = Counter(str(row.get("source") or "unknown") for row in rows)
    type_counts = Counter(str(row.get("type") or "unknown") for row in rows)
    missing_url = sum(not str(row.get("url") or "").strip() for row in rows)
    return {
        "listings": len(rows),
        "sources": len(source_counts),
        "formats": dict(sorted(type_counts.items())),
        "per_source": dict(sorted(source_counts.items())),
        "missing_urls": missing_url,
    }


def format_lorcana_coverage(summary):
    fmt = ",".join(f"{key}:{value}" for key, value in summary["formats"].items())
    sources = ",".join(f"{key}:{value}" for key, value in summary["per_source"].items())
    return (
        "LORCANA PRICE SHADOW: "
        f"{summary['listings']} eligible listings | "
        f"{summary['sources']} fresh sources | "
        f"formats={fmt or '-'} | sources={sources or '-'} | "
        f"missing_links={summary['missing_urls']} | Discord=off"
    )
