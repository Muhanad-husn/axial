import { ThemeControl } from "@/components/ThemeControl";

/** Wordmark left, the corpus pin and the theme control right. The spend
 * meters that sit beside the control are #746. */
export function TopBar({ corpusPin }: { corpusPin: string | null }) {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-rule2 py-[11px] pr-4 pl-5">
      <span className="text-[13px] font-semibold tracking-[0.14em] uppercase">Axial</span>
      <span className="flex items-center gap-3.5">
        {corpusPin && (
          <span className="hidden font-mono text-[10.5px] text-ink3 sm:inline">
            corpus {corpusPin.slice(0, 8)}
          </span>
        )}
        <ThemeControl />
      </span>
    </header>
  );
}
