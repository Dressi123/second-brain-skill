import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { TriageResult, TriageState, VaultSnapshot } from '../types'
import { SNAPSHOT_PY } from './snapshot'
import { buildChoices, buildCapture, checkVaultWrite, picked, question } from './vault'

const PANE = 'vault'
const snap = atom({ plugin: 'second-brain-mod', key: 'snap' } as const, null)
const isHidden = atom({ plugin: 'second-brain-mod', key: 'isHidden' } as const, false)
const IDLE: TriageState = { phase: 'idle', proposed: [], review: [], filed: [], note: '', asks: {} }
const triage = atom({ plugin: 'second-brain-mod', key: 'triage' } as const, IDLE)

// Subagents this mod started, by agent id: their answer arrives as their own turn.complete.
const waiting: Record<string, { file: string; kind: 'ask' | 'apply' | 'save' }> = {}

const isStuck = (state: string) => state !== 'active' && state !== 'finalizing'
// One committed palette: warm ink, a slate for chrome, amber for "look at this",
// coral for broken, mint for healthy. Fixed hex, so it assumes a dark pane.
const INK = '#E8E2D0'
const SLATE = '#6B7785'
const AMBER = '#F0B454'
const CORAL = '#F2777A'
const MINT = '#7FD6AE'

const stateColor = (state: string) =>
  state === 'crashed' || state === 'orphaned' ? CORAL : state === 'stale' ? AMBER : MINT

async function refresh($: EngineInterface): Promise<void> {
  try {
    const { exitCode, stdout } = await $.process.run(['python3', '-c', SNAPSHOT_PY, 'snap'], { timeoutMs: 20000 })
    if (exitCode === 0) {
      await update($, snap, () => JSON.parse(stdout) as VaultSnapshot)
    }
  } catch {
    // keep the last snapshot; the band simply stops updating
  }
}

// Button presses. Each takes `$` as a top-level function, as the validator requires.
async function openTarget($: EngineInterface, target: string): Promise<void> {
  await $.process.run(['open', target], { timeoutMs: 10000 })
}

async function setAsk(
  $: EngineInterface,
  file: string,
  ask: { kind: 'ask' | 'apply' | 'save'; status: 'running' | 'done' | 'failed'; text: string; hub: string | null },
): Promise<void> {
  await update($, triage, t => ({ ...t, asks: { ...t.asks, [file]: ask } }))
}

async function runScript($: EngineInterface, mode: 'triage-dry' | 'triage-apply'): Promise<void> {
  const applying = mode === 'triage-apply'
  await update($, triage, t => ({ ...t, phase: (applying ? 'filing' : 'running') as TriageState['phase'], note: '' }))
  try {
    const { stdout } = await $.process.run(['python3', '-c', SNAPSHOT_PY, mode], { timeoutMs: 120000 })
    const r = JSON.parse(stdout) as TriageResult
    await update($, triage, t => ({
      ...t,
      phase: (!r.ok ? 'error' : applying ? 'done' : 'ready') as TriageState['phase'],
      proposed: r.proposed,
      review: r.review,
      filed: applying ? r.filed : t.filed,
      note: !r.ok ? `Triage failed: ${r.err || 'no output'}` : r.noKey ? 'No TypeSafe key, so every capture needs review.' : '',
    }))
  } catch (err) {
    await update($, triage, t => ({ ...t, phase: 'error' as const, note: `Triage failed: ${String(err).slice(0, 120)}` }))
  }
  await refresh($)
}

async function askClaude($: EngineInterface, file: string): Promise<void> {
  await setAsk($, file, { kind: 'ask', status: 'running', text: '', hub: null })
  const started = await $.agent.spawn({
    subagentType: 'inbox-triage',
    description: 'Triage one capture',
    prompt:
      `Phase 1 only (read-only). Triage exactly one vault inbox capture: Inbox/${file}. ` +
      `Follow the second-brain skill's "triage inbox" operation: check the real taxonomy (list_taxonomy.py), read the capture, ` +
      `and decide which hub it belongs under, or none. Do not move or edit anything. ` +
      `End your reply with exactly one line: "HUB: <hub-id> | <one-line reason>" or "HUB: none | <reason>". Keep the whole reply under 120 words.`,
  })
  if (started.deny !== undefined || started.agentId === undefined) {
    await setAsk($, file, { kind: 'ask', status: 'failed', text: started.deny ?? 'The subagent did not start.', hub: null })
    return
  }
  waiting[started.agentId] = { file, kind: 'ask' }
}

