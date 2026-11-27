"""Interpret a plain-text run brief before persisting or planning with it."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlsplit

from app.schemas.autopilot import AutopilotInitialInput


_LOGIN_LABEL = r"user\s*(?:id|name)|username|email(?:\s+address)?|password|passwd|pwd|phone(?:\s+number)?|mobile(?:\s+number)?|pin"
_ASSIGNMENT = r"(?:\s*[:=]\s*|\s+is\s+)"
_LOGIN_VALUE = re.compile(rf"^(?:my\s+)?(?P<label>{_LOGIN_LABEL}){_ASSIGNMENT}(?P<value>.*)$", re.I)
_LOGIN_SPLIT = re.compile(rf"(?:\s*[;,]\s*|\s+and\s+)(?=(?:{_LOGIN_LABEL}){_ASSIGNMENT})", re.I)
_EMAIL_LOGIN_PAIR = re.compile(
    r"^(?:(?:uat\s+|login\s+)?credentials?\s*[:=]\s*)?"
    r"(?P<username>[\w.+%-]+@[\w.-]+\.[a-z]{2,})\s*/\s*(?P<password>\S+)(?:\s+(?P<rest>.*))?$",
    re.I,
)
_NAMED_INPUT = re.compile(r"^(?P<kind>test\s*data|login\s*data|auth(?:entication)?\s*data)\s*[:=]\s*(?P<value>.*)$", re.I)
_NAMED_ASSIGNMENT = re.compile(r"^(?P<label>[^:=]{1,120}?)\s*[:=]\s*(?P<value>.+)$")
_NAMED_SPLIT = re.compile(r"(?:\s*;\s*|,\s+)(?=[\w][^:=,;]{0,80}\s*[:=])")
_ONE_TIME = re.compile(r"\b(?:otp|one[- ]time|verification code|mfa code|2fa code)\b", re.I)
_MODULE_PREFIX = re.compile(r"^(?:modules?(?:\s+to\s+test)?|test\s+scope|journeys?\s+to\s+test)\s*[:=]\s*(.+)$", re.I)
_MODULE_SENTENCE = re.compile(
    r"^(?:please\s+)?(?:only\s+(?:test|run|cover|check)|(?:test|run|cover|check)\s+only|"
    r"focus\s+on|(?:limit|restrict)\s+(?:this\s+|the\s+)?(?:run|test(?:ing)?|execution)\s+to)\s+([^.!?\n]+)",
    re.I,
)
_MODULE_SUFFIX = re.compile(r"^(?:please\s+)?(?:test|run|cover|check)\s+([^.!?\n]+?)\s+only(?=[.!?]|$)", re.I)
_REUSE = re.compile(r"^(?:please\s+)?(?:use|reuse)\s+(?:(?:my|the)\s+)?(?:pre[- ]?filled|saved|existing)\s+(?:test\s+data|inputs?|values?|credentials)\b", re.I)
_FRESH = re.compile(r"^(?:please\s+)?(?:use|start with)\s+(?:fresh|new)\s+(?:test\s+data|inputs?|values?|credentials)\b", re.I)
_SECRET_ASSIGNMENT = re.compile(
    r"\b(?:user\s*(?:id|name)|username|email|password|passcode|pwd|passwd|otp|"
    r"verification\s+code|pin|token|api\s+key|secret)\s*(?:[:=]|\bis\b)", re.I,
)


@dataclass(repr=False)
class RunInstructions:
    context: str
    modules: list[str] = field(default_factory=list)
    inputs: list[AutopilotInitialInput] = field(default_factory=list)
    reuse: bool | None = None
    module_directive: bool = False


def field_identity(label: str) -> str:
    """Map an observed input to a supplied value without fuzzy secret matching."""
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(label or ""))
    name = " ".join(re.findall(r"[^\W_]+", words.casefold())).strip()
    name = re.sub(r"^(?:(?:enter|input|type)\s+)(?:your\s+)?", "", name)
    if re.fullmatch(r"(?:username|user name|user id|uid|user)(?: (?:or )?email(?: address)?)?|email(?: address)?", name):
        return "username"
    if name in {"password", "passwd", "pwd"}:
        return "password"
    if name in {"phone", "phone number", "mobile", "mobile number", "mobile phone number", "telephone"}:
        return "phone"
    return name


def auth_binding_key(label: str) -> str:
    return f"__observed_auth:{field_identity(label)}"


def _unquote(value: str) -> str:
    text = value.strip()
    return text[1:-1] if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'" else text


def _module_names(value: str) -> list[str]:
    names = []
    for part in re.split(r"\s*(?:[,;|]|\band\b)\s*", value, flags=re.I):
        name = re.sub(r"\s+(?:modules?|journeys?|features?|only)$", "", part.strip(), flags=re.I)
        name = re.sub(r"^(?:the\s+)?(?:(?:modules?|journeys?|features?)\s+)?", "", name, flags=re.I)
        name = name.strip(" \t.'\"")
        if name and len(name) <= 64 and len(name.split()) <= 7 and re.fullmatch(r"[\w][\w &/+()_-]*", name):
            if name.casefold() not in {"all", "all modules", "everything", "whole app"}:
                names.append(name)
        elif part.strip():
            raise ValueError("List the modules to test by name, for example “Only test Cards.”")
    return names


def parse_run_instructions(value: object) -> RunInstructions:
    if not isinstance(value, str) or len(value) > 8000:
        raise ValueError("Enter up to 8,000 characters of run instructions.")
    context: list[str] = []
    modules: dict[str, str] = {}
    inputs: dict[tuple[str, str], AutopilotInitialInput] = {}
    reuse: bool | None = None
    module_directive = False

    def add_input(label: str, raw: str, *, authentication: bool) -> None:
        label = " ".join(label.split()).strip()
        key = field_identity(label)
        supplied = _unquote(raw)
        if not label or not key or not supplied or len(supplied) > 4000:
            raise ValueError("Complete each starting input with a label and value.")
        if _ONE_TIME.search(label):
            raise ValueError("Enter a fresh verification code when the app presents its challenge.")
        category = "credential" if authentication else "test_data"
        identity = category, key
        if identity in inputs and inputs[identity].value != supplied:
            raise ValueError("A starting input has two different values. Keep one value for each label.")
        inputs[identity] = AutopilotInitialInput(
            label=label, value=supplied, category=category, credential_field=authentication,
        )

    for line in value.splitlines():
        text = line.strip()
        pair = _EMAIL_LOGIN_PAIR.fullmatch(text)
        if pair:
            add_input("User ID", pair["username"], authentication=True)
            add_input("Password", pair["password"], authentication=True)
            line = pair["rest"] or ""
            text = line.strip()
        named = _NAMED_INPUT.fullmatch(text)
        login = _LOGIN_VALUE.fullmatch(text)
        if named:
            is_auth = not named["kind"].casefold().startswith("test")
            for entry in _NAMED_SPLIT.split(named["value"]):
                assignment = _NAMED_ASSIGNMENT.fullmatch(entry.strip())
                if not assignment:
                    raise ValueError("For a named input, enter its label and value, for example “Test data: Search term = Sample”.")
                add_input(assignment["label"], assignment["value"], authentication=is_auth)
        elif login:
            for entry in _LOGIN_SPLIT.split(text):
                pair = _LOGIN_VALUE.fullmatch(entry)
                if pair is None:
                    raise ValueError("Put each sign-in input on its own line.")
                add_input(pair["label"], pair["value"], authentication=True)
        elif _REUSE.match(text) or _FRESH.match(text):
            choice = _REUSE.match(text) is not None
            if reuse is not None and reuse != choice:
                raise ValueError("Choose either saved Test Data or fresh Test Data for this run.")
            reuse = choice
        else:
            scoped = _MODULE_PREFIX.fullmatch(text) or _MODULE_SUFFIX.match(text) or _MODULE_SENTENCE.match(text)
            if scoped:
                module_directive = True
                for name in _module_names(scoped[1]):
                    modules.setdefault(name.casefold(), name)
            if _SECRET_ASSIGNMENT.search(text):
                # Keep unrecognized assignments away from the analysis prompt.
                raise ValueError("Put each sign-in input on a separate labeled line in Run instructions.")
            context.append(line)

    supplied_values = [item.value for item in inputs.values()]
    username = inputs.get(("credential", "username"))
    password = inputs.get(("credential", "password"))
    if username and password:
        inputs.pop(("credential", "username"))
        inputs.pop(("credential", "password"))
        inputs[("credential", "bundle")] = AutopilotInitialInput(
            label="UAT sign-in credentials",
            category="credential",
            value=json.dumps({"username": username.value, "password": password.value}),
        )
    if len(inputs) > 50 or len(modules) > 20:
        raise ValueError("Use at most 50 starting values and 20 modules for one run.")
    text = "\n".join(context).strip()
    if modules and not any(_MODULE_PREFIX.match(line.strip()) for line in context):
        text = f"Modules: {', '.join(modules.values())}\n{text}".strip()
    for value in sorted(set(supplied_values), key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", "[saved input]", text)
    return RunInstructions(text, list(modules.values()), list(inputs.values()), reuse, module_directive)


def _module_words(value: str) -> tuple[str, ...]:
    return tuple(word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word
                 for word in re.findall(r"[^\W_]+", str(value or "").casefold()))


def matches_module(modules: Iterable[str], *labels: str | None) -> bool:
    tokens = [_module_words(label) for label in labels if label]
    for module in modules:
        words = _module_words(module)
        if words and any(any(text[index:index + len(words)] == words for index in range(len(text)))
                         for text in tokens):
            return True
    return False


def route_path(url: str | None) -> str:
    return urlsplit(url).path if url else ""


_TRANSIT = {"home", "dashboard", "menu", "open menu", "main menu", "navigation", "more",
            "back", "get started", "skip", "close", "scrim", "login", "log in", "sign in",
            "continue to login", "open navigation"}
_TAB_LABEL = re.compile(r"\btab\s+\d+\s+of\s+\d+\b", re.I)


def is_transit(label: str) -> bool:
    return " ".join(_module_words(_TAB_LABEL.sub("", label))) in _TRANSIT


def is_primary_tab(label: str) -> bool:
    return _TAB_LABEL.search(label) is not None


def scope_allows_navigation(modules: list[str], label: str, *, inside: bool, global_navigation: bool = False) -> bool:
    return (
        not modules or matches_module(modules, label) or is_transit(label)
        or inside and not (global_navigation or is_primary_tab(label))
    )


def scope_allows_case(modules: list[str], test, scoped_screens: set[str]) -> bool:
    """Use grounded destinations before descriptive plan labels."""
    if not modules:
        return True
    steps = test.steps[test.sign_in_setup_count:]
    tab_actions = [
        step.target for step in steps
        if step.action in {"tap", "click"} and step.target and is_primary_tab(step.target)
    ]
    if any(not matches_module(modules, label) and not is_transit(label) for label in tab_actions):
        return False
    if any(matches_module(modules, label) for label in tab_actions):
        return True
    if any(step.expected_resulting_screen_id in scoped_screens for step in steps):
        return True
    if any(step.screen_id in scoped_screens for step in steps):
        return True
    if any(step.screen_id or step.expected_resulting_screen_id for step in steps):
        return False
    if matches_module(modules, test.journey, test.page_label, route_path(test.page_url)):
        return True
    return not (test.journey or test.page_label or test.page_url) and matches_module(modules, test.title)


def scope_allows_design_case(modules: list[str], test, scoped_screens: set[str]) -> bool:
    if not modules:
        return True
    target_steps = [step for step in test.steps if is_primary_tab(step) and re.search(r"\b(?:tap|click|activate|select)\b", step, re.I)]
    tab_labels = [re.sub(r"^.*?\b(?:tap|click|activate|select)\s+", "", step, flags=re.I) for step in target_steps]
    if any(not matches_module(modules, label) and not is_transit(label) for label in tab_labels):
        return False
    if any(matches_module(modules, label) for label in tab_labels):
        return True
    if test.runtime_screen_id:
        return test.runtime_screen_id in scoped_screens
    return (
        matches_module(modules, test.journey, test.page_label, route_path(test.page_url))
        or not (test.journey or test.page_label or test.page_url) and matches_module(modules, test.title)
    )
