# Contributing to Papyrus

Thanks for your interest in contributing! Papyrus is a single-file GTK4/Adwaita app — contributions that keep it simple and focused are always welcome.

## How to contribute

1. **Fork** the repository
2. **Create a branch** (`git checkout -b feature/my-feature`)
3. **Make your changes** — keep the single-file constraint (`papyrus.py` only)
4. **Test** — run `python3 papyrus.py` and verify nothing is broken
5. **Commit** with a clear message (`git commit -m "Add feature X"`)
6. **Push** (`git push origin feature/my-feature`)
7. **Open a pull request**

## Guidelines

- **No splitting into modules** — `papyrus.py` stays as one file
- **No type annotations** beyond what GI introspection provides
- **Follow existing code style** — look at the surrounding code and match it
- **No new dependencies** unless absolutely necessary (and discuss in an issue first)
- **Keep the diff small** — focus on one thing per PR

## Code of Conduct

All contributors must follow the [Code of Conduct](CODE_OF_CONDUCT.md).
