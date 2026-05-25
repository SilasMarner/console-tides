# Contributing to console-tides

Bug fixes and improvements are welcome. This is a single-file project so changes are easy to review.

## Getting started

1. Fork the repository
2. Create a branch: `git checkout -b fix/your-description`
3. Make your changes to `tides.py`
4. Test in your terminal
5. Open a pull request

## Development setup

### Prerequisites
- Python 3.10+
- Standard library only — no `pip install` needed
- A terminal with ANSI 256-colour support

### Running

```bash
python tides.py                  # default stations
python tides.py --search "name"  # station search
python tides.py --week           # 7-day hi/lo view
python tides.py --no-braille     # block bars instead of braille wave
```

## Code style

- Standard Python style — run `python -m py_compile tides.py` to check for syntax errors
- Keep it zero-dependency; do not add any `pip` requirements
- All NOAA/NWS fetches should stay in `concurrent.futures.ThreadPoolExecutor` for parallel loading
- ANSI colour codes live in the constants block at the top — add new colours there, not inline

## What to contribute

Good candidates:
- Bug fixes with a clear reproduction case
- Improvements to terminal compatibility (especially Windows Terminal / PowerShell)
- Additional NOAA data fields already returned by the existing API calls
- Better braille/block rendering for edge cases

Please open an issue first for larger changes (new views, new flags, new API integrations) before investing time in implementation.

## Pull request guidelines

- One logical change per PR
- Include a brief description of what changed and why
- Test on at least one terminal — include a screenshot if the output changed
- Link the issue if one exists (`Fixes #123`)

## Reporting bugs

Open a GitHub issue with:
- OS and terminal emulator
- Python version (`python --version`)
- The exact command you ran
- What you expected vs. what happened (paste the output or a screenshot)
