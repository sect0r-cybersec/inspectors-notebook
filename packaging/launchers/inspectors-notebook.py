from inspectors_notebook import diagnostics

diagnostics.start()  # before the heavy imports, so a hang while loading them is caught too

from inspectors_notebook.app import main  # noqa: E402

raise SystemExit(main())
