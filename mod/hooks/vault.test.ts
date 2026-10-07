import { expect, test } from 'claude-code/testing'

import { NOT_NOW, buildCapture, buildChoices, checkVaultWrite, picked, question, slugify } from './vault'

const V = '/Users/x/Vault'
const GOOD = '---\ndate: 2026-10-06\ntags: [a]\n---\n\n# T\n'

test('guard denies a vault Inbox note with no frontmatter', async () => {
  expect(checkVaultWrite(V, `${V}/Inbox/a.md`, '# just a title\n')).toContain('date: YYYY-MM-DD')
})

test('guard denies frontmatter that lacks a date', async () => {
  expect(checkVaultWrite(V, `${V}/Notes/a.md`, '---\ntags: [a]\n---\n')).toBeDefined()
})

test('guard allows a dated note, hubs, templates, dot-folders and outside paths', async () => {
  expect(checkVaultWrite(V, `${V}/Inbox/a.md`, GOOD)).toBeUndefined()
  expect(checkVaultWrite(V, `${V}/Projects/Hub.md`, '# hub\n')).toBeUndefined()
  expect(checkVaultWrite(V, `${V}/Notes/Topics/Hub.md`, '# hub\n')).toBeUndefined()
  expect(checkVaultWrite(V, `${V}/Templates/T.md`, '# t\n')).toBeUndefined()
  expect(checkVaultWrite(V, `${V}/.obsidian/x.md`, 'x')).toBeUndefined()
  expect(checkVaultWrite(V, `${V}/Claude Archive/Sessions/.drafts/d.md`, 'x')).toBeUndefined()
  expect(checkVaultWrite(V, '/Users/x/code/readme.md', 'x')).toBeUndefined()
  expect(checkVaultWrite(V, `${V}/Inbox/data.json`, '{}')).toBeUndefined()
})

test('guard does not match a sibling folder that shares the vault prefix', async () => {
  expect(checkVaultWrite(V, '/Users/x/Vault-copy/Inbox/a.md', 'x')).toBeUndefined()
})

test('capture builds capture-style frontmatter and a dated filename', async () => {
  const { filename, text } = buildCapture('Use next(e) to pass events on.\nMore.', new Date(2026, 9, 6, 17, 7))
  expect(filename).toBe('2026-10-06-1707-use-next-e-to-pass-events-on.md')
  expect(text.startsWith('---\ndate: 2026-10-06\ntags: [claude-code-capture]\nsource: claude-code\n---')).toBe(true)
  expect(text).toContain('# Use next(e) to pass events on.')
  expect(checkVaultWrite(V, `${V}/Inbox/${filename}`, text)).toBeUndefined()
})

test('slugify falls back for text with no letters', async () => {
  expect(slugify('!!!')).toBe('capture')
})

test('session-start choices: only what applies, Not now always last, labels matched exactly', () => {
  expect(buildChoices({ inbox: 0, hub: null })).toEqual([])
  const choices = buildChoices({ inbox: 2, hub: 'h' })
  expect(question(choices).options).toEqual(['Load h context', 'Triage inbox (2)', NOT_NOW])
  expect(picked('Load h context, Triage inbox (2)', choices)).toHaveLength(2)
  expect(picked(NOT_NOW, choices)).toEqual([])
  expect(picked('typed under Other', choices)).toEqual([])
})
