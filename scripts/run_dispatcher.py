"""V2-Dispatcher Entry-Point.

Wird als separates Skript ausgefuehrt damit `pipeline.dispatcher` nicht als
`__main__` laeuft (sonst werden Provider in einen separaten Modul-Dict
registriert und vom Dispatcher nicht gefunden — siehe dispatcher.main()-docstring).

Beispiele:
  python -m scripts.run_dispatcher --providers fred --series-pks 39,61,98 --dry-run
  python -m scripts.run_dispatcher --providers fred --only-default
  python -m scripts.run_dispatcher
"""
from pipeline.dispatcher import main

if __name__ == "__main__":
    main()
