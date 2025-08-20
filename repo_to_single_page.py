#!/usr/bin/env python3
"""
Flatten a GitHub repo into a single static HTML page for fast skimming and Ctrl+F.

Features
- Clones a repo URL to a temp dir
- Renders every small text file into one giant HTML page
  * Markdown files are rendered as HTML
  * Code files are syntax-highlighted via Pygments
  * Plaintext gets <pre><code>
- Skips binaries and files over a size threshold (default: 50 KiB)
- Lists skipped binaries / large files at the top
- Includes repo metadata, counts, and a directory tree header

Usage
    python repo_to_single_page.py https://github.com/user/repo -o out.html

Requirements
    pip install pygments markdown

Notes
- Requires a working `git` in PATH.
- If the `tree` command is unavailable, a Python fallback is used.
"""

from __future__ import annotations
import argparse
import html
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from dataclasses import dataclass
from typing import List, Tuple

# External deps
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_for_filename, TextLexer

try:
    import markdown  # Python-Markdown
except ImportError as e:
    print("Missing dependency: markdown. Install with `pip install markdown`.", file=sys.stderr)
    raise

MAX_DEFAULT_BYTES = 50 * 1024
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav", ".ogg", ".flac",
    ".ttf", ".otf", ".eot", ".woff", ".woff2",
    ".so", ".dll", ".dylib", ".class", ".jar", ".exe", ".bin",
}
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}

@dataclass
class RenderDecision:
    include: bool
    reason: str  # "ok" | "binary" | "too_large" | "ignored"

@dataclass
class FileInfo:
    path: pathlib.Path  # absolute path on disk
    rel: str            # path relative to repo root (slash-separated)
    size: int
    decision: RenderDecision


def run(cmd: List[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)


def git_clone(url: str, dst: str) -> None:
    run(["git", "clone", "--depth", "1", url, dst])


def git_head_commit(repo_dir: str) -> str:
    try:
        cp = run(["git", "rev-parse", "HEAD"], cwd=repo_dir)
        return cp.stdout.strip()
    except Exception:
        return "(unknown)"


def bytes_human(n: int) -> str:
    """Human-readable bytes: 1 decimal for KiB and above, integer for B."""
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    f = float(n)
    i = 0
    while f >= 1024.0 and i < len(units) - 1:
        f /= 1024.0
        i += 1
    if i == 0:
        return f"{int(f)} {units[i]}"
    else:
        return f"{f:.1f} {units[i]}"


def looks_binary(path: pathlib.Path) -> bool:
    ext = path.suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return True
    try:
        with path.open("rb") as f:
            chunk = f.read(8192)
        if b"\x00" in chunk:
            return True
        # Heuristic: try UTF-8 decode; if it hard-fails, likely binary
        try:
            chunk.decode("utf-8")
        except UnicodeDecodeError:
            return True
        return False
    except Exception:
        # If unreadable, treat as binary to be safe
        return True


def decide_file(path: pathlib.Path, repo_root: pathlib.Path, max_bytes: int) -> FileInfo:
    rel = str(path.relative_to(repo_root)).replace(os.sep, "/")
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        size = 0
    # Ignore VCS and build junk
    if "/.git/" in f"/{rel}/" or rel.startswith(".git/"):
        return FileInfo(path, rel, size, RenderDecision(False, "ignored"))
    if size > max_bytes:
        return FileInfo(path, rel, size, RenderDecision(False, "too_large"))
    if looks_binary(path):
        return FileInfo(path, rel, size, RenderDecision(False, "binary"))
    return FileInfo(path, rel, size, RenderDecision(True, "ok"))


def collect_files(repo_root: pathlib.Path, max_bytes: int) -> List[FileInfo]:
    infos: List[FileInfo] = []
    for p in sorted(repo_root.rglob("*")):
        if p.is_symlink():
            continue
        if p.is_file():
            infos.append(decide_file(p, repo_root, max_bytes))
    return infos


def generate_tree_fallback(root: pathlib.Path) -> str:
    """Minimal tree-like output if `tree` command is missing."""
    lines: List[str] = []
    prefix_stack: List[str] = []

    def walk(dir_path: pathlib.Path, prefix: str = ""):
        entries = [e for e in dir_path.iterdir() if e.name != ".git"]
        entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))
        for i, e in enumerate(entries):
            last = i == len(entries) - 1
            branch = "└── " if last else "├── "
            lines.append(prefix + branch + e.name)
            if e.is_dir():
                extension = "    " if last else "│   "
                walk(e, prefix + extension)

    lines.append(root.name)
    walk(root)
    return "\n".join(lines)


def try_tree_command(root: pathlib.Path) -> str:
    try:
        cp = run(["tree", "-a", "."], cwd=str(root))
        return cp.stdout
    except Exception:
        return generate_tree_fallback(root)


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def render_markdown_text(md_text: str) -> str:
    return markdown.markdown(md_text, extensions=["fenced_code", "tables", "toc"])  # type: ignore


def highlight_code(text: str, filename: str, formatter: HtmlFormatter) -> str:
    try:
        lexer = get_lexer_for_filename(filename, stripall=False)
    except Exception:
        lexer = TextLexer(stripall=False)
    return highlight(text, lexer, formatter)


def slugify(path_str: str) -> str:
    # Simple slug: keep alnum, dash, underscore; replace others with '-'
    out = []
    for ch in path_str:
        if ch.isalnum() or ch in {"-", "_"}:
            out.append(ch)
        else:
            out.append("-")
    return "".join(out)


def generate_cxml_text(infos: List[FileInfo], repo_dir: pathlib.Path) -> str:
    """Generate CXML format text for LLM consumption."""
    lines = ["<documents>"]
    
    rendered = [i for i in infos if i.decision.include]
    for index, i in enumerate(rendered, 1):
        lines.append(f'<document index="{index}">')
        lines.append(f"<source>{i.rel}</source>")
        lines.append("<document_content>")
        
        try:
            text = read_text(i.path)
            lines.append(text)
        except Exception as e:
            lines.append(f"Failed to read: {str(e)}")
            
        lines.append("</document_content>")
        lines.append("</document>")
    
    lines.append("</documents>")
    return "\n".join(lines)