async function fileUnder($: EngineInterface, file: string, hub: string): Promise<void> {
  await setAsk($, file, { kind: 'apply', status: 'running', text: '', hub })
  const started = await $.agent.spawn({
    subagentType: 'inbox-triage',
    description: 'File one capture',
    prompt:
      `The user approved. File the capture Inbox/${file} under hub ${hub} using the second-brain skill's "triage inbox" steps for a single capture: ` +
      `set exactly one of project:/topic: in its frontmatter, add a link under that hub's ## Captures, move it to Notes/, then run validate.py on it. ` +
      `Touch nothing else. End with exactly one line: "FILED: ok" or "FILED: failed | <reason>". Under 60 words.`,
  })
  if (started.deny !== undefined || started.agentId === undefined) {
    await setAsk($, file, { kind: 'apply', status: 'failed', text: started.deny ?? 'The subagent did not start.', hub })
    return
  }
  waiting[started.agentId] = { file, kind: 'apply' }
}

async function finishAgent(
  $: EngineInterface,
  file: string,
  kind: 'ask' | 'apply' | 'save',
  answer: string,
): Promise<void> {
  if (kind === 'save') {
    const saved = /^SAVED:\s*(.+)$/im.exec(answer)?.[1]?.trim()
    const skipped = /^SKIPPED:\s*(.+)$/im.exec(answer)?.[1]?.trim()
    await setAsk($, file, {
      kind,
      status: saved !== undefined ? 'done' : 'failed',
      text: saved !== undefined ? `saved as ${saved.split('/').pop()}` : `not saved: ${skipped ?? 'no clear answer'}`.slice(0, 140),
      hub: null,
    })
    await refresh($)
    return
  }
  if (kind === 'apply') {
    const ok = /FILED:\s*ok/i.test(answer)
    const why = /FILED:\s*failed\s*\|\s*(.*)$/im.exec(answer)?.[1] ?? ''
    await setAsk($, file, { kind, status: ok ? 'done' : 'failed', text: ok ? 'filed' : why || 'filing failed', hub: null })
    await refresh($)
    return
  }
  const m = /^HUB:\s*([a-z0-9-]+)\s*(?:\|\s*(.*))?$/im.exec(answer)
  const hub = m !== null && m[1].toLowerCase() !== 'none' ? m[1] : null
  const reason = (m?.[2] ?? '').trim() || (m === null ? 'no clear answer' : '')
  await setAsk($, file, { kind, status: 'done', text: reason.slice(0, 140), hub })
}

// An orphaned draft's finalize already ran, so its work is saved (or was judged not worth saving):
// move it aside rather than delete it, as the finalize hook does for skipped drafts.
async function archiveDraft($: EngineInterface, path: string): Promise<void> {
  const dir = path.slice(0, path.lastIndexOf('/')) + '/.superseded'
  await $.process.run(['mkdir', '-p', dir], { timeoutMs: 10000 })
  await $.process.run(['mv', path, dir + '/'], { timeoutMs: 10000 })
  await refresh($)
}

async function saveDraft($: EngineInterface, sid: string, path: string): Promise<void> {
  const key = `draft-${sid}`
  await setAsk($, key, { kind: 'save', status: 'running', text: '', hub: null })
  const started = await $.agent.spawn({
    subagentType: 'general-purpose',
    description: 'Save a draft as a summary',
    prompt:
      `The user clicked "save as summary" on a leftover session draft that was never finalized: ${path}. ` +
      `Read it. Following the second-brain skill's "save session summary" operation (~/.claude/skills/second-brain/SKILL.md): ` +
      `the transcript is not available, so write a short summary built ONLY from what the draft says, inventing nothing, ` +
      `and end its Reference section with a line saying it was reconstructed from a running draft. ` +
      `Use the draft file's modification date as the note's date. Pick one real hub from list_taxonomy.py, never an invented one; ` +
      `if none fits, stop. Check Claude Archive/Sessions/ for an existing summary that already covers the same work, and if one does, write nothing. ` +
      `Never overwrite an existing file. Write the note to Claude Archive/Sessions/<date>-<slug>.md, link it from the hub with add_session_to_hub.py, ` +
      `then run validate.py and fix any errors. Only after validation passes, move the draft into a .superseded folder next to it (mkdir -p first). ` +
      `End with exactly one line: "SAVED: <path>" or "SKIPPED: <one-line reason>". Keep the reply under 80 words.`,
  })
  if (started.deny !== undefined || started.agentId === undefined) {
    await setAsk($, key, { kind: 'save', status: 'failed', text: started.deny ?? 'The subagent did not start.', hub: null })
    return
  }
  waiting[started.agentId] = { file: key, kind: 'save' }
}

