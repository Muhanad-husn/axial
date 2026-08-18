import ReactMarkdown, { type Components } from "react-markdown";

/** The thesis, sections in plan order and prose the essay is served as
 * (issue #784) -- the exact string `GET /asks/{id}/paper`'s `essay` key
 * carries, `axial.paper.reader.render_reader_paper`'s own markdown: a `#`
 * title (the thesis), a `##` per section, and a `##` Bibliography. Rendered
 * with `react-markdown` rather than a hand-rolled parser (checked first:
 * nothing in `web/` renders markdown today) and no `remark-gfm` -- every
 * real essay on disk today uses no table and no strikethrough, so there is
 * nothing yet to add it for.
 *
 * The three evidence markers stay the only colour in this interface (#770);
 * this component adds none -- headings and prose are `--ink`/`--ink2`, the
 * same greyscale the claim list already uses. */
const COMPONENTS: Components = {
  h1: ({ children }) => <h1 className="m-0 mb-3 font-serif text-[19px] leading-[1.4] text-ink">{children}</h1>,
  h2: ({ children }) => (
    <h2 className="m-0 mt-5 mb-1.5 font-serif text-[15px] font-semibold leading-[1.4] text-ink">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="m-0 mt-4 mb-1 font-serif text-[13.5px] font-semibold leading-[1.4] text-ink">{children}</h3>
  ),
  p: ({ children }) => <p className="m-0 mb-3 font-serif text-[15.5px] leading-[1.62] text-ink">{children}</p>,
  // A blockquote reads as quoted book text, distinct from the tool's own
  // prose -- the same treatment `ClaimRow`'s quoted passages already use,
  // so the two surfaces agree on what "quoted" looks like. No real essay on
  // disk carries one today (the drafter is never asked to quote); this is
  // defensive against free-form prose that does. CommonMark wraps a
  // blockquote's text in its own `<p>`, which the `p` component above would
  // otherwise style right back to plain prose -- `[&_p]:...` overrides that
  // descendant directly rather than relying on inherited italic/colour,
  // which an explicit child style would win over anyway.
  blockquote: ({ children }) => (
    <blockquote className="m-0 mb-3 border-l-2 border-rule pl-2.5 [&_p]:m-0 [&_p]:font-serif [&_p]:text-[14px] [&_p]:leading-[1.55] [&_p]:text-ink2 [&_p]:italic">
      {children}
    </blockquote>
  ),
  ul: ({ children }) => <ul className="m-0 mb-3 list-disc pl-5 font-serif text-[13.5px] leading-[1.55] text-ink2">{children}</ul>,
  ol: ({ children }) => <ol className="m-0 mb-3 list-decimal pl-5 font-serif text-[13.5px] leading-[1.55] text-ink2">{children}</ol>,
  li: ({ children }) => <li className="mb-1">{children}</li>,
};

export function Essay({ markdown }: { markdown: string }) {
  return (
    <section data-testid="essay" className="pt-1">
      <ReactMarkdown components={COMPONENTS}>{markdown}</ReactMarkdown>
    </section>
  );
}
