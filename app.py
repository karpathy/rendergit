#!/usr/bin/env python3
"""
Minimal Flask web app for rendergit - reuses original CLI code
"""

import os
import tempfile
import shutil
from flask import Flask, request, send_file, jsonify
from pathlib import Path

# Import everything from the original CLI
from repo_to_single_page import (
    git_clone, git_head_commit, collect_files, try_tree_command,
    build_html, MAX_DEFAULT_BYTES, main
)

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>rendergit</title>
    <style>
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            max-width: 600px; 
            margin: 50px auto; 
            padding: 20px;
            background: #0d1117;
            color: #c9d1d9;
        }
        h1 { color: #58a6ff; }
        input, button {
            width: 100%;
            padding: 12px;
            margin: 10px 0;
            box-sizing: border-box;
            font-size: 16px;
        }
        input {
            background: #161b22;
            border: 1px solid #30363d;
            color: #c9d1d9;
        }
        button {
            background: #238636;
            color: white;
            border: none;
            cursor: pointer;
        }
        button:hover { background: #2ea043; }
        button:disabled { opacity: 0.5; }
        .error { color: #f85149; margin: 10px 0; }
        .info { color: #8b949e; margin: 20px 0; }
        code { background: #161b22; padding: 2px 5px; }
    </style>
</head>
<body>
    <h1>🚀 rendergit</h1>
    <p>Flatten any GitHub repository into a single HTML page</p>
    
    <input type="text" id="url" placeholder="https://github.com/user/repo">
    <button onclick="process()" id="btn">Generate HTML</button>
    <div id="msg"></div>
    
    <div class="info">
        <p><strong>Direct URL:</strong> <code id="example-url"></code></p>
        <p>Install locally: <code>pip install rendergit</code></p>
        <p>CLI usage: <code>rendergit https://github.com/user/repo</code></p>
    </div>
    
    <script>
    // Show example URL
    document.getElementById('example-url').textContent = 
        window.location.origin + '/github.com/karpathy/nanoGPT';
    </script>
    
    <script>
    async function process() {
        const url = document.getElementById('url').value;
        const btn = document.getElementById('btn');
        const msg = document.getElementById('msg');
        
        if (!url || !url.includes('github.com')) {
            msg.innerHTML = '<div class="error">Enter a valid GitHub URL</div>';
            return;
        }
        
        btn.disabled = true;
        msg.textContent = 'Processing...';
        
        try {
            const response = await fetch('/process', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({url})
            });
            
            if (!response.ok) throw new Error(await response.text());
            
            const blob = await response.blob();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = url.split('/').pop() + '.html';
            a.click();
            msg.textContent = 'Downloaded!';
        } catch (e) {
            msg.innerHTML = '<div class="error">' + e.message + '</div>';
        } finally {
            btn.disabled = false;
        }
    }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return HTML

@app.route('/<path:repo_path>')
def render_repo(repo_path):
    """Direct URL rendering: /github.com/user/repo"""
    try:
        # Construct GitHub URL from path
        if not repo_path.startswith('github.com/'):
            return f'Invalid path. Use format: {request.host_url}github.com/user/repo', 400
        
        repo_url = f'https://{repo_path}'
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Clone repo
            repo_dir = os.path.join(tmpdir, 'repo')
            git_clone(repo_url, repo_dir)
            
            # Get metadata
            commit = git_head_commit(repo_dir)
            
            # Collect files
            repo_path_obj = Path(repo_dir)
            files = collect_files(repo_path_obj, MAX_DEFAULT_BYTES)
            
            # Generate HTML using original function
            html_content = build_html(repo_url, repo_dir, commit, files)
            
            return html_content
            
    except Exception as e:
        return f'<h1>Error</h1><p>{str(e)}</p><p>Usage: {request.host_url}github.com/user/repo</p>', 500

@app.route('/process', methods=['POST'])
def process():
    try:
        repo_url = request.json.get('url', '').strip()
        if not repo_url or 'github.com' not in repo_url:
            return 'Invalid URL', 400
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Clone repo
            repo_dir = os.path.join(tmpdir, 'repo')
            git_clone(repo_url, repo_dir)
            
            # Get metadata
            commit = git_head_commit(repo_dir)
            repo_name = repo_url.rstrip('/').split('/')[-1].replace('.git', '')
            
            # Collect files
            repo_path = Path(repo_dir)
            files = collect_files(repo_path, MAX_DEFAULT_BYTES)
            
            # Generate HTML using original function
            html_content = build_html(repo_url, repo_dir, commit, files)
            
            # Write and send
            html_file = os.path.join(tmpdir, 'output.html')
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            return send_file(html_file, as_attachment=True, 
                           download_name=f'{repo_name}.html',
                           mimetype='text/html')
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)