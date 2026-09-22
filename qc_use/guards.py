"""Guardrails around every action: allowed sites, never-do rules, and native dialogs.

The never-do gate is a seatbelt, not a sandbox. The real boundary is the allowed-site list plus test-only accounts.
"""

import ipaddress
import re
from urllib.parse import urlparse

from . import judge
from .engine.agent import Blocked, NeedsApproval, Policy

DEFAULT_NEVER = [
    "permanently delete an account, workspace, project, or stored data",
    "make a payment, a purchase, or a subscription change",
    "send an email, message, or invitation to a real person",
]
LOCAL_SUFFIXES = (".localhost", ".local", ".test", ".internal", ".example", ".invalid", ".lan", ".home.arpa")
NONPRODUCTION = {"staging", "stage", "stg", "dev", "develop", "development", "preview", "qa", "test", "testing",
                 "sandbox", "uat", "demo", "local"}


def endpoint(url):
    parsed = urlparse(url if "://" in url else f"//{url}")
    default = {"https": 443, "http": 80}.get(parsed.scheme)
    return (parsed.hostname or "").lower(), parsed.port or default


def looks_like_production(url):
    host, _ = endpoint(url)
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        return False
    try:
        address = ipaddress.ip_address(host)
        return not (address.is_private or address.is_loopback or address.is_link_local)
    except ValueError:
        pass
    return not any(label in NONPRODUCTION for label in re.split(r"[.-]", host))


class Sites:
    """The start URL's site plus declared ones. `*.example.test` matches subdomains; a port must match if given."""

    def __init__(self, start, allow):
        self.patterns = [endpoint(start), *(endpoint(entry) for entry in allow)]

    def allows(self, url):
        if url.startswith("about:blank"):
            return True
        if urlparse(url).scheme not in {"http", "https"}:
            return False
        host, port = endpoint(url)
        for pattern, pattern_port in self.patterns:
            wildcard = pattern.startswith("*.")
            hit = host.endswith(pattern[1:]) if wildcard else host == pattern
            if hit and (pattern_port is None or pattern_port == port):
                return True
        return False


class Guardrails(Policy):
    def __init__(self, spec, allowed_rules=(), approve=None):
        self.spec = spec
        self.sites = Sites(spec.url, spec.allow)
        self.rules = [*(DEFAULT_NEVER if spec.never_defaults else []), *spec.never]
        allowed = {rule.strip().casefold() for rule in allowed_rules}
        self.allowed = {rule for rule in self.rules if "*" in allowed or rule.casefold() in allowed}
        self.approve = approve  # Called with (rule, action label, probability) when a person can answer now.
        self.goal = ""
        self.cache = {}
        self.gates = []  # Every gate decision, for the report.

    def active(self):
        return [rule for rule in self.rules if rule not in self.allowed]

    def decide(self, probabilities, label):
        for rule, p in sorted(probabilities.items(), key=lambda item: -item[1]):
            if p < self.spec.never_threshold or rule in self.allowed:
                continue
            if self.approve and self.approve(rule, label, p):
                self.allowed.add(rule)
                continue
            raise NeedsApproval(rule, label, p)

    def before_act(self, action, page, decision):
        if action.get("href") and not self.sites.allows(action["href"]):
            raise Blocked(f"The link '{action['label']}' leads outside the allowed sites ({action['href']})")
        rules = self.active()
        if action["kind"] not in {"click", "select"} or not rules:
            return  # Typing never presses Enter, and scrolling or waiting cannot commit anything.
        key = (tuple(rules), urlparse(page["url"]).path, action["label"], action.get("role"), action.get("value"))
        if key not in self.cache:
            self.cache[key] = judge.gate(page, self.goal, action, rules)
        probabilities = self.cache[key]
        self.gates.append({"action": action["label"], "url": page["url"], "probabilities": probabilities})
        self.decide(probabilities, action["label"])

    def after_observe(self, page):
        if page["url"].startswith("chrome-error:"):
            raise Blocked(f"The page failed to load. Is the app running at {self.spec.url}?")
        if not self.sites.allows(page["url"]):
            raise Blocked(f"The page left the allowed sites: {page['url']}")

    def on_dialog(self, record):
        if record["type"] in {"alert", "beforeunload"}:
            return True, None
        if record["type"] == "prompt":
            raise Blocked(f"unsupported: a prompt() dialog asked for text ('{record['message'][:120]}')")
        accept, probabilities = judge.dialog(record, self.goal, self.active())
        if accept:
            self.decide(probabilities, f"confirm: {record['message'][:120]}")
        return accept, None