def build_html(repo_url: str, repo_dir: pathlib.Path, head_commit: str, infos: List[FileInfo]) -> str:
    formatter = HtmlFormatter(nowrap=False)
    pygments_css = formatter.get_style_defs('.highlight')

    # Stats
    rendered = [i for i in infos if i.decision.include]
    skipped_binary = [i for i in infos if i.decision.reason == "binary"]
    skipped_large = [i for i in infos if i.decision.reason == "too_large"]
    skipped_ignored = [i for i in infos if i.decision.reason == "ignored"]
    total_files = len(rendered) + len(skipped_binary) + len(skipped_large) + len(skipped_ignored)

    # Directory tree
    tree_text = try_tree_command(repo_dir)
    
    # Generate CXML text for LLM view
    cxml_text = generate_cxml_text(infos, repo_dir)

    # Table of contents with directory tree structure
    toc_items: List[str] = []
    
    # Group files by directory for tree structure
    file_tree = {}
    for i in rendered:
        path_parts = i.rel.split('/')
        current = file_tree
        for part in path_parts[:-1]:  # directories
            if part not in current:
                current[part] = {}
            current = current[part]
        # Add file to the current directory
        if '_files' not in current:
            current['_files'] = []
        current['_files'].append(i)
    
    def generate_tree_items(tree, path_prefix="", depth=0):
        items = []
        
        # First add directories
        for dir_name in sorted(key for key in tree.keys() if key != '_files'):
            dir_path = f"{path_prefix}/{dir_name}" if path_prefix else dir_name
            indent = "  " * depth
            folder_icon = "📁" if depth == 0 else "📂"
            items.append(f'<li class="toc-directory" data-depth="{depth}"><span class="directory-name">{indent}{folder_icon} {html.escape(dir_name)}/</span></li>')
            items.extend(generate_tree_items(tree[dir_name], dir_path, depth + 1))
        
        # Then add files in current directory
        if '_files' in tree:
            for file_info in sorted(tree['_files'], key=lambda f: f.rel.split('/')[-1].lower()):
                anchor = slugify(file_info.rel)
                filename = file_info.rel.split('/')[-1]
                indent = "  " * (depth + 1)
                
                # Get file icon
                ext = pathlib.Path(filename).suffix.lower()
                file_icon = "📄"  # default
                if ext in MARKDOWN_EXTENSIONS:
                    file_icon = "📝"
                elif ext in {".py", ".pyw"}:
                    file_icon = "🐍"
                elif ext in {".js", ".jsx", ".ts", ".tsx"}:
                    file_icon = "⚡"
                elif ext in {".html", ".htm"}:
                    file_icon = "🌐"
                elif ext in {".css", ".scss", ".sass", ".less"}:
                    file_icon = "🎨"
                elif ext in {".json", ".jsonl", ".yaml", ".yml", ".toml"}:
                    file_icon = "⚙️"
                elif ext in {".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd"}:
                    file_icon = "🔧"
                elif ext in {".sql"}:
                    file_icon = "🗃️"
                elif ext in {".java", ".class"}:
                    file_icon = "☕"
                elif ext in {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp"}:
                    file_icon = "⚙️"
                elif ext in {".rs"}:
                    file_icon = "🦀"
                elif ext in {".go"}:
                    file_icon = "🔵"
                elif ext in {".php"}:
                    file_icon = "🐘"
                elif ext in {".rb"}:
                    file_icon = "💎"
                elif ext in {".swift"}:
                    file_icon = "🕊️"
                elif ext in {".kt", ".kts"}:
                    file_icon = "📱"
                elif filename.lower() in {"readme", "readme.md", "readme.txt"}:
                    file_icon = "📚"
                elif filename.lower() in {"license", "licence", "copying"}:
                    file_icon = "📜"
                elif ext in {".txt", ".log"}:
                    file_icon = "📋"
                elif ext in {".xml"}:
                    file_icon = "🏷️"
                elif ext in {".gitignore", ".gitattributes"}:
                    file_icon = "🙈"
                
                items.append(f'<li class="toc-file" data-depth="{depth + 1}"><a href="#file-{anchor}">{indent}{file_icon} {html.escape(filename)} <span class="muted">({bytes_human(file_info.size)})</span></a></li>')
        
        return items
    
    # Generate root level items
    root_items = generate_tree_items(file_tree)
    toc_html = "".join(root_items)

    # Render file sections
    sections: List[str] = []
    for i in rendered:
        anchor = slugify(i.rel)
        p = i.path
        ext = p.suffix.lower()
        
        # Determine file icon based on extension
        file_icon = "📄"  # default
        if ext in MARKDOWN_EXTENSIONS:
            file_icon = "📝"
        elif ext in {".py", ".pyw"}:
            file_icon = "🐍"
        elif ext in {".js", ".jsx", ".ts", ".tsx"}:
            file_icon = "⚡"
        elif ext in {".html", ".htm"}:
            file_icon = "🌐"
        elif ext in {".css", ".scss", ".sass", ".less"}:
            file_icon = "🎨"
        elif ext in {".json", ".jsonl", ".yaml", ".yml", ".toml"}:
            file_icon = "⚙️"
        elif ext in {".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd"}:
            file_icon = "🔧"
        elif ext in {".sql"}:
            file_icon = "🗃️"
        elif ext in {".java", ".class"}:
            file_icon = "☕"
        elif ext in {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp"}:
            file_icon = "⚙️"
        elif ext in {".rs"}:
            file_icon = "🦀"
        elif ext in {".go"}:
            file_icon = "🔵"
        elif ext in {".php"}:
            file_icon = "🐘"
        elif ext in {".rb"}:
            file_icon = "💎"
        elif ext in {".swift"}:
            file_icon = "🕊️"
        elif ext in {".kt", ".kts"}:
            file_icon = "📱"
        elif ext in {".dockerfile", ".dockerignore"} or p.name.lower() in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
            file_icon = "🐳"
        elif p.name.lower() in {"readme", "readme.md", "readme.txt"}:
            file_icon = "📚"
        elif p.name.lower() in {"license", "licence", "copying"}:
            file_icon = "📜"
        elif ext in {".txt", ".log"}:
            file_icon = "📋"
        elif ext in {".xml"}:
            file_icon = "🏷️"
        elif ext in {".gitignore", ".gitattributes"}:
            file_icon = "🙈"
        
        try:
            text = read_text(p)
            if ext in MARKDOWN_EXTENSIONS:
                body_html = f'<div class="markdown-content">{render_markdown_text(text)}</div>'
            else:
                code_html = highlight_code(text, i.rel, formatter)
                body_html = f'<div class="highlight">{code_html}</div>'
        except Exception as e:
            body_html = f'<pre class="error">Failed to render: {html.escape(str(e))}</pre>'
        
        sections.append(f"""
<section class="file-section" id="file-{anchor}">
  <h2 data-icon="{file_icon}">{html.escape(i.rel)} <span class="muted">({bytes_human(i.size)})</span></h2>
  <div class="file-body">{body_html}</div>
  <div class="back-top"><a href="#top">↑ Back to top</a></div>
</section>
""")

    # Skips lists
    def render_skip_list(title: str, items: List[FileInfo]) -> str:
        if not items:
            return ""
        lis = [
            f"<li><code>{html.escape(i.rel)}</code> "
            f"<span class='muted'>({bytes_human(i.size)})</span></li>"
            for i in items
        ]
        return (
            f"<details open><summary>{html.escape(title)} ({len(items)})</summary>"
            f"<ul class='skip-list'>\n" + "\n".join(lis) + "\n</ul></details>"
        )

    skipped_html = (
        render_skip_list("Skipped binaries", skipped_binary) +
        render_skip_list("Skipped large files", skipped_large)
    )

    # HTML with left sidebar TOC
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>📚 {html.escape(repo_url)} - Code Repository</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    --secondary-gradient: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    --success-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
    --danger-gradient: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
    
    --bg-primary: #ffffff;
    --bg-secondary: #f8fafc;
    --bg-tertiary: #f1f5f9;
    --bg-code: #0f172a;
    --bg-sidebar: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
    
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --text-tertiary: #94a3b8;
    --text-accent: #3b82f6;
    --text-code: #e2e8f0;
    
    --border-light: #e2e8f0;
    --border-medium: #cbd5e1;
    --border-strong: #94a3b8;
    
    --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
    --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
    --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
    --shadow-xl: 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1);
    
    --radius-sm: 8px;
    --radius-md: 12px;
    --radius-lg: 16px;
    --radius-xl: 20px;
  }}

  * {{
    box-sizing: border-box;
  }}

  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    margin: 0; 
    padding: 0; 
    line-height: 1.6;
    color: var(--text-primary);
    background: var(--bg-secondary);
    font-size: 14px;
  }}

  .container {{ 
    max-width: 1200px; 
    margin: 0 auto; 
    padding: 0 2rem; 
  }}

  /* Animated background elements */
  .bg-decoration {{
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    pointer-events: none;
    z-index: -1;
    overflow: hidden;
  }}
  
  .bg-decoration::before {{
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(circle, rgba(102, 126, 234, 0.1) 0%, transparent 50%);
    animation: float 20s ease-in-out infinite;
  }}
  
  .bg-decoration::after {{
    content: '';
    position: absolute;
    bottom: -50%;
    right: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(circle, rgba(118, 75, 162, 0.1) 0%, transparent 50%);
    animation: float 25s ease-in-out infinite reverse;
  }}

  @keyframes float {{
    0%, 100% {{ transform: translate(0px, 0px) rotate(0deg); }}
    33% {{ transform: translate(30px, -30px) rotate(120deg); }}
    66% {{ transform: translate(-20px, 20px) rotate(240deg); }}
  }}

  /* Layout with enhanced sidebar */
  .page {{ 
    display: grid; 
    grid-template-columns: 360px minmax(0,1fr); 
    gap: 0; 
    min-height: 100vh;
  }}

  #sidebar {{
    position: sticky; 
    top: 0; 
    align-self: start;
    height: 100vh; 
    overflow: auto;
    background: var(--bg-sidebar);
    border-right: 2px solid var(--border-light);
    backdrop-filter: blur(10px);
    box-shadow: var(--shadow-lg);
  }}
  
  #sidebar::-webkit-scrollbar {{
    width: 8px;
  }}
  
  #sidebar::-webkit-scrollbar-track {{
    background: transparent;
  }}
  
  #sidebar::-webkit-scrollbar-thumb {{
    background: var(--border-medium);
    border-radius: 4px;
  }}
  
  #sidebar::-webkit-scrollbar-thumb:hover {{
    background: var(--border-strong);
  }}

  #sidebar .sidebar-inner {{ 
    padding: 2rem 1.5rem; 
  }}

  #sidebar h2 {{ 
    margin: 0 0 1.5rem 0; 
    font-size: 1.25rem; 
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }}

  #sidebar h2::before {{
    content: '📋';
    font-size: 1.5rem;
  }}

  .toc {{ 
    list-style: none; 
    padding-left: 0; 
    margin: 0; 
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.85rem;
    line-height: 1.4;
  }}

  .toc li {{ 
    margin-bottom: 0.25rem;
    transition: all 0.2s ease;
  }}

  .toc li:hover {{
    background: rgba(255, 255, 255, 0.7);
    border-radius: var(--radius-sm);
  }}

  .toc-directory {{
    margin-bottom: 0.1rem;
  }}

  .toc-directory .directory-name {{
    display: block;
    padding: 0.4rem 0.75rem;
    color: var(--text-primary);
    font-weight: 600;
    font-size: 0.8rem;
    white-space: pre;
    cursor: default;
  }}

  .toc-file {{
    margin-left: 0;
  }}

  .toc-file a {{ 
    text-decoration: none; 
    color: var(--text-secondary);
    display: block;
    padding: 0.35rem 0.75rem;
    border-radius: var(--radius-sm);
    font-weight: 400;
    font-size: 0.8rem;
    transition: all 0.2s ease;
    position: relative;
    overflow: hidden;
    white-space: pre;
    font-family: inherit;
  }}

  .toc-file a::before {{
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    height: 100%;
    width: 2px;
    background: var(--primary-gradient);
    transform: scaleY(0);
    transition: transform 0.2s ease;
  }}

  .toc-file a:hover {{
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.9);
    box-shadow: var(--shadow-sm);
    transform: translateX(2px);
  }}

  .toc-file a:hover::before {{
    transform: scaleY(1);
  }}

  /* Special styling for root files */
  .toc-file[data-depth="1"] a {{
    font-weight: 500;
  }}

  /* Deeper nesting gets slightly muted */
  .toc-file[data-depth="3"] a,
  .toc-file[data-depth="4"] a {{
    color: var(--text-tertiary);
    font-size: 0.75rem;
  }}

  .muted {{ 
    color: var(--text-tertiary); 
    font-weight: 400; 
    font-size: 0.85em; 
  }}

  main.container {{ 
    padding: 2rem; 
    background: var(--bg-primary);
    border-radius: var(--radius-lg) 0 0 var(--radius-lg);
    margin-left: -1rem;
    box-shadow: var(--shadow-lg);
    position: relative;
    z-index: 1;
  }}

  /* Header section with gradient */
  .header-section {{
    background: var(--primary-gradient);
    color: white;
    padding: 3rem;
    margin: -2rem -2rem 2rem -2rem;
    border-radius: var(--radius-lg) 0 0 0;
    position: relative;
    overflow: hidden;
  }}

  .header-section::before {{
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><pattern id="grain" width="100" height="100" patternUnits="userSpaceOnUse"><circle cx="25" cy="25" r="1" fill="rgba(255,255,255,0.1)"/><circle cx="75" cy="75" r="1" fill="rgba(255,255,255,0.1)"/><circle cx="50" cy="10" r="0.5" fill="rgba(255,255,255,0.05)"/><circle cx="10" cy="50" r="0.5" fill="rgba(255,255,255,0.05)"/><circle cx="90" cy="30" r="0.5" fill="rgba(255,255,255,0.05)"/></pattern></defs><rect width="100" height="100" fill="url(%23grain)"/></svg>');
    opacity: 0.3;
  }}

  .header-content {{
    position: relative;
    z-index: 1;
  }}

  .repo-title {{
    font-size: 2rem;
    font-weight: 700;
    margin: 0 0 1rem 0;
    display: flex;
    align-items: center;
    gap: 1rem;
  }}

  .repo-title::before {{
    content: '🚀';
    font-size: 2.5rem;
    animation: pulse 2s infinite;
  }}

  @keyframes pulse {{
    0%, 100% {{ transform: scale(1); }}
    50% {{ transform: scale(1.1); }}
  }}

  .meta {{
    font-size: 1rem;
    opacity: 0.9;
  }}

  .meta a {{
    color: rgba(255, 255, 255, 0.9);
    text-decoration: none;
    border-bottom: 1px dotted rgba(255, 255, 255, 0.5);
    transition: all 0.2s ease;
  }}

  .meta a:hover {{
    color: white;
    border-bottom-color: white;
  }}

  .counts {{
    margin-top: 1rem;
    font-size: 0.95rem;
    background: rgba(255, 255, 255, 0.1);
    backdrop-filter: blur(10px);
    padding: 1rem 1.5rem;
    border-radius: var(--radius-md);
    border: 1px solid rgba(255, 255, 255, 0.2);
  }}

  /* View toggle with enhanced styling */
  .view-toggle {{ 
    margin: 2rem 0; 
    display: flex; 
    gap: 0.5rem; 
    align-items: center;
    background: var(--bg-secondary);
    padding: 0.5rem;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-sm);
    border: 1px solid var(--border-light);
  }}

  .view-toggle strong {{
    margin-right: 0.5rem;
    color: var(--text-secondary);
    font-weight: 600;
  }}

  .toggle-btn {{ 
    padding: 0.75rem 1.5rem; 
    border: none; 
    background: white;
    cursor: pointer; 
    border-radius: var(--radius-sm);
    font-size: 0.9rem;
    font-weight: 500;
    transition: all 0.2s ease;
    position: relative;
    overflow: hidden;
  }}

  .toggle-btn::before {{
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: var(--primary-gradient);
    opacity: 0;
    transition: opacity 0.2s ease;
  }}

  .toggle-btn span {{
    position: relative;
    z-index: 1;
  }}

  .toggle-btn.active {{ 
    background: var(--primary-gradient);
    color: white;
    box-shadow: var(--shadow-md);
    transform: translateY(-1px);
  }}

  .toggle-btn:hover:not(.active) {{ 
    background: var(--bg-tertiary);
    transform: translateY(-1px);
    box-shadow: var(--shadow-sm);
  }}

  /* Enhanced sections */
  .content-section {{
    background: white;
    margin: 2rem 0;
    padding: 2rem;
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-md);
    border: 1px solid var(--border-light);
    transition: all 0.2s ease;
  }}

  .content-section:hover {{
    box-shadow: var(--shadow-lg);
    transform: translateY(-2px);
  }}

  .content-section h2 {{
    margin: 0 0 1.5rem 0;
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding-bottom: 1rem;
    border-bottom: 2px solid var(--border-light);
  }}

  /* Enhanced code styling */
  pre {{ 
    background: var(--bg-code);
    color: var(--text-code);
    padding: 1.5rem; 
    overflow: auto; 
    border-radius: var(--radius-md);
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.875rem;
    line-height: 1.5;
    box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.1);
    position: relative;
  }}

  pre::before {{
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--primary-gradient);
    border-radius: var(--radius-md) var(--radius-md) 0 0;
  }}

  code {{ 
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.875rem;
  }}

  .highlight {{ 
    overflow-x: auto;
    background: var(--bg-code) !important;
    border-radius: var(--radius-md);
    position: relative;
  }}

  .highlight::before {{
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--success-gradient);
    border-radius: var(--radius-md) var(--radius-md) 0 0;
  }}

  /* File sections with enhanced styling */
  .file-section {{ 
    background: white;
    margin: 1.5rem 0;
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-md);
    border: 1px solid var(--border-light);
    overflow: hidden;
    transition: all 0.3s ease;
  }}

  .file-section:hover {{
    box-shadow: var(--shadow-xl);
    transform: translateY(-4px);
  }}

  .file-section h2 {{ 
    margin: 0;
    font-size: 1.25rem;
    font-weight: 600;
    padding: 1.5rem 2rem;
    background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-tertiary) 100%);
    border-bottom: 1px solid var(--border-light);
    display: flex;
    align-items: center;
    gap: 1rem;
    position: relative;
  }}

  .file-section h2::before {{
    content: attr(data-icon);
    font-size: 1.5rem;
  }}

  .file-body {{ 
    padding: 2rem;
  }}

  .back-top {{ 
    padding: 1rem 2rem;
    text-align: right;
    background: var(--bg-secondary);
    border-top: 1px solid var(--border-light);
  }}

  .back-top a {{
    color: var(--text-accent);
    text-decoration: none;
    font-weight: 500;
    padding: 0.5rem 1rem;
    border-radius: var(--radius-sm);
    transition: all 0.2s ease;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
  }}

  .back-top a:hover {{
    background: var(--primary-gradient);
    color: white;
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
  }}

  /* Enhanced skip lists */
  .skip-section {{
    background: linear-gradient(135deg, rgba(250, 112, 154, 0.1) 0%, rgba(254, 225, 64, 0.1) 100%);
    border: 1px solid rgba(250, 112, 154, 0.2);
    border-radius: var(--radius-lg);
    padding: 2rem;
  }}

  .skip-list {{ 
    list-style: none;
    padding: 0;
    margin: 0;
  }}

  .skip-list li {{
    padding: 0.75rem 1rem;
    margin: 0.5rem 0;
    background: rgba(255, 255, 255, 0.7);
    border-radius: var(--radius-sm);
    border-left: 4px solid var(--danger-gradient);
    transition: all 0.2s ease;
  }}

  .skip-list li:hover {{
    background: white;
    transform: translateX(4px);
    box-shadow: var(--shadow-sm);
  }}

  .skip-list code {{ 
    background: rgba(15, 23, 42, 0.1);
    color: var(--text-primary);
    padding: 0.25rem 0.5rem; 
    border-radius: 4px;
    font-weight: 500;
  }}

  .error {{ 
    color: #dc2626;
    background: linear-gradient(135deg, rgba(220, 38, 38, 0.1) 0%, rgba(239, 68, 68, 0.1) 100%);
    border: 1px solid rgba(220, 38, 38, 0.2);
    border-radius: var(--radius-md);
    padding: 1rem;
  }}

  /* Details/Summary styling */
  details {{
    margin: 1rem 0;
    border-radius: var(--radius-md);
    overflow: hidden;
  }}

  summary {{
    background: var(--bg-secondary);
    padding: 1rem 1.5rem;
    cursor: pointer;
    font-weight: 600;
    color: var(--text-primary);
    border: 1px solid var(--border-light);
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }}

  summary:hover {{
    background: var(--bg-tertiary);
  }}

  summary::before {{
    content: '📂';
    font-size: 1.2rem;
  }}

  details[open] summary {{
    background: var(--primary-gradient);
    color: white;
    border-color: transparent;
  }}

  details[open] summary::before {{
    content: '📁';
  }}

  /* Hide duplicate top TOC on wide screens */
  .toc-top {{ display: block; }}
  @media (min-width: 1200px) {{ .toc-top {{ display: none; }} }}

  :target {{ scroll-margin-top: 100px; }}

  /* LLM view enhancements */
  #llm-view {{ display: none; }}
  
  #llm-text {{ 
    width: 100%; 
    height: 70vh; 
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.875rem;
    border: 2px solid var(--border-light);
    border-radius: var(--radius-lg);
    padding: 2rem;
    resize: vertical;
    background: var(--bg-code);
    color: var(--text-code);
    line-height: 1.5;
    box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.1);
  }}

  .copy-hint {{ 
    margin-top: 1rem; 
    color: var(--text-tertiary); 
    font-size: 0.9em;
    text-align: center;
    padding: 1rem;
    background: var(--bg-tertiary);
    border-radius: var(--radius-md);
    border: 1px solid var(--border-light);
  }}

  /* Copy button styling */
  .copy-code-btn {{
    position: absolute;
    top: 1rem;
    right: 1rem;
    background: var(--primary-gradient);
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: 6px;
    font-size: 0.8rem;
    cursor: pointer;
    opacity: 0;
    transition: all 0.2s ease;
    z-index: 10;
    font-family: 'Inter', sans-serif;
    font-weight: 500;
  }}

  .file-body:hover .copy-code-btn {{
    opacity: 1;
  }}

  .copy-code-btn:hover {{
    opacity: 1 !important;
    transform: translateY(-1px);
    box-shadow: var(--shadow-md);
  }}

  /* Responsive design */
  @media (max-width: 1200px) {{
    .page {{
      grid-template-columns: 280px minmax(0,1fr);
    }}
    
    .container {{
      padding: 0 1rem;
    }}
    
    main.container {{
      padding: 1.5rem;
    }}
    
    .header-section {{
      padding: 2rem;
      margin: -1.5rem -1.5rem 1.5rem -1.5rem;
    }}
    
    .repo-title {{
      font-size: 1.75rem;
    }}
  }}

  @media (max-width: 768px) {{
    .page {{
      grid-template-columns: 1fr;
      gap: 0;
    }}
    
    #sidebar {{
      position: fixed;
      top: 0;
      left: -100%;
      width: 280px;
      height: 100vh;
      z-index: 1000;
      transition: left 0.3s ease;
      border-right: 2px solid var(--border-light);
    }}
    
    #sidebar.open {{
      left: 0;
    }}
    
    .sidebar-overlay {{
      display: none;
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.5);
      z-index: 999;
      backdrop-filter: blur(4px);
    }}
    
    .sidebar-overlay.show {{
      display: block;
    }}
    
    .mobile-nav {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 1rem;
      background: var(--bg-primary);
      border-bottom: 1px solid var(--border-light);
      position: sticky;
      top: 0;
      z-index: 100;
      box-shadow: var(--shadow-sm);
    }}
    
    .mobile-nav-btn {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.75rem 1rem;
      background: var(--primary-gradient);
      color: white;
      border: none;
      border-radius: var(--radius-md);
      font-size: 0.9rem;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s ease;
    }}
    
    .mobile-nav-btn:hover {{
      transform: translateY(-1px);
      box-shadow: var(--shadow-md);
    }}
    
    .mobile-nav-title {{
      font-size: 1rem;
      font-weight: 600;
      color: var(--text-primary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 60%;
    }}
    
    main.container {{
      order: 1;
      margin-left: 0;
      border-radius: 0;
      padding: 1rem;
    }}
    
    .header-section {{
      border-radius: 0;
      padding: 2rem 1rem;
      margin: -1rem -1rem 1rem -1rem;
    }}
    
    .repo-title {{
      font-size: 1.5rem;
      flex-direction: column;
      align-items: flex-start;
      gap: 0.5rem;
    }}
    
    .repo-title::before {{
      font-size: 2rem;
    }}
    
    .meta {{
      font-size: 0.9rem;
    }}
    
    .counts {{
      font-size: 0.85rem;
      padding: 0.75rem 1rem;
    }}
    
    .view-toggle {{
      flex-wrap: wrap;
      gap: 0.25rem;
      padding: 0.25rem;
    }}
    
    .toggle-btn {{
      padding: 0.5rem 1rem;
      font-size: 0.85rem;
    }}
    
    .content-section {{
      padding: 1.5rem;
      margin: 1.5rem 0;
    }}
    
    .content-section h2 {{
      font-size: 1.25rem;
    }}
    
    .file-section {{
      margin: 1rem 0;
    }}
    
    .file-section h2 {{
      font-size: 1.1rem;
      padding: 1rem 1.5rem;
    }}
    
    .file-body {{
      padding: 1.5rem;
    }}
    
    .back-top {{
      padding: 0.75rem 1.5rem;
    }}
    
    pre {{
      padding: 1rem;
      font-size: 0.8rem;
    }}
    
    .highlight {{
      font-size: 0.8rem;
    }}
    
    #llm-text {{
      height: 60vh;
      padding: 1rem;
      font-size: 0.8rem;
    }}
    
    .copy-hint {{
      font-size: 0.85rem;
      padding: 0.75rem;
    }}
    
    /* Hide desktop TOC on mobile */
    .toc-top {{
      display: none;
    }}
  }}

  @media (max-width: 480px) {{
    #sidebar {{
      width: 100%;
      left: -100%;
    }}
    
    .mobile-nav {{
      padding: 0.75rem;
    }}
    
    .mobile-nav-btn {{
      padding: 0.5rem 0.75rem;
      font-size: 0.85rem;
    }}
    
    .mobile-nav-title {{
      font-size: 0.9rem;
      max-width: 50%;
    }}
    
    main.container {{
      padding: 0.75rem;
    }}
    
    .header-section {{
      padding: 1.5rem 0.75rem;
      margin: -0.75rem -0.75rem 1rem -0.75rem;
    }}
    
    .repo-title {{
      font-size: 1.25rem;
    }}
    
    .content-section {{
      padding: 1rem;
    }}
    
    .file-section h2 {{
      padding: 0.75rem 1rem;
      font-size: 1rem;
    }}
    
    .file-body {{
      padding: 1rem;
    }}
    
    .back-top {{
      padding: 0.5rem 1rem;
    }}
    
    pre {{
      padding: 0.75rem;
      font-size: 0.75rem;
    }}
    
    .highlight {{
      font-size: 0.75rem;
    }}
    
    #llm-text {{
      height: 50vh;
      padding: 0.75rem;
      font-size: 0.75rem;
    }}
  }}

  /* Show mobile navigation only on mobile */
  .mobile-nav {{
    display: none;
  }}
  
  @media (max-width: 768px) {{
    .mobile-nav {{
      display: flex;
    }}
  }}

  /* Pygments theme overrides */
  .highlight pre {{
    background: var(--bg-code) !important;
    color: var(--text-code) !important;
  }}

  /* Custom pygments styling */
  {pygments_css}
  
  /* Markdown content styling */
  .markdown-content {{
    font-size: 1rem;
    line-height: 1.7;
  }}
  
  .markdown-content h1, .markdown-content h2, .markdown-content h3,
  .markdown-content h4, .markdown-content h5, .markdown-content h6 {{
    margin-top: 2rem;
    margin-bottom: 1rem;
    font-weight: 700;
    line-height: 1.25;
    color: var(--text-primary);
  }}
  
  .markdown-content h1 {{ font-size: 2rem; border-bottom: 3px solid var(--border-light); padding-bottom: 0.5rem; }}
  .markdown-content h2 {{ font-size: 1.75rem; border-bottom: 2px solid var(--border-light); padding-bottom: 0.5rem; }}
  .markdown-content h3 {{ font-size: 1.5rem; }}
  .markdown-content h4 {{ font-size: 1.25rem; }}
  .markdown-content h5 {{ font-size: 1.125rem; }}
  .markdown-content h6 {{ font-size: 1rem; color: var(--text-secondary); }}
  
  .markdown-content p {{
    margin-bottom: 1.25rem;
  }}
  
  .markdown-content ul, .markdown-content ol {{
    margin-bottom: 1.25rem;
    padding-left: 2rem;
  }}
  
  .markdown-content li {{
    margin-bottom: 0.5rem;
  }}
  
  .markdown-content blockquote {{
    border-left: 4px solid var(--primary-gradient);
    padding-left: 1.5rem;
    margin: 1.5rem 0;
    font-style: italic;
    color: var(--text-secondary);
    background: linear-gradient(135deg, rgba(102, 126, 234, 0.05) 0%, rgba(118, 75, 162, 0.05) 100%);
    padding: 1rem 1.5rem;
    border-radius: var(--radius-md);
  }}
  
  .markdown-content table {{
    width: 100%;
    margin: 1.5rem 0;
    border-collapse: collapse;
    border-radius: var(--radius-md);
    overflow: hidden;
    box-shadow: var(--shadow-sm);
  }}
  
  .markdown-content th, .markdown-content td {{
    padding: 1rem;
    text-align: left;
    border-bottom: 1px solid var(--border-light);
  }}
  
  .markdown-content th {{
    background: var(--primary-gradient);
    color: white;
    font-weight: 600;
  }}
  
  .markdown-content tr:nth-child(even) {{
    background: var(--bg-secondary);
  }}
  
  .markdown-content a {{
    color: var(--text-accent);
    text-decoration: none;
    border-bottom: 1px dotted var(--text-accent);
    transition: all 0.2s ease;
  }}
  
  .markdown-content a:hover {{
    color: var(--text-primary);
    border-bottom-color: var(--text-primary);
  }}
  
  .markdown-content img {{
    max-width: 100%;
    height: auto;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-md);
    margin: 1rem 0;
  }}
  
  .markdown-content hr {{
    border: none;
    height: 2px;
    background: var(--primary-gradient);
    margin: 2rem 0;
    border-radius: 1px;
  }}
