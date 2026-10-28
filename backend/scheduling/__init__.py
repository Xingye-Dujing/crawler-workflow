"""The scheduled-task domain: what to run, when it fires, and what actually happened.

One directory because one question lives here — *should something start on its own now, and what is
the record of last time?* — and three modules answer different parts of it:

``cron``    five-field expressions, refusals and "when next", with stdlib ``zoneinfo`` only;
``store``   the task ledger (``data/schedules.json``): normalization, next run, fire accounting,
            missed moments, and the per-task history the panel renders;
``clock``   the in-process daemon thread. It owns timekeeping but NOT a way to start a run:
            ``app.py`` injects the two seams (``set_run_starter``/``set_canvas_source``), so every
            fire takes the same ``begin_run`` path a manual 执行 does and a busy server queues it.

The edge worth keeping straight: ``clock`` reads ``store`` and ``store`` reads ``cron``; neither
asks ``app`` for anything, which is what lets the rules be driven across midnight, restarts and DST
edges in tests without a server or a real clock.
"""
