"""Static contracts for the browser and the code-owned action boundary."""

from typing import Literal, NotRequired, Protocol, TypedDict


class Action(TypedDict):
    """An action produced by the page reader, never a model-generated selector."""

    id: str
    kind: Literal["click", "fill", "select", "upload", "scroll", "wait"]
    label: str
    node: NotRequired[int]
    role: NotRequired[str]
    value: NotRequired[str]
    href: NotRequired[str]
    password: NotRequired[bool]
    secret: NotRequired[str]
    file: NotRequired[str]
    delta: NotRequired[int]


class Page(TypedDict):
    """The page facts required by decisions and fresh checks."""

    url: str
    title: str
    text: str
    actions: list[Action]
    fingerprint: str
    marker: list
    page_key: list
    guards: dict[str, list | None]
    screenshot: NotRequired[str]


class BrowserPort(Protocol):
    """The browser operations used by the action loop and independent checks."""

    def observe(self, screenshot: bool = True) -> Page: ...
    def fresh(self, page: Page, action: Action | None = None) -> bool: ...
    def act(self, action: Action, page: Page, text: str | None = None) -> object: ...
    def signals(self) -> list[dict]: ...
    def new_tabs(self) -> list[str]: ...
