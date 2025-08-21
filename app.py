#!/usr/bin/env python3
"""
Flask web app for rendergit with caching and repo cards
"""

import os
import json
import time
import hashlib
import tempfile
from datetime import datetime, timedelta
from flask import Flask, request, Response
from pathlib import Path

# Import from original CLI
from repo_to_single_page import (
    git_clone, git_head_commit, collect_files, 
    build_html, MAX_DEFAULT_BYTES
)

app = Flask(__name__)

# Cache configuration
CACHE_DIR = Path('/tmp/rendergit_cache')
CACHE_DIR.mkdir(exist_ok=True)
CACHE_METADATA = CACHE_DIR / 'metadata.json'
CACHE_TTL_HOURS = 24  # Cache for 24 hours
MAX_CACHED_REPOS = 100  # Keep last 100 repos

def get_cache_key(repo_url):
    """Generate cache key from repo URL"""
    return hashlib.md5(repo_url.encode()).hexdigest()

def load_metadata():
    """Load cache metadata"""
    if CACHE_METADATA.exists():
        try:
            with open(CACHE_METADATA, 'r') as f:
                return json.load(f)
        except:
            pass
    return {'repos': {}}

def save_metadata(metadata):
    """Save cache metadata"""
    with open(CACHE_METADATA, 'w') as f:
        json.dump(metadata, f)

def cleanup_old_cache():
    """Remove old cached items"""
    metadata = load_metadata()
    now = time.time()
    cutoff_time = now - (CACHE_TTL_HOURS * 3600)
    
    # Remove expired entries
    expired = []
    for key, info in metadata['repos'].items():
        if info['timestamp'] < cutoff_time:
            expired.append(key)
            cache_file = CACHE_DIR / f"{key}.html"
            cache_file.unlink(missing_ok=True)
    
    for key in expired:
        del metadata['repos'][key]
    
    # Keep only last N repos if exceeded
    if len(metadata['repos']) > MAX_CACHED_REPOS:
        sorted_repos = sorted(metadata['repos'].items(), 
                            key=lambda x: x[1]['timestamp'])
        for key, _ in sorted_repos[:-MAX_CACHED_REPOS]:
            del metadata['repos'][key]
            cache_file = CACHE_DIR / f"{key}.html"
            cache_file.unlink(missing_ok=True)
    
    save_metadata(metadata)

