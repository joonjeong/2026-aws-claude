import { ReactNode } from "react";

/** Hand-rolled, dependency-free markdown → React elements.
 * NO dangerouslySetInnerHTML — everything is built as React nodes.
 *
 * Supports: ## / ### headings, **bold**, `inline code`, - / * bullet lists,
 * numbered lists (1. / 1)), paragraphs. Called on every streaming delta, so
 * it must tolerate incomplete markdown: an unclosed ** renders bold-to-end
 * (settles once the closer arrives); an unclosed ` renders literally. */

function renderBold(text: string, keyBase: string): ReactNode[] {
  const parts = text.split("**");
  if (parts.length === 1) return [text];
  const out: ReactNode[] = [];
  parts.forEach((part, i) => {
    if (i % 2 === 1) {
      // odd chunk = inside **…**; a missing closer just bolds to the end
      out.push(<strong key={`${keyBase}-b${i}`}>{part}</strong>);
    } else if (part) {
      out.push(part);
    }
  });
  return out;
}

function renderInline(text: string, keyBase: string): ReactNode[] {
  const parts = text.split("`");
  if (parts.length === 1) return renderBold(text, keyBase);
  const out: ReactNode[] = [];
  parts.forEach((part, i) => {
    if (i % 2 === 1 && i < parts.length - 1) {
      out.push(<code key={`${keyBase}-c${i}`}>{part}</code>);
    } else if (i % 2 === 1) {
      // unclosed backtick mid-stream — keep it literal until the closer lands
      out.push(...renderBold(`\`${part}`, `${keyBase}-${i}`));
    } else if (part) {
      out.push(...renderBold(part, `${keyBase}-${i}`));
    }
  });
  return out;
}

interface ListState {
  ordered: boolean;
  items: ReactNode[][];
}

export function renderMarkdown(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let list: ListState | null = null;
  let para: string[] = [];

  const flushPara = () => {
    if (!para.length) return;
    const key = `p${out.length}`;
    out.push(<p key={key}>{renderInline(para.join(" "), key)}</p>);
    para = [];
  };
  const flushList = () => {
    if (!list) return;
    const key = `l${out.length}`;
    const children = list.items.map((item, i) => <li key={`${key}-${i}`}>{item}</li>);
    out.push(
      list.ordered ? <ol key={key}>{children}</ol> : <ul key={key}>{children}</ul>,
    );
    list = null;
  };

  text.split("\n").forEach((raw, n) => {
    const line = raw.trim();
    const heading = /^(#{2,3})\s+(.*)$/.exec(line);
    const bullet = /^[-*]\s+(.*)$/.exec(line);
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line);

    if (!line) {
      flushPara();
      flushList();
    } else if (heading) {
      flushPara();
      flushList();
      const key = `h${out.length}`;
      const body = renderInline(heading[2], key);
      out.push(
        heading[1].length === 2
          ? <h4 className="md-h2" key={key}>{body}</h4>
          : <h5 className="md-h3" key={key}>{body}</h5>,
      );
    } else if (bullet || numbered) {
      flushPara();
      const ordered = !!numbered;
      if (list && list.ordered !== ordered) flushList();
      if (!list) list = { ordered, items: [] };
      const body = (bullet ?? numbered)![1];
      list.items.push(renderInline(body, `li${out.length}-${n}`));
    } else {
      flushList();
      para.push(line);
    }
  });
  flushPara();
  flushList();
  return out;
}

/** Streaming-friendly markdown block (used by AIPanel + article analysis). */
export default function Markdown({ text }: { text: string }) {
  return <div className="md-body">{renderMarkdown(text)}</div>;
}
