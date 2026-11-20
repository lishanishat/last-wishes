# Last Wishes

*The agent follows up. The family decides.*

> Full README (architecture, SIE recipes, Cognee calls, benchmark, Firedrill results, sources) is written at CP5.

## Setup

**Python 3.12 is required.** Cognee does not support Python 3.14 (the macOS system default here), so the project pins 3.12 in `.python-version`.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt   # exact versions we tested
cp .env.example .env                              # then fill in keys
```

Always use the venv's binaries directly, never the system `python`/`streamlit`:

```bash
.venv/bin/python -m pytest -q
.venv/bin/streamlit run app.py
```

`requirements.txt` lists top-level dependencies; `requirements.lock.txt` is `pip freeze` from the working venv.
