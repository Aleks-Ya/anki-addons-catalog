# Repository scope

- Change files only in this repository, the Anki Addons Catalog web app.
- `../anki-addons-mcp` (the Anki Addons MCP server) and `../anki-addons-dataset` (the Anki Addons Dataset) are
  read-only. Read their source code when it helps, but never change anything there with any tool, including Bash and
  git.
- When a task needs a change in one of these two repositories, stop and do not work around it. Tell the user what has
  to change and why, then give them a prompt to paste into an AI session in that repository.
- Write that prompt in terms of the wanted result. Do not include implementation details such as file names, function
  names, code or test instructions: the session in that repository decides them.

# Testing with the real AI

- Run the app locally only through `.claude/skills/update-mcp/local_check.py` (usage in its docstring; the MCP version
  argument is only for `/update-mcp`), for page checks and AI questions alike. Never start `uv run anki-addons-catalog`
  by hand: the script picks a free port itself, reports the cost and always stops the app.
- To check a change that affects AI search (the system prompt, the tools, an MCP server upgrade), ask the real AI a
  few questions without asking the user first: with `--ask` of that script, or with the `/deploy` smoke test. Each
  question costs a few cents of Claude credits, which the user allows.
- Ask at most a handful of questions per change, report what they cost, and ask the user before anything that would
  cost noticeably more.
