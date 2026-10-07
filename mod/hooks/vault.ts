// Pure helpers, kept apart from register.tsx so they can be tested directly.

// Folders where a note without `date:` frontmatter is a real mistake. Hubs
// (Projects/, Notes/Topics/), Templates/ and dot-folders are exempt: checked
// against the live vault, this rule flags none of the 140 notes in these folders.
const GUARDED = ['Inbox/', 'Claude Archive/Sessions/', 'Notes/', 'Daily/']
const EXEMPT = ['Notes/Topics/']

export function checkVaultWrite(vault: string, path: string, content: string): string | undefined {
  const root = vault.endsWith('/') ? vault : vault + '/'
  if (!path.startsWith(root) || !path.endsWith('.md')) return undefined
  const rel = path.slice(root.length)
  if (rel.split('/').some(part => part.startsWith('.'))) return undefined
  if (!GUARDED.some(p => rel.startsWith(p)) || EXEMPT.some(p => rel.startsWith(p))) return undefined
  const fm = /^---\n([\s\S]*?)\n---/.exec(content)
  if (fm && /^date:\s*\d{4}-\d{2}-\d{2}/m.test(fm[1])) return undefined
  return `Vault note ${rel} needs YAML frontmatter with "date: YYYY-MM-DD" (second-brain guard). Add it and write again.`
}

export function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60)
      .replace(/-+$/, '') || 'capture'
  )
}

const two = (n: number) => String(n).padStart(2, '0')

export function buildCapture(selected: string, when: Date): { filename: string; text: string } {
  const body = selected.trim()
  const first = body.split('\n').find(l => l.trim() !== '') ?? 'Capture'
  const title = first.replace(/^#+\s*/, '').trim().slice(0, 80)
  const date = `${when.getFullYear()}-${two(when.getMonth() + 1)}-${two(when.getDate())}`
  const filename = `${date}-${two(when.getHours())}${two(when.getMinutes())}-${slugify(title)}.md`
  const text =
    `---\ndate: ${date}\ntags: [claude-code-capture]\nsource: claude-code\n---\n\n` +
    `# ${title}\n\n${body}\n`
  return { filename, text }
}

export type Choice = { label: string; prompt: string }

export const NOT_NOW = 'Not now'

// What is worth offering as the session opens. The dashboard needs no choice:
// the mod regenerates a stale one itself at session start.
export function buildChoices(s: { inbox: number; hub: string | null }): Choice[] {
  const out: Choice[] = []
  if (s.hub !== null) {
    out.push({
      label: `Load ${s.hub} context`,
      prompt: `Run the second-brain skill's "load context" operation for the [[${s.hub}]] hub.`,
    })
  }
  if (s.inbox > 0) {
    out.push({
      label: `Triage inbox (${s.inbox})`,
      prompt: `Delegate the ${s.inbox} Desktop/iOS captures in the vault Inbox to the inbox-triage agent (Sonnet), per the second-brain skill's "triage inbox" operation.`,
    })
  }

  return out
}

export function question(choices: Choice[]): { question: string; options: string[] } {
  return {
    question: 'Second brain: what should I do before we start?',
    options: [...choices.slice(0, 3).map(c => c.label), NOT_NOW],
  }
}

// ask() comma-joins a multi-select answer, and "Other" is free text: match labels exactly.
export function picked(answer: string, choices: Choice[]): Choice[] {
  const parts = answer.split(',').map(p => p.trim())

  return choices.filter(c => parts.includes(c.label))
}
