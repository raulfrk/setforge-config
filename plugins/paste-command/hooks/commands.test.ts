import { expect, test } from 'claude-code/testing'

import { extractCommands } from './commands'

test('finds single-line commands', () => {
  expect(extractCommands('run:\n! ls -la\nthen\n  ! pwd')).toEqual(['! ls -la', '! pwd'])
})

test('joins backslash continuations into one line', () => {
  expect(extractCommands('! cd x && \\\n  setforge stage \\\n  --profile=claude')).toEqual([
    '! cd x && setforge stage --profile=claude',
  ])
})

test('ignores text with no command', () => {
  expect(extractCommands('hello! world')).toEqual([])
})
