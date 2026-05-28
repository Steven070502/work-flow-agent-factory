# GitHub Submit Guide

## Safe files

Commit:

- `src/`
- `tests/`
- `scripts/`
- `docs/`
- `README.md`
- `requirements.txt`
- `pyproject.toml`
- `.env.example`
- `.gitignore`
- `Dockerfile`

Do not commit:

- `.env`
- API keys
- virtual environments
- cache files
- `__pycache__/`
- `.DS_Store`

## First push

```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```

## Run locally

```bash
pip install -r requirements.txt
python main.py --test
python tests/test_pipeline.py
```

or:

```bash
bash scripts/run_mock.sh
bash scripts/test.sh
```
