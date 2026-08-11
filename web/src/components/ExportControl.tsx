import { EXPORT_FORMATS, EXPORT_FORMAT_LABELS, exportUrl } from "@/lib/api";

/** The download control: `GET /asks/{id}/export?format=md|docx|odt`. The
 * server renders and converts; a plain `<a download>` per format is the
 * whole client -- there is nothing to fetch, no citation mode to enforce
 * (the server's guarantee, not this client's), and no format-specific
 * branch beyond the anchor's own `href`. */
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
            download
            className="text-[11.5px] text-ink2 underline decoration-rule underline-offset-2 hover:text-ink"
          >
            {EXPORT_FORMAT_LABELS[format]}
          </a>
        ))}
      </div>
    </details>
  );
}
