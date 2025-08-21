# Deployment & Publishing Guide for rendergit

## Quick Start

```bash
# 1. Build package for PyPI
python -m build

# 2. Upload to PyPI  
python -m twine upload dist/*

# 3. Deploy to Render
git push origin main
# Then connect repo on render.com
```

## 📦 Publishing to PyPI

### First-time setup

1. **Create PyPI account**
   - Go to https://pypi.org/account/register/
   - Verify your email

2. **Install build tools**
   ```bash
   pip install --upgrade pip build twine
   ```

3. **Create API token**
   - Go to https://pypi.org/manage/account/token/
   - Create a token with scope "Entire account"
   - Save the token securely

### Building and Publishing

1. **Update version** in `pyproject.toml` (currently 0.2.0)

2. **Build the package**
   ```bash
   python -m build
   ```
   This creates `dist/` directory with wheel and source distribution

3. **Upload to TestPyPI (optional, for testing)**
   ```bash
   python -m twine upload --repository testpypi dist/*
   ```
   Test install: `pip install -i https://test.pypi.org/simple/ rendergit`

4. **Upload to PyPI**
   ```bash
   python -m twine upload dist/*
   ```
   Enter your PyPI username: `__token__`
   Enter your password: `[paste your API token]`

5. **Verify installation**
   ```bash
   pip install rendergit
   rendergit --help
   ```

## 🚀 Deploying to Render

### Quick Deploy (Recommended)

1. **Push to GitHub**
   ```bash
   git add .
   git commit -m "Add web deployment configuration"
   git push origin main
   ```

2. **Deploy on Render**
   - Go to https://render.com
   - Sign up/Login with GitHub
   - Click "New +" → "Web Service"
   - Connect your GitHub repo
   - Render will auto-detect the `render.yaml` configuration
   - Click "Create Web Service"

3. **Your app will be live at:**
   ```
   https://rendergit.onrender.com
   ```

### Manual Deploy Alternative

If you prefer manual configuration:

1. On Render dashboard:
   - New → Web Service
   - Connect GitHub repo
   - Configure:
     - **Name**: rendergit
     - **Environment**: Python
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `gunicorn app:app`
     - **Plan**: Free

## 🛠️ Local Development

### Running the CLI locally
```bash
# Install in development mode
pip install -e .

# Test the CLI
rendergit https://github.com/karpathy/nanoGPT
```

### Running the web app locally
```bash
# Install dependencies
pip install -r requirements.txt

# Run Flask development server
python app.py

# Or with gunicorn (production-like)
gunicorn app:app --bind 0.0.0.0:5000
```

Visit http://localhost:5000

## 🔧 Configuration

### Environment Variables (for Render)

You can set these in Render dashboard → Environment:

- `PORT`: Auto-set by Render
- `PYTHON_VERSION`: Set in render.yaml (3.11.0)

### Updating the package

1. Make changes to code
2. Update version in `pyproject.toml`
3. Build and publish to PyPI (see above)
4. Push to GitHub (auto-deploys to Render)

## 📝 File Structure

```
rendergit/
├── rendergit/           # Package directory
│   ├── __init__.py      # Package initialization
│   └── cli.py           # CLI implementation (renamed from repo_to_single_page.py)
├── app.py               # Flask web application
├── pyproject.toml       # Package configuration
├── requirements.txt     # Web app dependencies
├── render.yaml          # Render deployment config
├── README.md            # Project documentation
├── DEPLOY.md            # This file
└── .gitignore           # Git ignore rules
```

## 🐛 Troubleshooting

### PyPI Upload Issues
- **Authentication failed**: Check API token is correct
- **Version exists**: Increment version in pyproject.toml
- **Missing files**: Ensure `python -m build` ran successfully

### Render Deployment Issues
- **Build failed**: Check requirements.txt has all dependencies
- **App crashes**: Check logs in Render dashboard
- **Slow cold starts**: Normal on free tier, upgrades available

### Local Development Issues
- **Import errors**: Run `pip install -e .` from project root
- **Git not found**: Ensure git is installed and in PATH

## 🔗 Links

- **PyPI Package**: https://pypi.org/project/rendergit/
- **Live Web App**: https://rendergit.onrender.com
- **GitHub Repo**: https://github.com/yourusername/rendergit

## 📄 License

Apache 2.0 - See LICENSE file