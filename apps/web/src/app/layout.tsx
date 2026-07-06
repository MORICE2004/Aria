/**
 * Root layout — wraps every page in the app.
 *
 * Provides the persistent dashboard shell: the sidebar on the left and a
 * content area on the right. The `dark` class on <html> enables Tailwind's
 * dark palette everywhere (a light/dark toggle arrives in a later phase).
 */
import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ARIA — Personal AI Assistant",
  description: "Your personal AI operating system.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`dark ${geistSans.variable}`}>
      <body className="min-h-screen bg-zinc-950 font-sans text-zinc-100 antialiased">
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 p-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
