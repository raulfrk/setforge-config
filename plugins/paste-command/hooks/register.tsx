import type { Register } from 'claude-code'

import { extractCommands } from './commands'

export const register: Register = on => {
  on('ui.render', { component: 'AssistantMessage' }, ($, e, next) => {
    const commands = extractCommands(e.props.text)

    if (commands.length === 0) {
      return next(e)
    }

    const { Box, Button, Markdown } = $.ui.resolve(e)

    return (
      <Box flexDirection="column">
        <Markdown text={e.props.text} />
        {commands.map((command, i) => {
          const short = command.length > 60 ? `${command.slice(0, 57)}...` : command
          const script = command.replace(/^!\s*/, '')

          return (
            <Box key={`row-${i}`}>
              <Button
                key={`run-${i}`}
                label={`run: ${short}`}
                onPress={async () => {
                  $.ui.toast(`Running: ${script.slice(0, 60)}`)
                  try {
                    const r = await $.process.run(['bash', '-c', script])
                    const out = `${r.stdout}${r.stderr}`.trimEnd().slice(0, 4000)
                    const text = `$ ${script}\n${out}\n[exit ${r.exitCode}]\n`
                    const filled = await $.prompt.fill({ text, mode: 'append' })
                    $.ui.toast(`Exit ${r.exitCode}${filled.isFilled ? ': output is in the prompt box' : ''}`)
                  } catch (err) {
                    $.ui.toast(`Could not run: ${String(err).slice(0, 80)}`)
                  }
                }}
              />
              <Button
                key={`paste-${i}`}
                label="paste"
                onPress={async () => {
                  const result = await $.prompt.fill({ text: command })
                  if (!result.isFilled) {
                    $.ui.toast('Could not paste: a dialog is open')
                  }
                }}
              />
            </Box>
          )
        })}
      </Box>
    )
  })
}