</style>
</head>
<body>
<div class="bg-decoration"></div>
<a id="top"></a>

<!-- Mobile Navigation -->
<div class="mobile-nav">
  <button class="mobile-nav-btn" onclick="toggleSidebar()">
    <span>📋</span>
    <span>Files</span>
  </button>
  <div class="mobile-nav-title">Repository Explorer</div>
</div>

<!-- Sidebar Overlay for Mobile -->
<div class="sidebar-overlay" onclick="closeSidebar()"></div>

<div class="page">
  <nav id="sidebar"><div class="sidebar-inner">
      <h2>Contents ({len(rendered)})</h2>
      <ul class="toc toc-sidebar">
        <li><a href="#top">↑ Back to top</a></li>
        {toc_html}
      </ul>
  </div></nav>

  <main class="container">
    <div class="header-section">
      <div class="header-content">
        <h1 class="repo-title">Repository Explorer</h1>
        <div class="meta">
          <div><strong>📍 Repository:</strong> <a href="{html.escape(repo_url)}" target="_blank" rel="noopener">{html.escape(repo_url)}</a></div>
          <div><strong>🔗 HEAD commit:</strong> <code>{html.escape(head_commit[:12])}</code></div>
          <div class="counts">
            <strong>📊 Statistics:</strong> {total_files} total files • {len(rendered)} rendered • {len(skipped_binary) + len(skipped_large) + len(skipped_ignored)} skipped
          </div>
        </div>
      </div>
    </div>

    <div class="view-toggle">
      <strong>View Mode:</strong>
      <button class="toggle-btn active" onclick="showHumanView(this)"><span>👤 Human Readable</span></button>
      <button class="toggle-btn" onclick="showLLMView(this)"><span>🤖 LLM Format</span></button>
    </div>

    <div id="human-view">
      <div class="content-section">
        <h2>🌳 Directory Structure</h2>
        <pre>{html.escape(tree_text)}</pre>
      </div>

      <div class="content-section toc-top">
        <h2>📋 File Index ({len(rendered)} files)</h2>
        <ul class="toc">{toc_html}</ul>
      </div>

      <div class="content-section skip-section">
        <h2>⚠️ Excluded Files</h2>
        {skipped_html}
      </div>

      <div style="margin-top: 2rem;">
        {''.join(sections)}
      </div>
    </div>

    <div id="llm-view">
      <div class="content-section">
        <h2>🤖 LLM-Optimized View</h2>
        <p style="margin-bottom: 1.5rem; color: var(--text-secondary); line-height: 1.6;">
          This view presents the repository content in CXML format, optimized for Large Language Model analysis. 
          Simply copy the content below and paste it into your preferred LLM interface.
        </p>
        <textarea id="llm-text" readonly>{html.escape(cxml_text)}</textarea>
        <div class="copy-hint">
          💡 <strong>Pro tip:</strong> Click in the text area above and use <kbd>Ctrl+A</kbd> (or <kbd>Cmd+A</kbd> on Mac) to select all content, then <kbd>Ctrl+C</kbd> (or <kbd>Cmd+C</kbd>) to copy to clipboard.
        </div>
      </div>
    </div>
  </main>
