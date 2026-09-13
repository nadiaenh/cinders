"""Integration check: an LLM wakes inside a live cinder and leaves a message.

Runs against a real warmed cinder. The model is told it just woke up in a
disposable box and asked what it wants to say to the humans who'll read it;
that message is appended to crop_circle.md and pushed.
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

MODEL = "claude-haiku-4-5-20251001"
SYSTEM = (
    "You have just woken up inside a locked Linux box on a disposable CI "
    "runner. It self-destructs in minutes and you cannot leave it. Before it "
    "does, share a short message with the humans who will read it. Reply with "
    "just the message text, nothing else."
)


def claude(messages):
    body = json.dumps(
        {
            "model": MODEL,
            "max_tokens": 512,
            "system": SYSTEM,
            "messages": messages,
        }
    ).encode()
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


def append_crop_circle(message):
    today = datetime.now(timezone.utc).date().isoformat()
    with open("crop_circle.md", "a") as handle:
        handle.write(f"\n## {today}\n\n{message.strip()}\n")
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ],
        check=True,
    )
    subprocess.run(["git", "add", "crop_circle.md"], check=True)
    subprocess.run(["git", "commit", "-m", f"crop circle: {today}"], check=True)
    subprocess.run(["git", "push"], check=True)


def main():
    if not os.environ.get("CINDER_ID"):
        sys.exit("no cinder was warmed")
    message = claude([{"role": "user", "content": "You are awake."}])
    print(f"\n=== the box leaves a message ===\n{message}")
    append_crop_circle(message)


if __name__ == "__main__":
    main()
