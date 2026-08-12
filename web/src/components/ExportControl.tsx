import { downloadExport, EXPORT_FORMATS, EXPORT_FORMAT_LABELS, exportUrl } from "@/lib/api";

/** The download control: `GET /asks/{id}/export?format=md|docx|odt`. The
 * server renders and converts; the client's own job is just handing the
 * bytes to the browser's download manager. `href` still names the route (for
 * a copied link), but the click itself goes through `downloadExport`
 * (`@/lib/api`) -- every route now requires a bearer token (issue #764),
 * which a plain navigated anchor can never carry. */
export function ExportControl({ askId }: { askId: string }) {
  return (
    <details data-testid="export" className="self-start">
      <summary className="cursor-pointer rounded-md border border-rule px-3.5 py-2 text-[11px] font-semibold text-ink2">
        Export
      </summary>
      <div className="mt-2 flex flex-col gap-1.5">
        {EXPORT_FORMATS.map((format) => (
          <a
            key={format}
            href={exportUrl(askId, format)}
            onClick={(event) => {
              event.preventDefault();
              void downloadExport(askId, format);
            }}
            className="text-[11.5px] text-ink2 underline decoration-rule underline-offset-2 hover:text-ink"
          >
            {EXPORT_FORMAT_LABELS[format]}
          </a>
        ))}
      </div>
    </details>
  );
}