</div>

<script>
// Mobile sidebar functionality
function toggleSidebar() {{
  const sidebar = document.getElementById('sidebar');
  const overlay = document.querySelector('.sidebar-overlay');
  
  if (sidebar && overlay) {{
    sidebar.classList.toggle('open');
    overlay.classList.toggle('show');
  }}
}}

function closeSidebar() {{
  const sidebar = document.getElementById('sidebar');
  const overlay = document.querySelector('.sidebar-overlay');
  
  if (sidebar && overlay) {{
    sidebar.classList.remove('open');
    overlay.classList.remove('show');
  }}
}}

// Enhanced view switching with smooth transitions
function showHumanView(buttonElement) {{
  const humanView = document.getElementById('human-view');
  const llmView = document.getElementById('llm-view');
  const toggleBtns = document.querySelectorAll('.toggle-btn');
  
  if (!humanView || !llmView) return;
  
  // Update button states first
  toggleBtns.forEach(btn => btn.classList.remove('active'));
  if (buttonElement) {{
    buttonElement.classList.add('active');
  }} else {{
    document.querySelector('.toggle-btn:first-of-type').classList.add('active');
  }}
  
  // Fade out current view
  llmView.style.opacity = '0';
  llmView.style.transform = 'translateY(20px)';
  
  setTimeout(() => {{
    llmView.style.display = 'none';
    humanView.style.display = 'block';
    humanView.style.opacity = '0';
    humanView.style.transform = 'translateY(20px)';
    
    // Fade in new view
    requestAnimationFrame(() => {{
      humanView.style.transition = 'all 0.3s ease';
      humanView.style.opacity = '1';
      humanView.style.transform = 'translateY(0)';
    }});
  }}, 150);
}}

