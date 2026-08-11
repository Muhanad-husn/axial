import type { Metadata } from "next";
import { Newsreader } from "next/font/google";

import { THEME_STORAGE_KEY } from "@/lib/theme";

import "./globals.css";

/** Newsreader for anything Axial wrote -- the question as posed, and the
 * paper #745 renders. The interface itself stays in Helvetica. */
const newsreader = Newsreader({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-newsreader",
});

export const metadata: Metadata = {
  title: "Axial",
  description: "Ask a question of the corpus and watch Axial read.",
};

/** Resolve the theme before first paint, so a dark machine never flashes
 * light. It repeats one line of `resolveTheme` on purpose: the alternative is
 * shipping a module to the browser ahead of hydration to save four tokens. */
const THEME_BOOT = `try{var c=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});var d=c==="dark"||(c!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.theme=d?"dark":"light"}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${newsreader.variable} h-full`} suppressHydrationWarning>
      <body className="flex min-h-full flex-col">
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
        {children}
      </body>
    </html>
  );
}
