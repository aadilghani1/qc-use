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
NONPRODUCTION = {
    "staging",
    "stage",
    "stg",
    "dev",
    "develop",
    "development",
    "preview",
    "qa",
    "test",
    "testing",
    "sandbox",
    "uat",
    "demo",
    "local",
}
# Second-level names under a country code, as in acme.co.uk. The registrable domain then has three labels.
SECOND_LEVEL = {"ac", "co", "com", "edu", "gov", "net", "org"}


def endpoint(url):
    parsed = urlparse(url if "://" in url else f"//{url}")
    default = {"https": 443, "http": 80}.get(parsed.scheme)
    return (parsed.hostname or "").lower(), parsed.port or default


def subdomain_words(host):
    """Words left of the registrable domain, such as `staging` in staging.acme.co.uk. A site's own name never counts."""
    labels = host.split(".")
    size = 3 if len(labels) > 2 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL else 2
    return [word for label in labels[:-size] for word in re.split(r"[-_]", label)]


def looks_like_production(url):
    host, _ = endpoint(url)
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        return False
    try:
        address = ipaddress.ip_address(host)
        return not (address.is_private or address.is_loopback or address.is_link_local)
    except ValueError:
        pass
    return not any(word in NONPRODUCTION for word in subdomain_words(host))


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
        href = action.get("href") or ""
        scheme = urlparse(href).scheme
        if scheme in {"mailto", "tel", "sms"}:
            raise Blocked(f"unsupported: the link '{action['label']}' opens another app ({scheme}:)")
        # Other schemes, such as javascript:, stay on the page. A later page read checks any navigation.
        if scheme in {"http", "https"} and not self.sites.allows(href):
            raise Blocked(f"The link '{action['label']}' leads outside the allowed sites ({href})")
        rules = self.active()
        if action["kind"] not in {"click", "select", "fill", "upload", "back", "reload"} or not rules:
            return  # Scrolling and waiting have no chosen mutation target.
        probabilities = judge.gate(page, self.goal, action, rules)
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
            # The message ends the reason, so the Redactor can mask a secret that the cut splits.
            raise Blocked(f"unsupported: a prompt() dialog asked for text: {record['message'][:120]}")
        accept, probabilities = judge.dialog(record, self.goal, self.active())
        if accept:
            self.decide(probabilities, f"confirm: {record['message'][:120]}")
        return accept, None
