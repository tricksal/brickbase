"""
llm-native-specs — Spec Loader / Compiler
Brickbase Pattern: Write specs, not code. LLM compiles on demand.

Source: https://codespeak.dev/
"""

import anthropic
import hashlib
from pathlib import Path


def compile_spec(spec: str, language: str = "python", model: str = "claude-sonnet-4-6") -> str:
    """
    Compile a human-readable spec string to executable code.

    Args:
        spec:     The specification text (markdown or plain text)
        language: Target programming language (default: python)
        model:    LLM model to use for compilation

    Returns:
        Executable code as string
    """
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": (
                f"Implement the following specification in {language}.\n"
                "Return ONLY the code — no explanation, no markdown fences, no comments "
                "unless they clarify non-obvious logic.\n\n"
                f"SPEC:\n{spec}"
            )
        }]
    )
    return response.content[0].text.strip()


def compile_spec_file(spec_file: str, language: str = "python") -> str:
    """
    Compile a .spec.md file to executable code.

    Args:
        spec_file: Path to the spec file
        language:  Target language

    Returns:
        Compiled code as string
    """
    spec = Path(spec_file).read_text(encoding="utf-8")
    return compile_spec(spec, language)


def load_compiled(
    spec_file: str,
    language: str = "python",
    cache_dir: str = ".compiled",
    force_recompile: bool = False
) -> str:
    """
    Load compiled code for a spec file, using cache when spec hasn't changed.

    Args:
        spec_file:       Path to the spec file
        language:        Target language
        cache_dir:       Directory to store compiled files
        force_recompile: Ignore cache and recompile

    Returns:
        Compiled code as string
    """
    spec_path = Path(spec_file)
    spec_content = spec_path.read_text(encoding="utf-8")

    # Cache key: spec filename + content hash
    content_hash = hashlib.md5(spec_content.encode()).hexdigest()[:8]
    ext = {"python": "py", "javascript": "js", "typescript": "ts"}.get(language, language)
    cache_path = Path(cache_dir) / f"{spec_path.stem}_{content_hash}.{ext}"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if not force_recompile and cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    compiled = compile_spec_file(spec_file, language)
    cache_path.write_text(compiled, encoding="utf-8")
    return compiled


def exec_spec(spec_file: str, namespace: dict | None = None) -> dict:
    """
    Compile and execute a spec file, returning the resulting namespace.

    Args:
        spec_file:  Path to the spec file
        namespace:  Optional existing namespace to execute into

    Returns:
        Namespace dict containing all defined functions/variables
    """
    if namespace is None:
        namespace = {}
    code = load_compiled(spec_file)
    exec(code, namespace)  # noqa: S102
    return namespace


# --- Example spec template ---
SPEC_TEMPLATE = """\
# FunctionName

## What it does
A clear description of the function in plain language.

## Input
- param_name (type): What it means, not just the type

## Output
- Type and what exactly gets returned

## Behavior
- Edge case 1: What happens when...
- Edge case 2: What happens when...

## Examples
Input: X -> Output: Y
Input: A -> Output: B
"""


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python spec_loader.py <spec_file.md> [language]")
        print("\nSpec template:")
        print(SPEC_TEMPLATE)
        sys.exit(0)

    spec_file = sys.argv[1]
    language = sys.argv[2] if len(sys.argv) > 2 else "python"

    print(f"Compiling {spec_file} to {language}...\n")
    code = compile_spec_file(spec_file, language)
    print(code)