async function rebuildDashboard($: EngineInterface, helpers: string): Promise<void> {
  await $.process.run(['python3', '-c', SNAPSHOT_PY, 'regen'], { timeoutMs: 120000 })
  await refresh($)
  await openTarget($, `${helpers}/brain-status.html`)
}

export const register: Register = on => {
  let didRegen = false

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'vault', description: 'Open the second-brain vault pane' })
    await $.command.register({
      name: 'vault-capture',
      description: 'Save the text you selected (fullscreen) to the vault Inbox',
    })
    await refresh($)
    const current = await read($, snap)
    if (current?.dashboardStale && !didRegen) {
      didRegen = true
      await $.process.run(['python3', '-c', SNAPSHOT_PY, 'regen'], { timeoutMs: 120000 })
      await refresh($)
    }
    $.clock.every(60000, () => refresh($))
    const result = await next(e)

    // Offer the choices in a dialog before the first prompt, instead of the model asking in its first reply.
    const status = await read($, snap)
    const choices = e.isInteractive && status !== null ? buildChoices({ inbox: status.inbox.length, hub: status.hub }) : []
    if (choices.length > 0) {
      try {
        const { question: q, options } = question(choices)
        const answer = await $.ui.ask(q, { options, header: 'Second brain', multiSelect: true })
        const prompts = picked(answer, choices).map(c => c.prompt)
        if (prompts.length > 0) void $.prompt.submit({ text: prompts.join(' Then: ') })
      } catch {
        // dismissed dialog: the session just opens as usual
      }
    }

    return result
  })

  on('turn.complete', async ($, e, next) => {
    const w = e.agentId !== undefined ? waiting[e.agentId] : undefined
    if (w !== undefined && e.agentId !== undefined) {
      delete waiting[e.agentId]
      await finishAgent($, w.file, w.kind, e.answer ?? '')
    }
    await refresh($)

    return next(e)
  })

  on('command.run', { command: 'vault' }, async $ => {
    await update($, isHidden, () => false)
    await refresh($)
    await $.ui.open({ id: PANE, title: 'Second brain' })

    return { text: 'Vault pane opened, status band shown.' }
  })

  on('command.run', { command: 'vault-capture' }, async $ => {
    const selected = await $.ui.selection()
    if (selected === undefined || selected.text.trim() === '') {
      return { text: 'Nothing selected. Select text with the mouse first (fullscreen mode only).' }
    }
    let current = await read($, snap)
    if (current === null) {
      await refresh($)
      current = await read($, snap)
    }
    if (current === null) return { text: 'Could not find the vault.' }
    const { filename, text } = buildCapture(selected.text, new Date(await $.clock.now()))
    await $.fs.write(`${current.vault}/Inbox/${filename}`, text)
    await refresh($)

    return { text: `Saved to Inbox/${filename}` }
  })

  // Deliberately no .catch: if this hook itself errors, the write goes through.
  on('tool.call', { tool: 'Write' }, async ($, e, next) => {
    const current = await read($, snap)
    if (current === null) return next(e)
    let path = e.file_path
    try {
      path = (await $.fs.stat(e.file_path, { resolve: true })).realPath ?? e.file_path
    } catch {
      // a file that does not exist yet has no realPath; use the path as given
    }
    const problem = checkVaultWrite(current.vault, path, e.content)
    if (problem !== undefined) return { deny: problem }

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const s = await read($, snap)
    if (e.props.hasSurvey || s === null || (await read($, isHidden))) return next(e)
    const stuck = s.drafts.filter(d => isStuck(d.state)).length
    const parts = [
      s.inbox.length > 0 ? `${s.inbox.length} in inbox` : 'inbox empty',
      s.dashboardStale ? 'dashboard stale' : 'dashboard current',
      s.hub !== null ? `hub: ${s.hub}` : 'no hub here',
    ]
    if (stuck > 0) parts.push(`${stuck} stuck draft${stuck > 1 ? 's' : ''}`)
    const { Box, Button, Text } = $.ui.resolve(e)

    return (
      <Box>
        <Text dimColor>Vault: {parts.join(' · ')} </Text>
        <Button key="open" label="Open" onPress={() => $.ui.open({ id: PANE, title: 'Second brain' })} />
        <Button key="hide" label="Hide" onPress={() => update($, isHidden, () => true)} />
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const s = await read($, snap)
    const tr = await read($, triage)
    const { Box, Button, Text } = $.ui.resolve(e)
    if (s === null) return <Text color={SLATE}>Loading vault status...</Text>
    const clearAsk = (file: string) =>
      update($, triage, t => ({ ...t, asks: Object.fromEntries(Object.entries(t.asks).filter(([f]) => f !== file)) }))
    const stuck = s.drafts.filter(d => isStuck(d.state)).length
    const todo = s.inbox.length
    const calm = stuck === 0 && todo === 0 && !s.dashboardStale
    const verdict = [
      todo > 0 ? `${todo} to triage` : null,
      stuck > 0 ? `${stuck} draft${stuck > 1 ? 's' : ''} stuck` : null,
      s.dashboardStale ? 'dashboard stale' : null,
    ].filter(Boolean)

    return (
      <Box flexDirection="column" gap={1} paddingX={2} paddingY={1}>
        <Box flexDirection="column">
          <Text bold color={INK}>S E C O N D   B R A I N</Text>
          <Text color={calm ? MINT : AMBER}>{calm ? '● all clear' : `● ${verdict.join('  ·  ')}`}</Text>
        </Box>

        <Box flexDirection="column" borderStyle="round" borderColor={todo > 0 ? AMBER : SLATE} paddingX={1}>
          <Box justifyContent="space-between">
            <Text><Text bold color={INK}>INBOX </Text><Text bold color={todo > 0 ? AMBER : MINT}>{todo}</Text></Text>
            {tr.phase === 'running' || tr.phase === 'filing' ? (
              <Text color={AMBER}>{tr.phase === 'running' ? 'triaging…' : 'filing…'}</Text>
            ) : tr.phase === 'ready' && tr.proposed.length > 0 ? (
              <Box gap={2}>
                <Button key="triage-apply" label={`File ${tr.proposed.length}`} variant="primary" onPress={() => runScript($, 'triage-apply')} />
                <Button key="triage-dismiss" dimColor label="dismiss" onPress={() => update($, triage, () => IDLE)} />
              </Box>
            ) : todo > 0 ? (
              <Button key="triage-all" label="Triage inbox" variant="primary" hotkey="t" onPress={() => runScript($, 'triage-dry')} />
            ) : null}
          </Box>
          {tr.note !== '' && <Text wrap="truncate-end" color={CORAL}>{tr.note}</Text>}
          {tr.phase === 'done' && tr.filed.length > 0 && (
            <Text color={MINT}>● filed {tr.filed.length}</Text>
          )}
          {todo === 0 && <Text color={SLATE}>Nothing to triage.</Text>}
          {s.inbox.map(n => {
            const ask = tr.asks[n.file]
            const proposal = tr.proposed.find(i => i.file === n.file)
            const review = tr.review.find(i => i.file === n.file)
            const canAsk = ask === undefined || ask.status === 'failed'

            return (
              <Box key={n.file} flexDirection="column">
                <Box gap={2}>
                  <Box flexGrow={1} flexShrink={1} minWidth={0}>
                    <Text wrap="truncate-end" color={INK}>› {n.title}</Text>
                  </Box>
                  <Box flexShrink={0} gap={2}>
                    {canAsk && <Button key={`triage-${n.file}`} label="triage" onPress={() => askClaude($, n.file)} />}
                    <Button key={`open-${n.file}`} dimColor label="open" onPress={() => openTarget($, n.uri)} />
                  </Box>
                </Box>
                {ask === undefined && proposal !== undefined && (
                  <Text wrap="truncate-end" color={SLATE}>  <Text color={MINT}>→ </Text>{proposal.why}</Text>
                )}
                {ask === undefined && review !== undefined && (
                  <Text wrap="truncate-end" color={SLATE}>  <Text color={AMBER}>? </Text>{review.why}</Text>
                )}
                {ask !== undefined && ask.status === 'running' && (
                  <Text color={AMBER}>  {ask.kind === 'apply' ? 'filing…' : 'Claude is looking…'}</Text>
                )}
                {ask !== undefined && ask.status === 'failed' && <Text color={CORAL}>  {ask.text}</Text>}
                {ask !== undefined && ask.status === 'done' && ask.kind === 'apply' && <Text color={MINT}>  ✓ {ask.text}</Text>}
                {ask !== undefined && ask.status === 'done' && ask.kind === 'ask' && (
                  <Box flexDirection="column">
                    {ask.hub !== null ? (
                      <Text bold color={MINT}>  → {ask.hub}</Text>
                    ) : (
                      <Text bold color={AMBER}>  ? no clear hub</Text>
                    )}
                    {ask.text !== '' && <Text color={INK}>    {ask.text}</Text>}
                  </Box>
                )}
                {ask !== undefined && ask.status !== 'running' && (
                  <Box gap={2} paddingLeft={2}>
                    {ask.kind === 'ask' && ask.status === 'done' && ask.hub !== null && (
                      <Button key={`file-${n.file}`} label={`File under ${ask.hub}`} variant="primary" onPress={() => fileUnder($, n.file, ask.hub ?? '')} />
                    )}
                    <Button key={`clear-${n.file}`} dimColor label="dismiss" onPress={() => clearAsk(n.file)} />
                  </Box>
                )}
              </Box>
            )
          })}
        </Box>

        <Box flexDirection="column" borderStyle="round" borderColor={SLATE} paddingX={1}>
          <Text><Text bold color={INK}>HUB </Text><Text color={s.hub !== null ? MINT : SLATE}>{s.hub ?? 'none for this directory'}</Text></Text>
          {s.hubSessions.map(sess => (
            <Box key={sess.uri} gap={2}>
              <Box flexGrow={1} flexShrink={1} minWidth={0}>
                <Text wrap="truncate-end" color={INK}><Text color={SLATE}>{sess.date}  </Text>{sess.title}</Text>
              </Box>
              <Box flexShrink={0}>
                <Button key={`sess-${sess.uri}`} dimColor label="open" onPress={() => openTarget($, sess.uri)} />
              </Box>
            </Box>
          ))}
        </Box>

        <Box flexDirection="column" borderStyle="round" borderColor={stuck > 0 ? CORAL : SLATE} paddingX={1}>
          <Text><Text bold color={INK}>DRAFTS </Text><Text bold color={stuck > 0 ? CORAL : MINT}>{stuck > 0 ? `${stuck} stuck` : 'clean'}</Text></Text>
          {s.drafts.map(d => {
            const ask = tr.asks[`draft-${d.sid}`]
            const stuckHere = isStuck(d.state)

            return (
              <Box key={d.sid} flexDirection="column">
                <Box gap={2}>
                  <Box flexGrow={1} flexShrink={1} minWidth={0}>
                    <Text wrap="truncate-end">
                      <Text color={stateColor(d.state)}>● {d.state.padEnd(10)}</Text>
                      <Text color={SLATE}> {d.sid}</Text>
                    </Text>
                  </Box>
                  {stuckHere && (
                    <Box flexShrink={0} gap={2}>
                      {d.state === 'orphaned' ? (
                        <Button key={`archive-${d.sid}`} label="archive" onPress={() => archiveDraft($, d.path)} />
                      ) : (
                        ask?.status !== 'running' && (
                          <Button key={`save-${d.sid}`} label="save as summary" onPress={() => saveDraft($, d.sid, d.path)} />
                        )
                      )}
                      <Button key={`draft-${d.sid}`} dimColor label="open" onPress={() => openTarget($, d.path)} />
                    </Box>
                  )}
                </Box>
                {stuckHere && <Text wrap="truncate-end" color={SLATE}>  {d.note}</Text>}
                {ask !== undefined && ask.status === 'running' && <Text color={AMBER}>  saving…</Text>}
                {ask !== undefined && ask.status === 'done' && <Text color={MINT}>  ✓ {ask.text}</Text>}
                {ask !== undefined && ask.status === 'failed' && (
                  <Box gap={2} paddingLeft={2}>
                    <Text color={CORAL} wrap="truncate-end">{ask.text}</Text>
                    <Button key={`clear-draft-${d.sid}`} dimColor label="dismiss" onPress={() => clearAsk(`draft-${d.sid}`)} />
                  </Box>
                )}
              </Box>
            )
          })}
        </Box>

        <Box flexDirection="column" borderStyle="round" borderColor={SLATE} paddingX={1}>
          <Text bold color={INK}>HEALTH</Text>
          {s.hooks.map(hook => (
            <Text wrap="truncate-end" color={INK}>
              <Text color={hook.last === null ? AMBER : MINT}>● </Text>
              {hook.name} <Text color={SLATE}>{hook.last === null ? 'never observed' : hook.last.slice(5, 16)}</Text>
            </Text>
          ))}
          <Text color={INK}>
            <Text color={s.dashboardStale ? AMBER : MINT}>● </Text>
            Dashboard <Text color={SLATE}>{s.dashboardStale ? 'stale' : 'current'}</Text>
          </Text>
          <Box gap={2}>
            <Button key="refresh" label="Refresh" hotkey="r" onPress={() => refresh($)} />
            <Button key="dashboard" label="Open dashboard" hotkey="d" onPress={() => rebuildDashboard($, s.helpers)} />
          </Box>
        </Box>
      </Box>
    )
  })
}
