import re
from pathlib import Path

def safe_filename(name: str) -> str:
    """Make string safe for filesystem."""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()

def parse_marker_sections(tex_content: str) -> dict:
    """
    Parses LaTeX content for sections demarcated by %% BEGIN Name %% and %% END Name %%.
    """
    pattern = re.compile(
        r"^(?P<indent>\s*)%%\s*BEGIN\s+(?P<name>.+?)\s*%%\s*$"
        r"(?P<body>.*?)"
        r"^(?P=indent)%%\s*END\s+(?P=name)\s*%%\s*$",
        re.MULTILINE | re.DOTALL,
    )
    sections = {}
    for m in pattern.finditer(tex_content):
        name = m.group("name").strip()
        body = m.group("body")

        start_char = m.start()
        end_char = m.end()
        start_line = tex_content[:start_char].count("\n")
        end_line = tex_content[:end_char].count("\n")

        sections[name] = {
            "start": start_line,
            "end": end_line,
            "content": body.strip(),
        }
    return sections

def inject_content_into_tex(template_str: str, tailored_content: dict, sections: dict) -> str:
    """
    Injects tailored content back into the LaTeX template string without altering original sections boundaries.
    """
    lines = template_str.split("\n")
    result_lines = lines.copy()

    # Sort in reverse to avoid shifting indices while replacing
    for section_name in sorted(tailored_content.keys(), key=lambda s: sections[s]["start"], reverse=True):
        if section_name not in sections:
            continue
        sec = sections[section_name]
        begin_line = sec["start"]
        end_line = sec["end"]
        new_content = tailored_content[section_name]
        result_lines[begin_line + 1:end_line] = [new_content]

    return "\n".join(result_lines)

def cleanup_latex_aux_files(output_dir: Path, filename: str):
    """
    Cleans up the .aux, .log, and .out files left behind by pdflatex compilation.
    """
    for ext in [".aux", ".log", ".out"]:
        aux_file = output_dir / f"{filename}{ext}"
        if aux_file.exists():
            try:
                aux_file.unlink()
            except OSError:
                pass