function showLLMView(buttonElement) {{
  const humanView = document.getElementById('human-view');
  const llmView = document.getElementById('llm-view');
  const toggleBtns = document.querySelectorAll('.toggle-btn');
  
  if (!humanView || !llmView) return;
  
  // Update button states first
  toggleBtns.forEach(btn => btn.classList.remove('active'));
  if (buttonElement) {{
    buttonElement.classList.add('active');
  }} else {{
    document.querySelector('.toggle-btn:last-of-type').classList.add('active');
  }}
  
  // Fade out current view
  humanView.style.opacity = '0';
  humanView.style.transform = 'translateY(20px)';
  
  setTimeout(() => {{
    humanView.style.display = 'none';
    llmView.style.display = 'block';
    llmView.style.opacity = '0';
    llmView.style.transform = 'translateY(20px)';
    
    // Fade in new view
    requestAnimationFrame(() => {{
      llmView.style.transition = 'all 0.3s ease';
      llmView.style.opacity = '1';
      llmView.style.transform = 'translateY(0)';
    }});
    
    // Auto-select all text when switching to LLM view for easy copying
    setTimeout(() => {{
      const textArea = document.getElementById('llm-text');
      if (textArea) {{
        textArea.focus();
        textArea.select();
      }}
    }}, 300);
  }}, 150);
}}

