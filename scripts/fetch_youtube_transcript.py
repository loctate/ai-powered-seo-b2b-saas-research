#!/usr/bin/env python3

"""
Fetch a publicly available YouTube transcript and save it as Markdown.

Example:
python scripts/fetch_youtube_transcript.py \
  "https://www.youtube.com/watch?v=AqAoKGftsSE" \
  --expert "Kevin Indig" \
  --title "Moving Beyond Old SEO Models in the Age of AI"
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "research" / "youtube-transcripts"

VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(video_input: str) -> str:
    """Extract a YouTube video ID from an ID or supported YouTube URL."""

    value = video_input.strip()

    if VIDEO_ID_PATTERN.fullmatch(value):
        return value

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    candidate: str | None = None

    if hostname in {"youtu.be", "www.youtu.be"} and path_parts:
        candidate = path_parts[0]

    elif hostname == "youtube.com" or hostname.endswith(".youtube.com"):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]

        elif (
            len(path_parts) >= 2
            and path_parts[0] in {"shorts", "embed", "live"}
        ):
            candidate = path_parts[1]

    if candidate and VIDEO_ID_PATTERN.fullmatch(candidate):
        return candidate

    raise ValueError(
        "Unable to identify a valid YouTube video ID from the supplied value."
    )


def slugify(value: str) -> str:
    """Convert text into a safe lowercase filename."""

    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")

    return slug or "youtube-transcript"


def normalize_text(value: str) -> str:
    """Clean transcript text and remove unnecessary whitespace."""

    decoded = html.unescape(value)
    return " ".join(decoded.replace("\n", " ").split())


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""

    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def group_snippets(
    snippets,
    maximum_seconds: int = 60,
    maximum_characters: int = 1200,
) -> list[tuple[float, str]]:
    """Group short subtitle snippets into readable transcript paragraphs."""

    grouped: list[tuple[float, str]] = []
    current_parts: list[str] = []
    current_start: float | None = None
    current_length = 0

    for snippet in snippets:
        text = normalize_text(snippet.text)

        if not text:
            continue

        if current_start is None:
            current_start = snippet.start

        exceeds_time = snippet.start - current_start >= maximum_seconds
        exceeds_length = current_length + len(text) > maximum_characters

        if current_parts and (exceeds_time or exceeds_length):
            grouped.append((current_start, " ".join(current_parts)))
            current_parts = []
            current_start = snippet.start
            current_length = 0

        current_parts.append(text)
        current_length += len(text) + 1

    if current_parts and current_start is not None:
        grouped.append((current_start, " ".join(current_parts)))

    return grouped


def build_markdown(
    *,
    title: str,
    expert: str,
    video_id: str,
    video_url: str,
    published: str,
    transcript,
) -> str:
    """Build the final Markdown document."""

    transcript_type = (
        "Auto-generated" if transcript.is_generated else "Manually created"
    )

    lines = [
        f"# {title}",
        "",
        f"- **Expert:** {expert}",
        f"- **Video URL:** {video_url}",
        f"- **Video ID:** `{video_id}`",
        f"- **Publication date:** {published or 'Not recorded'}",
        f"- **Transcript language:** {transcript.language}",
        f"- **Language code:** `{transcript.language_code}`",
        f"- **Transcript type:** {transcript_type}",
        f"- **Collected on:** {date.today().isoformat()}",
        "- **Collection method:** Python using `youtube-transcript-api`",
        "",
        "## Research Notes",
        "",
        "- **Summary:** To be added after reviewing the transcript.",
        "- **Key insights:** To be added after reviewing the transcript.",
        "- **Relevance to B2B SaaS:** To be added after reviewing the transcript.",
        "",
        "## Transcript",
        "",
    ]

    for start_time, paragraph in group_snippets(transcript):
        timestamp = format_timestamp(start_time)
        lines.extend(
            [
                f"### [{timestamp}]",
                "",
                paragraph,
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a public YouTube transcript and save it as a "
            "structured Markdown research file."
        )
    )

    parser.add_argument(
        "video",
        help="YouTube video URL or 11-character video ID.",
    )

    parser.add_argument(
        "--expert",
        required=True,
        help="Name of the expert or speaker.",
    )

    parser.add_argument(
        "--title",
        required=True,
        help="Title of the video.",
    )

    parser.add_argument(
        "--published",
        default="",
        help="Publication date, for example 2026-05-20.",
    )

    parser.add_argument(
        "--languages",
        nargs="+",
        default=["en"],
        help="Preferred transcript languages in priority order.",
    )

    parser.add_argument(
        "--output",
        help="Optional output filename. The .md extension is added automatically.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    try:
        video_id = extract_video_id(args.video)

        canonical_url = f"https://www.youtube.com/watch?v={video_id}"

        api = YouTubeTranscriptApi()

        transcript = api.fetch(
            video_id,
            languages=args.languages,
        )

        markdown = build_markdown(
            title=args.title,
            expert=args.expert,
            video_id=video_id,
            video_url=canonical_url,
            published=args.published,
            transcript=transcript,
        )

        OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

        if args.output:
            filename = args.output
            if not filename.endswith(".md"):
                filename = f"{filename}.md"
        else:
            filename = (
                f"{slugify(args.expert)}--"
                f"{slugify(args.title)}.md"
            )

        output_path = OUTPUT_DIRECTORY / filename
        output_path.write_text(markdown, encoding="utf-8")

        print("Transcript collected successfully.")
        print(f"Video ID : {video_id}")
        print(f"Language : {transcript.language}")
        print(f"Generated: {transcript.is_generated}")
        print(f"Saved to : {output_path.relative_to(REPOSITORY_ROOT)}")

        return 0

    except ValueError as error:
        print(f"Input error: {error}", file=sys.stderr)
        return 1

    except YouTubeTranscriptApiException as error:
        print("Unable to retrieve the transcript.", file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 2

    except OSError as error:
        print(f"Unable to save the file: {error}", file=sys.stderr)
        return 3

    except Exception as error:
        print(
            f"Unexpected error: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())