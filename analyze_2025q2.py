"""Utility script to summarize and help understand the data contained in the
`2025q2` folder.

Outputs generated (in the same directory as this script):
  - summary.md: Human‑readable markdown summary of each file.
  - combined_lines.csv: If all .txt files share identical line counts, a row‑wise alignment.

The script focuses on plain text (*.txt) and a single HTML file (readme.htm).
It performs:
  - Size & basic statistics (lines, chars, average line length).
  - Line uniqueness & duplication ratios.
  - Simple content heuristics (numeric lines %, tag prefixes, etc.).
  - Sampling (first & last few lines, plus middle lines for larger files).
  - Cross-file alignment if feasible.
  - HTML parsing to extract title, headings, and paragraph snippets.

Run:
    python3 analyze_2025q2.py

Optionally pass a path (defaults to relative ./2025q2):
    python3 analyze_2025q2.py /absolute/path/to/2025q2

No external dependencies required (stdlib only).
"""

from __future__ import annotations

import sys
import os
import csv
import statistics
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Dict, Optional


@dataclass
class FileSummary:
    name: str
    path: str
    lines: int
    chars: int
    avg_line_len: float
    unique_lines: int
    duplicate_ratio: float
    numeric_line_ratio: float
    samples: Dict[str, List[str]]
    notes: List[str]


class SimpleHTMLExtractor(HTMLParser):
    """Extract title, headings, and first paragraphs from an HTML file."""
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title: Optional[str] = None
        self.current_tag: Optional[str] = None
        self.headings: List[str] = []
        self.paragraphs: List[str] = []
        self._para_buffer: List[str] = []

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        if tag == 'title':
            self.in_title = True
        if tag == 'p':
            self._para_buffer = []

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if tag == 'p' and self._para_buffer:
            text = ' '.join(self._para_buffer).strip()
            if text:
                self.paragraphs.append(text)
            self._para_buffer = []
        self.current_tag = None

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self.in_title:
            self.title = (self.title or '') + text
        if self.current_tag and self.current_tag.startswith('h') and len(self.current_tag) == 2 and self.current_tag[1].isdigit():
            # heading h1..h6
            self.headings.append(text)
        if self.current_tag == 'p':
            self._para_buffer.append(text)


def read_text_file(path: str) -> List[str]:
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return [line.rstrip('\n') for line in f]


def summarize_text_file(path: str) -> FileSummary:
    lines = read_text_file(path)
    line_lengths = [len(l) for l in lines]
    chars = sum(line_lengths)
    avg_line_len = statistics.mean(line_lengths) if line_lengths else 0.0
    unique_lines = len(set(lines))
    duplicate_ratio = 1 - (unique_lines / len(lines)) if lines else 0.0
    numeric_lines = 0
    notes: List[str] = []

    for l in lines:
        stripped = l.strip()
        if stripped and all(c.isdigit() or c in {'.', ',', '-', ' '} for c in stripped):
            # very naive numeric detection
            numeric_lines += 1
    numeric_line_ratio = numeric_lines / len(lines) if lines else 0.0

    if numeric_line_ratio > 0.8:
        notes.append('Predominantly numeric content.')
    if duplicate_ratio > 0.5:
        notes.append('High duplication of lines (>50%).')
    if avg_line_len > 120:
        notes.append('Long average line length (>120 chars).')

    samples = sample_lines(lines)

    return FileSummary(
        name=os.path.basename(path),
        path=path,
        lines=len(lines),
        chars=chars,
        avg_line_len=avg_line_len,
        unique_lines=unique_lines,
        duplicate_ratio=duplicate_ratio,
        numeric_line_ratio=numeric_line_ratio,
        samples=samples,
        notes=notes,
    )


