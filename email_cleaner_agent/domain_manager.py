from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
BULK_TRASH_FILE = SCRIPT_DIR / "bulk_trash.py"


def normalize_domain(domain: str) -> str:
    cleaned = domain.strip().lower()
    cleaned = cleaned.removeprefix("http://").removeprefix("https://")
    cleaned = cleaned.split("/", 1)[0]
    cleaned = cleaned.split("@")[-1]
    return cleaned.strip(".")


def parse_domains(value: str) -> list[str]:
    seen: set[str] = set()
    domains: list[str] = []
    for part in re.split(r"[\s,;]+", value or ""):
        domain = normalize_domain(part)
        if not domain or "." not in domain or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
    return domains


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def load_trash_domains() -> list[str]:
    content = BULK_TRASH_FILE.read_text(encoding="utf-8")
    match = re.search(r"DOMAINS_TO_TRASH\s*=\s*(\[[\s\S]*?\])", content)
    if not match:
        raise RuntimeError("Could not locate DOMAINS_TO_TRASH in bulk_trash.py")
    return list(ast.literal_eval(match.group(1)))


def save_trash_domains(domains: list[str]) -> None:
    content = BULK_TRASH_FILE.read_text(encoding="utf-8")
    formatted = "DOMAINS_TO_TRASH = [\n" + "".join(f'    "{d}",\n' for d in sorted(set(domains))) + "]"
    updated = re.sub(r"DOMAINS_TO_TRASH\s*=\s*\[[\s\S]*?\]", formatted, content, count=1)
    BULK_TRASH_FILE.write_text(updated, encoding="utf-8")


def update_domains(action: str, domains: list[str]) -> None:
    if not domains:
        raise ValueError("No valid domains were provided.")

    config = load_config()
    whitelist = set(normalize_domain(d) for d in config.get("whitelist_domains", []))
    trash = set(normalize_domain(d) for d in load_trash_domains())

    if action == "whitelist":
        whitelist.update(domains)
        trash.difference_update(domains)
    elif action == "blacklist":
        trash.update(domains)
        whitelist.difference_update(domains)
    else:
        raise ValueError("action must be whitelist or blacklist")

    config["whitelist_domains"] = sorted(d for d in whitelist if d)
    save_config(config)
    save_trash_domains([d for d in trash if d])

    print(f"{action} updated for {len(domains)} domain(s): {', '.join(domains)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Move domains into whitelist or blacklist.")
    parser.add_argument("--action", choices=["whitelist", "blacklist"], required=True)
    parser.add_argument("--domains", required=True, help="Comma, space, or newline separated domains")
    args = parser.parse_args()

    update_domains(args.action, parse_domains(args.domains))


if __name__ == "__main__":
    main()
