def main() -> None:
    from .app import main as run  # lazy: tests import the package without pywebview's GUI deps

    run()


__all__ = ["main"]
