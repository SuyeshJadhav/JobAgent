import re
from pathlib import Path


def parse_marker_sections(tex_content: str) -> dict:
    """
    Parses LaTeX content for sections demarcated by %% BEGIN Name %% and %% END Name %%.
    This allows surgical injection of tailored content into specific resume sections.

    Args:
        tex_content (str): The raw LaTeX template string.

    Returns:
        dict: A dictionary of sections, where each key is the section name and 
              the value is a dict with 'start', 'end' (line numbers), and 'content'.
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
    Injects tailored text blocks back into the LaTeX template string.
    Preserves the original section boundaries (%% BEGIN/END markers).

    Args:
        template_str (str): The original LaTeX template string.
        tailored_content (dict): Mapping of section names to rewritten text.
        sections (dict): Metadata about section positions (from parse_marker_sections).

    Returns:
        str: The updated LaTeX string with tailored content injected.
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

        # Injects the new content between the %% BEGIN and %% END markers
        result_lines[begin_line + 1:end_line] = [new_content]

    return "\n".join(result_lines)


def cleanup_latex_aux_files(output_dir: Path, filename: str):
    """
    Cleans up the .aux, .log, and .out files left behind by the pdflatex 
    compilation process to keep application folders tidy.

    Args:
        output_dir (Path): The directory containing the build artifacts.
        filename (str): The base name of the generated files.
    """
    for ext in [".aux", ".log", ".out"]:
        aux_file = output_dir / f"{filename}{ext}"
        if aux_file.exists():
            try:
                aux_file.unlink()
            except OSError:
                pass


def escape_latex_text(text: str) -> str:
    """Escape special LaTeX characters in plain text.
    Single source of truth — import from here."""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    out = []
    for ch in text:
        out.append(replacements.get(ch, ch))
    return "".join(out)