def sample_lines(lines: List[str]) -> Dict[str, List[str]]:
    """Return representative samples: first 5, last 5, and up to 5 middle lines if large."""
    out: Dict[str, List[str]] = {}
    if not lines:
        return out
    out['first'] = lines[:5]
    out['last'] = lines[-5:] if len(lines) > 5 else []
    if len(lines) > 20:
        # pick evenly spaced middle indices
        step = max(len(lines) // 6, 1)
        middle_indices = list(range(step * 2, step * 5, step))[:5]
        out['middle'] = [lines[i] for i in middle_indices if i < len(lines)]
    return out


def parse_html(path: str) -> Dict[str, List[str] | str | None]:
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    parser = SimpleHTMLExtractor()
    parser.feed(content)
    return {
        'title': parser.title,
        'headings': parser.headings[:10],
        'paragraphs': parser.paragraphs[:5],
    }


def generate_alignment(text_summaries: List[FileSummary], output_path: str) -> Optional[str]:
    """If all text files have identical line counts (>0), produce a combined CSV aligning each line index."""
    if not text_summaries:
        return None
    line_counts = {s.lines for s in text_summaries}
    if len(line_counts) != 1:
        return None  # not alignable
    total_lines = next(iter(line_counts))
    if total_lines == 0:
        return None

    # Read raw lines again for alignment
    file_lines = {s.name: read_text_file(s.path) for s in text_summaries}
    fieldnames = ['line_index'] + [name for name in file_lines.keys()]
    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for i in range(total_lines):
            row = {'line_index': i}
            for name, lines in file_lines.items():
                row[name] = lines[i]
            writer.writerow(row)
    return output_path


def write_markdown_summary(text_summaries: List[FileSummary], html_info: Optional[Dict], md_path: str, alignment_csv: Optional[str]):
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('# 2025q2 Folder Summary\n\n')
        for s in text_summaries:
            f.write(f'## {s.name}\n')
            f.write(f'- Path: `{s.path}`\n')
            f.write(f'- Lines: {s.lines}\n')
            f.write(f'- Characters: {s.chars}\n')
            f.write(f'- Unique lines: {s.unique_lines}\n')
            f.write(f'- Duplicate ratio: {s.duplicate_ratio:.2%}\n')
            f.write(f'- Numeric line ratio: {s.numeric_line_ratio:.2%}\n')
            f.write(f'- Average line length: {s.avg_line_len:.2f}\n')
            if s.notes:
                f.write(f'- Notes: {"; ".join(s.notes)}\n')
            # Samples
            for label, lines in s.samples.items():
                if not lines:
                    continue
                f.write(f'### Sample ({label})\n')
                f.write('```\n')
                for line in lines:
                    f.write(f'{line}\n')
                f.write('```\n')
            f.write('\n')
        if html_info:
            f.write('## readme.htm (HTML)\n')
            f.write(f'- Title: {html_info.get("title") or "(none)"}\n')
            headings = html_info.get('headings') or []
            if headings:
                f.write('### Headings\n')
                for h in headings:
                    f.write(f'- {h}\n')
            paragraphs = html_info.get('paragraphs') or []
            if paragraphs:
                f.write('### Paragraph snippets\n')
                for p in paragraphs:
                    snippet = p[:240] + ('…' if len(p) > 240 else '')
                    f.write(f'- {snippet}\n')
        if alignment_csv:
            f.write('\n## Cross-file Alignment\n')
            f.write(f'All text files share identical line counts; aligned CSV generated at `{alignment_csv}`.\n')


def main():
    target_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '2025q2')
    if not os.path.isdir(target_dir):
        print(f'[ERROR] Target directory does not exist: {target_dir}', file=sys.stderr)
        sys.exit(1)

    entries = sorted(os.listdir(target_dir))
    text_files: List[FileSummary] = []
    html_info: Optional[Dict] = None
    for name in entries:
        path = os.path.join(target_dir, name)
        if not os.path.isfile(path):
            continue
        lower = name.lower()
        try:
            if lower.endswith('.txt'):
                text_files.append(summarize_text_file(path))
            elif lower.endswith('.htm') or lower.endswith('.html'):
                html_info = parse_html(path)
        except Exception as e:
            print(f'[WARN] Failed processing {name}: {e}', file=sys.stderr)

    alignment_csv = None
    if text_files:
        alignment_csv = generate_alignment(text_files, os.path.join(os.path.dirname(__file__), 'combined_lines.csv'))

    md_path = os.path.join(os.path.dirname(__file__), 'summary.md')
    write_markdown_summary(text_files, html_info, md_path, alignment_csv)

    # Console summary
    print('=== 2025q2 SUMMARY ===')
    for s in text_files:
        print(f'{s.name}: lines={s.lines} chars={s.chars} unique={s.unique_lines} dup_ratio={s.duplicate_ratio:.2%} numeric_ratio={s.numeric_line_ratio:.2%}')
        if s.notes:
            print(f'  Notes: {"; ".join(s.notes)}')
    if html_info:
        print('readme.htm title:', html_info.get('title'))
        if html_info.get('headings'):
            print('  Headings:', ', '.join(html_info['headings'][:5]))
    if alignment_csv:
        print(f'Aligned CSV created: {alignment_csv}')
    print(f'Markdown summary written: {md_path}')
    print('Done.')


if __name__ == '__main__':
    main()
