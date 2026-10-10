// A suggested command is a line starting with "! ". A trailing backslash
// continues it on the next line; the pieces are joined into one line so the
// pasted command runs as a single prompt entry.
export const extractCommands = (text: string): string[] => {
  const lines = text.split('\n')
  const out: string[] = []

  for (let i = 0; i < lines.length; i += 1) {
    const match = /^\s*(!\s+\S.*)$/.exec(lines[i])
    if (!match) continue

    let command = match[1].trimEnd()
    while (command.endsWith('\\') && i + 1 < lines.length) {
      i += 1
      command = `${command.slice(0, -1).trimEnd()} ${lines[i].trim()}`
    }
    out.push(command)
  }

  return out
}