// Smooth scrolling for anchor links
document.addEventListener('DOMContentLoaded', function() {{
  // Add smooth scrolling to all anchor links
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {{
    anchor.addEventListener('click', function (e) {{
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {{
        target.scrollIntoView({{
          behavior: 'smooth',
          block: 'start'
        }});
        
        // Close sidebar on mobile after navigation
        if (window.innerWidth <= 768) {{
          closeSidebar();
        }}
      }}
    }});
  }});
  
  // Add loading animation
  document.body.style.opacity = '0';
  requestAnimationFrame(() => {{
    document.body.style.transition = 'opacity 0.5s ease';
    document.body.style.opacity = '1';
  }});
  
  // Add intersection observer for fade-in animations
  const observer = new IntersectionObserver((entries) => {{
    entries.forEach(entry => {{
      if (entry.isIntersecting) {{
        entry.target.style.opacity = '1';
        entry.target.style.transform = 'translateY(0)';
      }}
    }});
  }}, {{ threshold: 0.1 }});
  
  // Observe file sections for fade-in effect
  document.querySelectorAll('.file-section').forEach(section => {{
    section.style.opacity = '0';
    section.style.transform = 'translateY(30px)';
    section.style.transition = 'all 0.6s ease';
    observer.observe(section);
  }});
  
  // Close sidebar when clicking outside on mobile
  document.addEventListener('click', function(e) {{
    if (window.innerWidth <= 768) {{
      const sidebar = document.getElementById('sidebar');
      const mobileNavBtn = document.querySelector('.mobile-nav-btn');
      
      if (sidebar && sidebar.classList.contains('open') && 
          !sidebar.contains(e.target) && 
          !mobileNavBtn.contains(e.target)) {{
        closeSidebar();
      }}
    }}
  }});
  
  // Handle window resize
  window.addEventListener('resize', function() {{
    if (window.innerWidth > 768) {{
      closeSidebar();
    }}
  }});
  
  // Add copy to clipboard functionality for code blocks
  document.querySelectorAll('.file-section').forEach(fileSection => {{
    const codeBlock = fileSection.querySelector('.highlight');
    if (!codeBlock) return;
    
    // Check if copy button already exists
    if (fileSection.querySelector('.copy-code-btn')) return;
    
    const copyBtn = document.createElement('button');
    copyBtn.textContent = '📋 Copy';
    copyBtn.className = 'copy-code-btn';
    
    const fileBody = fileSection.querySelector('.file-body');
    if (fileBody && codeBlock) {{
      fileBody.style.position = 'relative';
      fileBody.appendChild(copyBtn);
      
      copyBtn.addEventListener('click', (e) => {{
        e.preventDefault();
        e.stopPropagation();
        const code = codeBlock.textContent || '';
        
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          navigator.clipboard.writeText(code).then(() => {{
            copyBtn.textContent = '✅ Copied!';
            copyBtn.style.background = 'var(--success-gradient)';
            setTimeout(() => {{
              copyBtn.textContent = '📋 Copy';
              copyBtn.style.background = 'var(--primary-gradient)';
            }}, 2000);
          }}).catch(() => {{
            // Fallback for clipboard API failure
            fallbackCopy(code, copyBtn);
          }});
        }} else {{
          // Fallback for browsers without clipboard API
          fallbackCopy(code, copyBtn);
        }}
      }});
    }}
  }});
  
  // Fallback copy function
  function fallbackCopy(text, button) {{
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    textArea.style.top = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {{
      document.execCommand('copy');
      button.textContent = '✅ Copied!';
      button.style.background = 'var(--success-gradient)';
    }} catch (err) {{
      button.textContent = '❌ Failed';
      button.style.background = 'var(--danger-gradient)';
    }}
    
    document.body.removeChild(textArea);
    setTimeout(() => {{
      button.textContent = '📋 Copy';
      button.style.background = 'var(--primary-gradient)';
    }}, 2000);
  }}
}});

