def main() -> None:
    # lazy: tests import the package without pywebview's GUI deps
    from .app import main as run

    run()


__all__ = ["main"]
