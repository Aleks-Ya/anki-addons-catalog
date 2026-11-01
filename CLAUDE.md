# Repository scope

- Change files only in this repository, the Anki Addons Catalog web app.
- `../anki-addons-mcp` (the Anki Addons MCP server) and `../anki-addons-dataset` (the Anki Addons Dataset) are
  read-only. Read their source code when it helps, but never change anything there with any tool, including Bash and
  git.
- When a task needs a change in one of these two repositories, stop and do not work around it. Tell the user what has
  to change and why, then give them a prompt to paste into an AI session in that repository.
- Write that prompt in terms of the wanted result. Do not include implementation details such as file names, function
  names, code or test instructions: the session in that repository decides them.
