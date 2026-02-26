"""
Email content templates for alerts.
"""

from __future__ import annotations

from datetime import datetime


def _format_ts(ts: datetime | str | None, tz_name: str = "UTC") -> str:
    """Format a Firestore datetime in the configured timezone.

    Args:
        ts: A ``datetime`` (Firestore ``SERVER_TIMESTAMP``), a plain string
            (used in tests), or ``None``.
        tz_name: IANA timezone name, e.g. ``'UTC'``, ``'Asia/Jerusalem'``,
            ``'America/New_York'``.  Comes from ``alerting.timezone`` in
            the DMAF config — never hardcoded.

    Example output: ``'2026-02-25 22:07 UTC+2 (Asia/Jerusalem)'``
    Falls back gracefully for strings (passed through) and None.
    """
    if ts is None:
        return "unknown"
    # Plain strings (e.g. from tests) — pass through unchanged.
    if not isinstance(ts, datetime):
        return str(ts)[:57]
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
        local = ts.astimezone(tz)
        offset = local.utcoffset()
        offset_h = int(offset.total_seconds() // 3600) if offset is not None else 0
        label = f"UTC{offset_h:+d} ({tz_name})"
        return local.strftime(f"%Y-%m-%d %H:%M {label}")
    except Exception:
        return ts.strftime("%Y-%m-%d %H:%M UTC")


def format_borderline_alert(events: list[dict], tz_name: str = "UTC") -> tuple[str, str | None]:
    """
    Format borderline recognition events into email content.

    Args:
        events: List of borderline event dicts with keys:
            - file_path: str
            - match_score: float
            - tolerance: float
            - matched_person: str | None
            - created_ts: str (ISO format datetime)

    Returns:
        Tuple of (plain_text, html) email content (html may be None)
    """
    count = len(events)
    threshold_example = 1.0 - events[0]["tolerance"] if events else 0.48

    # Plain text version
    text_lines = [
        (
            f"DMAF detected {count} image(s) with borderline recognition "
            "scores that may warrant manual review."
        ),
        "",
        (
            f"These images had similarity scores close to but below "
            f"the match threshold ({threshold_example:.2f})."
        ),
        "They might contain known people that weren't recognized.",
        "",
    ]

    for event in events[:10]:  # Limit to 10 events in email
        threshold = 1.0 - event["tolerance"]
        text_lines.extend(
            [
                "┌─────────────────────────────────────────────────────────────────┐",
                f"│ Image: {event['file_path']:<58} │",
                f"│ Score: {event['match_score']:.2f} (threshold: {threshold:.2f})"
                + " " * (39 - len(f"{event['match_score']:.2f}") - len(f"{threshold:.2f}"))
                + "│",
                f"│ Closest match: {event['matched_person'] or 'Unknown':<47} │",
                f"│ Time: {_format_ts(event['created_ts'], tz_name):<57} │",
                "└─────────────────────────────────────────────────────────────────┘",
                "",
            ]
        )

    if count > 10:
        text_lines.append(f"... and {count - 10} more events (see database for full list)")
        text_lines.append("")

    text_lines.extend(
        [
            "Action: Review these images manually to decide if they should be uploaded.",
            "If you see missed recognitions often, consider lowering the tolerance threshold.",
        ]
    )

    plain_text = "\n".join(text_lines)

    # HTML version (optional - for now, None)
    html = None

    return plain_text, html


def format_error_alert(events: list[dict], tz_name: str = "UTC") -> tuple[str, str | None]:
    """
    Format error events into email content.

    Args:
        events: List of error event dicts with keys:
            - error_type: str
            - error_message: str
            - file_path: str | None
            - created_ts: str (ISO format datetime)

    Returns:
        Tuple of (plain_text, html) email content (html may be None)
    """
    count = len(events)

    # Plain text version
    text_lines = [
        f"DMAF encountered {count} error(s) during image processing.",
        "",
    ]

    for event in events[:10]:  # Limit to 10 events in email
        text_lines.extend(
            [
                "┌─────────────────────────────────────────────────────────────────┐",
                f"│ Error Type: {event['error_type']:<53} │",
                f"│ Message: {event['error_message'][:56]:<56} │",
            ]
        )
        if event["file_path"]:
            text_lines.append(f"│ File: {event['file_path'][:60]:<60} │")
        text_lines.extend(
            [
                f"│ Time: {_format_ts(event['created_ts'], tz_name):<57} │",
                "└─────────────────────────────────────────────────────────────────┘",
                "",
            ]
        )

    if count > 10:
        text_lines.append(f"... and {count - 10} more errors (see database for full list)")
        text_lines.append("")

    text_lines.append("Check the application logs for more details and stack traces if available.")

    plain_text = "\n".join(text_lines)

    # HTML version (optional - for now, None)
    html = None

    return plain_text, html


def format_combined_alert(
    borderline_events: list[dict], error_events: list[dict], tz_name: str = "UTC"
) -> tuple[str, str | None]:
    """
    Format combined borderline and error events into a single email.

    Args:
        borderline_events: List of borderline event dicts
        error_events: List of error event dicts

    Returns:
        Tuple of (plain_text, html) email content (html may be None)
    """
    text_lines = []

    if error_events:
        text_lines.append(f"== ERRORS ({len(error_events)}) ==")
        text_lines.append("")
        error_text, _ = format_error_alert(error_events, tz_name)
        text_lines.append(error_text)
        text_lines.append("")
        text_lines.append("")

    if borderline_events:
        text_lines.append(f"== BORDERLINE RECOGNITIONS ({len(borderline_events)}) ==")
        text_lines.append("")
        borderline_text, _ = format_borderline_alert(borderline_events, tz_name)
        text_lines.append(borderline_text)

    plain_text = "\n".join(text_lines)
    html = None

    return plain_text, html


def format_refresh_alert(refresh_results: list[dict]) -> tuple[str, str | None]:
    """
    Format known refresh events into email content.

    Args:
        refresh_results: List of refresh result dicts with keys:
            - person_name: str
            - source_file_path: str
            - target_file_path: str
            - match_score: float
            - target_score: float

    Returns:
        Tuple of (plain_text, html) email content (html may be None)
    """
    count = len(refresh_results)

    text_lines = [
        (
            f"DMAF has automatically added {count} new reference image(s) "
            "to improve face recognition."
        ),
        "",
        (
            "This happens periodically to keep recognition accurate as "
            "people's appearances gradually change."
        ),
        "",
    ]

    for result in refresh_results:
        text_lines.extend(
            [
                "┌─────────────────────────────────────────────────────────────────┐",
                f"│ Person: {result['person_name']:<57} │",
                f"│ Source: {result['source_file_path'][:57]:<57} │",
                f"│ Saved as: {result['target_file_path'][:55]:<55} │",
                (
                    f"│ Match Score: {result['match_score']:.2f} "
                    f"(target was {result['target_score']:.2f})"
                    + " "
                    * (
                        31
                        - len(f"{result['match_score']:.2f}")
                        - len(f"{result['target_score']:.2f}")
                    )
                    + "│"
                ),
                "└─────────────────────────────────────────────────────────────────┘",
                "",
            ]
        )

    text_lines.extend(
        [
            (
                f"Note: New images are selected with scores near "
                f"{refresh_results[0]['target_score']:.2f} (moderately challenging)"
            ),
            ("to help the system learn more diverse representations without being too easy"),
            "or risking false positives.",
            "",
            "If any image looks wrong, manually delete it from known_people/ and restart.",
        ]
    )

    plain_text = "\n".join(text_lines)
    html = None

    return plain_text, html
