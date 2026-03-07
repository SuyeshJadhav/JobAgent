from pathlib import Path

def parse_candidate_profile(filepath: Path) -> dict:
    """
    Parses the candidate's master profile Markdown file into a structured dictionary.
    This dictionary is used by the scoring engine and resume generator to ensure
    fact-based tailoring.
    
    Expected Markdown Structure:
    - ## Background (contains skills/degree)
    - ## Target Roles
    - ## Preferences
    
    Args:
        filepath (Path): Path to 'candidate_profile.md'.
        
    Returns:
        dict: A dictionary containing 'target_roles', 'skills', 
              'experience_level', and 'preferences' as formatted strings.
    """
    profile = {
        "target_roles": [],
        "skills": [],
        "experience_level": "",
        "preferences": []
    }
    if not filepath.exists():
        return profile
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    current_section = None
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("## "):
            current_section = line[3:].strip()
            continue
            
        if not line or not line.startswith("- "):
            continue
            
        value = line[2:].strip()
        if current_section == "Background":
            profile["skills"].append(value)
            if "Degree:" in value or "Experience:" in value:
                profile["experience_level"] += value + "; "
        elif current_section == "Target Roles":
            profile["target_roles"].append(value)
        elif current_section == "Preferences":
            profile["preferences"].append(value)
            
    # Format for scorer: join lists into searchable strings
    return {
        "target_roles": ", ".join(profile["target_roles"]),
        "skills": " | ".join(profile["skills"]),
        "experience_level": profile["experience_level"],
        "preferences": " | ".join(profile["preferences"])
    }
