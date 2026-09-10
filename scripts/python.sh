# Install the cinder CLI into a project venv; ./cinder re-execs under it.
py=""
for candidate in python3.12 python3.11 python3.10 python3; do
  have "$candidate" && py="$candidate" && break
done
[ -n "$py" ] || fail "Python 3.10+ not found" "run: brew install python@3.12"
[ -d .venv ] || quiet "$py" -m venv .venv || fail "could not create .venv"
quiet .venv/bin/python -m pip install -e . || fail "pip install failed"
ok "installed the cinder CLI into .venv"
