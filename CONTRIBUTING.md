# Contributing to AAna

Thank you for your interest in contributing to AAna!

## Development Setup

```bash
# Clone the repository
git clone git@github.com:wssaidong/AAna.git
cd AAna

# Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install akshare pandas requests

# Verify setup
python agents/main_agent.py --help
```

## Project Structure

```
AAna/
├── agents/            # Agent core logic (盘前/盘中/盘后)
├── analysis_tools/    # Data analysis and screening tools
├── data/              # Persistence layer (CSV + JSON snapshots)
├── docs/              # Knowledge base and templates
├── scripts/           # Executable scripts (尾盘选股, 东财同步)
├── state/             # Runtime state (daily JSON snapshots)
├── reports/           # Generated reports (YYYY-MM-DD/)
└── tests/             # Unit tests
```

## Coding Standards

- **Python version**: 3.9+
- **Type annotations**: Recommended for new code
- **Style**: Follow PEP 8; 100-character line limit
- **Error handling**: Never let network errors crash the agent; always log + fallback
- **Data paths**: Use `pathlib.Path`; resolve project root via `__file__`

## Data Layer Convention

All stock recommendation and tracking data must flow through `data/`:

```python
from data import append_recommendations_batch, append_tracking

# 尾盘选股结果 → 推荐日志
append_recommendations_batch(stocks)

# 次日追踪更新 → 追踪日志
append_tracking(code, name, sector, change_pct, hit)
```

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=term-missing
```

## Commit Message Format

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add weekend strategy module
fix: handle empty stock pool in morning screen
docs: update README with new architecture
refactor: extract data fetching into data/quotes.py
test: add unit tests for scoring functions
```

## Submitting Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature-name`
3. Make your changes and add tests
4. Ensure all tests pass: `python -m pytest tests/`
5. Commit with a clear message (see above format)
6. Push and open a Pull Request

## Reporting Issues

Please report issues with:
- Python version and OS
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output (remove sensitive data first)