@app.route('/')
def index():
    """Show homepage with repo cards"""
    metadata = load_metadata()
    repos = metadata.get('repos', {})
    
    # Sort by most recent
    sorted_repos = sorted(repos.items(), 
                         key=lambda x: x[1]['timestamp'], 
                         reverse=True)
    
    cards_html = ''
    for key, info in sorted_repos[:20]:  # Show last 20
        time_ago = datetime.fromtimestamp(info['timestamp']).strftime('%Y-%m-%d %H:%M')
        cards_html += f'''
        <div class="card">
            <h3><a href="/{info['path']}">{info['name']}</a></h3>
            <p class="url">{info['url']}</p>
            <p class="meta">
                <span>⭐ {info.get('stars', 'N/A')}</span>
                <span>📅 Cached: {time_ago}</span>
            </p>
        </div>
        '''
    
    if not cards_html:
        cards_html = '<p class="empty">No repositories cached yet. Try <a href="/github.com/karpathy/nanoGPT">this example</a></p>'
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>rendergit</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #0d1117;
                color: #c9d1d9;
                margin: 0;
                padding: 20px;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            h1 {{
                color: #58a6ff;
                text-align: center;
                margin-bottom: 10px;
            }}
            .subtitle {{
                text-align: center;
                color: #8b949e;
                margin-bottom: 30px;
            }}
            .input-group {{
                display: flex;
                gap: 10px;
                max-width: 600px;
                margin: 0 auto 40px;
            }}
            input {{
                flex: 1;
                padding: 12px;
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 6px;
                color: #c9d1d9;
                font-size: 16px;
            }}
            button {{
                padding: 12px 24px;
                background: #238636;
                color: white;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 16px;
            }}
            button:hover {{
                background: #2ea043;
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 20px;
                margin-top: 40px;
            }}
            .card {{
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 20px;
                transition: transform 0.2s;
            }}
            .card:hover {{
                transform: translateY(-2px);
                border-color: #58a6ff;
            }}
            .card h3 {{
                margin: 0 0 10px 0;
            }}
            .card a {{
                color: #58a6ff;
                text-decoration: none;
            }}
            .card a:hover {{
                text-decoration: underline;
            }}
            .url {{
                color: #8b949e;
                font-size: 14px;
                margin: 5px 0;
                word-break: break-all;
            }}
            .meta {{
                display: flex;
                gap: 20px;
                margin-top: 10px;
                font-size: 14px;
                color: #8b949e;
            }}
            .empty {{
                text-align: center;
                color: #8b949e;
                margin: 60px 0;
            }}
            .empty a {{
                color: #58a6ff;
            }}
            .info {{
                max-width: 600px;
                margin: 40px auto;
                text-align: center;
                color: #8b949e;
            }}
            code {{
                background: #161b22;
                padding: 2px 6px;
                border-radius: 3px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 rendergit</h1>
            <p class="subtitle">Flatten GitHub repositories into single HTML pages</p>
            
            <div class="input-group">
                <input type="text" id="url" placeholder="https://github.com/user/repo" 
                       onkeypress="if(event.key==='Enter') go()">
                <button onclick="go()">Render</button>
            </div>
            
            <div class="cards">
                {cards_html}
            </div>
            
            <div class="info">
                <p>Direct URL: <code>{request.host_url}github.com/user/repo</code></p>
                <p>Install locally: <code>pip install rendergit</code></p>
            </div>
        </div>
        
        <script>
        function go() {{
            const url = document.getElementById('url').value.trim();
            if (url) {{
                // Extract path from GitHub URL
                const path = url.replace(/^https?:\\/\\//, '');
                window.location.href = '/' + path;
            }}
        }}
        </script>
    </body>
    </html>
    '''

@app.route('/<path:repo_path>')
def render_repo(repo_path):
    """Render a repository with caching"""
    try:
        # Parse URL
        if repo_path.startswith('https://github.com/') or repo_path.startswith('http://github.com/'):
            repo_url = repo_path.replace('http://', 'https://')
        elif repo_path.startswith('github.com/'):
            repo_url = f'https://{repo_path}'
        else:
            return f'Invalid path. Use: {request.host_url}github.com/user/repo', 400
        
        # Check cache
        cache_key = get_cache_key(repo_url)
        cache_file = CACHE_DIR / f"{cache_key}.html"
        metadata = load_metadata()
        
        # Check if cached and not expired
        if cache_file.exists() and cache_key in metadata['repos']:
            cache_info = metadata['repos'][cache_key]
            if time.time() - cache_info['timestamp'] < (CACHE_TTL_HOURS * 3600):
                # Update access time
                cache_info['last_accessed'] = time.time()
                save_metadata(metadata)
                
                # Return cached content
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return f.read()
        
        # Generate fresh content
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = os.path.join(tmpdir, 'repo')
            git_clone(repo_url, repo_dir)
            
            commit = git_head_commit(repo_dir)
            repo_path_obj = Path(repo_dir)
            files = collect_files(repo_path_obj, MAX_DEFAULT_BYTES)
            
            html_content = build_html(repo_url, Path(repo_dir), commit, files)
            
            # Cache the result
            with open(cache_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Update metadata
            repo_name = repo_url.rstrip('/').split('/')[-1]
            metadata['repos'][cache_key] = {
                'url': repo_url,
                'path': repo_path,
                'name': repo_name,
                'timestamp': time.time(),
                'last_accessed': time.time(),
                'commit': commit[:8] if commit else 'unknown'
            }
            save_metadata(metadata)
            
            # Cleanup old cache periodically
            if len(metadata['repos']) % 10 == 0:
                cleanup_old_cache()
            
            return html_content
            
    except Exception as e:
        return f'''
        <html>
        <body style="font-family: sans-serif; padding: 40px; background: #0d1117; color: #c9d1d9;">
            <h1 style="color: #f85149;">Error</h1>
            <p>{str(e)}</p>
            <p>Usage: {request.host_url}github.com/user/repo</p>
            <a href="/" style="color: #58a6ff;">← Back to home</a>
        </body>
        </html>
        ''', 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)