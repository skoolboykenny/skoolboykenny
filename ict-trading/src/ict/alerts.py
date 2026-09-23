"""Alerts, so hands off does not mean blind.

The record asks for messages on fills, exits, halts and errors. This module is
the sink they go to, and it is deliberately dull: a console sink, a file sink
and a webhook sink, behind one method.

Two rules shape it.

**An alert must never stop the loop.** A webhook that times out at 3am cannot
be allowed to take down a process that is holding a position. Every sink
swallows its own failures and reports them once, and the loop carries on.

**A halt must be loud, and everything else must be quiet enough to keep
reading.** An alerting system people mute is worse than none, because it looks
like coverage. So fills and exits are one line, and halts carry the reason and
what was done about it.

Webhook URLs come from the environment, never the repository: a Telegram bot
token in a commit is a bot anyone can drive.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pandas as pd

log = logging.getLogger("ict.alerts")

#: How serious an alert is. Only ``halt`` and ``error`` should ever wake anyone.
LEVELS = ("info", "fill", "exit", "halt", "error")


@dataclass(frozen=True)
class Alert:
    """One thing worth telling a person about."""

    level: str
    text: str
    at: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.now(tz="UTC"))

    @property
    def is_urgent(self) -> bool:
        return self.level in ("halt", "error")

    def __str__(self) -> str:
        marker = "!!" if self.is_urgent else "  "
        return f"{marker} [{self.at:%Y-%m-%d %H:%M:%S}] {self.level}: {self.text}"


class Sink(Protocol):
    """Anywhere an alert can go."""

    def send(self, alert: Alert) -> None: ...


@dataclass
class ConsoleSink:
    """Prints. The default, and the only one that needs no configuration."""

    name: str = "console"

    def send(self, alert: Alert) -> None:
        print(str(alert), flush=True)


@dataclass
class FileSink:
    """Appends to a log, so a night's alerts survive the terminal closing."""

    path: Path
    name: str = "file"

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def send(self, alert: Alert) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(str(alert) + "\n")


@dataclass
class WebhookSink:
    """Posts JSON to a URL. Telegram, Slack, ntfy or anything else.

    The URL comes from the environment. It usually contains a bot token, and a
    token in a commit is a bot anyone can drive.
    """

    url: str = ""
    name: str = "webhook"
    timeout: float = 10.0
    field_name: str = "text"
    session: object | None = None
    #: Only send alerts at least this serious, so a phone is not buzzing all
    #: session. Halts and errors always go.
    minimum_level: str = "fill"

    @classmethod
    def from_env(cls, variable: str = "ICT_ALERT_WEBHOOK", **kwargs) -> "WebhookSink | None":
        """Build from an environment variable, or None when it is not set."""
        url = os.environ.get(variable, "").strip()
        return cls(url=url, **kwargs) if url else None

    def send(self, alert: Alert) -> None:
        if not self.url:
            return
        if not alert.is_urgent and LEVELS.index(alert.level) < LEVELS.index(
            self.minimum_level
        ):
            return

        session = self.session
        if session is None:
            import requests

            session = requests
        session.post(
            self.url,
            data=json.dumps({self.field_name: str(alert)}),
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )


@dataclass
class Alerts:
    """Every sink, with failures contained.

    A sink that raises is disabled after its first failure and reported once.
    Retrying a broken webhook on every fill turns one outage into a loop that
    spends its time on network timeouts instead of candles.
    """

    sinks: list = field(default_factory=list)
    sent: list[Alert] = field(default_factory=list)
    failed: dict = field(default_factory=dict)

    @classmethod
    def default(cls, log_path: str | Path | None = None) -> "Alerts":
        """Console, optionally a file, and a webhook if the environment has one."""
        sinks: list = [ConsoleSink()]
        if log_path:
            sinks.append(FileSink(log_path))
        webhook = WebhookSink.from_env()
        if webhook is not None:
            sinks.append(webhook)
        return cls(sinks=sinks)

    def send(self, level: str, text: str) -> Alert:
        alert = Alert(level=level if level in LEVELS else "info", text=text)
        self.sent.append(alert)
        for sink in self.sinks:
            name = getattr(sink, "name", sink.__class__.__name__)
            if name in self.failed:
                continue
            try:
                sink.send(alert)
            except Exception as error:
                # Never let an alert take down a loop that is holding a
                # position. One report, then that sink is done.
                self.failed[name] = str(error)
                log.error("alert sink %s failed and is now off: %s", name, error)
        return alert

    # Named helpers, so call sites read as what happened rather than as a level.

    def info(self, text: str) -> Alert:
        return self.send("info", text)

    def fill(self, text: str) -> Alert:
        return self.send("fill", text)

    def exit(self, text: str) -> Alert:
        return self.send("exit", text)

    def halt(self, text: str) -> Alert:
        return self.send("halt", text)

    def error(self, text: str) -> Alert:
        return self.send("error", text)

    @property
    def urgent(self) -> list[Alert]:
        return [a for a in self.sent if a.is_urgent]