// Add keyboard shortcuts
document.addEventListener('keydown', function(e) {{
  // Alt + 1 for Human view
  if (e.altKey && e.key === '1') {{
    e.preventDefault();
    const btn = document.querySelector('.toggle-btn:first-of-type');
    if (btn) showHumanView(btn);
  }}
  
  // Alt + 2 for LLM view
  if (e.altKey && e.key === '2') {{
    e.preventDefault();
    const btn = document.querySelector('.toggle-btn:last-of-type');
    if (btn) showLLMView(btn);
  }}
  
  // Ctrl/Cmd + K to focus search (if we add it later)
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {{
    e.preventDefault();
    // Focus search functionality could be added here
  }}
}});
</script>
</body>
</html>
"""


def derive_temp_output_path(repo_url: str) -> pathlib.Path:
    """Derive a temporary output path from the repo URL."""
    # Extract repo name from URL like https://github.com/owner/repo or https://github.com/owner/repo.git
    parts = repo_url.rstrip('/').split('/')
    if len(parts) >= 2:
        repo_name = parts[-1]
        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]
        filename = f"{repo_name}.html"
    else:
        filename = "repo.html"
    
    return pathlib.Path(tempfile.gettempdir()) / filename


def main() -> int:
    ap = argparse.ArgumentParser(description="Flatten a GitHub repo to a single HTML page")
    ap.add_argument("repo_url", help="GitHub repo URL (https://github.com/owner/repo[.git])")
    ap.add_argument("-o", "--out", help="Output HTML file path (default: temporary file derived from repo name)")
    ap.add_argument("--max-bytes", type=int, default=MAX_DEFAULT_BYTES, help="Max file size to render (bytes); larger files are listed but skipped")
    ap.add_argument("--no-open", action="store_true", help="Don't open the HTML file in browser after generation")
    args = ap.parse_args()
    
    # Set default output path if not provided
    if args.out is None:
        args.out = str(derive_temp_output_path(args.repo_url))

    tmpdir = tempfile.mkdtemp(prefix="flatten_repo_")
    repo_dir = pathlib.Path(tmpdir, "repo")

    try:
        print(f"📁 Cloning {args.repo_url} to temporary directory: {repo_dir}", file=sys.stderr)
        git_clone(args.repo_url, str(repo_dir))
        head = git_head_commit(str(repo_dir))
        print(f"✓ Clone complete (HEAD: {head[:8]})", file=sys.stderr)

        print(f"📊 Scanning files in {repo_dir}...", file=sys.stderr)
        infos = collect_files(repo_dir, args.max_bytes)
        rendered_count = sum(1 for i in infos if i.decision.include)
        skipped_count = len(infos) - rendered_count
        print(f"✓ Found {len(infos)} files total ({rendered_count} will be rendered, {skipped_count} skipped)", file=sys.stderr)
        
        print(f"🔨 Generating HTML...", file=sys.stderr)
        html_out = build_html(args.repo_url, repo_dir, head, infos)

        out_path = pathlib.Path(args.out)
        print(f"💾 Writing HTML file: {out_path.resolve()}", file=sys.stderr)
        out_path.write_text(html_out, encoding="utf-8")
        file_size = out_path.stat().st_size
        print(f"✓ Wrote {bytes_human(file_size)} to {out_path}", file=sys.stderr)
        
        if not args.no_open:
            print(f"🌐 Opening {out_path} in browser...", file=sys.stderr)
            webbrowser.open(f"file://{out_path.resolve()}")
        
        print(f"🗑️  Cleaning up temporary directory: {tmpdir}", file=sys.stderr)
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
