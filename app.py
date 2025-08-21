#!/usr/bin/env python3
"""
Flask web app for rendergit with caching and repo cards
"""

import os
import sys
import json
import time
import hashlib
import tempfile
from datetime import datetime, timedelta
from flask import Flask, request, Response
from pathlib import Path

# Ensure current directory is in path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

@app.route('/loading/<path:repo_path>')
def loading_page(repo_path):
    """Show loading page while repo is being processed"""
    repo_name = repo_path.split('/')[-1]
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Loading {repo_name} - rendergit</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #0d1117;
                color: #c9d1d9;
                margin: 0;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                padding: 20px;
            }}
            .loading-container {{
                text-align: center;
                max-width: 500px;
            }}
            h1 {{
                color: #58a6ff;
                margin-bottom: 20px;
            }}
            .repo-name {{
                color: #58a6ff;
                font-weight: bold;
            }}
            .spinner {{
                width: 50px;
                height: 50px;
                margin: 30px auto;
                border: 3px solid #30363d;
                border-top: 3px solid #58a6ff;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }}
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
            .status {{
                color: #8b949e;
                margin: 20px 0;
            }}
            .steps {{
                text-align: left;
                display: inline-block;
                margin: 20px 0;
            }}
            .step {{
                padding: 8px 0;
                color: #6e7681;
            }}
            .step.active {{
                color: #58a6ff;
            }}
            .step.done {{
                color: #3fb950;
            }}
        </style>
    </head>
    <body>
        <div class="loading-container">
            <h1>🚀 rendergit</h1>
            <div class="spinner"></div>
            <p>Processing <span class="repo-name">{repo_name}</span></p>
            <div class="steps">
                <div class="step active" id="step1">📥 Cloning repository...</div>
                <div class="step" id="step2">📂 Collecting files...</div>
                <div class="step" id="step3">🎨 Rendering HTML...</div>
                <div class="step" id="step4">💾 Caching result...</div>
            </div>
            <p class="status">This may take a few moments for large repositories</p>
        </div>
        <script>
            // Animate through steps
            let currentStep = 1;
            const totalSteps = 4;
            
            setInterval(() => {{
                if (currentStep < totalSteps) {{
                    document.getElementById('step' + currentStep).classList.remove('active');
                    document.getElementById('step' + currentStep).classList.add('done');
                    currentStep++;
                    document.getElementById('step' + currentStep).classList.add('active');
                }}
            }}, 1500);
            
            // Actually load the content
            setTimeout(() => {{
                window.location.href = '/{repo_path}?process=true';
            }}, 100);
        </script>
    </body>
    </html>
    '''

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
        cards_html += f'''
        <a href="/{info['path']}" class="card-link">
            <div class="card">
                <h3>{info['name']}</h3>
                <p class="url">{info['url']}</p>
            </div>
        </a>
        '''
    
    if not cards_html:
        cards_html = '''<div class="empty">
            <p>No repositories rendered yet.</p>
            <p>Try one of the examples above or enter your own GitHub URL!</p>
        </div>'''
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>rendergit</title>
        <style>
            * {{
                box-sizing: border-box;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #0d1117;
                color: #c9d1d9;
                margin: 0;
                padding: 10px;
            }}
            .container {{
                max-width: 900px;
                margin: 0 auto;
            }}
            h1 {{
                color: #58a6ff;
                text-align: center;
                margin-bottom: 10px;
                font-size: clamp(1.5rem, 5vw, 2.5rem);
            }}
            h2 {{
                font-size: clamp(1.2rem, 4vw, 1.5rem);
            }}
            .subtitle {{
                text-align: center;
                color: #8b949e;
                margin-bottom: 30px;
                font-size: clamp(0.9rem, 2.5vw, 1.1rem);
            }}
            .input-group {{
                display: flex;
                gap: 10px;
                max-width: 600px;
                margin: 0 auto 20px;
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
                white-space: nowrap;
            }}
            button:hover {{
                background: #2ea043;
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                gap: 15px;
                margin-top: 20px;
            }}
            .card-link {{
                text-decoration: none;
                display: block;
            }}
            .card {{
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 15px;
                transition: all 0.2s;
                cursor: pointer;
            }}
            .card:hover {{
                transform: translateY(-2px);
                border-color: #58a6ff;
                box-shadow: 0 4px 12px rgba(88, 166, 255, 0.1);
            }}
            .card h3 {{
                margin: 0 0 8px 0;
                font-size: 1.1rem;
                color: #58a6ff;
            }}
            .url {{
                color: #6e7681;
                font-size: 13px;
                margin: 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .empty {{
                text-align: center;
                color: #8b949e;
                margin: 40px 0;
                padding: 40px 20px;
                background: #161b22;
                border-radius: 8px;
            }}
            .empty a {{
                color: #58a6ff;
            }}
            .info {{
                max-width: 600px;
                margin: 40px auto;
                text-align: center;
                color: #8b949e;
                padding: 20px;
                background: #161b22;
                border-radius: 8px;
            }}
            code {{
                background: #0d1117;
                padding: 4px 8px;
                border-radius: 3px;
                font-size: 0.9em;
                word-break: break-all;
            }}
            @media (max-width: 640px) {{
                .input-group {{
                    flex-direction: column;
                }}
                button {{
                    width: 100%;
                }}
                .cards {{
                    grid-template-columns: 1fr;
                }}
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
            
            <h2 style="margin-top: 40px; color: #58a6ff;">Recently Rendered</h2>
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
        
        # If not processing flag, show loading page first
        if 'process' not in request.args:
            return loading_page(repo_path)
        
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