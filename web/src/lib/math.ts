// remark-math v6 only recognizes BLOCK math when `$$` sits on its own fence
// lines; the single-line `$$x^2$$` (and the multi-line `$$\begin{aligned}` …
// `\end{aligned}$$` variant) that LLMs overwhelmingly emit parses as inline
// instead. This line-oriented preprocessor promotes them to the fenced form,
// skipping fenced code blocks and falling back to raw text when the shape
// turns out not to close, so no input is ever mangled.
//
// Known trade-off (inherent to `$` syntax, same as pandoc): prose like
// "$5 和 $10" may pair into accidental inline math. We do not rewrite that.

const CODE_FENCE = /^[ \t]*(?:`{3,}|~{3,})/;
// Whole line: [indent]$$content$$  — content itself must not contain `$`.
const ONE_LINE = /^([ \t]*)\$\$([^$\r\n]+?)\$\$[ \t]*$/;
// Line opening a multi-line block: starts with $$, content after, no closer.
const MULTI_OPEN = /^([ \t]*)\$\$([^$\r\n]\S*(?:[^$\r\n]*[^$\r\n\s])?)$/;
// Line closing a multi-line block: content then $$.
const MULTI_CLOSE = /^([^$\r\n]*?)\$\$[ \t]*$/;

export function normalizeBlockMath(md: string): string {
  const lines = md.split('\n');
  const out: string[] = [];
  let inCodeFence = false;
  // Pending multi-line promotion: indent, first content piece, buffered body.
  let open: { indent: string; first: string; buf: string[]; raw: string[] } | null = null;

  const abortOpen = () => {
    if (open) out.push(...open.raw);
    open = null;
  };

  for (const line of lines) {
    if (CODE_FENCE.test(line)) {
      inCodeFence = !inCodeFence;
      abortOpen();
      out.push(line);
      continue;
    }
    if (inCodeFence) {
      out.push(line);
      continue;
    }

    if (open) {
      const close = line.match(MULTI_CLOSE);
      if (close && close[1].trim() !== '') {
        out.push(`${open.indent}$$`, `${open.indent}${open.first}`, ...open.buf, `${open.indent}${close[1]}`, `${open.indent}$$`);
        open = null;
        continue;
      }
      if (line.trim() === '' || open.buf.length > 80) {
        abortOpen(); // blank line or runaway: not a block formula after all
      } else {
        open.buf.push(line);
        open.raw.push(line);
        continue;
      }
    }

    const one = line.match(ONE_LINE);
    if (one) {
      const [, indent, content] = one;
      out.push(`${indent}$$`, `${indent}${content.trim()}`, `${indent}$$`);
      continue;
    }

    const multi = line.match(MULTI_OPEN);
    if (multi) {
      open = { indent: multi[1], first: multi[2].trim(), buf: [], raw: [line] };
      continue;
    }

    out.push(line);
  }
  abortOpen();
  return out.join('\n');
}
