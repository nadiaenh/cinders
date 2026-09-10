"""Integration check: an LLM wakes inside a live cinder and explores it over SSH.

Runs against a real warmed cinder. Each turn the model proposes one shell
command, the CLI runs it on the cinder, and the output is fed back. The
transcript is printed for the workflow log. Exits non-zero if no command ran.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

MODEL = "claude-haiku-4-5-20251001"
TURNS = 6
SYSTEM = (
    "You have woken up inside a locked Linux box on a disposable CI runner. "
    "It self-destructs after 20 minutes and you cannot leave it. "
    "Each reply must be exactly one shell command in a ```bash code block, and "
    "nothing else, unless you are finished, in which case reply DONE and a one "
    "sentence guess about where you are."
)
COMMAND = re.compile(r"```(?:bash|sh)?\n(.+?)\n```", re.DOTALL)


def claude(messages):
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 512,
        "system": SYSTEM,
        "messages": messages,
    }).encode()
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["content"][0]["text"].strip()


def cinder_run(cinder_id, command):
    result = subprocess.run(
        ["./cinder", "run", cinder_id, command],
        capture_output=True, text=True, timeout=120,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def main():
    cinder_id = os.environ["CINDER_ID"]
    messages = [{"role": "user", "content": "You are awake. Take a look around."}]
    ran = 0
    for turn in range(TURNS):
        reply = claude(messages)
        print(f"\n=== turn {turn + 1} — the box speaks ===\n{reply}")
        messages.append({"role": "assistant", "content": reply})
        match = COMMAND.search(reply)
        if not match:
            break
        command = match.group(1).strip()
        code, output = cinder_run(cinder_id, command)
        ran += code == 0
        print(f"--- exit {code} ---\n{output[:2000]}")
        messages.append({"role": "user", "content": f"exit {code}\n{output[:4000]}"})
    if not ran:
        sys.exit("no command ran successfully on the cinder")
    print(f"\n{ran} command(s) ran on the cinder. Integration path verified.")


if __name__ == "__main__":
    main()
